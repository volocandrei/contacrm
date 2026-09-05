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
import { DOCUMENT_STATUS_LABEL, ROLE_LABEL } from "@/lib/labels";
import { ROLE_CODE } from "@/types/domain";
import type {
  AccountingPeriod,
  AnafMandate,
  AnafStatus,
  AnafSyncResult,
  AssistantAction,
  AssistantLink,
  AssistantReply,
  AuditLogEntry,
  Client,
  ClientAlias,
  DocumentRequest,
  ExpectationTemplate,
  IssuedUploadLink,
  ClientStatus,
  ClientExpectation,
  ClientNote,
  DocumentTypeCode,
  Intake,
  Contact,
  ContactListItem,
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
  UploadLink,
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

/**
 * Agenda întreagă, cu numele firmei pe fiecare rând.
 *
 * `q` caută în numele persoanei, email, telefon **și** în numele firmei: cine
 * deschide agenda caută uneori omul, alteori firma, și nu are de unde ști în
 * care câmp stă ce caută.
 */
export function listAllContacts(filters: {
  q?: string;
  clientId?: string;
  includeInactive?: boolean;
  page?: number;
  pageSize?: number;
}): Paginated<ContactListItem> {
  const names = new Map(state.clients.map((client) => [client.id, client.name]));
  let items: ContactListItem[] = state.contacts
    .filter((contact) => names.has(contact.clientId))
    .map((contact) => ({ ...contact, clientName: names.get(contact.clientId)! }));

  if (!filters.includeInactive) items = items.filter((contact) => contact.isActive);
  if (filters.clientId) items = items.filter((contact) => contact.clientId === filters.clientId);
  if (filters.q) {
    items = items.filter((contact) =>
      matches(
        [contact.fullName, contact.email, contact.phone, contact.whatsappNumber, contact.clientName],
        filters.q!,
      ),
    );
  }

  items.sort(
    (a, b) =>
      a.clientName.localeCompare(b.clientName) ||
      Number(b.isPrimary) - Number(a.isPrimary) ||
      a.fullName.localeCompare(b.fullName),
  );
  return paginate(items, filters.page, filters.pageSize);
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
  // Aici învață sistemul. Doar aici: o potrivire automată nu produce niciodată
  // un alias, altfel prima greșeală s-ar transforma în regulă.
  const learned = learnFromAssignment(doc.id, client.id);
  recordAudit(
    "DOCUMENT_REASSIGNED",
    "Document",
    doc.id,
    learned ? `${client.name} · învățat expeditorul ${learned}` : client.name,
  );
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
    .map((period) => {
      // Ultima cerere pentru clientul ăsta, pe luna asta. Linkurile revocate
      // rămân în calcul: o cerere trimisă s-a trimis, iar faptul că i-am închis
      // între timp drumul nu înseamnă că n-am întrebat.
      const requests = uploadLinks
        .filter(
          (link) => link.clientId === period.clientId && link.referenceMonth === referenceMonth,
        )
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      return {
        period,
        missing: period.checklist.filter((item) => !item.isSatisfied),
        deadline,
        requestedAt: requests[0]?.createdAt ?? null,
        // Documentele se adună peste toate cererile lunii: o a doua cerere nu
        // șterge de pe ecran ce trimisese omul după prima.
        receivedThroughLink: requests.reduce((total, link) => total + link.uploadCount, 0),
      };
    })
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

/**
 * O sarcină nouă.
 *
 * Oglindește `POST /tasks`: titlul se taie de spații **înainte** de verificare
 * (altfel „   " ar deveni o sarcină fără nume), iar clientul și colegul se caută
 * în organizația celui care scrie — un id inventat nu devine o legătură tăcută
 * către nimic.
 */
export function createTask(input: Record<string, unknown>): Task {
  requirePermission("tasks:write");

  const title = String(input.title ?? "").trim();
  if (!title || title.length > 255) {
    throw new ApiError("VALIDATION_ERROR", "Titlul este obligatoriu.", 422, {
      title: ["Titlul este obligatoriu."],
    });
  }

  const clientId = (input.clientId as string | undefined) ?? null;
  if (clientId && !state.clients.some((row) => row.id === clientId)) {
    throw new ApiError("VALIDATION_ERROR", "Clientul nu există.", 422, {
      clientId: ["Client inexistent."],
    });
  }

  const assignedToId = (input.assignedToId as string | undefined) ?? null;
  const assignee = assignedToId ? state.users.find((row) => row.id === assignedToId) : undefined;
  if (assignedToId && !assignee) {
    throw new ApiError("VALIDATION_ERROR", "Colegul nu există.", 422, {
      assignedToId: ["Utilizator inexistent."],
    });
  }

  taskCounter += 1;
  const task: Task = {
    id: `task-nou-${taskCounter}`,
    title,
    description: String(input.description ?? "").trim(),
    clientId,
    clientName: clientId
      ? (state.clients.find((row) => row.id === clientId)?.name ?? null)
      : null,
    assignedToId,
    assignedToName: assignee?.fullName ?? null,
    priority: (input.priority as Task["priority"]) ?? "NORMAL",
    status: "TODO",
    dueDate: (input.dueDate as string | undefined) ?? null,
    createdAt: MOCK_NOW,
    completedAt: null,
  };
  state.tasks.unshift(task);
  recordAudit("TASK_CREATED", "Task", task.id, task.title);
  return task;
}

let taskCounter = 0;

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
    { key: "AI_MODEL", group: "EXTRACTION", value: "claude-sonnet-5" },
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

/* ─── Șabloane de așteptări ────────────────────────────────────────────────── */

/**
 * Oglinda lui `services/expectation_templates.py`.
 *
 * **Șablonul nu este o legătură.** Se aplică o dată, iar rezultatul rămâne al
 * clientului: se scrie în listele lui și acolo rămâne. Dacă ar moșteni la
 * distanță, o bifă scoasă azi ar dispărea de pe doisprezece clienți fără ca
 * cineva să le fi atins ecranul.
 */
const templates: ExpectationTemplate[] = [];
let templateCounter = 0;

export function listExpectationTemplates(): ExpectationTemplate[] {
  requirePermission("documents:read");
  return [...templates].sort((a, b) => a.name.localeCompare(b.name, "ro"));
}

/** Numele curățat, refuzat dacă e gol sau deja folosit. */
function checkName(name: string, keeping: string | null): string {
  const trimmed = name.trim();
  if (!trimmed) {
    throw new ApiError("VALIDATION_ERROR", "Șablonul are nevoie de un nume.", 422, {
      name: ["Scrie un nume."],
    });
  }
  const clash = templates.find(
    (row) => row.name.toLocaleLowerCase("ro") === trimmed.toLocaleLowerCase("ro") && row.id !== keeping,
  );
  if (clash) {
    // Două rânduri pe care nimeni nu le poate deosebi, iar unul rescrie clienți.
    throw new ApiError("VALIDATION_ERROR", `Există deja un șablon numit „${clash.name}”.`, 422, {
      name: ["Alege alt nume."],
    });
  }
  return trimmed;
}

function toExpectations(
  wanted: Array<{ documentTypeCode: string; expectedMinCount: number }>,
): ClientExpectation[] {
  return wanted.map((entry) => {
    const label = DOCUMENT_TYPE_LABEL.get(entry.documentTypeCode as DocumentTypeCode);
    if (!label) {
      // Ignorat în tăcere, ar lipsi din raport abia peste o lună.
      throw new ApiError("NOT_FOUND", `Tip de document inexistent: ${entry.documentTypeCode}`, 404);
    }
    return {
      documentTypeCode: entry.documentTypeCode,
      documentTypeLabel: label,
      expectedMinCount: entry.expectedMinCount,
    };
  });
}

export function createExpectationTemplate(
  name: string,
  wanted: Array<{ documentTypeCode: string; expectedMinCount: number }>,
): ExpectationTemplate {
  requirePermission("periods:manage");
  const clean = checkName(name, null);
  const expectations = toExpectations(wanted);

  templateCounter += 1;
  const template: ExpectationTemplate = { id: `tpl-${templateCounter}`, name: clean, expectations };
  templates.push(template);
  recordAudit("EXPECTATION_TEMPLATE_CREATED", "ExpectationTemplate", template.id, clean);
  return template;
}

export function saveExpectationTemplate(
  id: string,
  name: string,
  wanted: Array<{ documentTypeCode: string; expectedMinCount: number }>,
): ExpectationTemplate {
  requirePermission("periods:manage");
  const template = templates.find((row) => row.id === id);
  if (!template) notFound("Șablon", id);

  template.name = checkName(name, id);
  template.expectations = toExpectations(wanted);
  recordAudit("EXPECTATION_TEMPLATE_UPDATED", "ExpectationTemplate", id, template.name);
  return template;
}

export function deleteExpectationTemplate(id: string): void {
  requirePermission("periods:manage");
  const index = templates.findIndex((row) => row.id === id);
  if (index < 0) notFound("Șablon", id);
  // Clienții configurați cu el rămân configurați: ce s-a aplicat este al lor.
  const [removed] = templates.splice(index, 1);
  recordAudit("EXPECTATION_TEMPLATE_DELETED", "ExpectationTemplate", id, removed!.name);
}

/** Salvează ce s-a configurat deja pe un client, ca profil. */
export function templateFromClient(clientId: string, name: string): ExpectationTemplate {
  requirePermission("periods:manage");
  getClient(clientId);
  const current = listExpectations(clientId);
  if (current.length === 0) {
    // Un șablon gol aplicat pe doisprezece clienți le-ar goli checklistul.
    throw new ApiError(
      "VALIDATION_ERROR",
      "Clientul nu are nicio așteptare configurată, deci nu are ce salva.",
      422,
      { name: ["Configurează întâi ce se așteaptă de la client."] },
    );
  }
  return createExpectationTemplate(name, current);
}

export function applyExpectationTemplate(id: string, clientIds: string[]): { applied: number } {
  requirePermission("periods:manage");
  const template = templates.find((row) => row.id === id);
  if (!template) notFound("Șablon", id);

  // Toți clienții, înainte de orice scriere: aplicată pe jumătate, operația ar
  // lăsa pe cineva fără să știe care jumătate.
  const unique = [...new Set(clientIds)];
  for (const clientId of unique) getClient(clientId);

  for (const clientId of unique) {
    setExpectations(
      clientId,
      template.expectations.map((item) => ({
        documentTypeCode: item.documentTypeCode,
        expectedMinCount: item.expectedMinCount,
      })),
    );
  }
  recordAudit(
    "EXPECTATION_TEMPLATE_APPLIED",
    "ExpectationTemplate",
    id,
    `${template.name} · ${unique.length} clienți`,
  );
  return { applied: unique.length };
}

/* ─── Linkurile de trimitere (M14) ─────────────────────────────────────────── */

/**
 * Oglinda lui `services/upload_links.py`.
 *
 * Tokenul se vede o singură dată, ca pe server. Aici nu se face hash — este un
 * backend simulat, în memoria browserului — dar forma răspunsului este identică:
 * `url` doar la creare, niciodată la listare. Un ecran care ar putea reafișa
 * linkul ar fi scris altfel decât cel real, iar diferența s-ar vedea abia în
 * producție.
 */
const uploadLinks: Array<UploadLink & { clientId: string }> = [];
let uploadLinkCounter = 0;

/** Aceeași valabilitate implicită ca pe server: o lună plus marja de depunere. */
const MOCK_LINK_VALIDITY_DAYS = 45;

/**
 * Adresa de la care se compune linkul — oglinda lui `PUBLIC_BASE_URL`.
 *
 * În browser este chiar originul paginii. `window` nu există însă peste tot unde
 * rulează codul ăsta: testele backendului simulat rulează în Node, iar o citire
 * directă ar arunca acolo, nu în producție — adică exact unde nu se vede.
 */
function mockPublicOrigin(): string {
  return typeof window === "undefined" ? "http://localhost:5173" : window.location.origin;
}

export function listUploadLinks(clientId: string): UploadLink[] {
  requirePermission("clients:read");
  return uploadLinks
    .filter((link) => link.clientId === clientId)
    .map(({ clientId: _clientId, ...link }) => link);
}

export function createUploadLink(clientId: string, referenceMonth?: string): IssuedUploadLink {
  requirePermission("documents:write");
  getClient(clientId);

  uploadLinkCounter += 1;
  const expires = new Date(Date.now() + MOCK_LINK_VALIDITY_DAYS * 86_400_000).toISOString();
  const link: UploadLink & { clientId: string } = {
    id: `link-${uploadLinkCounter}`,
    clientId,
    expiresAt: expires,
    revokedAt: null,
    uploadCount: 0,
    lastUsedAt: null,
    createdAt: new Date().toISOString(),
    // Luna leagă linkul de cerere. Fără ea, rândul spune doar că s-a deschis un
    // drum; cu ea, spune că **i s-a cerut**.
    referenceMonth: referenceMonth ?? null,
  };
  uploadLinks.unshift(link);
  recordAudit("UPLOAD_LINK_ISSUED", "ClientUploadLink", link.id, getClient(clientId).name);

  const { clientId: _clientId, ...rest } = link;
  return {
    ...rest,
    url: `${mockPublicOrigin()}/incarca/token-simulat-${uploadLinkCounter}`,
  };
}

export function revokeUploadLink(linkId: string): void {
  requirePermission("documents:write");
  const link = uploadLinks.find((row) => row.id === linkId);
  if (!link) notFound("Link", linkId);
  // Nu se șterge rândul: urma că a existat rămâne, ca pe server.
  // Ora reală, ca la creare: un link deschis acum și „revocat" la o dată din
  // trecut este o cronologie pe care nimeni nu o poate citi.
  link.revokedAt = new Date().toISOString();
  recordAudit("UPLOAD_LINK_REVOKED", "ClientUploadLink", linkId, null);
}

/* ─── Ce a învățat sistemul (§8) ───────────────────────────────────────────── */

/**
 * Oglinda lui `services/client_aliases.py`.
 *
 * Se scrie **doar** din atribuiri făcute de oameni: o potrivire automată nu
 * produce niciodată un alias, altfel prima greșeală s-ar transforma în regulă.
 * Ultima decizie a unui om câștigă — atribuirea nouă mută rândul, nu adaugă unul.
 */
const aliases: ClientAlias[] = [];
const aliasClient = new Map<string, string>();
let aliasCounter = 0;

function normalizeSender(raw: string | null | undefined): string {
  return (raw ?? "").trim().toLowerCase();
}

/**
 * Adresa de la care a sosit documentul, dacă a sosit de undeva.
 *
 * Aceeași sursă ca pentru cronologia de recepții: două păreri despre „de la
 * cine" ar face ca ecranul „Mesaje" și învățarea să nu fie de acord.
 */
function senderOfDocument(documentId: string): string {
  const doc = state.documents.find((row) => row.id === documentId);
  // Un document urcat manual nu are expeditor extern: nu e nimic de învățat.
  if (!doc || doc.source === "UPLOAD") return "";
  return normalizeSender(senderFor(doc));
}

function learnFromAssignment(documentId: string, clientId: string): string | null {
  const sender = senderOfDocument(documentId);
  if (!sender) return null;

  const existing = aliases.find((alias) => alias.value === sender);
  if (existing) {
    if (aliasClient.get(existing.id) === clientId) return null;
    // Contorul repornește: potrivirile de până acum au fost pentru alt client.
    aliasClient.set(existing.id, clientId);
    existing.matchedCount = 0;
    return sender;
  }

  aliasCounter += 1;
  const alias: ClientAlias = {
    id: `alias-${aliasCounter}`,
    kind: "SENDER",
    value: sender,
    matchedCount: 0,
    createdAt: MOCK_NOW,
  };
  aliases.push(alias);
  aliasClient.set(alias.id, clientId);
  return sender;
}

export function listClientAliases(clientId: string): ClientAlias[] {
  requirePermission("clients:read");
  return aliases
    .filter((alias) => aliasClient.get(alias.id) === clientId)
    .sort((a, b) => b.matchedCount - a.matchedCount || a.value.localeCompare(b.value));
}

export function forgetAlias(aliasId: string): void {
  requirePermission("clients:write");
  const index = aliases.findIndex((alias) => alias.id === aliasId);
  if (index < 0) notFound("Alias", aliasId);
  recordAudit("CLIENT_ALIAS_FORGOTTEN", "ClientAlias", aliasId, aliases[index]!.value);
  aliases.splice(index, 1);
  aliasClient.delete(aliasId);
}

/* ─── Solicitarea de documente ─────────────────────────────────────────────── */

/** Numele lunilor, ca într-un mesaj către un client. */
const MONTH_NAMES = [
  "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
  "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
];

/**
 * Oglinda lui `services/document_request.py`.
 *
 * Textul spune numele cabinetului, listează ce lipsește și dă termenul lunii:
 * este conținut de business, nu formatare de ecran. Ecranul „Documente lipsă" și
 * asistentul îl cer din același loc — două formulări ar însemna că doi clienți
 * primesc, în aceeași zi, mesaje diferite de la același cabinet.
 */
/** „2026-10-20T09:00:00Z" → „20.10.2026". Un client nu citește date ISO. */
function dayMonthYear(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
}

export function buildDocumentRequest(
  clientId: string,
  referenceMonth: string,
  upload?: { url: string; expiresAt: string },
): string {
  const client = state.clients.find((row) => row.id === clientId);
  if (!client) notFound("Client", clientId);

  const period = state.periods.find(
    (row) => row.clientId === clientId && row.referenceMonth === referenceMonth,
  );
  const missing = (period?.checklist ?? []).filter((item) => !item.isSatisfied);
  if (missing.length === 0) {
    throw new ApiError(
      "VALIDATION_ERROR",
      "Clientul nu are documente lipsă în luna cerută.",
      422,
      { referenceMonth: ["Nimic de cerut."] },
    );
  }

  const [year, month] = referenceMonth.split("-");
  const deadline = filingDeadline(referenceMonth);
  const lines = missing.map((item) => {
    // Câte bucăți mai lipsesc, nu doar că lipsește: „Facturi de achiziție" nu
    // spune nimic unui client care crede că le-a trimis.
    if (item.receivedCount > 0) {
      const left = item.expectedMinCount - item.receivedCount;
      const seen = `${item.receivedCount} din ${item.expectedMinCount}`;
      return `• ${item.documentTypeLabel} — mai așteptăm ${left} (am primit ${seen})`;
    }
    const piece = item.expectedMinCount === 1 ? "bucată" : "bucăți";
    return `• ${item.documentTypeLabel} — ${item.expectedMinCount} ${piece}`;
  });

  return [
    "Bună ziua,",
    "",
    `Pentru evidența contabilă a lunii ${MONTH_NAMES[Number(month) - 1]} ${year} ` +
      "mai avem nevoie de următoarele documente:",
    "",
    ...lines,
    "",
    `Vă rugăm să ni le transmiteți până la ${dayMonthYear(deadline)}, ` +
      "ca declarațiile să poată fi depuse la timp.",
    // Cererea și drumul pe care sosește răspunsul pleacă împreună: o listă de ce
    // lipsește îi spune clientului *ce* să caute, dar îl lasă singur cu *cum*.
    ...(upload
      ? [
          "",
          "Cel mai simplu este să le încărcați direct aici, fără cont și fără parolă:",
          upload.url,
          `Linkul este valabil până la ${dayMonthYear(upload.expiresAt)}.`,
        ]
      : []),
    "",
    "Vă mulțumim,",
    currentUser.organizationName,
  ].join("\n");
}

/**
 * Solicitarea de documente, cu link cu tot.
 *
 * Ordinea contează și aici: mai întâi se verifică dacă e ceva de cerut, abia
 * apoi se deschide linkul. Un drum public deschis pentru un mesaj care oricum
 * nu pleacă ar rămâne deschis degeaba 45 de zile.
 */
export function composeDocumentRequest(
  clientId: string,
  referenceMonth: string,
): DocumentRequest {
  requirePermission("documents:write");
  // Aruncă înainte de a deschide ceva, dacă nu lipsește nimic.
  buildDocumentRequest(clientId, referenceMonth);

  const link = createUploadLink(clientId, referenceMonth);
  return {
    message: buildDocumentRequest(clientId, referenceMonth, {
      url: link.url,
      expiresAt: link.expiresAt,
    }),
    uploadUrl: link.url,
    uploadExpiresAt: link.expiresAt,
  };
}

/* ─── Asistentul (M13) ─────────────────────────────────────────────────────── */

/**
 * Oglinda lui `services/assistant` din backend.
 *
 * Aceleași intenții, aceleași unelte, aceleași limite de rol. Ce se verifică în
 * `api/mock/assistant.test.ts` trebuie să se comporte identic în
 * `tests/test_assistant_api.py` — backendul simulat este contractul (§14).
 *
 * Ca și acolo: **numai citire**. Asistentul propune un drum, omul îl deschide.
 */
type AssistantToolResult = {
  text: string;
  links?: AssistantLink[];
  suggestions?: string[];
  actions?: AssistantAction[];
};

type AssistantTool = {
  name: string;
  permission: Permission;
  description: string;
  run: (argument: string) => AssistantToolResult;
};

/** Fără diacritice, litere mici — într-un chat se scrie repede. */
function assistantNormalise(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

/** Luna care se depune acum: cea încheiată, nu cea în curs. */
function assistantPreviousMonth(): string {
  const [year, month] = CURRENT_MONTH.split("-").map(Number) as [number, number];
  return month === 1
    ? `${year - 1}-12`
    : `${year}-${String(month - 1).padStart(2, "0")}`;
}

function assistantTools(): AssistantTool[] {
  return [
    {
      name: "workload",
      permission: "documents:read",
      description: "Câte documente așteaptă verificare, atribuire sau au eșuat.",
      run: () => {
        const review = state.documents.filter((d) => d.status === "REVIEW_REQUIRED").length;
        const unmatched = state.documents.filter((d) => d.status === "UNMATCHED").length;
        const errors = state.documents.filter((d) => d.status === "ERROR").length;
        if (review + unmatched + errors === 0) {
          return { text: "Nu așteaptă niciun document. Coada este goală." };
        }
        const parts: string[] = [];
        const links: AssistantLink[] = [];
        if (review) {
          parts.push(`${review} ${review === 1 ? "document așteaptă" : "documente așteaptă"} verificare`);
          links.push({ label: "Deschide verificarea", path: "/documente/verificare" });
        }
        if (unmatched) {
          parts.push(`${unmatched} ${unmatched === 1 ? "document e neatribuit" : "documente sunt neatribuite"}`);
          links.push({ label: "Vezi neatribuitele", path: "/documente/neatribuite" });
        }
        if (errors) parts.push(`${errors} ${errors === 1 ? "document a eșuat" : "documente au eșuat"}`);
        return { text: `${parts.join(". ")}.`, links };
      },
    },
    {
      name: "deadline",
      permission: "documents:read",
      description: "Termenul de depunere pentru luna încheiată.",
      run: (argument) => {
        const month = argument || assistantPreviousMonth();
        const deadline = filingDeadline(month);
        const days = Math.round(
          (new Date(`${deadline}T00:00:00`).getTime() -
            new Date(new Date().toISOString().slice(0, 10) + "T00:00:00").getTime()) /
            86_400_000,
        );
        const when =
          days < 0 ? `a trecut de ${Math.abs(days)} zile` : days === 0 ? "este astăzi" : `mai sunt ${days} zile`;
        const [year, day, monthPart] = [deadline.slice(0, 4), deadline.slice(8), deadline.slice(5, 7)];
        return {
          text: `Termenul pentru luna ${month} este ${day}.${monthPart}.${year} — ${when}.`,
          links: [{ label: "Perioade", path: "/contabilitate/perioade" }],
        };
      },
    },
    {
      name: "missing_documents",
      permission: "documents:read",
      description: "Ce documente lipsesc, per client, pentru o lună.",
      run: (argument) => {
        const month = argument || assistantPreviousMonth();
        const entries = listMissingDocuments(month);
        if (entries.length === 0) {
          return { text: `Pentru luna ${month}, toți clienții au documentele complete.` };
        }
        const lines = entries.slice(0, 5).map((entry) => {
          const listed = entry.missing
            .map((item) => `${item.documentTypeLabel} (${item.receivedCount}/${item.expectedMinCount})`)
            .join(", ");
          return `• ${entry.period.clientName} — lipsesc: ${listed}`;
        });
        const head = entries.length === 1 ? "1 client are" : `${entries.length} clienți au`;
        let text = `Pentru luna ${month}, ${head} documente lipsă:\n${lines.join("\n")}`;
        if (entries.length > 5) text += `\n…și încă ${entries.length - 5}.`;
        return {
          text,
          links: [{ label: "Documente lipsă", path: `/contabilitate/lipsa?referenceMonth=${month}` }],
        };
      },
    },
    {
      name: "explain_document",
      permission: "documents:read",
      description:
        "Explică de ce un document este în starea în care este: ce îi lipsește, " +
        "de ce așteaptă verificare, de ce nu i s-a găsit clientul.",
      run: (argument) => {
        if (!argument) return { text: "Spune-mi care document — o bucată din nume ajunge." };

        const page = listDocuments({ q: argument, pageSize: 5 });
        if (page.items.length === 0) {
          return { text: `Nu am găsit niciun document pentru „${argument}”.` };
        }
        if (page.items.length > 1) {
          const listed = page.items.map((row) => `• ${row.originalFilename}`).join("\n");
          const more = page.total > page.items.length ? ` (din ${page.total})` : "";
          return {
            text:
              `Se potrivesc mai multe documente cu „${argument}”${more}:\n${listed}\n` +
              "Spune-mi numele întreg al celui care te interesează.",
            links: [{ label: "Caută în documente", path: "/documente/inbox" }],
          };
        }

        const item = page.items[0]!;
        const lines = [`„${item.originalFilename}” — ${DOCUMENT_STATUS_LABEL[item.status]}.`];
        if (item.clientName) {
          lines.push(`Client: ${item.clientName}.`);
        } else if (item.status === "UNMATCHED") {
          lines.push(
            "Clientul nu a fost identificat: pe document nu s-a găsit niciun CUI " +
              "de-al vostru. Atribuie-l o dată, iar de la aceeași adresă documentele " +
              "următoare vor merge singure.",
          );
        }

        // Motivele vin de unde le ia și ecranul de verificare. Un al doilea set
        // de reguli, scris aici pentru un text mai frumos, ar fi început să
        // contrazică ecranul la prima modificare a unuia dintre ele.
        const issues = getDocument(item.id).validationIssues;
        if (issues.length > 0) {
          lines.push("De rezolvat:");
          lines.push(...issues.map((issue) => `• ${issue}`));
        } else if (item.status === "REVIEW_REQUIRED") {
          lines.push(
            "Nu are nimic de corectat — așteaptă doar confirmarea unui om, " +
              "fiindcă aprobarea automată este oprită.",
          );
        }

        return {
          text: lines.join("\n"),
          links: [
            {
              label: `Deschide ${item.originalFilename}`,
              path: `/documente/verificare/${item.id}`,
            },
          ],
        };
      },
    },
    {
      name: "find_client",
      permission: "clients:read",
      description: "Găsește un client după nume sau CUI.",
      run: (argument) => {
        if (!argument) return { text: "Spune-mi numele firmei sau CUI-ul." };
        const page = listClients({ q: argument, pageSize: 5 });
        if (page.items.length === 0) {
          return { text: `Nu am găsit niciun client pentru „${argument}”.` };
        }
        if (page.items.length === 1) {
          const client = page.items[0]!;
          return {
            text: `${client.name}, CUI ${client.taxId ?? "—"}.`,
            links: [{ label: `Deschide ${client.name}`, path: `/crm/clienti/${client.id}` }],
            suggestions: [`ce lipsește la ${client.name}`],
          };
        }
        return {
          text: `${page.total} clienți se potrivesc cu „${argument}”:\n${page.items.map((c) => `• ${c.name}`).join("\n")}`,
          links: page.items.map((c) => ({ label: `Deschide ${c.name}`, path: `/crm/clienti/${c.id}` })),
        };
      },
    },
    {
      name: "client_month",
      permission: "clients:read",
      description: "Cum stă un client cu luna în curs de depunere.",
      run: (argument) => {
        if (!argument) return { text: "Spune-mi despre care client." };
        const page = listClients({ q: argument, pageSize: 2 });
        if (page.items.length === 0) {
          return { text: `Nu am găsit niciun client pentru „${argument}”.` };
        }
        if (page.items.length > 1) {
          return { text: "Sunt mai mulți clienți cu numele ăsta. Spune-mi CUI-ul sau numele întreg." };
        }
        const client = page.items[0]!;
        const link = { label: `Deschide ${client.name}`, path: `/crm/clienti/${client.id}` };
        const month = assistantPreviousMonth();
        const period = state.periods.find(
          (p) => p.clientId === client.id && p.referenceMonth === month,
        );
        if (!period) {
          return {
            text: `Pentru ${client.name} nu a sosit niciun document în luna ${month}.`,
            links: [link],
          };
        }
        const gaps = period.checklist.filter((item) => !item.isSatisfied);
        if (gaps.length === 0) {
          return {
            text: `${client.name} are luna ${month} completă: ${period.satisfiedCount}/${period.expectedCount}.`,
            links: [link],
          };
        }
        const listed = gaps
          .map((gap) => `${gap.documentTypeLabel} (${gap.receivedCount}/${gap.expectedMinCount})`)
          .join(", ");
        return {
          text: `${client.name}, luna ${month}: ${period.satisfiedCount}/${period.expectedCount}. Lipsesc: ${listed}.`,
          links: [link],
        };
      },
    },
    {
      name: "draft_request",
      permission: "clients:read",
      description:
        "Scrie solicitarea de documente pentru un client, gata de trimis. Nu trimite nimic.",
      run: (argument) => {
        if (!argument) return { text: "Spune-mi pentru care client." };
        const page = listClients({ q: argument, pageSize: 2 });
        if (page.items.length === 0) {
          return { text: `Nu am găsit niciun client pentru „${argument}”.` };
        }
        if (page.items.length > 1) {
          return { text: "Sunt mai mulți clienți cu numele ăsta. Spune-mi numele întreg." };
        }
        const client = page.items[0]!;
        const month = assistantPreviousMonth();
        try {
          // Fără link în text: deschiderea unui link scrie, iar asistentul nu
          // execută nimic care schimbă date. Îl propune, omul apasă.
          return {
            text: buildDocumentRequest(client.id, month),
            actions: currentUser.permissions.includes("documents:write")
              ? [
                  {
                    kind: "request_documents" as const,
                    label: "Deschide un link și copiază cererea",
                    summary:
                      `Se deschide un link de trimitere pentru ${client.name}, iar textul ` +
                      "de mai sus îl primești cu linkul în el, gata de copiat.",
                    payload: { clientId: client.id, referenceMonth: month },
                  },
                ]
              : [],
            links: [
              { label: "Documente lipsă", path: `/contabilitate/lipsa?referenceMonth=${month}` },
            ],
          };
        } catch {
          return { text: `${client.name} nu are documente lipsă pe ${month}. Nu e nimic de cerut.` };
        }
      },
    },
    {
      name: "propose_task",
      permission: "tasks:write",
      description: "Pregătește o sarcină cu titlul cerut. Nu o creează: omul confirmă.",
      run: (argument) => {
        const title = argument.trim().slice(0, 255);
        if (!title) return { text: "Spune-mi ce să notez." };
        return {
          text: `Pot nota sarcina „${title}”, pe numele tău.`,
          actions: [
            {
              kind: "create_task",
              label: "Notează sarcina",
              summary: `Se creează sarcina „${title}”, atribuită ție.`,
              payload: { title, assignedToId: currentUser.id },
            },
          ],
          links: [{ label: "Sarcini", path: "/crm/sarcini" }],
        };
      },
    },
    {
      name: "propose_assignment",
      permission: "documents:write",
      description:
        "Pregătește atribuirea unui document neatribuit către un client. Nu atribuie: omul confirmă.",
      run: (argument) => {
        if (!argument) return { text: "Spune-mi către care client." };
        const page = listClients({ q: argument, pageSize: 2 });
        if (page.items.length === 0) {
          return { text: `Nu am găsit niciun client pentru „${argument}”.` };
        }
        if (page.items.length > 1) {
          return { text: "Sunt mai mulți clienți cu numele ăsta. Spune-mi numele întreg." };
        }
        const client = page.items[0]!;
        const unmatched = state.documents.filter((doc) => doc.status === "UNMATCHED");
        if (unmatched.length === 0) return { text: "Nu există documente neatribuite." };

        const listed = unmatched.slice(0, 5).map((doc) => `• ${doc.originalFilename}`).join("\n");
        const first = unmatched[0]!;
        return {
          text:
            `Sunt ${unmatched.length} documente neatribuite. Primele:\n${listed}\n` +
            `Le pot pregăti pentru ${client.name} — verifică-le înainte de a confirma.`,
          actions: [
            {
              kind: "assign_client",
              label: `Atribuie primul lui ${client.name}`,
              summary: `„${first.originalFilename}” trece la ${client.name} și intră la verificare.`,
              payload: { documentId: first.id, clientId: client.id },
            },
          ],
          links: [{ label: "Neatribuite", path: "/documente/neatribuite" }],
        };
      },
    },
    {
      name: "my_tasks",
      permission: "tasks:read",
      description: "Sarcinile deschise ale utilizatorului curent.",
      run: () => {
        const mine = state.tasks.filter(
          (task) => task.assignedToId === currentUser.id && task.status !== "DONE",
        );
        if (mine.length === 0) return { text: "Nu ai nicio sarcină deschisă." };
        const lines = mine
          .slice(0, 5)
          .map((task) => `• ${task.title}${task.dueDate ? ` — termen ${task.dueDate}` : ""}`);
        return {
          text: `Sarcinile tale deschise:\n${lines.join("\n")}`,
          links: [{ label: "Toate sarcinile", path: "/crm/sarcini" }],
        };
      },
    },
  ];
}

/** Ordinea contează: de la cea mai îngustă intenție la cea mai largă. */
const ASSISTANT_INTENTS: Array<{
  tool: string;
  triggers: string[][];
  argument?: "month" | "client" | "raw" | "document";
}> = [
  // Prima, fiindcă este cea mai îngustă: „de ce e la verificare X" conține și
  // „verificare", care mai jos înseamnă cu totul altceva („cât e de lucru").
  { tool: "explain_document", triggers: [["de ce", "verificare"], ["de ce", "document"], ["de ce", "fisier"], ["explica", "document"], ["ce e cu"]], argument: "document" },
  { tool: "draft_request", triggers: [["scrie", "solicitare"], ["cere", "documente"], ["mesaj", "client"]], argument: "client" },
  { tool: "propose_task", triggers: [["noteaza"], ["adauga sarcina"], ["sarcina noua"], ["aminteste"]], argument: "raw" },
  { tool: "propose_assignment", triggers: [["atribuie"], ["neatribuit"], ["fara client"]], argument: "client" },
  { tool: "client_month", triggers: [["lipseste", "la"], ["cum sta"], ["situatia", "la"], ["stadiu"]], argument: "client" },
  { tool: "missing_documents", triggers: [["lipse"], ["nu au trimis"], ["incomplet"], ["nu a venit"]], argument: "month" },
  { tool: "deadline", triggers: [["termen"], ["scadent"], ["deadline"]], argument: "month" },
  { tool: "my_tasks", triggers: [["sarcin"], ["task"]] },
  { tool: "workload", triggers: [["cate"], ["cat", "lucru"], ["astept"], ["coada"], ["verificare"]] },
  { tool: "find_client", triggers: [["client"], ["firma"], ["cui"], ["caut"], ["deschide"]], argument: "client" },
];

const ASSISTANT_MONTHS: Record<string, number> = {
  ianuarie: 1, februarie: 2, martie: 3, aprilie: 4, mai: 5, iunie: 6,
  iulie: 7, august: 8, septembrie: 9, octombrie: 10, noiembrie: 11, decembrie: 12,
};

function assistantMonth(text: string): string {
  const explicit = /\b(20\d{2})[-/](0[1-9]|1[0-2])\b/.exec(text);
  if (explicit) return `${explicit[1]}-${explicit[2]}`;
  const normalised = assistantNormalise(text);
  for (const [name, number] of Object.entries(ASSISTANT_MONTHS)) {
    if (normalised.includes(name)) {
      return `${assistantPreviousMonth().slice(0, 4)}-${String(number).padStart(2, "0")}`;
    }
  }
  return "";
}

/** Numele scris între ghilimele — singurul mod de a spune unul cu spații. */
const ASSISTANT_QUOTED = /[„"']([^„”"']{2,120})[”"']/;

/** Terminațiile pe care le poartă un fișier acceptat la încărcare. */
const ASSISTANT_FILE_SUFFIX = /\S+\.(?:pdf|xml|jpe?g|png|webp)\b/i;

/**
 * Care document, dintr-o întrebare scrisă de om. Oglindește `extract_document`.
 *
 * Un nume de fișier se recunoaște singur, oriunde ar sta în frază. Când lipsește,
 * se ia ce urmează după „documentul"/„fișierul"; dacă nici asta nu e, se întoarce
 * gol, ca unealta să ceară lămurirea în loc să caute la întâmplare.
 */
function assistantDocument(text: string): string {
  // Ghilimelele întâi: un nume cu spații („28.5 scan.pdf") nu se poate prinde
  // altfel, iar tăiat la primul spațiu ar deveni „scan.pdf".
  const quoted = ASSISTANT_QUOTED.exec(text);
  if (quoted) return quoted[1]!.trim();

  const found = ASSISTANT_FILE_SUFFIX.exec(text);
  if (found) return found[0].replace(/^[\s?.,:;"„”]+|[\s?.,:;"„”]+$/g, "");

  const lowered = text.toLowerCase();
  for (const lead of ["documentul ", "document ", "fisierul ", "fișierul ", "factura "]) {
    const index = lowered.indexOf(lead);
    if (index >= 0) {
      return text.slice(index + lead.length).replace(/^[\s?.,:;"„”]+|[\s?.,:;"„”]+$/g, "");
    }
  }
  return "";
}

/** Ce a cerut omul, fără cuvântul de comandă din față. */
function assistantRaw(text: string): string {
  const normalised = assistantNormalise(text);
  for (const phrase of ["noteaza", "adauga sarcina", "sarcina noua", "aminteste-mi", "aminteste"]) {
    const index = normalised.indexOf(phrase);
    if (index >= 0) return text.slice(index + phrase.length).replace(/^[\s?.,:;-]+|[\s?.,:;-]+$/g, "");
  }
  return text.replace(/^[\s?.,:;]+|[\s?.,:;]+$/g, "");
}

function assistantClient(text: string): string {
  const normalised = assistantNormalise(text);
  // Ordinea contează: prima expresie găsită câștigă, deci cele lungi stau
  // înaintea celor scurte. Oglindește `extract_client` din backend.
  for (const phrase of [
    "scrie solicitarea pentru", "solicitarea pentru", "cere documente de la",
    "cere documentele de la", "atribuie documentele lui", "atribuie documentele catre",
    "atribuie lui", "atribuie", "ce lipseste la", "cum sta", "situatia la", "stadiu",
    "clientul", "client", "firma", "deschide", "caut", "cui",
  ]) {
    const index = normalised.indexOf(phrase);
    if (index >= 0) return text.slice(index + phrase.length).replace(/^[\s?.,:;]+|[\s?.,:;]+$/g, "");
  }
  return text.replace(/^[\s?.,:;]+|[\s?.,:;]+$/g, "");
}

const ASSISTANT_STARTERS: Array<[string, string]> = [
  ["cât e de lucru?", "workload"],
  ["când e termenul?", "deadline"],
  ["ce documente lipsesc?", "missing_documents"],
  ["sarcinile mele", "my_tasks"],
];

export function assistantAnswer(message: string): AssistantReply {
  const permissions = currentUser.permissions;
  const tools = assistantTools();
  const allowed = tools.filter((tool) => permissions.includes(tool.permission));
  const suggestions = ASSISTANT_STARTERS.filter(([, name]) =>
    allowed.some((tool) => tool.name === name),
  ).map(([starter]) => starter);

  const text = message.trim();
  const normalised = assistantNormalise(text);

  for (const intent of ASSISTANT_INTENTS) {
    if (!intent.triggers.some((group) => group.every((word) => normalised.includes(word)))) continue;

    const tool = tools.find((candidate) => candidate.name === intent.tool)!;
    if (!permissions.includes(tool.permission)) {
      return {
        text: `Rolul tău nu include permisiunea \`${tool.permission}\`, deci nu pot răspunde la asta.`,
        links: [],
        actions: [],
        suggestions,
        used: [],
        engine: "rules",
      };
    }

    const argument =
      intent.argument === "month"
        ? assistantMonth(text)
        : intent.argument === "client"
          ? assistantClient(text)
          : intent.argument === "raw"
            ? assistantRaw(text)
            : intent.argument === "document"
              ? assistantDocument(text)
              : "";
    const result = tool.run(argument);
    return {
      text: result.text,
      links: result.links ?? [],
      actions: result.actions ?? [],
      suggestions: result.suggestions ?? suggestions,
      used: [tool.name],
      engine: "rules",
    };
  }

  const lead = text ? "N-am înțeles întrebarea." : "Întreabă-mă ceva despre documentele sau clienții tăi.";
  return {
    text: `${lead} Pot răspunde la:\n${allowed.map((tool) => `• ${tool.description}`).join("\n")}`,
    links: [],
    actions: [],
    suggestions,
    used: [],
    engine: "rules",
  };
}
