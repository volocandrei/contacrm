/**
 * Backend simulat, în memorie. Implementează aceleași rute și aceeași semantică
 * (paginare, filtrare, coduri de eroare) ca API-ul real planificat, ca trecerea la
 * backend să fie o schimbare de configurare, nu o rescriere a interfeței.
 *
 * Starea trăiește doar în tab-ul curent: la reîncărcare se reia de la setul sintetic.
 */
import { ApiError, type Paginated } from "@/api/types";
import {
  ACTIVE_CLIENTS,
  AUDIT_LOGS,
  CLIENTS,
  CLIENT_NOTES,
  CONTACTS,
  DOCUMENTS,
  DOCUMENT_TYPES,
  DOCUMENT_TYPE_LABEL,
  MOCK_NOW,
  PERIODS,
  TASKS,
  USERS,
  buildFields,
  derivePeriodStatus,
  type StoredDocument,
  periodProgress,
} from "@/api/mock/seed";
import { buildArchivePath, buildDocumentFilename, type FilenameInput } from "@/lib/filename";
import { ROLE_LABEL } from "@/lib/labels";
import { ROLE_CODE } from "@/types/domain";
import type {
  AccountingPeriod,
  AnafMandate,
  AnafStatus,
  AnafSyncResult,
  AuditLogEntry,
  Client,
  ClientStatus,
  ClientExpectation,
  ClientNote,
  DocumentTypeCode,
  Intake,
  Contact,
  CurrentUser,
  DashboardClosing,
  DashboardData,
  DayCount,
  StatusSlice,
  DocumentAction,
  DocumentDetail,
  DocumentFieldName,
  DocumentListItem,
  DocumentStatus,
  DriveBrowseItem,
  DriveFolder,
  DriveStatus,
  DriveSyncResult,
  MailBrowseItem,
  MailFolder,
  Permission,
  ReportBucket,
  ReportSummary,
  RoleCode,
  RoleInfo,
  SettingEntry,
  Task,
  UserSummary,
} from "@/types/domain";

/* ─── Stare mutabilă ───────────────────────────────────────────────────────── */

const state = {
  clients: structuredClone(CLIENTS) as Client[],
  contacts: structuredClone(CONTACTS) as Contact[],
  notes: structuredClone(CLIENT_NOTES) as ClientNote[],
  documents: structuredClone(DOCUMENTS) as StoredDocument[],
  periods: structuredClone(PERIODS),
  tasks: structuredClone(TASKS) as Task[],
  audit: structuredClone(AUDIT_LOGS) as AuditLogEntry[],
  users: structuredClone(USERS) as UserSummary[],
};

let auditCounter = state.audit.length;

/** Luna de referinta a setului sintetic; perioadele anterioare sunt inchise. */
const CURRENT_MONTH = "2026-08";

/* ─── Permisiuni per rol (§32) ─────────────────────────────────────────────── */

const ALL_PERMISSIONS: Permission[] = [
  "clients:read",
  "clients:write",
  "documents:read",
  "documents:write",
  "documents:approve",
  "documents:delete",
  "periods:manage",
  "tasks:read",
  "tasks:write",
  "communication:send",
  "admin:users",
  "admin:settings",
  "audit:read",
];

export const ROLE_PERMISSIONS: Record<RoleCode, Permission[]> = {
  SUPER_ADMIN: ALL_PERMISSIONS,
  ADMIN: ALL_PERMISSIONS.filter((p) => p !== "documents:delete"),
  ACCOUNTANT: [
    "clients:read",
    "documents:read",
    "documents:write",
    "documents:approve",
    "periods:manage",
    "tasks:read",
    "tasks:write",
    "communication:send",
    "audit:read",
  ],
  OPERATOR: ["clients:read", "documents:read", "documents:write", "tasks:read", "tasks:write"],
  REVIEWER: ["clients:read", "documents:read", "documents:write", "documents:approve", "tasks:read"],
  VIEWER: ["clients:read", "documents:read", "tasks:read"],
};

/* ─── Utilitare ────────────────────────────────────────────────────────────── */

function paginate<T>(items: T[], page = 1, pageSize = 25): Paginated<T> {
  const safePage = Math.max(1, page);
  const safeSize = Math.min(Math.max(1, pageSize), 200);
  const start = (safePage - 1) * safeSize;
  return {
    items: items.slice(start, start + safeSize),
    page: safePage,
    pageSize: safeSize,
    total: items.length,
    totalPages: Math.max(1, Math.ceil(items.length / safeSize)),
  };
}

function notFound(entity: string, id: string): never {
  throw new ApiError("NOT_FOUND", `${entity} inexistent: ${id}`, 404);
}

