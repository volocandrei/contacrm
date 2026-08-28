/**
 * Set de date sintetice pentru development (§101).
 * Toate denumirile, CUI-urile, emailurile și numerele de telefon sunt inventate.
 * Generarea este deterministă (PRNG cu seed fix), ca interfața să arate identic
 * la fiecare reîncărcare și ca testele să fie reproductibile.
 */
import type {
  AccountingPeriod,
  AuditLogEntry,
  ChecklistItem,
  Client,
  ClientNote,
  CommunicationMessage,
  Contact,
  DocumentDetail,
  DocumentFields,
  DocumentSource,
  DocumentStatus,
  DocumentType,
  ExtractedField,
  Task,
  UserSummary,
} from "@/types/domain";
import { buildDocumentFilename } from "@/lib/filename";

/** Momentul de referință al setului de date. */
export const MOCK_NOW = "2026-08-27T15:00:00+03:00";

/* ─── PRNG determinist ─────────────────────────────────────────────────────── */

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rand = mulberry32(20260827);

function pick<T>(items: readonly T[]): T {
  const item = items[Math.floor(rand() * items.length)];
  // items este întotdeauna nevid în acest fișier; verificarea ține mulțumit `noUncheckedIndexedAccess`.
  return item ?? items[0]!;
}

function randInt(min: number, max: number): number {
  return min + Math.floor(rand() * (max - min + 1));
}

function chance(probability: number): boolean {
  return rand() < probability;
}

/* ─── Tipuri de document (§6) ──────────────────────────────────────────────── */

export const DOCUMENT_TYPES: DocumentType[] = [
  {
    code: "FACTURA_INTRARE",
    label: "Factură intrare",
    isActive: true,
    requiredFields: ["documentDate", "documentNumber", "supplierName", "totalAmount"],
  },
  {
    code: "FACTURA_IESIRE",
    label: "Factură ieșire",
    isActive: true,
    requiredFields: ["documentDate", "documentNumber", "customerName", "totalAmount"],
  },
  {
    code: "EXTRAS_CONT",
    label: "Extras cont",
    isActive: true,
    requiredFields: ["documentDate", "supplierName"],
  },
  {
    code: "BON_FISCAL",
    label: "Bon fiscal",
    isActive: true,
    requiredFields: ["documentDate", "totalAmount"],
  },
  {
    code: "CHITANTA",
    label: "Chitanță",
    isActive: true,
    requiredFields: ["documentDate", "totalAmount"],
  },
  { code: "CONTRACT", label: "Contract", isActive: true, requiredFields: ["documentDate"] },
  { code: "OP", label: "Ordin de plată", isActive: true, requiredFields: ["documentDate"] },
  { code: "NOTA_CONTABILA", label: "Notă contabilă", isActive: true, requiredFields: ["documentDate"] },
  {
    code: "DOCUMENT_BANCAR",
    label: "Document bancar",
    isActive: true,
    requiredFields: ["documentDate"],
  },
  { code: "ALTE_DOCUMENTE", label: "Alte documente", isActive: true, requiredFields: [] },
];

export const DOCUMENT_TYPE_LABEL = new Map(DOCUMENT_TYPES.map((t) => [t.code, t.label]));

/* ─── Utilizatori ──────────────────────────────────────────────────────────── */

export const USERS: UserSummary[] = [
  {
    id: "usr-1",
    fullName: "Ioana Marinescu",
    email: "admin@contacrm.test",
    role: "ADMIN",
    isActive: true,
    lastLoginAt: "2026-08-27T08:12:00+03:00",
  },
  {
    id: "usr-2",
    fullName: "Andrei Popa",
    email: "contabil@contacrm.test",
    role: "ACCOUNTANT",
    isActive: true,
    lastLoginAt: "2026-08-27T09:04:00+03:00",
  },
  {
    id: "usr-3",
    fullName: "Elena Dinu",
    email: "operator@contacrm.test",
    role: "OPERATOR",
    isActive: true,
    lastLoginAt: "2026-08-27T07:55:00+03:00",
  },
  {
    id: "usr-4",
    fullName: "Mihai Rusu",
    email: "verificator@contacrm.test",
    role: "REVIEWER",
    isActive: true,
    lastLoginAt: "2026-08-26T16:40:00+03:00",
  },
  {
    id: "usr-5",
    fullName: "Carmen Ilie",
    email: "vizitator@contacrm.test",
    role: "VIEWER",
    isActive: false,
    lastLoginAt: null,
  },
];

