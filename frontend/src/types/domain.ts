/**
 * Tipurile de domeniu, oglindind contractul backend-ului planificat.
 * Sursa de adevăr rămâne backend-ul; aici doar tipăm ce consumă interfața.
 */

/* ─── Statusuri centralizate (§53) ─────────────────────────────────────────── */

export const DOCUMENT_STATUS = [
  "RECEIVED",
  "PROCESSING",
  "REVIEW_REQUIRED",
  "APPROVED",
  "ARCHIVED",
  "ERROR",
  "DUPLICATE",
  "REJECTED",
  "UNMATCHED",
] as const;
export type DocumentStatus = (typeof DOCUMENT_STATUS)[number];

export const CLIENT_STATUS = ["ACTIVE", "INACTIVE", "PROSPECT", "SUSPENDED"] as const;
export type ClientStatus = (typeof CLIENT_STATUS)[number];

export const PERIOD_STATUS = [
  "NOT_STARTED",
  "COLLECTING",
  "PARTIAL",
  "COMPLETE",
  "PROCESSING",
  "REVIEW",
  "FINALIZED",
] as const;
export type PeriodStatus = (typeof PERIOD_STATUS)[number];

export const DOCUMENT_SOURCE = [
  "EMAIL",
  "WHATSAPP",
  "UPLOAD",
  "API",
  "ONEDRIVE",
  "EFACTURA",
] as const;
export type DocumentSource = (typeof DOCUMENT_SOURCE)[number];

/** Motivul structurat al unui eșec de procesare — se afișează, nu se aruncă (§53). */
export const DOCUMENT_ERROR_CODE = [
  "INVALID_FILE",
  "UNSUPPORTED_FORMAT",
  "FILE_TOO_LARGE",
  "OCR_FAILED",
  "EXTRACTION_FAILED",
  "CLASSIFICATION_FAILED",
  "VALIDATION_FAILED",
  "DUPLICATE_DETECTED",
  "CLIENT_NOT_FOUND",
  "STORAGE_FAILED",
  "ARCHIVE_FAILED",
  "INTERNAL_ERROR",
] as const;
export type DocumentErrorCode = (typeof DOCUMENT_ERROR_CODE)[number];

/**
 * Ce poate face utilizatorul curent cu un document, în starea lui de acum.
 * Lista vine de la server (`availableActions`): regulile ciclului de viață trăiesc
 * în backend, iar interfața doar le respectă. Nu le recalculează — o a doua copie
 * ar rămâne în urmă tăcut.
 */
export const DOCUMENT_ACTION = [
  "edit",
  "assignClient",
  "approve",
  "reject",
  "markDuplicate",
  "reprocess",
  "download",
] as const;
export type DocumentAction = (typeof DOCUMENT_ACTION)[number];

export const TASK_STATUS = ["TODO", "IN_PROGRESS", "BLOCKED", "DONE"] as const;
export type TaskStatus = (typeof TASK_STATUS)[number];

export const TASK_PRIORITY = ["LOW", "NORMAL", "HIGH", "URGENT"] as const;
export type TaskPriority = (typeof TASK_PRIORITY)[number];

export const ROLE_CODE = [
  "SUPER_ADMIN",
  "ADMIN",
  "ACCOUNTANT",
  "OPERATOR",
  "REVIEWER",
  "VIEWER",
] as const;
export type RoleCode = (typeof ROLE_CODE)[number];

/* ─── Tipuri de document (§6) — extensibile din administrare ────────────────── */

export type DocumentTypeCode = string;

export type DocumentType = {
  code: DocumentTypeCode;
  label: string;
  isActive: boolean;
  /** Câmpuri fără de care documentul nu poate fi aprobat (§17). */
  requiredFields: string[];
};

/* ─── Utilizatori și permisiuni ────────────────────────────────────────────── */

export type Permission =
  | "clients:read"
  | "clients:write"
  | "documents:read"
  | "documents:write"
  | "documents:approve"
  | "documents:delete"
  | "periods:manage"
  | "tasks:read"
  | "tasks:write"
  | "communication:send"
  | "admin:users"
  | "admin:settings"
  | "audit:read";

export type CurrentUser = {
  id: string;
  fullName: string;
  email: string;
  role: RoleCode;
  permissions: Permission[];
  organizationId: string;
  organizationName: string;
};

export type UserSummary = {
  id: string;
  fullName: string;
  email: string;
  role: RoleCode;
  isActive: boolean;
  lastLoginAt: string | null;
};

