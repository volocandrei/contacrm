import { ApiError } from "@/api/types";

/**
 * Mesajul pe care îl vede utilizatorul când o acțiune eșuează.
 *
 * Detaliile de validare se adaugă la mesaj: „Documentul nu poate fi aprobat" fără
 * să spună de ce nu ajută pe nimeni.
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details ? Object.values(error.details).flat() : [];
    return details.length > 0 ? `${error.message} ${details.join(" ")}` : error.message;
  }
  return error instanceof Error ? error.message : "Eroare neașteptată.";
}