/* ─── Clienți ──────────────────────────────────────────────────────────────── */

const CLIENT_NAMES = [
  "ALFA CONTA SRL",
  "BETA SERVICE SRL",
  "GAMA DISTRIBUTIE SRL",
  "DELTA PROD SRL",
  "EPSILON TRANS SRL",
  "ZETA CONSULTING SRL",
  "ETA MEDICAL SRL",
  "THETA CONSTRUCT SRL",
  "IOTA AGRO SRL",
  "KAPPA RETAIL SRL",
  "LAMBDA SOFTWARE SRL",
  "OMEGA LOGISTIC SRL",
] as const;

const CITIES = ["București", "Cluj-Napoca", "Timișoara", "Iași", "Brașov", "Constanța"] as const;
const TAGS = ["TVA lunar", "TVA trimestrial", "microîntreprindere", "prioritar", "sezonier"] as const;

/** CUI sintetic — format valid ca formă, fără corespondent real. */
function syntheticTaxId(index: number): string {
  return `RO${(10000000 + index * 137).toString().slice(0, 8)}`;
}

export const CLIENTS: Client[] = CLIENT_NAMES.map((name, i) => {
  const accountant = i % 3 === 0 ? USERS[1]! : i % 3 === 1 ? USERS[0]! : USERS[3]!;
  const status = i === 9 ? "SUSPENDED" : i === 10 ? "PROSPECT" : i === 11 ? "INACTIVE" : "ACTIVE";
  return {
    id: `cl-${i + 1}`,
    name,
    taxId: syntheticTaxId(i + 1),
    registrationNumber: `J40/${1000 + i * 17}/2019`,
    address: `Str. Exemplu nr. ${randInt(1, 90)}, ${pick(CITIES)}`,
    status,
    assignedAccountantId: accountant.id,
    assignedAccountantName: accountant.fullName,
    tags: [pick(TAGS), ...(chance(0.3) ? [pick(TAGS)] : [])].filter(
      (tag, index, all) => all.indexOf(tag) === index,
    ),
    lastInteractionAt: `2026-08-${String(randInt(10, 27)).padStart(2, "0")}T${String(randInt(8, 18)).padStart(2, "0")}:${String(randInt(0, 59)).padStart(2, "0")}:00+03:00`,
    createdAt: `202${randInt(2, 5)}-0${randInt(1, 9)}-1${randInt(0, 9)}T10:00:00+03:00`,
  } satisfies Client;
});

const ACTIVE_CLIENTS = CLIENTS.filter((c) => c.status === "ACTIVE");

/* ─── Contacte ─────────────────────────────────────────────────────────────── */

const FIRST_NAMES = ["Ana", "Bogdan", "Cristina", "Dan", "Elena", "Florin", "Gabriela", "Horia"];
const LAST_NAMES = ["Ionescu", "Popescu", "Stan", "Vasile", "Moldovan", "Radu", "Toma", "Neagu"];
const CONTACT_ROLES = ["Administrator", "Contabil intern", "Asistent", "Director economic"];

export const CONTACTS: Contact[] = CLIENTS.flatMap((client, clientIndex) => {
  const count = randInt(1, 3);
  return Array.from({ length: count }, (_, i) => {
    const fullName = `${pick(FIRST_NAMES)} ${pick(LAST_NAMES)}`;
    const slug = fullName.toLowerCase().replace(/\s+/g, ".").replace(/[ăâîșț]/g, "a");
    return {
      id: `ct-${clientIndex + 1}-${i + 1}`,
      clientId: client.id,
      fullName,
      role: i === 0 ? "Administrator" : pick(CONTACT_ROLES),
      email: `${slug}@${client.name.split(" ")[0]?.toLowerCase()}.test`,
      phone: `+407${randInt(10000000, 99999999)}`,
      whatsappNumber: chance(0.6) ? `+407${randInt(10000000, 99999999)}` : null,
      isPrimary: i === 0,
      isActive: chance(0.9),
    } satisfies Contact;
  });
});