/* ─── CRM ──────────────────────────────────────────────────────────────────── */

export type Client = {
  id: string;
  name: string;
  taxId: string;
  registrationNumber: string;
  address: string;
  status: ClientStatus;
  assignedAccountantId: string | null;
  assignedAccountantName: string | null;
  tags: string[];
  lastInteractionAt: string | null;
  createdAt: string;
};

export type Contact = {
  id: string;
  clientId: string;
  fullName: string;
  role: string;
  email: string | null;
  phone: string | null;
  whatsappNumber: string | null;
  isPrimary: boolean;
  isActive: boolean;
};

export type ClientNote = {
  id: string;
  clientId: string;
  authorName: string;
  body: string;
  createdAt: string;
};

export type Task = {
  id: string;
  title: string;
  description: string;
  clientId: string | null;
  clientName: string | null;
  assignedToId: string | null;
  assignedToName: string | null;
  priority: TaskPriority;
  status: TaskStatus;
  dueDate: string | null;
  createdAt: string;
  completedAt: string | null;
};

/* ─── Contabilitate ────────────────────────────────────────────────────────── */

export type ChecklistItem = {
  documentType: DocumentTypeCode;
  documentTypeLabel: string;
  expectedMinCount: number;
  receivedCount: number;
  isSatisfied: boolean;
};

/**
 * Ce se așteaptă lunar de la un client.
 *
 * Fără ele, checklistul lunii este gol, „Documente lipsă" nu are ce raporta, iar
 * fiecare perioadă apare completă — pentru că nu i se cere nimic.
 */
export type ClientExpectation = {
  /** Tipul se numește prin cod, ca peste tot în contract — nu prin id intern. */
  documentTypeCode: string;
  documentTypeLabel: string;
  expectedMinCount: number;
};

export type AccountingPeriod = {
  id: string;
  clientId: string;
  clientName: string;
  year: number;
  month: number;
  /** "YYYY-MM" */
  referenceMonth: string;
  status: PeriodStatus;
  /** Toate documentele primite pentru client în luna respectivă, de orice tip. */
  receivedCount: number;
  /**
   * Câte dintre documentele *așteptate* au sosit — suma pe checklist a lui
   * min(primite, minim cerut). Ăsta este numărul care măsoară progresul; o factură
   * în plus nu compensează un extras de cont lipsă.
   */
  satisfiedCount: number;
  /** Suma minimelor din checklist. */
  expectedCount: number;
  checklist: ChecklistItem[];
  openedAt: string | null;
  closedAt: string | null;
  completedAt: string | null;
};

/* ─── Documente ────────────────────────────────────────────────────────────── */

/**
 * De unde provine valoarea unui câmp — se afișează în ecranul de verificare (§22).
 *
 * `DERIVED` înseamnă calculată de o regulă a sistemului, nu citită de pe document:
 * luna contabilă dedusă din data documentului (ADR-008). Se ține separat de `AI`
 * pentru că un badge „AI 83%" pe o valoare pe care modelul nu a produs-o ar fi exact
 * minciuna pe care ecranul promite să nu o spună.
 */
export type FieldSource = "AI" | "OCR" | "MANUAL" | "DERIVED" | "EMPTY";

export type ExtractedField<T = string> = {
  value: T | null;
  source: FieldSource;
  /** null pentru valori introduse manual sau lipsă. */
  confidence: number | null;
};

export type DocumentFields = {
  documentType: ExtractedField<DocumentTypeCode>;
  documentDate: ExtractedField<string>;
  series: ExtractedField<string>;
  documentNumber: ExtractedField<string>;
  supplierName: ExtractedField<string>;
  supplierTaxId: ExtractedField<string>;
  customerName: ExtractedField<string>;
  customerTaxId: ExtractedField<string>;
  currency: ExtractedField<string>;
  /** Sumele circulă ca string — Decimal în backend, niciodată float (§72). */
  subtotal: ExtractedField<string>;
  vatAmount: ExtractedField<string>;
  totalAmount: ExtractedField<string>;
  referenceMonth: ExtractedField<string>;
};

export type DocumentFieldName = keyof DocumentFields;

