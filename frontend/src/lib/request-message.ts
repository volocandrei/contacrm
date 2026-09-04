/**
 * Solicitarea de documente, ca text gata de trimis.
 *
 * **De ce există.** Aplicația știe exact ce lipsește fiecărui client și până
 * când — ecranul „Documente lipsă" o arată. Ce nu poate face este să **trimită**:
 * asta cere un provider de email sau WhatsApp și rămâne în Faza 2. Între „știm"
 * și „clientul află" stătea, până acum, un om care recitea tabelul și rescria de
 * mână aceeași listă de treizeci de ori pe lună — cu greșeli, pentru că o listă
 * copiată cu ochiul se copiază greșit.
 *
 * Textul se construiește din aceleași date pe care le arată ecranul și se pune
 * în clipboard. Trimiterea rămâne a contabilului, din clientul lui de email, cu
 * semnătura lui — ceea ce, până la Faza 2, este și mai onest: niciun mesaj nu
 * pleacă în numele cabinetului fără ca cineva să îl fi citit.
 *
 * Șablonul este cel din „Comunicare → Șabloane", cu locurile completate.
 */
import type { ChecklistItem } from "@/types/domain";
import { formatDate, formatReferenceMonth } from "@/lib/format";

export type RequestMessageInput = {
  clientName: string;
  referenceMonth: string;
  /** Termenul de depunere, „YYYY-MM-DD". */
  deadline: string;
  missing: ChecklistItem[];
  /** Numele cabinetului, pentru semnătură. */
  organizationName: string;
};

/**
 * Câte bucăți mai lipsesc dintr-un tip, nu doar că lipsește.
 *
 * „Facturi de achiziție" nu spune nimic unui client care crede că le-a trimis;
 * „mai așteptăm 2 (am primit 3 din 5)" spune exact ce are de căutat.
 */
function line(item: ChecklistItem): string {
  const left = item.expectedMinCount - item.receivedCount;
  const detail =
    item.receivedCount > 0
      ? ` — mai așteptăm ${left} (am primit ${item.receivedCount} din ${item.expectedMinCount})`
      : ` — ${item.expectedMinCount} ${item.expectedMinCount === 1 ? "bucată" : "bucăți"}`;
  return `• ${item.documentTypeLabel}${detail}`;
}

export function buildRequestMessage(input: RequestMessageInput): string {
  const month = formatReferenceMonth(input.referenceMonth);
  return [
    "Bună ziua,",
    "",
    `Pentru evidența contabilă a lunii ${month} mai avem nevoie de următoarele documente:`,
    "",
    ...input.missing.map(line),
    "",
    `Vă rugăm să ni le transmiteți până la ${formatDate(input.deadline)}, ca declarațiile să poată fi depuse la timp.`,
    "",
    "Vă mulțumim,",
    input.organizationName,
  ].join("\n");
}
