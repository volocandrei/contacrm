/**
 * Culoarea fiecărei stări, pentru desene.
 *
 * Insigna are tonurile ei (fundal, text, inel); un arc de grafic are nevoie doar
 * de culoarea liniei. Harta stătea în `dashboard-page.tsx`, iar în momentul în
 * care ecranul de rapoarte desenează același inel trebuie să iasă de acolo:
 * două copii ar da două grafice care spun aceeași stare cu culori diferite.
 */
import type { DocumentStatus } from "@/types/domain";

export const STATUS_ARC: Record<DocumentStatus, string> = {
  ARCHIVED: "stroke-emerald-500",
  APPROVED: "stroke-emerald-400",
  REVIEW_REQUIRED: "stroke-amber-500",
  PROCESSING: "stroke-blue-500",
  RECEIVED: "stroke-blue-400",
  UNMATCHED: "stroke-violet-500",
  DUPLICATE: "stroke-slate-400",
  ERROR: "stroke-red-500",
  REJECTED: "stroke-red-400",
};

/** Aceeași culoare, ca fundal — pentru bulinele din legendă. */
export function statusDot(status: DocumentStatus): string {
  return STATUS_ARC[status].replace("stroke-", "bg-");
}
