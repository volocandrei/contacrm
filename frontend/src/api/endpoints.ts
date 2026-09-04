/** Funcțiile tipate care acoperă API-ul (§38). Un singur loc care cunoaște căile. */
import { api } from "@/api/client";
import type { Paginated, QueryParams } from "@/api/types";
import type {
  AccountingPeriod,
  AnafMandate,
  AnafStatus,
  AnafSyncResult,
  AuditLogEntry,
  ChecklistItem,
  Client,
  ClientExpectation,
  ClientNote,
  ClientStatus,
  Contact,
  CurrentUser,
  DashboardData,
  DocumentDetail,
  DocumentFieldName,
  DocumentListItem,
  DocumentType,
  DriveBrowseItem,
  DriveFolder,
  DriveStatus,
  DriveSyncResult,
  MailBrowseItem,
  MailFolder,
  ReportSummary,
  SettingEntry,
  Task,
  TaskStatus,
  UserSummary,
} from "@/types/domain";

export type SidebarCounts = {
  inbox: number;
  review: number;
  unmatched: number;
  tasks: number;
};

export type BulkResult = {
  succeeded: string[];
  failed: Array<{ id: string; message: string }>;
};

export type BulkPayload =
  | { action: "approve" }
  | { action: "reject"; reason: string }
  | { action: "assignClient"; clientId: string }
  | { action: "markDuplicate" }
  | { action: "reprocess" };

export const auth = {
  login: (email: string, password: string) =>
    api.post<CurrentUser>("/auth/login", { email, password }),
  logout: () => api.post<{ ok: boolean }>("/auth/logout"),
  me: () => api.get<CurrentUser>("/me"),
};

export const reports = {
  summary: (params: QueryParams) => api.get<ReportSummary>("/reports/summary", params),
};

export const dashboard = {
  get: () => api.get<DashboardData>("/dashboard"),
  counts: () => api.get<SidebarCounts>("/dashboard/counts"),
};

/** Ce se poate scrie despre un client. Fără `tags`: etichetele au ecranul lor. */
export type ClientInput = {
  name?: string;
  taxId?: string | null;
  registrationNumber?: string | null;
  address?: string | null;
  status?: ClientStatus;
  assignedAccountantId?: string | null;
};

export type ContactInput = {
  fullName?: string;
  role?: string | null;
  email?: string | null;
  phone?: string | null;
  whatsappNumber?: string | null;
  isPrimary?: boolean;
  isActive?: boolean;
};

export const clients = {
  list: (params: QueryParams) => api.get<Paginated<Client>>("/clients", params),
  create: (input: ClientInput) => api.post<Client>("/clients", { ...input }),
  // `PATCH`, nu `PUT`: ce nu se trimite rămâne neatins. Un formular care trimite
  // doar statusul nu are voie să golească CUI-ul.
  update: (id: string, input: ClientInput) => api.patch<Client>(`/clients/${id}`, { ...input }),
  createContact: (clientId: string, input: ContactInput) =>
    api.post<Contact>(`/clients/${clientId}/contacts`, { ...input }),
  updateContact: (clientId: string, contactId: string, input: ContactInput) =>
    api.patch<Contact>(`/clients/${clientId}/contacts/${contactId}`, { ...input }),
  get: (id: string) => api.get<Client>(`/clients/${id}`),
  contacts: (id: string) => api.get<Contact[]>(`/clients/${id}/contacts`),
  notes: (id: string) => api.get<ClientNote[]>(`/clients/${id}/notes`),
  createNote: (id: string, body: string) =>
    api.post<ClientNote>(`/clients/${id}/notes`, { body }),
  expectations: (id: string) => api.get<ClientExpectation[]>(`/clients/${id}/expectations`),
  // PUT, nu PATCH: se trimite lista întreagă, adică starea de după.
  setExpectations: (
    id: string,
    expectations: Array<{ documentTypeCode: string; expectedMinCount: number }>,
  ) => api.put<ClientExpectation[]>(`/clients/${id}/expectations`, { expectations }),
  periods: (id: string) => api.get<AccountingPeriod[]>(`/clients/${id}/periods`),
};