export const CLIENT_NOTES: ClientNote[] = ACTIVE_CLIENTS.slice(0, 6).map((client, i) => ({
  id: `note-${i + 1}`,
  clientId: client.id,
  authorName: pick(USERS).fullName,
  body: pick([
    "Clientul trimite de regulă documentele în ultima săptămână a lunii.",
    "Extrasul bancar vine separat, pe email, de la departamentul financiar.",
    "Bonurile sosesc fotografiate pe WhatsApp — calitate variabilă, necesită verificare.",
    "A cerut raport de cheltuieli lunar. De discutat la închiderea perioadei.",
  ]),
  createdAt: `2026-0${randInt(6, 8)}-${String(randInt(1, 28)).padStart(2, "0")}T11:20:00+03:00`,
}));

/* ─── Documente ────────────────────────────────────────────────────────────── */

const SUPPLIERS = [
  "FURNIZOR ALFA SRL",
  "UTILITATI EXEMPLU SA",
  "PAPETARIE DEMO SRL",
  "TRANSPORT MODEL SRL",
  "SOFTWARE TEST SRL",
  "SERVICE AUTO FICTIV SRL",
  "CATERING SINTETIC SRL",
] as const;

const BANKS = ["BANCA DEMO", "BANCA EXEMPLU", "BANCA TEST"] as const;

/**
 * Cotă TVA folosită DOAR pentru a genera cifre coerente în datele sintetice.
 * Sistemul real nu calculează niciodată TVA — îl extrage din document.
 * TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION.
 */
const MOCK_VAT_RATE = 0.19;

const MONTHS = ["2026-06", "2026-07", "2026-08"] as const;

function field<T>(value: T | null, source: ExtractedField<T>["source"], confidence: number | null) {
  return { value, source, confidence } satisfies ExtractedField<T>;
}

/** Sumele se calculează în bani (integer), niciodată în float (§72). */
function money(cents: number): string {
  return (cents / 100).toFixed(2);
}

function buildFields(
  typeCode: string,
  clientName: string | null,
  date: string,
  referenceMonth: string,
  baseConfidence: number,
): DocumentFields {
  const isBank = typeCode === "EXTRAS_CONT" || typeCode === "DOCUMENT_BANCAR";
  const isReceipt = typeCode === "BON_FISCAL" || typeCode === "CHITANTA";
  const isOutgoing = typeCode === "FACTURA_IESIRE";

  const subtotalCents = randInt(5_000, 1_500_000);
  const vatCents = Math.round(subtotalCents * MOCK_VAT_RATE);
  const totalCents = subtotalCents + vatCents;

  const jitter = () => Math.min(0.99, Math.max(0.35, baseConfidence + (rand() - 0.5) * 0.12));
  const supplier = isBank ? pick(BANKS) : pick(SUPPLIERS);

  return {
    documentType: field(typeCode, "AI", jitter()),
    documentDate: field(date, "AI", jitter()),
    series: isReceipt || isBank ? field(null, "EMPTY", null) : field(pick(["F", "AA", "BX"]), "AI", jitter()),
    documentNumber: isBank
      ? field(null, "EMPTY", null)
      : field(String(randInt(100, 9999)), "AI", jitter()),
    supplierName: isOutgoing
      ? field(clientName, "AI", jitter())
      : field(supplier, "AI", jitter()),
    supplierTaxId: isBank ? field(null, "EMPTY", null) : field(syntheticTaxId(randInt(20, 90)), "AI", jitter()),
    customerName: isOutgoing ? field(pick(SUPPLIERS), "AI", jitter()) : field(clientName, "AI", jitter()),
    customerTaxId: field(clientName ? syntheticTaxId(randInt(1, 12)) : null, clientName ? "AI" : "EMPTY", clientName ? jitter() : null),
    currency: field("RON", "AI", jitter()),
    subtotal: isBank ? field(null, "EMPTY", null) : field(money(subtotalCents), "AI", jitter()),
    vatAmount: isBank || isReceipt ? field(null, "EMPTY", null) : field(money(vatCents), "AI", jitter()),
    totalAmount: field(money(totalCents), "AI", jitter()),
    referenceMonth: field(referenceMonth, "AI", jitter()),
  };
}

