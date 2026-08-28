/**
 * Formatare pentru interfață (§71, §72).
 * UI: DD.MM.YYYY · API: ISO 8601 · fus orar implicit: Europe/Bucharest,
 * configurabil, nu presupus în logică.
 */

export const APP_LOCALE = "ro-RO";
export const APP_TIME_ZONE = "Europe/Bucharest";

const dateFormatter = new Intl.DateTimeFormat(APP_LOCALE, {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: APP_TIME_ZONE,
});

const dateTimeFormatter = new Intl.DateTimeFormat(APP_LOCALE, {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: APP_TIME_ZONE,
});

const timeFormatter = new Intl.DateTimeFormat(APP_LOCALE, {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: APP_TIME_ZONE,
});

const monthFormatter = new Intl.DateTimeFormat(APP_LOCALE, {
  month: "long",
  year: "numeric",
  timeZone: APP_TIME_ZONE,
});

/** Acceptă ISO 8601 din API. */
export function formatDate(iso: string): string {
  return dateFormatter.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return dateTimeFormatter.format(new Date(iso));
}

export function formatTime(iso: string): string {
  return timeFormatter.format(new Date(iso));
}

/** `reference_month` vine ca "YYYY-MM". */
export function formatReferenceMonth(referenceMonth: string): string {
  const [year, month] = referenceMonth.split("-");
  return monthFormatter.format(new Date(Number(year), Number(month) - 1, 1));
}

/**
 * Sumele circulă ca string prin API (Decimal în backend, §72) tocmai ca să nu treacă
 * printr-un float. Conversia la number se face doar aici, la afișare.
 */
export function formatMoney(amount: string | number, currency = "RON"): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  return new Intl.NumberFormat(APP_LOCALE, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number): string {
  return new Intl.NumberFormat(APP_LOCALE, {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(value);
}

/** Dimensiunea fișierului, pentru afișare în ecranul de verificare. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat(APP_LOCALE, { maximumFractionDigits: 1 }).format(value)} ${units[unitIndex]}`;
}