export const documents = {
  list: (params: QueryParams) => api.get<Paginated<DocumentListItem>>("/documents", params),
  get: (id: string) => api.get<DocumentDetail>(`/documents/${id}`),
  upload: (file: File, clientId?: string) =>
    api.upload<DocumentDetail>(
      "/documents/upload",
      file,
      clientId ? { clientId } : undefined,
    ),
  nextReview: (after?: string) =>
    api.get<DocumentDetail | null>("/documents/next-review", after ? { after } : undefined),
  updateFields: (id: string, updates: Array<{ field: DocumentFieldName; value: string | null }>) =>
    api.patch<DocumentDetail>(`/documents/${id}`, { updates }),
  assignClient: (id: string, clientId: string) =>
    api.post<DocumentDetail>(`/documents/${id}/assign-client`, { clientId }),
  approve: (id: string) => api.post<DocumentDetail>(`/documents/${id}/approve`),
  reject: (id: string, reason: string) =>
    api.post<DocumentDetail>(`/documents/${id}/reject`, { reason }),
  markDuplicate: (id: string, duplicateOfId?: string | null) =>
    api.post<DocumentDetail>(`/documents/${id}/duplicate`, { duplicateOfId: duplicateOfId ?? null }),
  reprocess: (id: string) => api.post<DocumentDetail>(`/documents/${id}/reprocess`),
  bulk: (ids: string[], payload: BulkPayload) =>
    api.post<BulkResult>("/documents/bulk", { ids, payload }),
  types: () => api.get<DocumentType[]>("/document-types"),
};

export type MissingDocumentsEntry = {
  period: AccountingPeriod;
  missing: ChecklistItem[];
};

export const periods = {
  list: (params: QueryParams) => api.get<AccountingPeriod[]>("/periods", params),
  missing: (referenceMonth: string) =>
    api.get<MissingDocumentsEntry[]>("/periods/missing", { referenceMonth }),
};

export const tasks = {
  list: (params: QueryParams) => api.get<Task[]>("/tasks", params),
  updateStatus: (id: string, status: TaskStatus) => api.patch<Task>(`/tasks/${id}`, { status }),
};

export const administration = {
  auditLogs: (params: QueryParams) => api.get<Paginated<AuditLogEntry>>("/audit-logs", params),
  users: () => api.get<UserSummary[]>("/users"),
  settings: () => api.get<SettingEntry[]>("/settings"),
};

/**
 * Integrarea e-Factura / SPV ANAF (M11). Tokenul nu circulă niciodată pe aici (§73).
 *
 * `authorize` întoarce o adresă care **cere certificatul digital** în browser.
 * Pasul acela nu se poate face de pe server și nu se poate automatiza.
 */
export const anaf = {
  status: () => api.get<AnafStatus>("/integrations/anaf"),
  authorize: () => api.post<{ authorizeUrl: string }>("/integrations/anaf/authorize"),
  connect: (code: string, state: string, certificateHolder?: string) =>
    api.post<AnafStatus>("/integrations/anaf/connect", { code, state, certificateHolder }),
  disconnect: () => api.delete<void>("/integrations/anaf"),
  addMandate: (clientId: string) =>
    api.post<AnafMandate>("/integrations/anaf/mandates", { clientId }),
  updateMandate: (id: string, isActive: boolean) =>
    api.patch<AnafMandate>(`/integrations/anaf/mandates/${id}`, { isActive }),
  removeMandate: (id: string) => api.delete<void>(`/integrations/anaf/mandates/${id}`),
  sync: () => api.post<AnafSyncResult>("/integrations/anaf/sync"),
};

/** Integrarea OneDrive (M9). Tokenul nu circulă niciodată pe aici (§73). */
export const drive = {
  status: () => api.get<DriveStatus>("/integrations/onedrive"),
  authorize: () => api.post<{ authorizeUrl: string }>("/integrations/onedrive/authorize"),
  connect: (code: string, state: string) =>
    api.post<DriveStatus>("/integrations/onedrive/connect", { code, state }),
  disconnect: () => api.delete<void>("/integrations/onedrive"),
  browse: (parentId?: string) =>
    api.get<DriveBrowseItem[]>(
      "/integrations/onedrive/browse",
      parentId ? { parentId } : undefined,
    ),
  trackFolder: (input: {
    driveId: string;
    itemId: string;
    path: string;
    clientId?: string | null;
  }) => api.post<DriveFolder>("/integrations/onedrive/folders", { ...input }),
  updateFolder: (id: string, input: { clientId?: string | null; isActive?: boolean }) =>
    api.patch<DriveFolder>(`/integrations/onedrive/folders/${id}`, { ...input }),
  untrackFolder: (id: string) => api.delete<void>(`/integrations/onedrive/folders/${id}`),
  sync: () => api.post<DriveSyncResult>("/integrations/onedrive/sync"),
  // Cutia poștală: aceeași conexiune, alt fel de sursă.
  browseMail: () => api.get<MailBrowseItem[]>("/integrations/onedrive/mail-folders"),
  trackMailFolder: (input: { folderId: string; displayName: string }) =>
    api.post<MailFolder>("/integrations/onedrive/mail-folders", { ...input }),
  updateMailFolder: (id: string, isActive: boolean) =>
    api.patch<MailFolder>(`/integrations/onedrive/mail-folders/${id}`, { isActive }),
  untrackMailFolder: (id: string) =>
    api.delete<void>(`/integrations/onedrive/mail-folders/${id}`),
};