export type DocumentListItem = {
  id: string;
  originalFilename: string;
  storedFilename: string | null;
  clientId: string | null;
  clientName: string | null;
  documentTypeCode: DocumentTypeCode | null;
  documentTypeLabel: string | null;
  source: DocumentSource;
  receivedAt: string;
  documentDate: string | null;
  referenceMonth: string | null;
  supplierName: string | null;
  documentNumber: string | null;
  totalAmount: string | null;
  currency: string | null;
  status: DocumentStatus;
  confidence: number | null;
  isDuplicate: boolean;
  reviewRequired: boolean;
};

export type DocumentHistoryEntry = {
  id: string;
  at: string;
  actor: string;
  action: string;
  detail: string | null;
};

export type DocumentDetail = DocumentListItem & {
  mimeType: string;
  fileSize: number;
  sha256: string;
  duplicateOfId: string | null;
  /** Prezent doar când procesarea a eșuat; codul se traduce, urma de stivă nu. */
  errorCode: DocumentErrorCode | null;
  processingAttempts: number;
  fields: DocumentFields;
  ocr: {
    provider: string;
    confidence: number | null;
    /** Fragment din textul OCR, pentru context în verificare. */
    textPreview: string | null;
  };
  extraction: {
    provider: string;
    model: string | null;
    promptVersion: string | null;
    durationMs: number | null;
  };
  /** Motivele pentru care documentul a fost trimis la verificare (§17). */
  validationIssues: string[];
  /** Ergonomie de interfață: serverul reverifică oricum la fiecare cerere. */
  availableActions: DocumentAction[];
  /** Ce mai lipsește pentru aprobare — aceleași motive pe care le-ar da un 422. */
  approvalBlockers: string[];
  /** `null` când reprocesarea este posibilă; altfel motivul, în cuvintele serverului. */
  reprocessBlockedReason: string | null;
  history: DocumentHistoryEntry[];
  /**
   * Fișierele documentului, când sunt mai multe decât unul.
   *
   * Există pentru factura electronică, unde „documentul" ajunge ca trei fișiere:
   * XML-ul (originalul fiscal, cel de la butonul de descărcare), arhiva ZIP cu
   * sigiliul ANAF și PDF-ul tipăribil. Goală pentru restul documentelor.
   */
  files: DocumentFile[];
};

/** Un fișier al documentului. Eticheta vine de la server, nu dintr-o hartă locală. */
export type DocumentFile = {
  id: string;
  kind: string;
  label: string;
  mimeType: string;
  fileSize: number;
  createdAt: string;
};

/* ─── Dashboard ────────────────────────────────────────────────────────────── */

export type AttentionReason =
  | "UNMATCHED_CLIENT"
  | "OCR_FAILED"
  | "LOW_CONFIDENCE"
  | "POSSIBLE_DUPLICATE"
  | "MISSING_DATE"
  | "STUCK_IN_PROCESSING"
  | "INCOMPLETE_PERIOD";

export type AttentionItem = {
  id: string;
  documentId: string | null;
  reason: AttentionReason;
  title: string;
  detail: string;
  occurredAt: string;
};

export type TimelineEvent = {
  id: string;
  occurredAt: string;
  kind: "DOCUMENTS_RECEIVED" | "PROCESSED" | "NEEDS_REVIEW" | "NOTIFICATION_SENT" | "MESSAGE";
  description: string;
};

export type DashboardKpis = {
  clientsTotal: number;
  clientsActive: number;
  clientsComplete: number;
  clientsMissingDocs: number;
  documentsToday: number;
  documentsProcessing: number;
  documentsError: number;
  documentsNeedReview: number;
  documentsDuplicate: number;
  documentsUnmatched: number;
};

export type DashboardData = {
  /**
   * Luna pe care o descriu cifrele, sau `null` când nu există niciun document.
   *
   * Vine de la server pentru că el o știe: o derivă din date (`latest_active_month`),
   * nu din calendar. Ecranul o scria de mână — „August 2026" — sub niște cifre care
   * puteau fi din altă lună.
   */
  referenceMonth: string | null;
  kpis: DashboardKpis;
  attention: AttentionItem[];
  recentDocuments: DocumentListItem[];
  periods: AccountingPeriod[];
  timeline: TimelineEvent[];
  /**
   * Termenul lunii în lucru și cine mai are de trimis.
   *
   * `null` când nu există nicio lună în lucru — nu un termen inventat pentru luna
   * calendaristică de azi.
   */
  closing: DashboardClosing | null;
};

/** Un client de la care încă se așteaptă documente pentru luna în lucru. */
export type Laggard = {
  clientId: string;
  clientName: string;
  receivedCount: number;
  missingCount: number;
  /** Ce lipsește, în cuvintele tipurilor de document. Trunchiată la câteva. */
  missing: string[];
};