function normalize(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

function matches(haystack: Array<string | null | undefined>, needle: string): boolean {
  const q = normalize(needle.trim());
  if (!q) return true;
  return haystack.some((value) => value && normalize(value).includes(q));
}

function toListItem(doc: StoredDocument): DocumentListItem {
  const {
    mimeType: _mimeType,
    fileSize: _fileSize,
    sha256: _sha256,
    duplicateOfId: _duplicateOfId,
    fields: _fields,
    ocr: _ocr,
    extraction: _extraction,
    validationIssues: _validationIssues,
    history: _history,
    ...listItem
  } = doc;
  return listItem;
}

/**
 * Ce tranziții permite fiecare stare.
 *
 * **Sursa de adevăr este backend-ul** (`app/domain/document_state.py`). Copia asta
 * există doar ca backendul simulat să răspundă la fel; `tests/test_contract_document_actions.py`
 * compară cele două și cade dacă se despart.
 */
const ALLOWED_TRANSITIONS: Record<DocumentStatus, DocumentStatus[]> = {
  RECEIVED: ["PROCESSING", "DUPLICATE", "ERROR", "UNMATCHED", "REJECTED"],
  PROCESSING: ["REVIEW_REQUIRED", "APPROVED", "DUPLICATE", "ERROR", "UNMATCHED"],
  REVIEW_REQUIRED: ["APPROVED", "REJECTED", "DUPLICATE", "PROCESSING"],
  UNMATCHED: ["REVIEW_REQUIRED", "PROCESSING", "REJECTED", "DUPLICATE"],
  APPROVED: ["ARCHIVED", "REVIEW_REQUIRED"],
  ARCHIVED: ["PROCESSING"],
  REJECTED: ["REVIEW_REQUIRED", "PROCESSING"],
  DUPLICATE: ["REVIEW_REQUIRED", "PROCESSING"],
  ERROR: ["PROCESSING", "REJECTED"],
};

function reachable(from: DocumentStatus, to: DocumentStatus): boolean {
  return from !== to && ALLOWED_TRANSITIONS[from].includes(to);
}

/**
 * Un document arhivat nu se mai corectează pe loc: numele din arhivă codifică data,
 * tipul, clientul, seria și numărul (§10). Oglinda lui `is_editable`.
 */
function isEditable(status: DocumentStatus): boolean {
  return status !== "ARCHIVED";
}

/** Oglinda lui `app/domain/document_actions.py`. */
function availableActionsFor(doc: StoredDocument): DocumentAction[] {
  const has = (permission: Permission) => currentUser.permissions.includes(permission);
  const actions: DocumentAction[] = [];

  if (has("documents:write") && isEditable(doc.status)) actions.push("edit", "assignClient");
  if (has("documents:approve") && reachable(doc.status, "APPROVED")) actions.push("approve");
  if (has("documents:approve") && reachable(doc.status, "REJECTED")) actions.push("reject");
  if (has("documents:write") && reachable(doc.status, "DUPLICATE")) actions.push("markDuplicate");
  if (has("documents:write") && reprocessBlockedReason(doc) === null) actions.push("reprocess");
  if (has("documents:read")) actions.push("download");

  return actions;
}

/**
 * Limita de reprocesări, oglinda lui `settings.max_processing_attempts`. Un document
 * care a eșuat de trei ori nu se repară a patra oară.
 */
const MAX_PROCESSING_ATTEMPTS = 3;

/** Oglinda lui `reprocess_check` din `app/domain/document_actions.py`. */
function reprocessBlockedReason(doc: StoredDocument): string | null {
  if (doc.processingAttempts >= MAX_PROCESSING_ATTEMPTS) {
    return `Documentul a fost procesat de ${doc.processingAttempts} ori; limita configurată a fost atinsă.`;
  }
  if (!reachable(doc.status, "PROCESSING")) {
    return `Nu se poate reprocesa din starea ${doc.status}.`;
  }
  return null;
}

/** Ce mai lipsește pentru aprobare — aceleași motive pe care le-ar da API-ul real. */
function approvalBlockersFor(doc: StoredDocument): string[] {
  const blockers: string[] = [];
  if (!doc.clientId) blockers.push("Documentul nu are client atribuit.");
  const required = DOCUMENT_TYPES.find((t) => t.code === doc.documentTypeCode)?.requiredFields;
  const missing = (required ?? []).filter(
    (field) => !doc.fields[field as DocumentFieldName]?.value,
  );
  if (missing.length > 0) {
    blockers.push("Câmpuri obligatorii lipsă: " + missing.join(", "));
  }
  return blockers;
}

/**
 * Forma pe care o vede interfața.
 *
 * `storagePath` rămâne în starea internă, dar nu iese niciodată printr-un răspuns:
 * o cale de stocare nu are ce căuta într-un API (§73). Backendul real nu o trimite,
 * deci nici cel simulat nu are voie.
 */
export function toDetail(doc: StoredDocument): DocumentDetail {
  const { storagePath: _storagePath, ...detail } = doc;
  return {
    ...detail,
    availableActions: availableActionsFor(doc),
    approvalBlockers: approvalBlockersFor(doc),
    reprocessBlockedReason: reprocessBlockedReason(doc),
  };
}

function recordAudit(action: string, entityType: string, entityId: string, detail: string | null) {
  auditCounter += 1;
  state.audit.unshift({
    id: `audit-${auditCounter}`,
    at: MOCK_NOW,
    userName: currentUser.fullName,
    action,
    entityType,
    entityId,
    detail,
    ip: "127.0.0.1",
  });
}

/**
 * Recalculează perioada după ce un document își schimbă apartenența sau statusul.
 * Statusul se re-derivă odată cu contoarele — altfel badge-ul rămâne cel inițial
 * și ajunge să contrazică propriul checklist.
 */
function refreshPeriods() {
  for (const period of state.periods) {
    const docs = state.documents.filter(
      (d) => d.clientId === period.clientId && d.referenceMonth === period.referenceMonth,
    );
    period.receivedCount = docs.length;
    for (const item of period.checklist) {
      item.receivedCount = docs.filter((d) => d.documentTypeCode === item.documentType).length;
      item.isSatisfied = item.receivedCount >= item.expectedMinCount;
    }
    period.satisfiedCount = periodProgress(period.checklist).satisfied;
    period.status = derivePeriodStatus(
      period.checklist,
      period.receivedCount,
      period.referenceMonth < CURRENT_MONTH,
    );
  }
}

/* ─── Autentificare (simulată) ─────────────────────────────────────────────── */

/**
 * ATENȚIE: aceasta este o simulare pentru development. Nu există verificare reală
 * de parolă și nicio garanție de securitate — autorizarea efectivă se face în backend.
 */
let currentUser: CurrentUser = {
  id: USERS[0]!.id,
  fullName: USERS[0]!.fullName,
  email: USERS[0]!.email,
  role: USERS[0]!.role,
  permissions: ROLE_PERMISSIONS[USERS[0]!.role],
  organizationId: "org-1",
  organizationName: "Cabinet Contabil Demo SRL",
};

export function mockLogin(email: string): CurrentUser {
  const user = state.users.find((u) => u.email.toLowerCase() === email.trim().toLowerCase());
  if (!user) {
    throw new ApiError("UNAUTHORIZED", "Email sau parolă incorecte.", 401);
  }
  if (!user.isActive) {
    throw new ApiError("FORBIDDEN", "Contul este dezactivat.", 403);
  }
  currentUser = {
    id: user.id,
    fullName: user.fullName,
    email: user.email,
    role: user.role,
    permissions: ROLE_PERMISSIONS[user.role],
    organizationId: "org-1",
    organizationName: "Cabinet Contabil Demo SRL",
  };
  user.lastLoginAt = MOCK_NOW;
  recordAudit("USER_LOGIN", "User", user.id, user.email);
  return currentUser;
}

export function mockCurrentUser(): CurrentUser {
  return currentUser;
}

function requirePermission(permission: Permission) {
  if (!currentUser.permissions.includes(permission)) {
    throw new ApiError("FORBIDDEN", "Nu ai permisiunea necesară pentru această acțiune.", 403);
  }
}

/* ─── Clienți ──────────────────────────────────────────────────────────────── */

export type ClientFilters = {
  q?: string;
  status?: string;
  accountantId?: string;
  page?: number;
  pageSize?: number;
};

export function listClients(filters: ClientFilters): Paginated<Client> {
  let items = state.clients;
  if (filters.q) {
    items = items.filter((c) => matches([c.name, c.taxId, c.registrationNumber, c.address], filters.q!));
  }
  if (filters.status) items = items.filter((c) => c.status === filters.status);
  if (filters.accountantId) items = items.filter((c) => c.assignedAccountantId === filters.accountantId);
  return paginate([...items].sort((a, b) => a.name.localeCompare(b.name)), filters.page, filters.pageSize);
}

export function getClient(id: string): Client {
  return state.clients.find((c) => c.id === id) ?? notFound("Client", id);
}

export function listContacts(clientId: string): Contact[] {
  return state.contacts.filter((c) => c.clientId === clientId);
}

export function listNotes(clientId: string): ClientNote[] {
  return state.notes.filter((n) => n.clientId === clientId);
}

/** Cât poate avea o notă. Oglindește `MAX_NOTE_LENGTH` din backend. */
const MOCK_MAX_NOTE_LENGTH = 4000;

/**
 * Scrie o notă internă pe client.
 *
 * **Autorul se păstrează ca text**, nu ca legătură: cine a scris o notă nu
 * trebuie să dispară odată cu contul lui.
 *
 * Nu există modificare și nu există ștergere, deliberat: o notă este o
 * consemnare, iar una care se poate rescrie nu mai este una.
 */
export function createNote(clientId: string, body: string): ClientNote {
  requirePermission("clients:write");
  getClient(clientId);

  const text = body.trim();
  if (!text) {
    throw new ApiError("VALIDATION_ERROR", "Nota nu poate fi goală.", 422, {
      body: ["Text obligatoriu."],
    });
  }
  if (text.length > MOCK_MAX_NOTE_LENGTH) {
    throw new ApiError(
      "VALIDATION_ERROR",
      `Nota depășește ${MOCK_MAX_NOTE_LENGTH} de caractere.`,
      422,
      { body: ["Text prea lung."] },
    );
  }

  const note: ClientNote = {
    id: `note-${state.notes.length + 1}-${Date.now()}`,
    clientId,
    authorName: currentUser.fullName,
    body: text,
    createdAt: new Date().toISOString(),
  };
  // Cele mai noi primele, ca în listă.
  state.notes.unshift(note);
  // Jurnalul spune **că** s-a scris o notă, nu ce scrie în ea.
  recordAudit("CLIENT_NOTE_ADDED", "Client", clientId, `Notă pe ${getClient(clientId).name}`);
  return note;
}

/**
 * `RO14399840` și `14399840` sunt același cod fiscal.
 *
 * Oglindește `client_matching.normalize_tax_id` din backend. Fără normalizare,
 * aceeași firmă ar putea fi adăugată de două ori, iar identificarea automată a
 * clientului ar găsi apoi doi candidați și n-ar mai atribui niciun document.
 */
function normalizeTaxId(raw: string | null | undefined): string {
  const cleaned = (raw ?? "").toUpperCase().replace(/[\s.-]/g, "");
  const digits = cleaned.startsWith("RO") ? cleaned.slice(2) : cleaned;
  return digits.replace(/^0+/, "");
}

export type ClientInput = {
  name?: string;
  taxId?: string | null;
  registrationNumber?: string | null;
  address?: string | null;
  status?: ClientStatus;
  assignedAccountantId?: string | null;
};

function cleanText(raw: string | null | undefined): string | null {
  const text = (raw ?? "").trim();
  return text || null;
}

function assertTaxIdIsFree(taxId: string | null, exceptId: string | null) {
  if (!taxId) return;
  const wanted = normalizeTaxId(taxId);
  if (!wanted) return;
  const owner = state.clients.find(
    (c) => c.id !== exceptId && normalizeTaxId(c.taxId) === wanted,
  );
  if (owner) {
    throw new ApiError("CONFLICT", `CUI-ul ${taxId} aparține deja clientului ${owner.name}.`, 409, {
      taxId: ["CUI folosit deja."],
    });
  }
}

function requiredText(raw: string | null | undefined, field: string, label: string): string {
  const text = (raw ?? "").trim();
  if (!text) {
    throw new ApiError("VALIDATION_ERROR", `${label} este obligatorie.`, 422, {
      [field]: ["Câmp obligatoriu."],
    });
  }
  return text;
}

export function createClient(input: ClientInput): Client {
  requirePermission("clients:write");
  const name = requiredText(input.name, "name", "Denumirea");
  const taxId = cleanText(input.taxId);
  assertTaxIdIsFree(taxId, null);

  const accountant = input.assignedAccountantId
    ? (state.users.find((u) => u.id === input.assignedAccountantId) ?? null)
    : null;

  const client: Client = {
    id: `client-${state.clients.length + 1}-${Date.now()}`,
    name,
    taxId: taxId ?? "",
    registrationNumber: cleanText(input.registrationNumber) ?? "",
    address: cleanText(input.address) ?? "",
    // ACTIV, nu PROSPECT: cine adaugă un client îi ține contabilitatea.
    status: input.status ?? "ACTIVE",
    assignedAccountantId: accountant?.id ?? null,
    assignedAccountantName: accountant?.fullName ?? null,
    tags: [],
    lastInteractionAt: null,
    createdAt: new Date(MOCK_NOW).toISOString(),
  };
  state.clients.push(client);
  recordAudit("CLIENT_CREATED", "Client", client.id, client.name);
  return client;
}

export function updateClient(id: string, input: ClientInput): Client {
  requirePermission("clients:write");
  const client = getClient(id);
  let changed = false;

  if ("name" in input) {
    client.name = requiredText(input.name, "name", "Denumirea");
    changed = true;
  }
  if ("taxId" in input) {
    const taxId = cleanText(input.taxId);
    assertTaxIdIsFree(taxId, client.id);
    client.taxId = taxId ?? "";
    changed = true;
  }
  if ("registrationNumber" in input) {
    client.registrationNumber = cleanText(input.registrationNumber) ?? "";
    changed = true;
  }
  if ("address" in input) {
    client.address = cleanText(input.address) ?? "";
    changed = true;
  }
  if (input.status) {
    client.status = input.status;
    changed = true;
  }
  if ("assignedAccountantId" in input) {
    const accountant = input.assignedAccountantId
      ? (state.users.find((u) => u.id === input.assignedAccountantId) ?? null)
      : null;
    client.assignedAccountantId = accountant?.id ?? null;
    client.assignedAccountantName = accountant?.fullName ?? null;
    changed = true;
  }

  if (changed) recordAudit("CLIENT_UPDATED", "Client", client.id, client.name);
  return client;
}

export type ContactInput = {
  fullName?: string;
  role?: string | null;
  email?: string | null;
  phone?: string | null;
  whatsappNumber?: string | null;
  isPrimary?: boolean;
  isActive?: boolean;
};

/**
 * Aceeași adresă la doi clienți nu produce nicio eroare la preluare — doar o
 * oprește: `MailSyncService` scoate din hartă adresele ambigue, pentru că nu are
 * cum să aleagă. Documentele nu ar mai ajunge la nimeni.
 */
function assertEmailIsFree(email: string | null, exceptId: string | null) {
  if (!email) return;
  const owner = state.contacts.find((c) => c.id !== exceptId && c.email === email);
  if (!owner) return;
  const client = state.clients.find((c) => c.id === owner.clientId);
  throw new ApiError(
    "CONFLICT",
    `Adresa ${email} este deja contactul clientului ${client?.name ?? "necunoscut"}. ` +
      "Două contacte cu aceeași adresă opresc atribuirea automată a emailurilor.",
    409,
    { email: ["Adresă folosită deja."] },
  );
}

/** Litere mici: potrivirea expeditorului se face pe adresa normalizată (§8). */
function normalizeEmail(raw: string | null | undefined): string | null {
  const email = cleanText(raw);
  return email ? email.toLowerCase() : null;
}

function demoteOtherPrimaries(clientId: string, keep: string) {
  for (const other of state.contacts) {
    if (other.clientId === clientId && other.id !== keep) other.isPrimary = false;
  }
}

export function createContact(clientId: string, input: ContactInput): Contact {
  requirePermission("clients:write");
  getClient(clientId);
  const email = normalizeEmail(input.email);
  assertEmailIsFree(email, null);

  const contact: Contact = {
    id: `contact-${state.contacts.length + 1}-${Date.now()}`,
    clientId,
    fullName: requiredText(input.fullName, "fullName", "Numele"),
    role: cleanText(input.role) ?? "",
    email,
    phone: cleanText(input.phone),
    whatsappNumber: cleanText(input.whatsappNumber),
    isPrimary: input.isPrimary ?? false,
    isActive: input.isActive ?? true,
  };
  state.contacts.push(contact);
  if (contact.isPrimary) demoteOtherPrimaries(clientId, contact.id);
  recordAudit("CONTACT_CREATED", "Contact", contact.id, contact.fullName);
  return contact;
}

export function updateContact(clientId: string, contactId: string, input: ContactInput): Contact {
  requirePermission("clients:write");
  getClient(clientId);
  const contact = state.contacts.find((c) => c.id === contactId && c.clientId === clientId);
  if (!contact) return notFound("Contact", contactId);

  if ("fullName" in input) contact.fullName = requiredText(input.fullName, "fullName", "Numele");
  if ("role" in input) contact.role = cleanText(input.role) ?? "";
  if ("email" in input) {
    const email = normalizeEmail(input.email);
    assertEmailIsFree(email, contact.id);
    contact.email = email;
  }
  if ("phone" in input) contact.phone = cleanText(input.phone);
  if ("whatsappNumber" in input) contact.whatsappNumber = cleanText(input.whatsappNumber);
  if (input.isActive !== undefined) contact.isActive = input.isActive;
  if (input.isPrimary) {
    contact.isPrimary = true;
    demoteOtherPrimaries(clientId, contact.id);
  }

  recordAudit("CONTACT_UPDATED", "Contact", contact.id, contact.fullName);
  return contact;
}

export function listClientPeriods(clientId: string) {
  return state.periods
    .filter((p) => p.clientId === clientId)
    .sort((a, b) => b.referenceMonth.localeCompare(a.referenceMonth));
}

/* ─── Documente ────────────────────────────────────────────────────────────── */

export type DocumentFilters = {
  q?: string;
  clientId?: string;
  status?: string;
  source?: string;
  type?: string;
  referenceMonth?: string;
  year?: string;
  reviewRequired?: string;
  duplicatesOnly?: string;
  minConfidence?: string;
  maxConfidence?: string;
  page?: number;
  pageSize?: number;
  sort?: string;
  order?: "asc" | "desc";
};

/* ─── Încărcare (§38) ──────────────────────────────────────────────────────── */

/**
 * Cât „durează" procesarea în demonstrație.
 *
 * Aici nu există worker. Un document urcat rămâne `RECEIVED` până când cineva îl
 * citește după acest prag — nu printr-un cronometru, ci pentru că fiecare citire
 * verifică întâi ce s-a scurs. Efectul pentru interfață este identic cu cel real:
 * ecranul se reîmprospătează singur cât timp documentul este în lucru și se
 * oprește când ajunge într-o stare care așteaptă un om.
 */
const MOCK_PROCESSING_MS = 2500;

/**
 * Limitele de mai jos **simulează** serverul, nu îl înlocuiesc.
 *
 * Serverul adevărat stabilește tipul din primii octeți ai fișierului, nu din ce
 * declară browserul (§50), recunoaște duplicatele după SHA-256 și își ia limita
 * de dimensiune din configurare. Aici nu avem octeți — avem doar ce spune
 * fișierul despre sine, așa că un fișier redenumit `.pdf` trece, iar același
 * document urcat de două ori nu este văzut ca duplicat. Este limita simulării și
 * e scrisă unde se vede.
 */
const MOCK_MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const MOCK_ACCEPTED_MIME = new Set([
  "application/pdf",
  // Factura electronică (e-Factura, UBL 2.1). Serverul adevărat o recunoaște din
  // declarația `<?xml`, nu din ce spune browserul — aici nu avem octeți.
  "application/xml",
  "text/xml",
  "image/jpeg",
  "image/png",
  "image/webp",
]);

/** Documentele urcate în sesiunea curentă și momentul de la care „s-au procesat". */
const processingDeadlines = new Map<string, number>();

let uploadCounter = 0;

export type UploadInput = { filename: string; size: number; mimeType: string };

/**
 * Promovează documentele urcate cărora le-a trecut „procesarea".
 *
 * Se cheamă din fiecare drum de citire. Un cronometru ar fi părut mai direct, dar
 * ar continua să bată după ce componenta a dispărut și ar face testele să depindă
 * de ceasul real.
 */
function settleProcessing() {
  if (processingDeadlines.size === 0) return;
  const now = Date.now();

  for (const [id, deadline] of processingDeadlines) {
    if (now < deadline) continue;
    processingDeadlines.delete(id);

    const document = state.documents.find((d) => d.id === id);
    if (!document) continue;

    // Providerul simulat inventează valori — la fel ca `OCR_PROVIDER=mock` pe
    // server. Ce iese de aici nu este citit de pe document, iar ecranul de
    // verificare o spune: fiecare câmp își poartă proveniența.
    const fields = buildFields("FACTURA_INTRARE", null, MOCK_NOW.slice(0, 10), CURRENT_MONTH, 0.82);
    document.fields = fields;
    document.status = "REVIEW_REQUIRED";
    document.reviewRequired = true;
    document.confidence = 0.82;
    document.processingAttempts = 1;
    document.documentTypeCode = fields.documentType.value;
    document.documentTypeLabel = fields.documentType.value
      ? (DOCUMENT_TYPE_LABEL.get(fields.documentType.value) ?? null)
      : null;
    document.documentDate = fields.documentDate.value;
    document.referenceMonth = fields.referenceMonth.value;
    document.supplierName = fields.supplierName.value;
    document.documentNumber = fields.documentNumber.value;
    document.totalAmount = fields.totalAmount.value;
    document.currency = fields.currency.value;
    document.ocr = {
      provider: "mock",
      confidence: 0.82,
      textPreview: `FACTURA FISCALA\nFurnizor: ${fields.supplierName.value ?? "-"}\nTotal de plata: ${fields.totalAmount.value ?? "-"} RON`,
    };
    document.validationIssues = ["Încredere sub pragul automat (82%)"];
    document.history.push({
      id: `${document.id}-h2`,
      at: new Date().toISOString(),
      actor: "Sistem",
      action: "EXTRACTION_COMPLETED",
      detail: "Extracție finalizată (confidence 82%)",
    });
  }
}

export function uploadDocument(input: UploadInput): StoredDocument {
  requirePermission("documents:write");

  if (input.size === 0) {
    throw new ApiError("VALIDATION_ERROR", "Fișierul este gol.", 422, {
      file: ["Fișierul este gol."],
    });
  }
  if (input.size > MOCK_MAX_UPLOAD_BYTES) {
    throw new ApiError(
      "VALIDATION_ERROR",
      `Fișierul depășește limita de ${MOCK_MAX_UPLOAD_BYTES / (1024 * 1024)} MB.`,
      422,
      { file: ["Fișier prea mare."] },
    );
  }
  if (!MOCK_ACCEPTED_MIME.has(input.mimeType)) {
    throw new ApiError(
      "VALIDATION_ERROR",
      "Tip de fișier neacceptat. Se acceptă PDF, XML (e-Factura), JPEG, PNG și WEBP.",
      422,
      { file: ["Tip neacceptat."] },
    );
  }

  uploadCounter += 1;
  const id = `doc-upload-${uploadCounter}`;
  const at = new Date().toISOString();

  // Un document proaspăt urcat nu are niciun câmp citit: proveniența fiecăruia
  // este `EMPTY`, nu `AI` cu valoare nulă. Diferența se vede pe ecran.
  const fields = buildFields("FACTURA_INTRARE", null, at.slice(0, 10), CURRENT_MONTH, 0);
  for (const key of Object.keys(fields) as (keyof typeof fields)[]) {
    fields[key] = { value: null, source: "EMPTY", confidence: null } as never;
  }

  const document: StoredDocument = {
    id,
    originalFilename: input.filename,
    storedFilename: null,
    clientId: null,
    clientName: null,
    documentTypeCode: null,
    documentTypeLabel: null,
    source: "UPLOAD",
    receivedAt: at,
    documentDate: null,
    referenceMonth: null,
    supplierName: null,
    documentNumber: null,
    totalAmount: null,
    currency: null,
    status: "RECEIVED",
    confidence: null,
    isDuplicate: false,
    reviewRequired: false,
    mimeType: input.mimeType,
    fileSize: input.size,
    // Serverul calculează hash-ul în timp ce citește octeții; aici nu îi avem.
    sha256: id.padEnd(64, "0"),
    storagePath: null,
    duplicateOfId: null,
    errorCode: null,
    processingAttempts: 0,
    fields,
    ocr: { provider: "mock", confidence: null, textPreview: null },
    extraction: {
      provider: "mock",
      model: "mock-extractor",
      promptVersion: "v1",
      durationMs: null,
    },
    validationIssues: [],
    // Un fișier încărcat de om este unul singur. Lista are conținut doar pentru
    // factura electronică din SPV, care vine cu trei.
    files: [],
    history: [
      {
        id: `${id}-h1`,
        at,
        actor: currentUser.fullName,
        action: "DOCUMENT_UPLOADED",
        detail: input.filename,
      },
    ],
  };

  state.documents.unshift(document);
  processingDeadlines.set(id, Date.now() + MOCK_PROCESSING_MS);
  recordAudit("DOCUMENT_UPLOADED", "Document", id, input.filename);
  return document;
}

export function listDocuments(filters: DocumentFilters): Paginated<DocumentListItem> {
  settleProcessing();
  let items = state.documents;

  if (filters.q) {
    items = items.filter((d) =>
      matches(
        [
          d.originalFilename,
          d.storedFilename,
          d.clientName,
          d.supplierName,
          d.documentNumber,
          // Și ce scrie **în** document. Toate celelalte sunt *despre* el.
          // Serverul caută în `ocr_text` întreg, cu index de căutare integrală;
          // aici avem doar fragmentul, dar semantica este aceeași: căsuța de
          // căutare găsește și documentele al căror text conține termenul.
          d.ocr.textPreview,
        ],
        filters.q!,
      ),
    );
  }
  if (filters.clientId) items = items.filter((d) => d.clientId === filters.clientId);
  if (filters.status) {
    const wanted = filters.status.split(",");
    items = items.filter((d) => wanted.includes(d.status));
  }
  if (filters.source) items = items.filter((d) => d.source === filters.source);
  if (filters.type) items = items.filter((d) => d.documentTypeCode === filters.type);
  if (filters.referenceMonth) items = items.filter((d) => d.referenceMonth === filters.referenceMonth);
  if (filters.year) items = items.filter((d) => d.referenceMonth?.startsWith(filters.year!));
  if (filters.reviewRequired === "true") items = items.filter((d) => d.reviewRequired);
  if (filters.duplicatesOnly === "true") items = items.filter((d) => d.isDuplicate);
  if (filters.minConfidence) {
    const min = Number(filters.minConfidence);
    items = items.filter((d) => d.confidence !== null && d.confidence >= min);
  }
  if (filters.maxConfidence) {
    const max = Number(filters.maxConfidence);
    items = items.filter((d) => d.confidence !== null && d.confidence <= max);
  }

  const sortKey = filters.sort ?? "receivedAt";
  const direction = filters.order === "asc" ? 1 : -1;
  const sorted = [...items].sort((a, b) => {
    const av = String(a[sortKey as keyof DocumentListItem] ?? "");
    const bv = String(b[sortKey as keyof DocumentListItem] ?? "");
    return av.localeCompare(bv) * direction;
  });

  return paginate(sorted.map(toListItem), filters.page, filters.pageSize);
}

export function getDocument(id: string): StoredDocument {
  settleProcessing();
  return state.documents.find((d) => d.id === id) ?? notFound("Document", id);
}

/** Următorul document care așteaptă verificare — pentru fluxul rapid al operatorului (§67). */
export function nextReviewDocument(afterId?: string): DocumentDetail | null {
  const queue = state.documents.filter(
    (d) => d.status === "REVIEW_REQUIRED" || d.status === "UNMATCHED",
  );
  // `after` scoate din coadă documentul tocmai închis, ca operatorul să nu revină pe el.
  const next = afterId ? queue.find((d) => d.id !== afterId) : queue[0];
  return next ? toDetail(next) : null;
}

export type FieldUpdate = { field: DocumentFieldName; value: string | null };

/** Oglinda lui `DocumentService._assert_editable`. */
function requireEditable(doc: StoredDocument) {
  if (!isEditable(doc.status)) {
    throw new ApiError(
      "CONFLICT",
      `Documentul este ${doc.status} și nu mai poate fi modificat direct. ` +
        "Cere o reprocesare dacă datele trebuie corectate.",
      409,
    );
  }
}

export function updateDocumentFields(id: string, updates: FieldUpdate[]): StoredDocument {
  requirePermission("documents:write");
  const doc = getDocument(id);
  requireEditable(doc);
  for (const { field, value } of updates) {
    const previous = doc.fields[field];
    if (previous.value === value) continue;
    // Orice corectură umană devine sursă MANUAL și rămâne în istoric (§2).
    doc.fields[field] = { value, source: "MANUAL", confidence: null } as never;
    doc.history.push({
      id: `h-${doc.id}-${doc.history.length + 1}`,
      at: MOCK_NOW,
      actor: currentUser.fullName,
      action: "FIELD_CORRECTED",
      detail: `${field}: „${previous.value ?? "—"}" → „${value ?? "—"}"`,
    });
  }
  syncDocumentSummary(doc);
  recordAudit("DOCUMENT_UPDATED", "Document", doc.id, doc.originalFilename);
  return doc;
}

/** Câmpurile de listă derivă din câmpurile extrase — le ținem sincronizate. */
function syncDocumentSummary(doc: StoredDocument) {
  doc.documentTypeCode = doc.fields.documentType.value;
  doc.documentTypeLabel = doc.fields.documentType.value
    ? (DOCUMENT_TYPE_LABEL.get(doc.fields.documentType.value) ?? null)
    : null;
  doc.documentDate = doc.fields.documentDate.value;
  doc.referenceMonth = doc.fields.referenceMonth.value;
  doc.supplierName = doc.fields.supplierName.value;
  doc.documentNumber = doc.fields.documentNumber.value;
  doc.totalAmount = doc.fields.totalAmount.value;
  doc.currency = doc.fields.currency.value;
}

export function assignClient(id: string, clientId: string): StoredDocument {
  requirePermission("documents:write");
  const doc = getDocument(id);
  requireEditable(doc);
  const client = getClient(clientId);
  doc.clientId = client.id;
  doc.clientName = client.name;
  doc.fields.customerName = { value: client.name, source: "MANUAL", confidence: null };
  if (doc.status === "UNMATCHED") doc.status = "REVIEW_REQUIRED";
  doc.validationIssues = doc.validationIssues.filter(
    (issue) => !issue.includes("Expeditorul nu este mapat"),
  );
  doc.history.push({
    id: `h-${doc.id}-${doc.history.length + 1}`,
    at: MOCK_NOW,
    actor: currentUser.fullName,
    action: "DOCUMENT_REASSIGNED",
    detail: `Atribuit clientului ${client.name}`,
  });
  recordAudit("DOCUMENT_REASSIGNED", "Document", doc.id, client.name);
  refreshPeriods();
  return doc;
}

/** Verificările care blochează aprobarea (§17). */
export function validateForApproval(doc: StoredDocument): string[] {
  const errors: string[] = [];
  if (!doc.clientId) errors.push("Documentul nu are client atribuit.");
  const typeCode = doc.fields.documentType.value;
  if (!typeCode) errors.push("Tipul documentului nu este stabilit.");
  const type = DOCUMENT_TYPES.find((t) => t.code === typeCode);
  for (const required of type?.requiredFields ?? []) {
    const value = doc.fields[required as DocumentFieldName]?.value;
    if (!value) {
      errors.push(`Câmp obligatoriu lipsă pentru ${type?.label}: ${required}`);
    }
  }
  return errors;
}

/**
 * Numele sub care documentul intră în arhivă. Regulile de sanitizare trăiesc în
 * `@/lib/filename` — aceleași care trebuie implementate în `FilenameGeneratorService`
 * din backend. La coliziune în același director se adaugă un sufix numeric (R7).
 */
function archiveFilename(doc: StoredDocument): string {
  const input: FilenameInput = {
    documentDate: doc.fields.documentDate.value,
    documentTypeLabel: doc.documentTypeLabel,
    clientName: doc.clientName,
    series: doc.fields.series.value,
    documentNumber: doc.fields.documentNumber.value,
    originalFilename: doc.originalFilename,
    mimeType: doc.mimeType,
  };

  const taken = new Set(
    state.documents
      .filter((other) => other.id !== doc.id && other.storagePath === doc.storagePath)
      .map((other) => other.storedFilename),
  );

  let candidate = buildDocumentFilename(input);
  for (let suffix = 2; taken.has(candidate); suffix += 1) {
    candidate = buildDocumentFilename({ ...input, collisionSuffix: suffix });
  }
  return candidate;
}

export function approveDocument(id: string): StoredDocument {
  requirePermission("documents:approve");
  const doc = getDocument(id);
  const errors = validateForApproval(doc);
  if (errors.length > 0) {
    throw new ApiError("VALIDATION_ERROR", "Documentul nu poate fi aprobat.", 422, {
      document: errors,
    });
  }
  doc.status = "ARCHIVED";
  doc.reviewRequired = false;
  doc.validationIssues = [];
  doc.storagePath = buildArchivePath(doc.referenceMonth, doc.clientName);
  doc.storedFilename = archiveFilename(doc);
  doc.history.push({
    id: `h-${doc.id}-${doc.history.length + 1}`,
    at: MOCK_NOW,
    actor: currentUser.fullName,
    action: "DOCUMENT_APPROVED",
    detail: `Arhivat ca ${doc.storedFilename}`,
  });
  recordAudit("DOCUMENT_APPROVED", "Document", doc.id, doc.storedFilename);
  refreshPeriods();
  return doc;
}

export function rejectDocument(id: string, reason: string): StoredDocument {
  requirePermission("documents:approve");
  const doc = getDocument(id);
  if (!reason.trim()) {
    throw new ApiError("VALIDATION_ERROR", "Motivul respingerii este obligatoriu.", 422, {
      reason: ["Câmp obligatoriu."],
    });
  }
  doc.status = "REJECTED";
  doc.reviewRequired = false;
  doc.history.push({
    id: `h-${doc.id}-${doc.history.length + 1}`,
    at: MOCK_NOW,
    actor: currentUser.fullName,
    action: "DOCUMENT_REJECTED",
    detail: reason,
  });
  recordAudit("DOCUMENT_REJECTED", "Document", doc.id, reason);
  refreshPeriods();
  return doc;
}

export function markDuplicate(id: string, duplicateOfId: string | null): StoredDocument {
  requirePermission("documents:write");
  const doc = getDocument(id);
  doc.status = "DUPLICATE";
  doc.isDuplicate = true;
  doc.reviewRequired = false;
  doc.duplicateOfId = duplicateOfId;
  doc.history.push({
    id: `h-${doc.id}-${doc.history.length + 1}`,
    at: MOCK_NOW,
    actor: currentUser.fullName,
    action: "DOCUMENT_MARKED_DUPLICATE",
    detail: duplicateOfId ? `Duplicat al ${duplicateOfId}` : "Marcat manual ca duplicat",
  });
  recordAudit("DOCUMENT_MARKED_DUPLICATE", "Document", doc.id, duplicateOfId);
  refreshPeriods();
  return doc;
}

export function reprocessDocument(id: string): StoredDocument {
  requirePermission("documents:write");
  const doc = getDocument(id);
  doc.status = "PROCESSING";
  doc.history.push({
    id: `h-${doc.id}-${doc.history.length + 1}`,
    at: MOCK_NOW,
    actor: currentUser.fullName,
    action: "DOCUMENT_REPROCESS_QUEUED",
    detail: "Reprocesare cerută manual",
  });
  recordAudit("DOCUMENT_REPROCESS_QUEUED", "Document", doc.id, doc.originalFilename);
  return doc;
}

export type BulkAction =
  | { action: "approve" }
  | { action: "reject"; reason: string }
  | { action: "assignClient"; clientId: string }
  | { action: "markDuplicate" }
  | { action: "reprocess" };

export type BulkResult = {
  succeeded: string[];
  failed: Array<{ id: string; message: string }>;
};

/** Operațiile în masă sunt autorizate și auditate individual (§60). */
export function bulkDocuments(ids: string[], payload: BulkAction): BulkResult {
  const result: BulkResult = { succeeded: [], failed: [] };
  for (const id of ids) {
    try {
      switch (payload.action) {
        case "approve":
          approveDocument(id);
          break;
        case "reject":
          rejectDocument(id, payload.reason);
          break;
        case "assignClient":
          assignClient(id, payload.clientId);
          break;
        case "markDuplicate":
          markDuplicate(id, null);
          break;
        case "reprocess":
          reprocessDocument(id);
          break;
      }
      result.succeeded.push(id);
    } catch (error) {
      result.failed.push({
        id,
        message: error instanceof Error ? error.message : "Eroare necunoscută",
      });
    }
  }
  return result;
}

/* ─── Perioade ─────────────────────────────────────────────────────────────── */

export function listPeriods(filters: { referenceMonth?: string; clientId?: string; status?: string }) {
  let items = state.periods;
  if (filters.referenceMonth) items = items.filter((p) => p.referenceMonth === filters.referenceMonth);
  if (filters.clientId) items = items.filter((p) => p.clientId === filters.clientId);
  if (filters.status) items = items.filter((p) => p.status === filters.status);
  return [...items].sort((a, b) => a.clientName.localeCompare(b.clientName));
}

/** Ziua din luna următoare până la care se depun declarațiile (`FILING_DEADLINE_DAY`). */
const MOCK_DEADLINE_DAY = 25;

/**
 * Termenul de depunere al unei luni, „YYYY-MM-DD".
 *
 * Este în luna **următoare**: documentele lui august se depun până pe 25
 * septembrie. Ziua este mărginită la 28 în configurare, deci există în orice
 * lună — inclusiv februarie. Oglindește `filing_deadline()` din backend.
 */
export function filingDeadline(referenceMonth: string): string {
  const [year, month] = referenceMonth.split("-").map(Number) as [number, number];
  const day = String(MOCK_DEADLINE_DAY).padStart(2, "0");
  return month === 12
    ? `${year + 1}-01-${day}`
    : `${year}-${String(month + 1).padStart(2, "0")}-${day}`;
}

/** Documentele așteptate care încă lipsesc, per client (§19). */
export function listMissingDocuments(referenceMonth: string) {
  const deadline = filingDeadline(referenceMonth);
  return listPeriods({ referenceMonth })
    .map((period) => ({
      period,
      missing: period.checklist.filter((item) => !item.isSatisfied),
      deadline,
    }))
    .filter((entry) => entry.missing.length > 0);
}

/* ─── Rapoarte (§84) ───────────────────────────────────────────────────────── */

/**
 * Oglinda lui `ReportService` din backend.
 *
 * Regulile sunt aceleași și trebuie să rămână aceleași: ce se numără drept
 * „procesat", ce se întâmplă când nu s-a terminat nimic, unde ajung documentele
 * fără lună sau fără client. Dacă cele două se despart, demonstrația arată
 * altceva decât aplicația — exact genul de diferență care se descoperă târziu.
 *
 * Un lucru **nu** se oglindește, deliberat: plafonul de 200. Acolo era greșeala
 * pe care mutarea în backend a reparat-o, iar aici numărăm tot.
 */

/** „Procesat" = sistemul a terminat, indiferent dacă a ieșit bine. */
const IN_PROGRESS: DocumentStatus[] = ["RECEIVED", "PROCESSING"];

/** Câți clienți intră în clasament; restul sunt raportați ca număr. */
const TOP_CLIENTS = 10;

function tally(
  documents: StoredDocument[],
  key: (doc: StoredDocument) => { key: string | null; label: string | null },
): ReportBucket[] {
  const buckets = new Map<string, ReportBucket>();
  for (const doc of documents) {
    const { key: bucketKey, label } = key(doc);
    // `null` are nevoie de o cheie proprie în hartă, altfel s-ar amesteca cu
    // documentele care chiar au valoarea "null" ca text.
    const id = bucketKey ?? "\0absent";
    const existing = buckets.get(id);
    if (existing) existing.count += 1;
    else buckets.set(id, { key: bucketKey, label, count: 1 });
  }
  return [...buckets.values()];
}

function byCountDesc(a: ReportBucket, b: ReportBucket): number {
  return b.count - a.count || (a.label ?? "").localeCompare(b.label ?? "");
}

export function reportSummary(filters: {
  fromMonth?: string;
  toMonth?: string;
  clientId?: string;
}): ReportSummary {
  requirePermission("documents:read");

  let items = state.documents;
  // Un document fără lună nu intră într-un interval de luni: nu se poate spune
  // că este înainte sau după.
  if (filters.fromMonth) {
    items = items.filter((d) => d.referenceMonth !== null && d.referenceMonth >= filters.fromMonth!);
  }
  if (filters.toMonth) {
    items = items.filter((d) => d.referenceMonth !== null && d.referenceMonth <= filters.toMonth!);
  }
  if (filters.clientId) items = items.filter((d) => d.clientId === filters.clientId);

  const total = items.length;
  const processed = items.filter((d) => !IN_PROGRESS.includes(d.status)).length;
  const failed = items.filter((d) => d.status === "ERROR").length;

  const byMonth = tally(items, (d) => ({ key: d.referenceMonth, label: d.referenceMonth }));
  const dated = byMonth.filter((b) => b.key !== null).sort((a, b) => b.key!.localeCompare(a.key!));
  const undated = byMonth.filter((b) => b.key === null);

  const byClient = tally(items, (d) => ({ key: d.clientId, label: d.clientName })).sort(byCountDesc);

  return {
    total,
    processed,
    failed,
    duplicates: items.filter((d) => d.isDuplicate).length,
    // `null`, nu zero: zero s-ar citi ca „totul a eșuat".
    successRate: processed === 0 ? null : (processed - failed) / processed,
    byStatus: tally(items, (d) => ({ key: d.status, label: null })).sort(byCountDesc),
    // Luna recentă prima, documentele fără lună la coadă.
    byMonth: [...dated, ...undated],
    byType: tally(items, (d) => ({ key: d.documentTypeCode, label: d.documentTypeLabel })).sort(
      byCountDesc,
    ),
    byClient: byClient.slice(0, TOP_CLIENTS),
    clientCount: byClient.length,
  };
}

/* ─── Sarcini ──────────────────────────────────────────────────────────────── */

export function listTasks(filters: { status?: string; assignedToId?: string; clientId?: string }) {
  let items = state.tasks;
  if (filters.status) items = items.filter((t) => t.status === filters.status);
  if (filters.assignedToId) items = items.filter((t) => t.assignedToId === filters.assignedToId);
  if (filters.clientId) items = items.filter((t) => t.clientId === filters.clientId);
  const order = { TODO: 0, IN_PROGRESS: 1, BLOCKED: 2, DONE: 3 };
  return [...items].sort((a, b) => order[a.status] - order[b.status]);
}

export function updateTaskStatus(id: string, status: Task["status"]): Task {
  requirePermission("tasks:write");
  const task = state.tasks.find((t) => t.id === id) ?? notFound("Sarcină", id);
  task.status = status;
  task.completedAt = status === "DONE" ? MOCK_NOW : null;
  recordAudit("TASK_UPDATED", "Task", task.id, `${task.title} → ${status}`);
  return task;
}

/* ─── Audit, utilizatori, mesaje ───────────────────────────────────────────── */

export function listAudit(filters: { q?: string; action?: string; page?: number; pageSize?: number }) {
  requirePermission("audit:read");
  let items = state.audit;
  if (filters.q) items = items.filter((a) => matches([a.userName, a.detail, a.entityId], filters.q!));
  if (filters.action) items = items.filter((a) => a.action === filters.action);
  return paginate(items, filters.page, filters.pageSize);
}

/** Oglinda lui `GET /roles`: aceeași hartă pe care o folosește și autorizarea. */
export function listRoles(): RoleInfo[] {
  requirePermission("admin:users");
  return ROLE_CODE.map((code) => ({
    code,
    label: ROLE_LABEL[code],
    permissions: ROLE_PERMISSIONS[code],
  }));
}

export function listUsers(): UserSummary[] {
  requirePermission("admin:users");
  return state.users;
}

/** Aceeași lungime minimă ca la `create-admin`. Oglindește `MIN_PASSWORD_LENGTH`. */
const MOCK_MIN_PASSWORD_LENGTH = 12;

/**
 * Adaugă un coleg.
 *
 * Parola o pune administratorul și o comunică el: nu există invitație prin email
 * (nu există provider), iar o parolă generată și afișată nu mai este un secret.
 */
export function createUser(input: {
  email: string;
  fullName: string;
  role: RoleCode;
  password: string;
}): UserSummary {
  requirePermission("admin:users");

  const email = normalizeEmail(input.email);
  if (!email) {
    throw new ApiError("VALIDATION_ERROR", "Adresă de email invalidă.", 422, {
      email: ["Adresă invalidă."],
    });
  }
  if (!input.fullName.trim()) {
    throw new ApiError("VALIDATION_ERROR", "Numele este obligatoriu.", 422, {
      fullName: ["Câmp obligatoriu."],
    });
  }
  if (input.password.length < MOCK_MIN_PASSWORD_LENGTH) {
    throw new ApiError(
      "VALIDATION_ERROR",
      `Parola are minimum ${MOCK_MIN_PASSWORD_LENGTH} caractere.`,
      422,
      { password: ["Prea scurtă."] },
    );
  }
  if (state.users.some((row) => normalizeEmail(row.email) === email)) {
    throw new ApiError("CONFLICT", `Adresa ${email} este deja folosită în cabinet.`, 409);
  }

  const user: UserSummary = {
    id: `user-${state.users.length + 1}-${Date.now()}`,
    fullName: input.fullName.trim(),
    email,
    role: input.role,
    isActive: true,
    lastLoginAt: null,
  };
  state.users.push(user);
  // Parola nu se păstrează nicăieri: backendul simulat nu verifică parole.
  recordAudit("USER_CREATED", "User", user.id, `${user.fullName} (${email}) · ${input.role}`);
  return user;
}

/** Schimbă rolul, numele, sau dezactivează contul. Nu există ștergere. */
export function updateUser(
  id: string,
  input: { fullName?: string; role?: RoleCode; isActive?: boolean },
): UserSummary {
  requirePermission("admin:users");
  const user = state.users.find((row) => row.id === id) ?? notFound("User", id);

  // Nimeni nu se poate încuia singur pe dinafară: amândouă se simt la fel
  // („nu mai am acces") și amândouă cer, ca remediu, un terminal.
  if (user.email === currentUser.email) {
    if (input.isActive === false) {
      throw new ApiError(
        "VALIDATION_ERROR",
        "Nu te poți dezactiva pe tine. Roagă alt administrator.",
        422,
      );
    }
    if (input.role !== undefined && input.role !== user.role) {
      throw new ApiError(
        "VALIDATION_ERROR",
        "Nu îți poți schimba propriul rol. Roagă alt administrator.",
        422,
      );
    }
  }

  if (input.fullName !== undefined) user.fullName = input.fullName.trim();
  if (input.role !== undefined) user.role = input.role;
  if (input.isActive !== undefined) user.isActive = input.isActive;

  recordAudit("USER_UPDATED", "User", user.id, `${user.fullName} (${user.email})`);
  return user;
}

/** Resetarea parolei unui coleg. Auditul spune că s-a întâmplat, nu ce s-a scris. */
export function resetUserPassword(id: string, password: string): UserSummary {
  requirePermission("admin:users");
  const user = state.users.find((row) => row.id === id) ?? notFound("User", id);

  if (password.length < MOCK_MIN_PASSWORD_LENGTH) {
    throw new ApiError(
      "VALIDATION_ERROR",
      `Parola are minimum ${MOCK_MIN_PASSWORD_LENGTH} caractere.`,
      422,
      { password: ["Prea scurtă."] },
    );
  }

  recordAudit(
    "USER_PASSWORD_RESET",
    "User",
    user.id,
    `Parolă resetată pentru ${user.fullName} (${user.email})`,
  );
  return user;
}

/**
 * Setările pe care rulează **demonstrația** (§16, §73).
 *
 * Oglinda lui `app/api/v1/settings.py`, cu valorile care sunt adevărate aici:
 * backendul simulat nu are nici disc, nici provider de OCR, nici bază de date.
 * Tocmai de aceea trebuie să spună `mock` — dacă ar copia valorile de producție,
 * ecranul ar minti la fel ca înainte, doar cu alt text.
 *
 * Lista este albă și aici: nu există nicio valoare sensibilă de scăpat, pentru
 * că nu se citește nimic dintr-un mediu.
 */
/* ─── OneDrive (M9) ────────────────────────────────────────────────────────── */

/**
 * Integrarea, simulată.
 *
 * Aici nu există Microsoft, deci „conectarea" nu cere consimțământ: butonul duce
 * înapoi în aplicație cu un cod inventat. Ce contează pentru demonstrație este
 * **forma**: dosare care se răsfoiesc, se leagă de clienți, aduc documente și
 * arată când au sincronizat ultima dată.
 *
 * Structura de dosare de mai jos este cea pe care o descrie cabinetul — una per
 * client, sub un dosar comun.
 */
const MOCK_DRIVE_ID = "drive-demo";

const MOCK_DRIVE_TREE: Record<string, Array<{ itemId: string; name: string }>> = {
  root: [
    { itemId: "d-clienti", name: "Clienți" },
    { itemId: "d-arhiva", name: "Arhivă 2025" },
  ],
  "d-clienti": ACTIVE_CLIENTS.map((client) => ({
    itemId: `d-${client.id}`,
    name: client.name,
  })),
};

/** Dosarele din cutia poștală, ca într-un Outlook obișnuit. */
const MOCK_MAIL_FOLDERS: Array<{ folderId: string; displayName: string; totalItems: number }> = [
  { folderId: "inbox", displayName: "Inbox", totalItems: 1284 },
  { folderId: "m-documente", displayName: "Documente clienți", totalItems: 213 },
  { folderId: "m-facturi", displayName: "Facturi primite", totalItems: 97 },
];

type MockDriveState = {
  connected: boolean;
  accountEmail: string | null;
  connectedAt: string | null;
  lastSyncAt: string | null;
  folders: DriveFolder[];
  mailFolders: MailFolder[];
};

const driveState: MockDriveState = {
  connected: false,
  accountEmail: null,
  connectedAt: null,
  lastSyncAt: null,
  folders: [],
  mailFolders: [],
};

let driveFolderCounter = 0;

export function getDriveStatus(): DriveStatus {
  requirePermission("admin:settings");
  return {
    // În demonstrație integrarea este întotdeauna „configurată": nu există server
    // pe care să lipsească ceva. Ecranul real citește valorile adevărate.
    configured: true,
    encryptionReady: true,
    connected: driveState.connected,
    accountEmail: driveState.accountEmail,
    accountName: driveState.connected ? "Cabinet Contabil Demo SRL" : null,
    connectedAt: driveState.connectedAt,
    lastSyncAt: driveState.lastSyncAt,
    lastError: null,
    folders: driveState.folders,
    mailFolders: driveState.mailFolders,
  };
}

export function driveAuthorizeUrl(): { authorizeUrl: string } {
  requirePermission("admin:settings");
  // Fără Microsoft, „consimțământul" este o întoarcere imediată în aplicație cu
  // un cod inventat — exact drumul pe care îl face și cel real.
  return {
    authorizeUrl: "/administrare/surse?code=cod-simulat&state=stare-simulata",
  };
}

export function connectDrive(): DriveStatus {
  requirePermission("admin:settings");
  driveState.connected = true;
  driveState.accountEmail = "contabil@cabinet-demo.ro";
  driveState.connectedAt = MOCK_NOW;
  recordAudit("DRIVE_CONNECTED", "DriveConnection", "drive-demo", driveState.accountEmail);
  return getDriveStatus();
}

export function disconnectDrive(): void {
  requirePermission("admin:settings");
  recordAudit("DRIVE_DISCONNECTED", "DriveConnection", "drive-demo", driveState.accountEmail);
  driveState.connected = false;
  driveState.accountEmail = null;
  driveState.connectedAt = null;
  driveState.lastSyncAt = null;
  // Dosarele nu au ce căuta fără conexiunea prin care se citeau.
  driveState.folders = [];
  driveState.mailFolders = [];
}

export function browseDrive(parentId?: string): DriveBrowseItem[] {
  requirePermission("admin:settings");
  if (!driveState.connected) {
    throw new ApiError("CONFLICT", "Niciun cont Microsoft conectat.", 409);
  }

  const children = MOCK_DRIVE_TREE[parentId ?? "root"] ?? [];
  const tracked = new Set(driveState.folders.map((folder) => folder.itemId));
  return children.map((child) => ({
    driveId: MOCK_DRIVE_ID,
    itemId: child.itemId,
    name: child.name,
    path: `/${parentId === "d-clienti" ? "Clienți/" : ""}${child.name}`,
    isTracked: tracked.has(child.itemId),
  }));
}

export function trackDriveFolder(input: {
  driveId: string;
  itemId: string;
  path: string;
  clientId?: string | null;
}): DriveFolder {
  requirePermission("admin:settings");
  if (driveState.folders.some((folder) => folder.itemId === input.itemId)) {
    throw new ApiError("CONFLICT", "Dosarul este deja urmărit.", 409);
  }

  driveFolderCounter += 1;
  // Numele dosarului este numele clientului: în demonstrație îl legăm singuri,
  // ca ecranul să arate ce ar arăta după ce contabilul face maparea o dată.
  const guessed = state.clients.find((client) => input.path.endsWith(client.name));
  const folder: DriveFolder = {
    id: `drive-folder-${driveFolderCounter}`,
    driveId: input.driveId,
    itemId: input.itemId,
    path: input.path,
    clientId: input.clientId ?? guessed?.id ?? null,
    clientName: input.clientId
      ? (state.clients.find((c) => c.id === input.clientId)?.name ?? null)
      : (guessed?.name ?? null),
    lastSyncedAt: null,
    lastError: null,
    filesIngested: 0,
    isActive: true,
  };
  driveState.folders.push(folder);
  recordAudit("DRIVE_FOLDER_TRACKED", "DriveFolder", folder.id, folder.path);
  return folder;
}

export function updateDriveFolder(
  id: string,
  input: { clientId?: string | null; isActive?: boolean },
): DriveFolder {
  requirePermission("admin:settings");
  const folder = driveState.folders.find((row) => row.id === id) ?? notFound("DriveFolder", id);

  folder.clientId = input.clientId ?? null;
  folder.clientName = input.clientId
    ? (state.clients.find((client) => client.id === input.clientId)?.name ?? null)
    : null;
  if (input.isActive !== undefined) folder.isActive = input.isActive;

  recordAudit("DRIVE_FOLDER_UPDATED", "DriveFolder", folder.id, folder.path);
  return folder;
}

export function untrackDriveFolder(id: string): void {
  requirePermission("admin:settings");
  const folder = driveState.folders.find((row) => row.id === id) ?? notFound("DriveFolder", id);
  driveState.folders = driveState.folders.filter((row) => row.id !== id);
  recordAudit("DRIVE_FOLDER_UNTRACKED", "DriveFolder", id, folder.path);
}

let mailFolderCounter = 0;

export function browseMailFolders(): MailBrowseItem[] {
  requirePermission("admin:settings");
  if (!driveState.connected) {
    throw new ApiError("CONFLICT", "Niciun cont Microsoft conectat.", 409);
  }

  const tracked = new Set(driveState.mailFolders.map((folder) => folder.folderId));
  return MOCK_MAIL_FOLDERS.map((folder) => ({
    ...folder,
    isTracked: tracked.has(folder.folderId),
  }));
}

export function trackMailFolder(input: { folderId: string; displayName: string }): MailFolder {
  requirePermission("admin:settings");
  if (driveState.mailFolders.some((folder) => folder.folderId === input.folderId)) {
    throw new ApiError("CONFLICT", "Dosarul de email este deja urmărit.", 409);
  }

  mailFolderCounter += 1;
  const folder: MailFolder = {
    id: `mail-folder-${mailFolderCounter}`,
    folderId: input.folderId,
    displayName: input.displayName,
    lastSyncedAt: null,
    lastError: null,
    filesIngested: 0,
    isActive: true,
  };
  driveState.mailFolders.push(folder);
  recordAudit("MAIL_FOLDER_TRACKED", "MailFolder", folder.id, folder.displayName);
  return folder;
}

export function updateMailFolder(id: string, isActive: boolean): MailFolder {
  requirePermission("admin:settings");
  const folder =
    driveState.mailFolders.find((row) => row.id === id) ?? notFound("MailFolder", id);
  folder.isActive = isActive;
  recordAudit("MAIL_FOLDER_UPDATED", "MailFolder", folder.id, folder.displayName);
  return folder;
}

export function untrackMailFolder(id: string): void {
  requirePermission("admin:settings");
  const folder =
    driveState.mailFolders.find((row) => row.id === id) ?? notFound("MailFolder", id);
  driveState.mailFolders = driveState.mailFolders.filter((row) => row.id !== id);
  recordAudit("MAIL_FOLDER_UNTRACKED", "MailFolder", id, folder.displayName);
}

export function syncDrive(): DriveSyncResult {
  requirePermission("admin:settings");
  if (!driveState.connected) {
    throw new ApiError("CONFLICT", "Niciun cont Microsoft conectat.", 409);
  }

  const active = driveState.folders.filter((folder) => folder.isActive);
  const activeMail = driveState.mailFolders.filter((folder) => folder.isActive);
  let ingested = 0;

  for (const folder of active) {
    // Un document nou per dosar, la fiecare tur: destul cât demonstrația să arate
    // documentele apărând singure, fără să umple setul sintetic.
    const document = uploadDocument({
      filename: `${randomDay()}.08 scan.pdf`,
      size: 180_000,
      mimeType: "application/pdf",
    });
    document.source = "ONEDRIVE";
    document.clientId = folder.clientId;
    document.clientName = folder.clientName;

    folder.filesIngested += 1;
    folder.lastSyncedAt = MOCK_NOW;
    ingested += 1;
  }

  // Emailul: clientul il da expeditorul, deci in demonstratie atribuim unul
  // dintre clientii activi — ca pe ecran sa se vada cazul identificat.
  for (const folder of activeMail) {
    const sender = ACTIVE_CLIENTS[Math.floor(Math.random() * ACTIVE_CLIENTS.length)];
    const document = uploadDocument({
      filename: `factura-${randomDay()}.pdf`,
      size: 210_000,
      mimeType: "application/pdf",
    });
    document.source = "EMAIL";
    document.clientId = sender?.id ?? null;
    document.clientName = sender?.name ?? null;
    folder.filesIngested += 1;
    folder.lastSyncedAt = MOCK_NOW;
    ingested += 1;
  }

  driveState.lastSyncAt = MOCK_NOW;
  return {
    ingested,
    failed: 0,
    hasMore: false,
    folders: [...active.map((f) => f.path), ...activeMail.map((f) => f.displayName)],
  };
}

/* ─── e-Factura / SPV ANAF (M11) ──────────────────────────────────────────── */

type MockAnafState = {
  connected: boolean;
  certificateHolder: string | null;
  connectedAt: string | null;
  expiresAt: string | null;
  lastSyncAt: string | null;
  mandates: AnafMandate[];
};

const anafState: MockAnafState = {
  connected: false,
  certificateHolder: null,
  connectedAt: null,
  expiresAt: null,
  lastSyncAt: null,
  mandates: [],
};

let anafMandateCounter = 0;

/** Cât ține autorizarea ANAF: un an. Reînnoirea cere din nou certificatul. */
const ANAF_AUTHORISATION_DAYS = 365;

export function getAnafStatus(): AnafStatus {
  requirePermission("admin:settings");
  return {
    // În demonstrație integrarea este întotdeauna „configurată": nu există server
    // pe care să lipsească ceva. Ecranul real citește valorile adevărate.
    configured: true,
    encryptionReady: true,
    connected: anafState.connected,
    environment: "test",
    certificateHolder: anafState.certificateHolder,
    connectedAt: anafState.connectedAt,
    expiresAt: anafState.expiresAt,
    lastSyncAt: anafState.lastSyncAt,
    lastError: null,
    mandates: anafState.mandates,
  };
}

export function anafAuthorizeUrl(): { authorizeUrl: string } {
  requirePermission("admin:settings");
  // Fără ANAF, „autorizarea" este o întoarcere imediată în aplicație cu un cod
  // inventat — exact drumul pe care îl face și cea reală. Ce nu se poate simula
  // este pasul de dinaintea ei: certificatul digital cerut de browser.
  return { authorizeUrl: "/administrare/e-factura?code=cod-simulat&state=stare-simulata" };
}

export function connectAnaf(certificateHolder?: string | null): AnafStatus {
  requirePermission("admin:settings");
  anafState.connected = true;
  anafState.certificateHolder = cleanText(certificateHolder) ?? "Certificat cabinet (simulat)";
  anafState.connectedAt = MOCK_NOW;
  anafState.expiresAt = new Date(
    new Date(MOCK_NOW).getTime() + ANAF_AUTHORISATION_DAYS * 86_400_000,
  ).toISOString();
  recordAudit("ANAF_CONNECTED", "AnafConnection", "anaf-demo", anafState.certificateHolder);
  return getAnafStatus();
}

export function disconnectAnaf(): void {
  requirePermission("admin:settings");
  recordAudit("ANAF_DISCONNECTED", "AnafConnection", "anaf-demo", anafState.certificateHolder);
  anafState.connected = false;
  anafState.certificateHolder = null;
  anafState.connectedAt = null;
  anafState.expiresAt = null;
  anafState.lastSyncAt = null;
  // Împuternicirile sunt afirmații despre un certificat care nu mai e conectat.
  anafState.mandates = [];
}

function requireAnafConnection(): void {
  if (!anafState.connected) {
    throw new ApiError("CONFLICT", "SPV-ul ANAF nu este conectat.", 409);
  }
}

export function addAnafMandate(clientId: string): AnafMandate {
  requirePermission("admin:settings");
  requireAnafConnection();

  const client = state.clients.find((row) => row.id === clientId) ?? notFound("Client", clientId);
  const taxId = normalizeTaxId(client.taxId);
  if (!taxId) {
    throw new ApiError(
      "VALIDATION_ERROR",
      `${client.name} nu are CUI. Completează-l în fișa clientului sau trimite-l aici.`,
      422,
      { taxId: ["CUI lipsă."] },
    );
  }
  // Două rânduri pe același CUI ar aduce fiecare factură de două ori și ar dubla
  // cererile către ANAF, care le numără.
  if (anafState.mandates.some((row) => row.taxId === taxId || row.clientId === client.id)) {
    throw new ApiError(
      "CONFLICT",
      "Există deja o împuternicire pentru clientul sau CUI-ul acesta.",
      409,
    );
  }

  anafMandateCounter += 1;
  const mandate: AnafMandate = {
    id: `anaf-mandate-${anafMandateCounter}`,
    clientId: client.id,
    clientName: client.name,
    taxId,
    syncedThrough: null,
    lastSyncedAt: null,
    lastError: null,
    invoicesIngested: 0,
    isActive: true,
  };
  anafState.mandates.push(mandate);
  recordAudit("ANAF_MANDATE_ADDED", "AnafMandate", mandate.id, `${client.name} · CUI ${taxId}`);
  return mandate;
}

export function updateAnafMandate(id: string, isActive: boolean): AnafMandate {
  requirePermission("admin:settings");
  const mandate = anafState.mandates.find((row) => row.id === id) ?? notFound("AnafMandate", id);
  mandate.isActive = isActive;
  if (isActive) {
    // Reactivată, nu mai arată eroarea de acum două luni.
    mandate.lastError = null;
  }
  recordAudit("ANAF_MANDATE_UPDATED", "AnafMandate", mandate.id, mandate.clientName);
  return mandate;
}

export function removeAnafMandate(id: string): void {
  requirePermission("admin:settings");
  const mandate = anafState.mandates.find((row) => row.id === id) ?? notFound("AnafMandate", id);
  anafState.mandates = anafState.mandates.filter((row) => row.id !== id);
  recordAudit("ANAF_MANDATE_REMOVED", "AnafMandate", id, `CUI ${mandate.taxId}`);
}

export function syncAnaf(): AnafSyncResult {
  requirePermission("admin:settings");
  requireAnafConnection();

  const active = anafState.mandates.filter((mandate) => mandate.isActive);
  let ingested = 0;

  for (const mandate of active) {
    // O factură nouă per client, la fiecare tur: destul cât demonstrația să arate
    // facturile apărând singure, fără să umple setul sintetic.
    const document = uploadDocument({
      filename: `${3000 + anafMandateCounter + ingested}.xml`,
      size: 24_000,
      mimeType: "application/xml",
    });
    document.source = "EFACTURA";
    document.clientId = mandate.clientId;
    document.clientName = mandate.clientName;
    // Cele trei fișiere ale unei facturi electronice, pe un singur document.
    document.files = [
      {
        id: `${document.id}-original`,
        kind: "original",
        label: "Fișierul primit",
        mimeType: "application/xml",
        fileSize: 24_000,
        createdAt: MOCK_NOW,
      },
      {
        id: `${document.id}-anaf-zip`,
        kind: "anaf_zip",
        label: "Arhiva ANAF (cu sigiliul de acceptare)",
        mimeType: "application/zip",
        fileSize: 31_000,
        createdAt: MOCK_NOW,
      },
      {
        id: `${document.id}-anaf-pdf`,
        kind: "anaf_pdf",
        label: "PDF oficial ANAF",
        mimeType: "application/pdf",
        fileSize: 84_000,
        createdAt: MOCK_NOW,
      },
    ];

    mandate.invoicesIngested += 1;
    mandate.lastSyncedAt = MOCK_NOW;
    mandate.syncedThrough = MOCK_NOW;
    ingested += 1;
  }

  anafState.lastSyncAt = MOCK_NOW;
  return {
    ingested,
    failed: 0,
    hasMore: false,
    mandates: active.map((mandate) => mandate.taxId),
  };
}

/** Ziua din numele fișierului. Doar ca documentele simulate să nu arate identic. */
function randomDay(): number {
  return 1 + Math.floor(Math.random() * 28);
}

export function listSettings(): SettingEntry[] {
  requirePermission("admin:settings");
  return [
    { key: "CONFIDENCE_AUTO_THRESHOLD", group: "PROCESSING", value: "0.90" },
    { key: "CONFIDENCE_REVIEW_THRESHOLD", group: "PROCESSING", value: "0.70" },
    { key: "AUTO_APPROVE_ENABLED", group: "PROCESSING", value: "false" },
    { key: "MAX_PROCESSING_ATTEMPTS", group: "PROCESSING", value: "3" },
    { key: "PROCESSING_STALE_AFTER_MINUTES", group: "PROCESSING", value: "15" },
    { key: "STORAGE_PROVIDER", group: "STORAGE", value: "local" },
    { key: "MAX_UPLOAD_SIZE_MB", group: "STORAGE", value: "25" },
    {
      key: "ALLOWED_MIME_TYPES",
      group: "STORAGE",
      value: "application/pdf,image/jpeg,image/png,image/webp",
    },
    { key: "ARCHIVE_PATTERN", group: "STORAGE", value: "/ARHIVA/{an}/{luna}/{client}/" },
    { key: "OCR_PROVIDER", group: "EXTRACTION", value: "mock" },
    { key: "AI_PROVIDER", group: "EXTRACTION", value: "mock" },
    { key: "PROMPT_VERSION", group: "EXTRACTION", value: "v1" },
    { key: "REFERENCE_PERIOD_STRATEGY", group: "PERIODS", value: "document_date" },
    { key: "DEFAULT_TIMEZONE", group: "PERIODS", value: "Europe/Bucharest" },
    { key: "NOTIFICATIONS_ENABLED", group: "NOTIFICATIONS", value: "false" },
    { key: "RETENTION_ENABLED", group: "RETENTION", value: "false" },
    { key: "TRUSTED_PROXY_COUNT", group: "SECURITY", value: "0" },
    { key: "ONEDRIVE", group: "SECURITY", value: "true" },
  ];
}

/**
 * Ce se așteaptă lunar de la un client.
 *
 * Pe server, checklistul fiecărei luni se **derivă** din `client_expectations`.
 * Aici perioadele își poartă checklistul direct, deci așteptările se citesc din
 * el și se scriu în el — comportamentul văzut din afară este același, care este
 * tot ce promite contractul.
 */
export function listExpectations(clientId: string): ClientExpectation[] {
  requirePermission("documents:read");
  getClient(clientId);

  const periods = state.periods.filter((period) => period.clientId === clientId);
  const latest = periods.sort((a, b) => b.referenceMonth.localeCompare(a.referenceMonth))[0];
  return (latest?.checklist ?? []).map((item) => ({
    documentTypeCode: item.documentType,
    documentTypeLabel: item.documentTypeLabel,
    expectedMinCount: item.expectedMinCount,
  }));
}

/** Înlocuiește lista întreagă. Ce nu mai apare nu se mai așteaptă. */
export function setExpectations(
  clientId: string,
  wanted: Array<{ documentTypeCode: string; expectedMinCount: number }>,
): ClientExpectation[] {
  // `periods:manage`: a hotărî ce datorează un client este act contabil, nu
  // editare de fișă. Aceeași permisiune ca închiderea lunii.
  requirePermission("periods:manage");
  getClient(clientId);

  for (const entry of wanted) {
    if (!DOCUMENT_TYPE_LABEL.has(entry.documentTypeCode as DocumentTypeCode)) {
      throw new ApiError("NOT_FOUND", `Tip de document inexistent: ${entry.documentTypeCode}`, 404);
    }
    if (entry.expectedMinCount < 1) {
      throw new ApiError(
        "VALIDATION_ERROR",
        "Se așteaptă cel puțin un document; absența se exprimă scoțând rândul.",
        422,
        { expectedMinCount: ["Minim 1."] },
      );
    }
  }

  for (const period of state.periods.filter((row) => row.clientId === clientId)) {
    period.checklist = wanted.map((entry) => ({
      documentType: entry.documentTypeCode as DocumentTypeCode,
      documentTypeLabel:
        DOCUMENT_TYPE_LABEL.get(entry.documentTypeCode as DocumentTypeCode) ??
        entry.documentTypeCode,
      expectedMinCount: entry.expectedMinCount,
      receivedCount: 0,
      isSatisfied: false,
    }));
  }
  // Contoarele și statusul se re-derivă: altfel checklistul nou ar arăta zero
  // primite pentru documente care există deja în lună.
  refreshPeriods();

  recordAudit(
    "CLIENT_EXPECTATIONS_UPDATED",
    "Client",
    clientId,
    `${wanted.length} tipuri așteptate lunar`,
  );
  return listExpectations(clientId);
}

export function listDocumentTypes() {
  return DOCUMENT_TYPES;
}

/* ─── Recepții (M12) ───────────────────────────────────────────────────────── */

/**
 * Cronologia recepțiilor.
 *
 * Pe server, fiecare intrare are rândul ei în `document_intakes`. Aici o derivăm
 * din documente: setul sintetic nu are tabelă separată, iar ce promite
 * contractul este forma răspunsului, nu felul în care e stocat.
 *
 * `rawPayload` nu apare nici acolo, nici aici (§73).
 */
export function listIntakes(filters: DocumentFilters & { source?: string } = {}): Paginated<Intake> {
  requirePermission("documents:read");
  settleProcessing();

  let items = state.documents.filter((doc) => doc.source !== "UPLOAD");
  if (filters.clientId) items = items.filter((doc) => doc.clientId === filters.clientId);
  if (filters.source) items = items.filter((doc) => doc.source === filters.source);

  const rows: Intake[] = items
    .map((doc) => ({
      id: `intake-${doc.id}`,
      source: doc.source,
      status: (doc.isDuplicate ? "DUPLICATE" : "ACCEPTED") as Intake["status"],
      sender: senderFor(doc),
      subject: doc.documentTypeLabel ?? "Document primit",
      originalFilename: doc.originalFilename,
      receivedAt: doc.receivedAt,
      documentId: doc.id,
      clientId: doc.clientId,
      clientName: doc.clientName,
      rejectionReason: null,
    }))
    .sort((a, b) => b.receivedAt.localeCompare(a.receivedAt));

  return paginate(rows, Number(filters.page ?? 1), Number(filters.pageSize ?? 25));
}

/** De unde a venit, în cuvintele sursei. */
function senderFor(doc: StoredDocument): string {
  switch (doc.source) {
    case "EMAIL":
      return doc.clientName ? `contact@${slugify(doc.clientName)}.ro` : "expeditor necunoscut";
    case "ONEDRIVE":
      return `/Clienți/${doc.clientName ?? "Nemapat"}`;
    case "EFACTURA":
      return `ANAF SPV · ${doc.clientName ?? "—"}`;
    default:
      return doc.source;
  }
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/* ─── Dashboard ────────────────────────────────────────────────────────────── */

export function getDashboard(): DashboardData {
  settleProcessing();
  const docs = state.documents;
  const today = MOCK_NOW.slice(0, 10);
  const countByStatus = (status: DocumentStatus) => docs.filter((d) => d.status === status).length;

  const currentPeriods = listPeriods({ referenceMonth: CURRENT_MONTH });
  const complete = currentPeriods.filter((p) => p.status === "COMPLETE" || p.status === "FINALIZED");

  const attention = [
    ...docs
      .filter((d) => d.status === "UNMATCHED")
      .slice(0, 3)
      .map((d) => ({
        id: `att-${d.id}`,
        documentId: d.id,
        reason: "UNMATCHED_CLIENT" as const,
        title: "Client neidentificat",
        detail: `${d.originalFilename} — expeditor nemapat`,
        occurredAt: d.receivedAt,
      })),
    ...docs
      .filter((d) => d.status === "ERROR")
      .slice(0, 3)
      .map((d) => ({
        id: `att-${d.id}`,
        documentId: d.id,
        reason: "OCR_FAILED" as const,
        title: "OCR eșuat",
        detail: `${d.originalFilename} — necesită reîncărcare sau procesare manuală`,
        occurredAt: d.receivedAt,
      })),
    ...docs
      .filter((d) => d.status === "REVIEW_REQUIRED" && (d.confidence ?? 1) < 0.75)
      .slice(0, 3)
      .map((d) => ({
        id: `att-${d.id}`,
        documentId: d.id,
        reason: "LOW_CONFIDENCE" as const,
        title: "Încredere scăzută la extracție",
        detail: `${d.originalFilename} · ${d.clientName ?? "—"} · ${Math.round((d.confidence ?? 0) * 100)}%`,
        occurredAt: d.receivedAt,
      })),
    ...docs
      .filter((d) => d.isDuplicate)
      .slice(0, 2)
      .map((d) => ({
        id: `att-${d.id}`,
        documentId: d.id,
        reason: "POSSIBLE_DUPLICATE" as const,
        title: "Posibil document duplicat",
        detail: `${d.originalFilename} · ${d.clientName ?? "—"}`,
        occurredAt: d.receivedAt,
      })),
  ].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));

  return {
    // Luna pe care o descriu cifrele. Aici este cea a setului sintetic; pe
    // serverul real o dă `latest_active_month`, derivată din date.
    referenceMonth: CURRENT_MONTH,
    kpis: {
      clientsTotal: state.clients.length,
      clientsActive: state.clients.filter((c) => c.status === "ACTIVE").length,
      clientsComplete: complete.length,
      clientsMissingDocs: currentPeriods.length - complete.length,
      documentsToday: docs.filter((d) => d.receivedAt.startsWith(today)).length,
      documentsProcessing: countByStatus("PROCESSING"),
      documentsError: countByStatus("ERROR"),
      documentsNeedReview: countByStatus("REVIEW_REQUIRED"),
      documentsDuplicate: countByStatus("DUPLICATE"),
      documentsUnmatched: countByStatus("UNMATCHED"),
    },
    attention: attention.slice(0, 8),
    recentDocuments: docs.slice(0, 8).map(toListItem),
    periods: currentPeriods.slice(0, 6),
    closing: buildClosing(currentPeriods),
    trend: buildTrend(docs),
    byStatus: buildStatusSlices(docs),
    // Doar ce s-a întâmplat cu documentele: panoul principal este despre fluxul
    // de documente, nu despre autentificări.
    timeline: state.audit
      .filter((entry) => entry.entityType === "Document")
      .slice(0, 6)
      .map((entry) => ({
        id: entry.id,
        occurredAt: entry.at,
        kind:
          entry.action.startsWith("EMAIL") || entry.action.startsWith("WHATSAPP")
            ? ("NOTIFICATION_SENT" as const)
            : entry.action.includes("APPROVED") || entry.action.includes("ARCHIVED")
              ? ("PROCESSED" as const)
              : ("MESSAGE" as const),
        description: `${entry.userName}: ${entry.action}${entry.detail ? ` — ${entry.detail}` : ""}`,
      })),
  };
}