function statusFor(monthIndex: number): DocumentStatus {
  // Lunile închise sunt aproape complet arhivate; luna curentă are amestec de stări.
  if (monthIndex < 2) return chance(0.95) ? "ARCHIVED" : "APPROVED";
  const roll = rand();
  if (roll < 0.42) return "ARCHIVED";
  if (roll < 0.58) return "APPROVED";
  if (roll < 0.76) return "REVIEW_REQUIRED";
  if (roll < 0.84) return "PROCESSING";
  if (roll < 0.89) return "DUPLICATE";
  if (roll < 0.94) return "ERROR";
  // UNMATCHED nu se generează aici: statusul înseamnă „expeditorul nu a putut fi
  // mapat la un client" și îl decide exclusiv apelantul, când clientul este null.
  return "RECEIVED";
}

function sourceFor(): DocumentSource {
  const roll = rand();
  if (roll < 0.45) return "EMAIL";
  if (roll < 0.8) return "WHATSAPP";
  if (roll < 0.97) return "UPLOAD";
  return "API";
}

function filenameFor(source: DocumentSource, typeCode: string): string {
  if (source === "WHATSAPP") return `IMG_${randInt(1000, 9999)}.jpg`;
  if (source === "UPLOAD") return `scan_${String(randInt(1, 99)).padStart(3, "0")}.pdf`;
  if (typeCode === "EXTRAS_CONT") return `extras_${randInt(1, 12)}.pdf`;
  return `factura-${randInt(1000, 9999)}.pdf`;
}

/** Convenția din §10: YYYY-MM-DD_[Tip]_[Client]_[SerieNumar].pdf */
const OCR_SNIPPETS = [
  "FACTURA FISCALA\nSeria {series} nr. {number}\nData: {date}\nFurnizor: {supplier}\nTotal de plata: {total} RON",
  "BON FISCAL\n{supplier}\nData {date}\nTOTAL {total} RON\nTVA inclus",
  "EXTRAS DE CONT\n{supplier}\nPerioada: {date}\nSold final: {total} RON",
];

let documentCounter = 0;