export type DashboardClosing = {
  referenceMonth: string;
  /** Ziua până la care trebuie depuse declarațiile lunii încheiate. */
  deadline: string;
  /** Poate fi negativ: termenul a trecut. Se spune, nu se ascunde. */
  daysLeft: number;
  clientsWaiting: number;
  laggards: Laggard[];
};

/* ─── Recepții (M12) ───────────────────────────────────────────────────────── */

/**
 * O recepție: un fișier care a intrat, cu de unde a venit.
 *
 * Ține locul cronologiei de mesaje pe care ecranul „Mesaje" o promitea și nu o
 * avea. Sistemul încă nu **trimite** nimic, dar ce a primit știe cu exactitate:
 * fiecare atașament de email, fiecare fișier din OneDrive și fiecare factură din
 * SPV lasă o urmă cu expeditorul și momentul.
 */
export type Intake = {
  id: string;
  source: DocumentSource;
  status: IntakeStatus;
  /** Adresa de email, dosarul din OneDrive, CUI-ul din SPV. */
  sender: string | null;
  subject: string | null;
  originalFilename: string;
  receivedAt: string;
  /** `null` pentru o recepție respinsă: nu a devenit document. */
  documentId: string | null;
  clientId: string | null;
  clientName: string | null;
  rejectionReason: string | null;
};

export const INTAKE_STATUS = ["RECEIVED", "ACCEPTED", "REJECTED", "DUPLICATE"] as const;
export type IntakeStatus = (typeof INTAKE_STATUS)[number];

/* ─── Audit (§31) ──────────────────────────────────────────────────────────── */

export type AuditLogEntry = {
  id: string;
  at: string;
  userName: string;
  action: string;
  entityType: string;
  entityId: string;
  detail: string | null;
  ip: string;
};

/* ─── Comunicare ───────────────────────────────────────────────────────────── */

/* ─── Rapoarte (§84) ───────────────────────────────────────────────────────── */

/**
 * O linie de clasament dintr-un raport.
 *
 * `key` și `label` sunt amândouă `null` exact când gruparea este „nimic": un
 * document fără client, fără tip sau fără lună de referință. Acelea nu sunt
 * sărite din raport — un document care nu are lună contabilă este chiar ce
 * trebuie să vadă cineva.
 *
 * Formularea absenței o alege interfața, nu serverul. La fel etichetele de
 * status, pe care `status-badge.tsx` le traduce de mult: dacă ar veni și din
 * backend, ar exista două surse pentru același text.
 */
export type ReportBucket = {
  key: string | null;
  label: string | null;
  count: number;
};

export type ReportSummary = {
  total: number;
  /** Câte au terminat drumul — indiferent dacă au ieșit bine. */
  processed: number;
  failed: number;
  duplicates: number;
  /**
   * `null` când nu s-a terminat încă nimic. Zero ar însemna „totul a eșuat",
   * ceea ce este altceva și s-ar citi greșit pe ecran.
   */
  successRate: number | null;
  byStatus: ReportBucket[];
  byMonth: ReportBucket[];
  byType: ReportBucket[];
  /** Doar primii; `clientCount` spune câți sunt de fapt. */
  byClient: ReportBucket[];
  clientCount: number;
};

/* ─── Integrare OneDrive / SharePoint (M9) ─────────────────────────────────── */

/**
 * Un dosar urmărit din OneDrive, legat de clientul căruia îi aparțin documentele.
 *
 * Maparea asta este piesa care scutește identificarea clientului: contabilul are
 * deja un dosar per client, iar un fișier apărut acolo aparține acelui client —
 * mai sigur decât orice citire de CUI, pentru că merge și pentru o poză neclară.
 */
export type DriveFolder = {
  id: string;
  driveId: string;
  itemId: string;
  path: string;
  clientId: string | null;
  clientName: string | null;
  lastSyncedAt: string | null;
  lastError: string | null;
  filesIngested: number;
  isActive: boolean;
};

