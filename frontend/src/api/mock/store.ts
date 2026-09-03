/**
 * Backend simulat, în memorie. Implementează aceleași rute și aceeași semantică
 * (paginare, filtrare, coduri de eroare) ca API-ul real planificat, ca trecerea la
 * backend să fie o schimbare de configurare, nu o rescriere a interfeței.
 *
 * Starea trăiește doar în tab-ul curent: la reîncărcare se reia de la setul sintetic.
 */
import { ApiError, type Paginated } from "@/api/types";
import {
  AUDIT_LOGS,
  CLIENTS,
  CLIENT_NOTES,
  CONTACTS,
  DOCUMENTS,
  DOCUMENT_TYPES,
  DOCUMENT_TYPE_LABEL,
  MESSAGES,
  MOCK_NOW,
  PERIODS,
  TASKS,
  USERS,
  derivePeriodStatus,
  type StoredDocument,
  periodProgress,
} from "@/api/mock/seed";
import { buildArchivePath, buildDocumentFilename, type FilenameInput } from "@/lib/filename";
import type {
  AuditLogEntry,
  Client,
  ClientNote,
  CommunicationMessage,
  Contact,
  CurrentUser,
  DashboardData,
  DocumentAction,
  DocumentDetail,
  DocumentFieldName,
  DocumentListItem,
  DocumentStatus,
  Permission,
  ReportBucket,
  ReportSummary,
  RoleCode,
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
  messages: structuredClone(MESSAGES) as CommunicationMessage[],
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

export function listClientMessages(clientId: string): CommunicationMessage[] {
  return state.messages.filter((m) => m.clientId === clientId);
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

export function listDocuments(filters: DocumentFilters): Paginated<DocumentListItem> {
  let items = state.documents;

  if (filters.q) {
    items = items.filter((d) =>
      matches(
        [d.originalFilename, d.storedFilename, d.clientName, d.supplierName, d.documentNumber],
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

/** Documentele așteptate care încă lipsesc, per client (§19). */
export function listMissingDocuments(referenceMonth: string) {
  return listPeriods({ referenceMonth })
    .map((period) => ({
      period,
      missing: period.checklist.filter((item) => !item.isSatisfied),
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

export function listUsers(): UserSummary[] {
  requirePermission("admin:users");
  return state.users;
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
  ];
}

export function listMessages(filters: { clientId?: string; channel?: string }) {
  let items = state.messages;
  if (filters.clientId) items = items.filter((m) => m.clientId === filters.clientId);
  if (filters.channel) items = items.filter((m) => m.channel === filters.channel);
  return items;
}

export function listDocumentTypes() {
  return DOCUMENT_TYPES;
}

/* ─── Dashboard ────────────────────────────────────────────────────────────── */

export function getDashboard(): DashboardData {
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

/** Contoarele afișate în meniul lateral. */
export function getSidebarCounts() {
  return {
    inbox: state.documents.filter((d) => d.status === "RECEIVED" || d.status === "PROCESSING").length,
    review: state.documents.filter((d) => d.status === "REVIEW_REQUIRED").length,
    unmatched: state.documents.filter((d) => d.status === "UNMATCHED").length,
    tasks: state.tasks.filter((t) => t.status !== "DONE").length,
  };
}