function buildDocument(
  client: Client | null,
  monthIndex: number,
  typeCode: string,
): DocumentDetail {
  documentCounter += 1;
  const referenceMonth = MONTHS[monthIndex]!;
  const [year, month] = referenceMonth.split("-").map(Number) as [number, number];
  const day = monthIndex === 2 ? randInt(1, 27) : randInt(1, 28);
  const date = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const receivedHour = randInt(7, 19);
  const receivedAt = `${date}T${String(receivedHour).padStart(2, "0")}:${String(randInt(0, 59)).padStart(2, "0")}:00+03:00`;

  const status = client === null ? "UNMATCHED" : statusFor(monthIndex);
  const source = sourceFor();
  const originalFilename = filenameFor(source, typeCode);
  const extension = originalFilename.split(".").pop() ?? "pdf";

  // Documentele fotografiate au sistematic încredere mai mică decât PDF-urile native.
  const baseConfidence =
    status === "ERROR" || status === "UNMATCHED"
      ? 0.4
      : source === "WHATSAPP"
        ? 0.74
        : status === "REVIEW_REQUIRED"
          ? 0.78
          : 0.94;

  const fields = buildFields(typeCode, client?.name ?? null, date, referenceMonth, baseConfidence);

  // Documentele în eroare nu au trecut de OCR — nu inventăm câmpuri pentru ele.
  if (status === "ERROR" || status === "PROCESSING" || status === "RECEIVED") {
    for (const key of Object.keys(fields) as (keyof DocumentFields)[]) {
      fields[key] = { value: null, source: "EMPTY", confidence: null } as never;
    }
  }

  const confidences = Object.values(fields)
    .map((f) => f.confidence)
    .filter((c): c is number => c !== null);
  const confidence =
    confidences.length === 0
      ? null
      : Math.round((confidences.reduce((a, b) => a + b, 0) / confidences.length) * 100) / 100;

  const typeLabel = DOCUMENT_TYPE_LABEL.get(typeCode) ?? null;
  const archived = status === "ARCHIVED";

  const validationIssues: string[] = [];
  if (status === "REVIEW_REQUIRED") {
    if (confidence !== null && confidence < 0.9) {
      validationIssues.push(`Încredere sub pragul automat (${Math.round(confidence * 100)}%)`);
    }
    if (source === "WHATSAPP") validationIssues.push("Document fotografiat — verificare recomandată");
  }
  if (status === "ERROR") validationIssues.push("OCR eșuat: imagine neclară sau fișier corupt");
  if (status === "UNMATCHED") validationIssues.push("Expeditorul nu este mapat la niciun client");
  if (status === "DUPLICATE") validationIssues.push("Hash identic cu un document deja arhivat");

  const ocrTemplate = pick(OCR_SNIPPETS);
  const textPreview =
    status === "ERROR" || status === "PROCESSING" || status === "RECEIVED"
      ? null
      : ocrTemplate
          .replace("{series}", fields.series.value ?? "-")
          .replace("{number}", fields.documentNumber.value ?? "-")
          .replace("{date}", date)
          .replace("{supplier}", fields.supplierName.value ?? "-")
          .replace("{total}", fields.totalAmount.value ?? "-");

  const history = [
    {
      id: `h-${documentCounter}-1`,
      at: receivedAt,
      actor: "Sistem",
      action: "DOCUMENT_RECEIVED",
      detail: `Recepționat prin ${source}`,
    },
  ];
  if (status !== "RECEIVED" && status !== "PROCESSING") {
    history.push({
      id: `h-${documentCounter}-2`,
      at: receivedAt,
      actor: "Sistem",
      action: status === "ERROR" ? "PROCESSING_FAILED" : "EXTRACTION_COMPLETED",
      detail:
        status === "ERROR"
          ? "OCR eșuat după 3 încercări"
          : `Extracție finalizată (confidence ${confidence !== null ? Math.round(confidence * 100) : 0}%)`,
    });
  }
  if (archived || status === "APPROVED") {
    history.push({
      id: `h-${documentCounter}-3`,
      at: receivedAt,
      actor: pick(USERS).fullName,
      action: "DOCUMENT_APPROVED",
      detail: "Aprobat automat peste pragul de încredere",
    });
  }

  return {
    id: `doc-${documentCounter}`,
    originalFilename,
    storedFilename: archived
      ? buildDocumentFilename({
          documentDate: date,
          documentTypeLabel: typeLabel,
          clientName: client?.name ?? null,
          series: fields.series.value,
          documentNumber: fields.documentNumber.value,
          originalFilename,
        })
      : null,
    clientId: client?.id ?? null,
    clientName: client?.name ?? null,
    documentTypeCode: fields.documentType.value,
    documentTypeLabel: fields.documentType.value ? typeLabel : null,
    source,
    receivedAt,
    documentDate: fields.documentDate.value,
    referenceMonth: fields.referenceMonth.value,
    supplierName: fields.supplierName.value,
    documentNumber: fields.documentNumber.value,
    totalAmount: fields.totalAmount.value,
    currency: fields.currency.value,
    status,
    confidence,
    isDuplicate: status === "DUPLICATE",
    reviewRequired: status === "REVIEW_REQUIRED",
    mimeType: extension === "jpg" ? "image/jpeg" : "application/pdf",
    fileSize: randInt(80_000, 4_500_000),
    sha256: Array.from({ length: 64 }, () => "0123456789abcdef"[randInt(0, 15)]).join(""),
    storagePath: archived
      ? `/ARHIVA/${year}/${String(month).padStart(2, "0")}/${(client?.name ?? "NEIDENTIFICAT").replace(/\s+/g, "")}/`
      : null,
    duplicateOfId: null,
    fields,
    ocr: {
      provider: "mock",
      confidence: confidence,
      textPreview,
    },
    extraction: {
      provider: "mock",
      model: "mock-extractor",
      promptVersion: "v1",
      durationMs: randInt(400, 5200),
    },
    validationIssues,
    history,
  };
}

const TYPE_WEIGHTS: string[] = [
  ...Array(10).fill("FACTURA_INTRARE"),
  ...Array(5).fill("BON_FISCAL"),
  ...Array(4).fill("FACTURA_IESIRE"),
  ...Array(2).fill("CHITANTA"),
  "EXTRAS_CONT",
  "CONTRACT",
  "OP",
  "ALTE_DOCUMENTE",
];

export const DOCUMENTS: DocumentDetail[] = [];

for (const client of ACTIVE_CLIENTS) {
  MONTHS.forEach((_, monthIndex) => {
    const count = monthIndex === 2 ? randInt(4, 12) : randInt(6, 14);
    for (let i = 0; i < count; i += 1) {
      DOCUMENTS.push(buildDocument(client, monthIndex, pick(TYPE_WEIGHTS)));
    }
    // Fiecare lună are cel puțin un extras de cont.
    DOCUMENTS.push(buildDocument(client, monthIndex, "EXTRAS_CONT"));
  });
}