/** Câte zile arată graficul de sosiri. Oglindește `TREND_DAYS` din backend. */
const MOCK_TREND_DAYS = 14;

/**
 * Sosirile pe zi, ultimele două săptămâni.
 *
 * Zilele goale apar cu zero, nu lipsesc — la fel ca pe server. Un grafic cu
 * goluri arată un ritm care nu există.
 */
function buildTrend(documents: StoredDocument[]): DayCount[] {
  const counted = new Map<string, number>();
  for (const document of documents) {
    const day = document.receivedAt.slice(0, 10);
    counted.set(day, (counted.get(day) ?? 0) + 1);
  }

  const today = new Date();
  const days: DayCount[] = [];
  for (let offset = MOCK_TREND_DAYS - 1; offset >= 0; offset -= 1) {
    const date = new Date(today);
    date.setDate(today.getDate() - offset);
    const day = date.toISOString().slice(0, 10);
    days.push({ day, count: counted.get(day) ?? 0 });
  }
  return days;
}

/** Distribuția pe stări. Doar ce există: o felie de zero este o minciună desenată. */
function buildStatusSlices(documents: StoredDocument[]): StatusSlice[] {
  const counted = new Map<DocumentStatus, number>();
  for (const document of documents) {
    counted.set(document.status, (counted.get(document.status) ?? 0) + 1);
  }
  return [...counted.entries()]
    .filter(([, count]) => count > 0)
    .map(([status, count]) => ({ status, count }))
    .sort((a, b) => b.count - a.count);
}

