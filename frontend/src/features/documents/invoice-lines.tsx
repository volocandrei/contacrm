/**
 * Liniile facturii, pe ecranul de verificare (§9).
 *
 * **Ce a cerut cabinetul.** „TVA-ul pe fiecare produs sau serviciu, și
 * descrierea lui." Nu este o preferință de afișare: pe aceeași factură pot sta
 * 21% pentru un produs, 11% pentru altul și 0% pentru un serviciu scutit, iar
 * decontul le cere separat. Din totalul documentului defalcarea nu se poate
 * reconstitui, deci contabilul o retasta de pe hârtie.
 *
 * **De ce apare doar la unele documente.** Liniile se citesc numai din facturi
 * electronice, unde fiecare valoare stă într-un element cu nume. Din PDF nu se
 * citesc și nu se ghicesc: o linie inventată intră direct în decontul de TVA.
 * Un tabel gol cu „—" pe fiecare coloană ar sugera că documentul chiar nu are
 * linii; de aceea, când lista este goală, blocul lipsește cu totul.
 *
 * **Rezumatul pe cote stă sus, nu jos.** Este numărul pe care îl caută
 * contabilul — „cât la 21, cât la 11" — iar el nu are voie să depindă de cât de
 * lungă este factura. Într-o factură cu patruzeci de linii, un total pus la coadă
 * este un total pe care nimeni nu îl vede.
 */
import { Rows3 } from "lucide-react";
import { formatMoney } from "@/lib/format";
import { mutedText, pillClass } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { DocumentLine } from "@/types/domain";

/**
 * Categoriile UBL care explică un `0%`.
 *
 * Fără ele, o linie cu zero arată ca o eroare de citire. `AE` — taxare inversă —
 * este cazul obișnuit la achizițiile intracomunitare, iar acolo zero este corect
 * și **trebuie** să fie zero.
 */
const CATEGORY_LABEL: Record<string, string> = {
  S: "cotă standard",
  AE: "taxare inversă",
  E: "scutit",
  Z: "cotă zero",
  O: "în afara sferei",
  K: "livrare intracomunitară",
  G: "export scutit",
};

/** Suma pe cotă, în ordinea descrescătoare a cotei. */
function byRate(lines: DocumentLine[], currency: string) {
  const totals = new Map<string, number>();
  for (const line of lines) {
    if (line.vatRate === null || line.netAmount === null) continue;
    const amount = Number(line.netAmount);
    if (!Number.isFinite(amount)) continue;
    totals.set(line.vatRate, (totals.get(line.vatRate) ?? 0) + amount);
  }
  return [...totals.entries()]
    .sort((a, b) => Number(b[0]) - Number(a[0]))
    .map(([rate, amount]) => ({ rate, amount, currency }));
}

export function InvoiceLines({
  lines,
  currency,
}: {
  lines: DocumentLine[];
  currency: string | null;
}) {
  if (lines.length === 0) return null;

  const money = currency ?? "RON";
  const rates = byRate(lines, money);

  return (
    <div className="mb-4 rounded-lg border border-slate-200 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <p className="flex items-center gap-1.5 text-sm font-medium text-slate-900 dark:text-slate-100">
          <Rows3 className="h-4 w-4" aria-hidden="true" />
          Produse și servicii
          <span className={cn("font-normal", mutedText)}>({lines.length})</span>
        </p>

        {rates.length > 0 && (
          <ul className="flex flex-wrap items-center gap-2">
            {rates.map((entry) => (
              <li key={entry.rate} className={pillClass(entry.rate === "0" ? "slate" : "blue")}>
                {entry.rate}%: {formatMoney(String(entry.amount), entry.currency)}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">
            Liniile facturii: descriere, cantitate, preț unitar, valoare și cota de TVA
          </caption>
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">
                #
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Descriere
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Cantitate
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Preț unitar
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Valoare
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                TVA
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {lines.map((line) => (
              <tr key={line.position}>
                <td className={cn("px-4 py-2 whitespace-nowrap", mutedText)}>
                  {line.number ?? line.position}
                </td>
                <td className="px-4 py-2 text-slate-900 dark:text-slate-100">
                  {line.description ?? "—"}
                </td>
                <td className="px-4 py-2 text-right whitespace-nowrap text-slate-600 dark:text-slate-400">
                  {line.quantity ?? "—"}
                  {line.unitCode && (
                    <span className={cn("ml-1 text-xs", mutedText)}>{line.unitCode}</span>
                  )}
                </td>
                <td className="px-4 py-2 text-right whitespace-nowrap text-slate-600 dark:text-slate-400">
                  {line.unitPrice ? formatMoney(line.unitPrice, money) : "—"}
                </td>
                <td className="px-4 py-2 text-right whitespace-nowrap font-medium text-slate-900 dark:text-slate-100">
                  {line.netAmount ? formatMoney(line.netAmount, money) : "—"}
                </td>
                <td className="px-4 py-2 text-right whitespace-nowrap">
                  {line.vatRate === null ? (
                    <span className={mutedText}>—</span>
                  ) : (
                    <span
                      className="font-medium text-slate-900 dark:text-slate-100"
                      title={
                        line.vatCategory ? CATEGORY_LABEL[line.vatCategory] : undefined
                      }
                    >
                      {line.vatRate}%
                      {line.vatCategory && CATEGORY_LABEL[line.vatCategory] && (
                        <span className={cn("ml-1 text-xs font-normal", mutedText)}>
                          {CATEGORY_LABEL[line.vatCategory]}
                        </span>
                      )}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
