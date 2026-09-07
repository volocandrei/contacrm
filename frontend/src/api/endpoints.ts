/** Funcțiile tipate care acoperă API-ul (§38). Un singur loc care cunoaște căile. */
import { api, request } from "@/api/client";
import type { Paginated, QueryParams } from "@/api/types";
import type {
  AccountingPeriod,
  AnafMandate,
  AnafStatus,
  AnafSyncResult,
  AssistantReply,
  AuditLogEntry,
  ChecklistItem,
  Client,
  ClientAlias,
  ClientExpectation,
  ClientFee,
  ClientNote,
  ClientStatus,
  ClientTimelineEvent,
  Contact,
  ContactListItem,
  CurrentUser,
  DashboardData,
  DocumentDetail,
  DocumentFieldName,
  DocumentListItem,
  DocumentRequest,
  DocumentRequestSent,
  DocumentType,
  DriveBrowseItem,
  DriveFolder,
  DriveStatus,
  DriveSyncResult,
  DueObligation,
  ExpectationTemplate,
  FeeMonth,
  FeeRow,
  FilingsResult,
  Intake,
  IssuedUploadLink,
  MailBrowseItem,
  MailFolder,
  ObligationFiling,
  ObligationType,
  Reminders,
  ReminderSendReport,
  ReportSummary,
  RoleCode,
  RoleInfo,
  SendRequestsResult,
  SettingEntry,
  Task,
  TaskPriority,
  TaskStatus,
  UploadLink,
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

/**
 * Asistentul (M13).
 *
 * O singură rută, de citire. Nu există aici nicio funcție care schimbă date —
 * asistentul propune drumuri, omul le urmează.
 */
export const assistant = {
  ask: (message: string) => api.post<AssistantReply>("/assistant/chat", { message }),
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
  aliases: (id: string) => api.get<ClientAlias[]>(`/clients/${id}/aliases`),
  /** Ce s-a întâmplat cu clientul, în ordine: documente, cereri, depuneri, luni. */
  timeline: (id: string) => api.get<ClientTimelineEvent[]>(`/clients/${id}/timeline`),
  uploadLinks: (id: string) => api.get<UploadLink[]>(`/clients/${id}/upload-links`),
  createUploadLink: (id: string) =>
    api.post<IssuedUploadLink>(`/clients/${id}/upload-links`),
  revokeUploadLink: (clientId: string, linkId: string) =>
    api.delete<void>(`/clients/${clientId}/upload-links/${linkId}`),
  forgetAlias: (clientId: string, aliasId: string) =>
    api.delete<void>(`/clients/${clientId}/aliases/${aliasId}`),
  /**
   * Textul prin care i se cer clientului documentele lipsă.
   *
   * Vine de la server, nu se compune aici: mesajul spune numele
   * cabinetului și listează ce lipsește — este conținut de business, iar
   * asistentul îl scrie din același loc. Două formulări ar însemna că doi
   * clienți primesc, în aceeași zi, mesaje diferite de la același cabinet.
   */
  /**
   * Compune solicitarea și deschide drumul pe care sosesc documentele.
   *
   * Este POST fiindcă **creează** un link de trimitere. Un GET care creează ceva
   * s-ar executa din nou la fiecare reîncărcare de pagină și la fiecare retry.
   */
  /**
   * Aceeași solicitare, dar **trimisă** din aplicație.
   *
   * Rută separată de cea care compune: compunerea se face și când omul vrea doar
   * să copieze textul, iar a trimite este o acțiune cu efect în afara aplicației.
   * Efectele acelea nu se produc ca efect secundar al unei citiri.
   */
  sendDocumentRequest: (id: string, referenceMonth: string, to?: string) =>
    // `request` direct, ca la ruta care compune: luna merge prin `params`, iar
    // lipită în cale backendul simulat n-ar mai potrivi tiparul.
    request<DocumentRequestSent>("POST", `/clients/${id}/document-request/send`, {
      params: { referenceMonth },
      body: { to: to ?? null },
    }),
  documentRequest: (id: string, referenceMonth: string) =>
    // `request` direct, nu `api.post`: interogarea trebuie să meargă prin
    // `params`, iar `api.post` ia doar corpul. Lipită în cale, backendul simulat
    // n-ar mai potrivi ruta — el compară tipare pe calea curată.
    request<DocumentRequest>("POST", `/clients/${id}/document-request`, {
      params: { referenceMonth },
    }),
};

/**
 * Reminderele către clienți.
 *
 * Citirea nu trimite nimic și nu deschide niciun link: ecranul arată cine ar
 * primi și **de ce ceilalți nu**. Efectele se produc doar din `send`.
 */
export const reminders = {
  list: () => api.get<Reminders>("/reminders"),
  send: () => api.post<ReminderSendReport>("/reminders/send"),
};

/**
 * Agenda cabinetului (§8).
 *
 * O singură cerere pentru tot ecranul. Înainte, „Contacte" cerea lista de
 * clienți și apoi contactele fiecăruia — treizeci de cereri pentru treizeci
 * de clienți, pornite deodată.
 */
export const contacts = {
  list: (params: QueryParams) => api.get<Paginated<ContactListItem>>("/contacts", params),
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
  /** Termenul de depunere al lunii, „YYYY-MM-DD". Același pentru toate rândurile. */
  deadline: string;
  /**
   * Când s-a pregătit ultima cerere pentru clientul ăsta, pe luna asta.
   *
   * `null` înseamnă **nu i s-a cerut niciodată** — cel mai util lucru de pe rând:
   * dintr-o listă de treizeci de clienți, aceia sunt cei la care mai e ceva de
   * făcut; restul așteaptă răspuns.
   *
   * Spune că textul a fost **compus**. Dacă a și plecat din aplicație o spune
   * `notifiedAt`; când acela lipsește, mesajul a fost copiat, iar aplicația nu
   * are de unde ști dacă omul l-a lipit într-un email.
   */
  requestedAt: string | null;
  /**
   * Când a plecat mesajul din aplicație, dacă a plecat.
   *
   * Singura diferență între „Pregătit" și „Trimis" care nu este o presupunere.
   */
  notifiedAt: string | null;
  /** Câte documente au intrat prin linkul acelei cereri. Zero = n-a atins drumul. */
  receivedThroughLink: number;
};

export type ExpectationInput = { documentTypeCode: string; expectedMinCount: number };

export const expectationTemplates = {
  list: () => api.get<ExpectationTemplate[]>("/expectation-templates"),
  create: (name: string, expectations: ExpectationInput[], obligationTypeIds: string[] = []) =>
    api.post<ExpectationTemplate>("/expectation-templates", {
      name,
      expectations,
      obligationTypeIds,
    }),
  update: (
    id: string,
    name: string,
    expectations: ExpectationInput[],
    obligationTypeIds: string[] = [],
  ) =>
    api.put<ExpectationTemplate>(`/expectation-templates/${id}`, {
      name,
      expectations,
      obligationTypeIds,
    }),
  remove: (id: string) => api.delete<void>(`/expectation-templates/${id}`),
  /** Salvează ce s-a configurat deja pe un client, ca profil. */
  fromClient: (clientId: string, name: string) =>
    api.post<ExpectationTemplate>(`/expectation-templates/from-client/${clientId}`, { name }),
  apply: (id: string, clientIds: string[]) =>
    api.post<{ applied: number }>(`/expectation-templates/${id}/apply`, { clientIds }),
};

export const periods = {
  list: (params: QueryParams) => api.get<AccountingPeriod[]>("/periods", params),
  missing: (referenceMonth: string) =>
    api.get<MissingDocumentsEntry[]>("/periods/missing", { referenceMonth }),
  /**
   * Cererea către mai mulți clienți deodată.
   *
   * Se trimit **id-urile de pe ecran**, nu „toți cei care se potrivesc": un
   * „tuturor" interpretat de server ar putea scrie, la o diferență de o secundă
   * între ce s-a afișat și ce s-a apăsat, unui client în plus. Iar un email
   * plecat nu se retrage.
   */
  sendRequests: (referenceMonth: string, clientIds: string[]) =>
    request<SendRequestsResult>("POST", "/periods/missing/send-requests", {
      params: { referenceMonth },
      body: { clientIds },
    }),
};

/**
 * Termenele de depunere.
 *
 * Fereastra implicită o alege serverul și pornește **din urmă**: un termen ratat
 * nu se rezolvă trecând timpul, iar o listă care ar începe de azi l-ar ascunde
 * exact pe cel care contează cel mai mult.
 */
export const obligations = {
  upcoming: (params: QueryParams = {}) => api.get<DueObligation[]>("/obligations", params),
  types: () => api.get<ObligationType[]>("/obligations/types"),
  updateType: (id: string, changes: Partial<Omit<ObligationType, "id" | "code">>) =>
    api.patch<ObligationType>(`/obligations/types/${id}`, { ...changes }),
  forClient: (clientId: string) =>
    api.get<ObligationType[]>(`/obligations/clients/${clientId}`),
  setForClient: (clientId: string, obligationTypeIds: string[]) =>
    api.put<ObligationType[]>(`/obligations/clients/${clientId}`, { obligationTypeIds }),
  markFiled: (input: { clientId: string; obligationTypeId: string; period: string }) =>
    api.post<ObligationFiling>("/obligations/filings", { ...input }),
  /**
   * Un teanc de depuneri deodată.
   *
   * Se trimit **rândurile de pe ecran**, nu un criteriu. Un „toate cele de pe 25
   * septembrie" interpretat de server ar putea prinde o declarație în plus, iar
   * „depus" este o afirmație care ajunge într-o evidență contabilă.
   */
  markManyFiled: (filings: { clientId: string; obligationTypeId: string; period: string }[]) =>
    api.post<FilingsResult>("/obligations/filings/bulk", { filings }),
  unmarkFiled: (input: { clientId: string; obligationTypeId: string; period: string }) =>
    api.delete<void>("/obligations/filings", { ...input }),
};

/**
 * Onorariile cabinetului.
 *
 * O singură cerere aduce tot ecranul: rândurile, cifrele și restanțele vechi.
 * Trei cereri separate ar fi putut ajunge pe ecran în trei stări diferite ale
 * aceleiași luni.
 */
export const fees = {
  month: (referenceMonth: string) => api.get<FeeMonth>("/fees", { referenceMonth }),
  generate: (referenceMonth: string) => api.post<FeeMonth>("/fees/generate", { referenceMonth }),
  forClient: (clientId: string) => api.get<ClientFee>(`/fees/clients/${clientId}`),
  /** Ce s-a facturat clientului, luna cu luna — răspunsul la „eu am plătit în martie". */
  history: (clientId: string) => api.get<FeeRow[]>(`/fees/clients/${clientId}/history`),
  setForClient: (
    clientId: string,
    input: {
      amount: string | null;
      currency?: string;
      startsOn?: string | null;
      note?: string | null;
    },
  ) => api.put<ClientFee>(`/fees/clients/${clientId}`, { ...input }),
  markPaid: (input: { clientId: string; referenceMonth: string; paidOn?: string | null }) =>
    api.post<FeeRow>("/fees/payments", { ...input }),
  unmarkPaid: (input: { clientId: string; referenceMonth: string }) =>
    api.delete<FeeRow>("/fees/payments", { ...input }),
};

export type TaskInput = {
  title: string;
  description?: string;
  clientId?: string | null;
  assignedToId?: string | null;
  priority?: TaskPriority;
  dueDate?: string | null;
};

export const tasks = {
  list: (params: QueryParams) => api.get<Task[]>("/tasks", params),
  create: (input: TaskInput) => api.post<Task>("/tasks", { ...input }),
  updateStatus: (id: string, status: TaskStatus) => api.patch<Task>(`/tasks/${id}`, { status }),
};

/** Cronologia recepțiilor (M12): ce a sosit, de la cine și când. */
export const intakes = {
  list: (params: QueryParams) => api.get<Paginated<Intake>>("/intakes", params),
  forClient: (id: string, params?: QueryParams) =>
    api.get<Paginated<Intake>>(`/clients/${id}/intakes`, params),
};

export const administration = {
  auditLogs: (params: QueryParams) => api.get<Paginated<AuditLogEntry>>("/audit-logs", params),
  users: () => api.get<UserSummary[]>("/users"),
  // Matricea rol × permisiune. Nu depinde de organizație și nu se schimbă
  // decât la un deploy — de aceea ecranul o poate ține în cache mult.
  roles: () => api.get<RoleInfo[]>("/roles"),
  createUser: (input: {
    email: string;
    fullName: string;
    role: RoleCode;
    password: string;
  }) => api.post<UserSummary>("/users", { ...input }),
  updateUser: (
    id: string,
    input: { fullName?: string; role?: RoleCode; isActive?: boolean },
  ) => api.patch<UserSummary>(`/users/${id}`, { ...input }),
  // `POST`, nu `PATCH`: nu este o modificare a contului, este o resetare.
  resetPassword: (id: string, password: string) =>
    api.post<UserSummary>(`/users/${id}/password`, { password }),
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