/** Câți clienți în întârziere încap pe panou, și câte etichete pe rând. */
const MOCK_MAX_LAGGARDS = 5;
const MOCK_MAX_MISSING_LABELS = 3;

/**
 * Termenul lunii și cine încă nu a trimis.
 *
 * Termenul este în luna **următoare**: documentele lui august se depun până pe
 * 25 septembrie. Clienții se ordonează după cât le lipsește, nu alfabetic —
 * primul rând trebuie să fie cel care costă cel mai mult dacă rămâne așa.
 */
function buildClosing(periods: AccountingPeriod[]): DashboardClosing {
  const deadline = filingDeadline(CURRENT_MONTH);

  const waiting = periods
    .map((period) => ({
      period,
      gaps: period.checklist.filter((item) => item.receivedCount < item.expectedMinCount),
    }))
    .filter((entry) => entry.gaps.length > 0)
    .sort(
      (a, b) =>
        b.gaps.length - a.gaps.length || a.period.clientName.localeCompare(b.period.clientName),
    );

  const midnight = new Date(`${deadline}T00:00:00`).getTime();
  const today = new Date(new Date().toISOString().slice(0, 10) + "T00:00:00").getTime();

  return {
    referenceMonth: CURRENT_MONTH,
    deadline,
    daysLeft: Math.round((midnight - today) / 86_400_000),
    clientsWaiting: waiting.length,
    laggards: waiting.slice(0, MOCK_MAX_LAGGARDS).map(({ period, gaps }) => ({
      clientId: period.clientId,
      clientName: period.clientName,
      receivedCount: period.receivedCount,
      missingCount: gaps.length,
      missing: gaps.slice(0, MOCK_MAX_MISSING_LABELS).map((item) => item.documentTypeLabel),
    })),
  };
}

/** Contoarele afișate în meniul lateral. */
export function getSidebarCounts() {
  settleProcessing();
  return {
    inbox: state.documents.filter((d) => d.status === "RECEIVED" || d.status === "PROCESSING").length,
    review: state.documents.filter((d) => d.status === "REVIEW_REQUIRED").length,
    unmatched: state.documents.filter((d) => d.status === "UNMATCHED").length,
    tasks: state.tasks.filter((t) => t.status !== "DONE").length,
  };
}