// Documente sosite fără client identificabil (§14).
for (let i = 0; i < 5; i += 1) {
  DOCUMENTS.push(buildDocument(null, 2, pick(TYPE_WEIGHTS)));
}

// Marcăm duplicatele către un document arhivat al aceluiași client.
for (const doc of DOCUMENTS) {
  if (!doc.isDuplicate) continue;
  const original = DOCUMENTS.find(
    (d) => d.id !== doc.id && d.clientId === doc.clientId && d.status === "ARCHIVED",
  );
  doc.duplicateOfId = original?.id ?? null;
}

DOCUMENTS.sort((a, b) => b.receivedAt.localeCompare(a.receivedAt));

/* ─── Perioade contabile ───────────────────────────────────────────────────── */

const CHECKLIST_TEMPLATE: Array<{ code: string; min: number }> = [
  { code: "FACTURA_INTRARE", min: 5 },
  { code: "FACTURA_IESIRE", min: 2 },
  { code: "EXTRAS_CONT", min: 1 },
  { code: "BON_FISCAL", min: 3 },
];

/**
 * Statusul unei perioade contabile.
 *
 * O perioadă este completă doar când **fiecare** document așteptat a sosit — nu
 * când s-a atins un total. Un total poate fi atins cu documente de alt tip, iar
 * „Documente complete" este semnalul după care se închide luna: dacă minte, se
 * închide o lună cu documente obligatorii lipsă.
 *
 * Pragul de 60% care separă PARTIAL de COLLECTING este doar ergonomie de interfață.
 * TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION: cine confirmă că „completă"
 * înseamnă exact „toate tipurile din checklist au atins minimul"?
 */
/**
 * Progresul unei perioade: cât din ce se aștepta a sosit efectiv.
 * Fiecare item contribuie cel mult cu minimul cerut, deci surplusul de un tip nu
 * maschează lipsa altuia.
 */
export function periodProgress(checklist: ChecklistItem[]): {
  satisfied: number;
  expected: number;
} {
  let satisfied = 0;
  let expected = 0;
  for (const item of checklist) {
    satisfied += Math.min(item.receivedCount, item.expectedMinCount);
    expected += item.expectedMinCount;
  }
  return { satisfied, expected };
}

export function derivePeriodStatus(
  checklist: ChecklistItem[],
  receivedCount: number,
  isClosedMonth: boolean,
): AccountingPeriod["status"] {
  if (isClosedMonth) return "FINALIZED";
  if (receivedCount === 0) return "NOT_STARTED";
  if (checklist.length === 0) return "COLLECTING";
  if (checklist.every((item) => item.isSatisfied)) return "COMPLETE";
  const { satisfied, expected } = periodProgress(checklist);
  return expected > 0 && satisfied / expected >= 0.6 ? "PARTIAL" : "COLLECTING";
}

export const PERIODS: AccountingPeriod[] = CLIENTS.flatMap((client) =>
  MONTHS.map((referenceMonth, monthIndex) => {
    const [year, month] = referenceMonth.split("-").map(Number) as [number, number];
    const clientDocs = DOCUMENTS.filter(
      (d) => d.clientId === client.id && d.referenceMonth === referenceMonth,
    );
    const checklist: ChecklistItem[] = CHECKLIST_TEMPLATE.map((item) => {
      const receivedCount = clientDocs.filter((d) => d.documentTypeCode === item.code).length;
      return {
        documentType: item.code,
        documentTypeLabel: DOCUMENT_TYPE_LABEL.get(item.code) ?? item.code,
        expectedMinCount: item.min,
        receivedCount,
        isSatisfied: receivedCount >= item.min,
      };
    });
    const { satisfied: satisfiedCount, expected: expectedCount } = periodProgress(checklist);
    const receivedCount = clientDocs.length;
    return {
      id: `per-${client.id}-${referenceMonth}`,
      clientId: client.id,
      clientName: client.name,
      year,
      month,
      referenceMonth,
      status: derivePeriodStatus(checklist, receivedCount, monthIndex < 2),
      receivedCount,
      satisfiedCount,
      expectedCount,
      checklist,
      openedAt: `${referenceMonth}-01T00:00:00+03:00`,
      closedAt: monthIndex < 2 ? `${referenceMonth}-28T18:00:00+03:00` : null,
      completedAt: monthIndex < 2 ? `${referenceMonth}-28T18:00:00+03:00` : null,
    } satisfies AccountingPeriod;
  }),
);