/** Starea integrării, într-un singur răspuns. Tokenul nu apare niciodată (§73). */
export type DriveStatus = {
  /** Lipsesc MS_CLIENT_ID / MS_CLIENT_SECRET? Ecranul o spune, nu oferă un buton care cade. */
  configured: boolean;
  /** Lipsește DRIVE_TOKEN_KEY? Fără ea nu stocăm tokenul, deci nu conectăm. */
  encryptionReady: boolean;
  connected: boolean;
  accountEmail: string | null;
  accountName: string | null;
  connectedAt: string | null;
  lastSyncAt: string | null;
  lastError: string | null;
  folders: DriveFolder[];
  /** Dosarele de email urmărite. Listă separată: sunt lucruri diferite. */
  mailFolders: MailFolder[];
};

/**
 * Un dosar din cutia poștală, din ale cărui mesaje luăm atașamentele.
 *
 * Nu are `clientId`, spre deosebire de un dosar de drive, și asta este diferența
 * de fond: într-o cutie poștală intră toți clienții deodată, deci clientul îl dă
 * **expeditorul**, potrivit pe contactele din CRM.
 */
export type MailFolder = {
  id: string;
  folderId: string;
  displayName: string;
  lastSyncedAt: string | null;
  lastError: string | null;
  filesIngested: number;
  isActive: boolean;
};

/** Un dosar din cutia poștală, la răsfoire. */
export type MailBrowseItem = {
  folderId: string;
  displayName: string;
  totalItems: number;
  isTracked: boolean;
};

/** Un dosar de pe drive, la răsfoire. */
export type DriveBrowseItem = {
  driveId: string;
  itemId: string;
  name: string;
  path: string;
  isTracked: boolean;
};

export type DriveSyncResult = {
  ingested: number;
  failed: number;
  hasMore: boolean;
  folders: string[];
};

/* ─── e-Factura / SPV ANAF (M11) ──────────────────────────────────────────── */

/**
 * Împuternicirea unui client, plus starea preluării lui.
 *
 * Rândul **nu creează** dreptul: acela se depune în SPV, de către client
 * (formularul 150). Aici spunem doar pentru ce CUI să întrebăm. Când
 * împuternicirea lipsește la ANAF, refuzul apare în `lastError` — pe rândul
 * clientului, nu pe conexiune, pentru că îl privește doar pe el.
 */
export type AnafMandate = {
  id: string;
  clientId: string;
  clientName: string;
  /** Forma normalizată, cea pe care o cere API-ul ANAF: fără `RO`, doar cifre. */
  taxId: string;
  /** Până când am citit lista de mesaje. `null` = împuternicire nouă. */
  syncedThrough: string | null;
  lastSyncedAt: string | null;
  lastError: string | null;
  invoicesIngested: number;
  isActive: boolean;
};

/** Starea integrării, într-un singur răspuns. Tokenul nu apare niciodată (§73). */
export type AnafStatus = {
  /** Lipsesc ANAF_CLIENT_ID / ANAF_CLIENT_SECRET? Ecranul o spune. */
  configured: boolean;
  /** Lipsește DRIVE_TOKEN_KEY? Fără ea nu stocăm tokenul, deci nu conectăm. */
  encryptionReady: boolean;
  connected: boolean;
  /** `prod` sau `test`. Sunt baze separate la ANAF, nu niveluri de log. */
  environment: string;
  certificateHolder: string | null;
  connectedAt: string | null;
  /** Autorizarea ține un an, iar reînnoirea cere din nou certificatul. */
  expiresAt: string | null;
  lastSyncAt: string | null;
  lastError: string | null;
  mandates: AnafMandate[];
};

export type AnafSyncResult = {
  ingested: number;
  failed: number;
  hasMore: boolean;
  mandates: string[];
};

/* ─── Setări (§16, §73) ────────────────────────────────────────────────────── */

export const SETTING_GROUPS = [
  "PROCESSING",
  "STORAGE",
  "EXTRACTION",
  "PERIODS",
  "NOTIFICATIONS",
  "RETENTION",
  "SECURITY",
] as const;
export type SettingGroup = (typeof SETTING_GROUPS)[number];

/**
 * O valoare de configurare, așa cum rulează chiar acum procesul care a răspuns.
 *
 * `key` este numele variabilei de mediu, nu o etichetă: cine se uită la ecran
 * trebuie să știe ce anume să schimbe, nu doar ce este acum. Textul în română îl
 * pune interfața.
 *
 * Ce ajunge aici este o listă albă din backend, nu tot ce există în configurare:
 * `SECRET_KEY`, `DATABASE_URL`, cheile S3 și căile de pe disc nu ies niciodată
 * printr-un răspuns HTTP (§73).
 */
export type SettingEntry = {
  key: string;
  group: SettingGroup;
  value: string;
};
