/**
 * Generarea numelor de fișier și a căilor de arhivă (§10, §11, §74).
 *
 * Regula de bază: numele venit de la utilizator sau de la expeditor nu ajunge
 * NICIODATĂ nemodificat într-o cale de filesystem. Tot ce iese de aici este
 * compus din segmente sanitizate.
 *
 * Aceleași reguli trebuie implementate identic în backend (`FilenameGeneratorService`
 * și `StoragePathService`) — aici sunt pentru previzualizare și pentru testare.
 */

/**
 * Caractere interzise în nume de fișier pe Windows/POSIX, separatorii de cale și
 * caracterele de control. Cratima și underscore rămân permise — apar în serii reale.
 */
// Intenționat: caracterele de control nu au ce căuta într-un nume de fișier.
// eslint-disable-next-line no-control-regex
const ILLEGAL_CHARS = /[<>:"/\\|?*\x00-\x1F]/g;

/** Nume rezervate pe Windows — un fișier numit „CON.pdf" nu poate fi creat. */
const RESERVED_NAMES = new Set([
  "con", "prn", "aux", "nul",
  "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
  "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
]);

const MAX_SEGMENT_LENGTH = 60;
const MAX_FILENAME_LENGTH = 180;

const ALLOWED_EXTENSIONS = new Set(["pdf", "jpg", "jpeg", "png", "webp", "tif", "tiff"]);
const DEFAULT_EXTENSION = "pdf";

/**
 * Transformă un text arbitrar într-un segment sigur de nume de fișier:
 * fără diacritice, fără caractere ilegale, fără separatori de cale, lungime limitată.
 */
export function sanitizeSegment(value: string, maxLength = MAX_SEGMENT_LENGTH): string {
  const withoutDiacritics = value
    .normalize("NFD")
    // Elimină semnele diacritice combinate rămase după descompunere.
    .replace(/\p{Diacritic}/gu, "")
    // ș/ț cu virgulă și ligaturi care nu se descompun în toate fonturile.
    .replace(/[șş]/gi, "s")
    .replace(/[țţ]/gi, "t")
    .replace(/ß/g, "ss");

  const cleaned = withoutDiacritics
    .replace(ILLEGAL_CHARS, "")
    // Punctele repetate ar permite „..", deci și traversare de cale.
    .replace(/\.{2,}/g, ".")
    .replace(/\s+/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/_{2,}/g, "_")
    // Windows nu acceptă nume care se termină cu punct sau spațiu.
    .replace(/^[.\s]+|[.\s]+$/g, "");

  const truncated = cleaned.slice(0, maxLength);

  if (truncated === "" || RESERVED_NAMES.has(truncated.toLowerCase())) {
    return `_${truncated}`;
  }
  return truncated;
}

/** Extensia se ia din lista permisă, nu din ce a trimis expeditorul. */
export function normalizeExtension(filename: string, mimeType?: string): string {
  const fromMime: Record<string, string> = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/tiff": "tif",
  };
  if (mimeType && fromMime[mimeType]) return fromMime[mimeType];

  const candidate = filename.includes(".")
    ? (filename.split(".").pop() ?? "").toLowerCase().replace(/[^a-z0-9]/g, "")
    : "";
  return ALLOWED_EXTENSIONS.has(candidate) ? candidate : DEFAULT_EXTENSION;
}

export type FilenameInput = {
  /** ISO `YYYY-MM-DD`. Lipsa datei nu blochează arhivarea. */
  documentDate: string | null;
  documentTypeLabel: string | null;
  clientName: string | null;
  series: string | null;
  documentNumber: string | null;
  /** Numele original — folosit doar pentru a deduce extensia. */
  originalFilename: string;
  mimeType?: string;
  /** Sufix anti-coliziune, adăugat de apelant când numele există deja. */
  collisionSuffix?: number;
};

/**
 * Convenția (§10):
 *   `YYYY-MM-DD_[TipDocument]_[NumeClient]_[SerieNumar].ext`
 * iar când documentul nu are serie/număr, ultimul segment lipsește.
 */
export function buildDocumentFilename(input: FilenameInput): string {
  const date = isValidIsoDate(input.documentDate) ? input.documentDate! : "fara-data";

  const segments = [
    date,
    sanitizeSegment(input.documentTypeLabel ?? "Document"),
    sanitizeSegment(input.clientName ?? "ClientNeidentificat"),
  ];

  const serial = sanitizeSegment(
    [input.series ?? "", input.documentNumber ?? ""].join(""),
    30,
  );
  // `sanitizeSegment("")` întoarce "_", deci verificăm sursa, nu rezultatul.
  if ((input.series ?? "") + (input.documentNumber ?? "") !== "") {
    segments.push(serial);
  }

  if (input.collisionSuffix !== undefined && input.collisionSuffix > 0) {
    segments.push(String(input.collisionSuffix));
  }

  const extension = normalizeExtension(input.originalFilename, input.mimeType);
  const stem = segments.join("_").slice(0, MAX_FILENAME_LENGTH - extension.length - 1);
  return `${stem}.${extension}`;
}

/**
 * Structura de arhivare (§11): `/ARHIVA/{an}/{luna}/{client}/`.
 * Fiecare segment este sanitizat separat, deci „../" nu poate ieși din rădăcină.
 */
export function buildArchivePath(
  referenceMonth: string | null,
  clientName: string | null,
  root = "/ARHIVA",
): string {
  const [year, month] = (referenceMonth ?? "").split("-");
  const safeYear = /^\d{4}$/.test(year ?? "") ? year! : "fara-perioada";
  const safeMonth = /^(0[1-9]|1[0-2])$/.test(month ?? "") ? month! : "00";
  const safeClient = sanitizeSegment(clientName ?? "ClientNeidentificat");
  return `${root}/${safeYear}/${safeMonth}/${safeClient}/`;
}

function isValidIsoDate(value: string | null): boolean {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(value);
}