/* ─── Sarcini ──────────────────────────────────────────────────────────────── */

export const TASKS: Task[] = Array.from({ length: 14 }, (_, i) => {
  const client = chance(0.8) ? pick(ACTIVE_CLIENTS) : null;
  const assignee = pick(USERS);
  const status = pick(["TODO", "TODO", "IN_PROGRESS", "BLOCKED", "DONE"] as const);
  return {
    id: `task-${i + 1}`,
    title: pick([
      "Solicită extrasul bancar lipsă",
      "Verifică documentele cu încredere scăzută",
      "Confirmă perioada contabilă",
      "Actualizează datele de contact",
      "Clarifică factura fără serie",
      "Închide perioada iulie",
    ]),
    description: "Sarcină generată în setul de date sintetice pentru development.",
    clientId: client?.id ?? null,
    clientName: client?.name ?? null,
    assignedToId: assignee.id,
    assignedToName: assignee.fullName,
    priority: pick(["LOW", "NORMAL", "NORMAL", "HIGH", "URGENT"] as const),
    status,
    dueDate: `2026-0${randInt(8, 9)}-${String(randInt(1, 28)).padStart(2, "0")}`,
    createdAt: `2026-08-${String(randInt(1, 26)).padStart(2, "0")}T10:00:00+03:00`,
    completedAt: status === "DONE" ? "2026-08-26T14:00:00+03:00" : null,
  } satisfies Task;
});

/* ─── Audit (§31) ──────────────────────────────────────────────────────────── */

const AUDIT_ACTIONS = [
  "DOCUMENT_APPROVED",
  "DOCUMENT_RENAMED",
  "DOCUMENT_REASSIGNED",
  "CLIENT_UPDATED",
  "PERMISSION_CHANGED",
  "DOCUMENT_DELETED",
  "EMAIL_SENT",
  "WHATSAPP_SENT",
  "USER_LOGIN",
] as const;

export const AUDIT_LOGS: AuditLogEntry[] = Array.from({ length: 60 }, (_, i) => {
  const action = pick(AUDIT_ACTIONS);
  const isDocument = action.startsWith("DOCUMENT");
  const doc = pick(DOCUMENTS);
  const client = pick(CLIENTS);
  return {
    id: `audit-${i + 1}`,
    at: `2026-08-${String(randInt(20, 27)).padStart(2, "0")}T${String(randInt(7, 19)).padStart(2, "0")}:${String(randInt(0, 59)).padStart(2, "0")}:00+03:00`,
    userName: pick(USERS).fullName,
    action,
    entityType: isDocument ? "Document" : action === "CLIENT_UPDATED" ? "Client" : "User",
    entityId: isDocument ? doc.id : action === "CLIENT_UPDATED" ? client.id : pick(USERS).id,
    detail: isDocument ? doc.originalFilename : action === "CLIENT_UPDATED" ? client.name : null,
    ip: `10.0.${randInt(0, 4)}.${randInt(2, 240)}`,
  } satisfies AuditLogEntry;
}).sort((a, b) => b.at.localeCompare(a.at));

/* ─── Comunicare ───────────────────────────────────────────────────────────── */

export const MESSAGES: CommunicationMessage[] = Array.from({ length: 30 }, (_, i) => {
  const client = pick(ACTIVE_CLIENTS);
  const direction = chance(0.6) ? "INBOUND" : "OUTBOUND";
  const channel = pick(["EMAIL", "WHATSAPP", "EMAIL"] as const);
  return {
    id: `msg-${i + 1}`,
    clientId: client.id,
    clientName: client.name,
    direction,
    channel,
    subject: channel === "EMAIL" ? pick(["Documente august", "Facturi", "Extras cont", "Bonuri"]) : null,
    preview:
      direction === "INBOUND"
        ? "Bună ziua, vă transmit documentele pentru luna în curs."
        : "Am recepționat documentele. Vă anunțăm dacă lipsește ceva.",
    occurredAt: `2026-08-${String(randInt(18, 27)).padStart(2, "0")}T${String(randInt(8, 18)).padStart(2, "0")}:${String(randInt(0, 59)).padStart(2, "0")}:00+03:00`,
    attachmentCount: direction === "INBOUND" ? randInt(0, 6) : 0,
  } satisfies CommunicationMessage;
}).sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));
