/**
 * Teancul scanat, și unde s-ar tăia (§8, §29).
 *
 * **Când apare.** Numai când în fișier s-a găsit mai mult de un document. Un
 * panou care ar apărea pe fiecare PDF ca să spună „nu am ce tăia" ar fi zgomot pe
 * ecranul care contează cel mai mult din aplicație.
 *
 * **Ce arată înainte de apăsare.** Fiecare bucată: paginile, tipul citit,
 * numărul, și **de ce** s-a tăiat acolo. Fără motive, contabilul nu are cum să
 * verifice tăietura — iar o factură tăiată greșit produce două jumătăți care
 * arată ca documente adevărate și intră în decont.
 *
 * **De ce nu se taie singur.** Ar fi fost simplu: detectarea rulează oricum la
 * deschidere. Dar tăierea creează documente contabile, iar ele nu apar fără ca
 * cineva să fi apăsat. Aceeași regulă ca la aprobare și ca la reconciliere.
 */
import { useState } from "react";
import { Scissors } from "lucide-react";
import { useSplitDocument, useSplitPreview } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { buttonPrimary, mutedText, pillClass } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { DocumentDetail } from "@/types/domain";

export function SplitPanel({ document }: { document: DocumentDetail }) {
  const isPdf = document.mimeType === "application/pdf";
  const preview = useSplitPreview(document.id, isPdf);
  const split = useSplitDocument();
  const [done, setDone] = useState(false);

  const plan = preview.data;

  // Documentul este deja o bucată dintr-un teanc: nu se mai desface.
  if (!isPdf || !plan?.splittable) return null;

  const failure = split.error instanceof ApiError ? split.error.message : null;

  return (
    <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-900/20">
      <p className="flex items-center gap-1.5 text-sm font-medium text-amber-900 dark:text-amber-100">
        <Scissors className="size-4" aria-hidden />
        Fișierul pare să conțină {plan.segments.length} documente
        <span className={cn("font-normal", mutedText)}>({plan.pageCount} pagini)</span>
      </p>

      <ol className="mt-3 space-y-2">
        {plan.segments.map((segment) => (
          <li
            key={segment.pageFrom}
            className="rounded-md bg-white px-3 py-2 text-sm dark:bg-slate-900"
          >
            <span className="flex flex-wrap items-baseline gap-2">
              <span className={pillClass("slate")}>
                {segment.pageFrom === segment.pageTo
                  ? `pagina ${segment.pageFrom}`
                  : `paginile ${segment.pageFrom}–${segment.pageTo}`}
              </span>
              <span className="font-medium text-slate-900 dark:text-slate-100">
                {segment.documentType ?? "document"}
                {segment.documentNumber && ` nr. ${segment.documentNumber}`}
              </span>
            </span>
            {segment.reasons.length > 0 && (
              <ul className={cn("mt-1 space-y-0.5 text-xs", mutedText)}>
                {segment.reasons.map((reason) => (
                  <li key={reason}>· {reason}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      {failure && (
        <p role="alert" className="mt-3 text-xs text-rose-600 dark:text-rose-400">
          {failure}
        </p>
      )}
      {done && (
        <p role="status" className="mt-3 text-xs text-emerald-700 dark:text-emerald-400">
          Gata. Fișierul original rămâne, marcat „desfăcut", iar fiecare bucată a intrat ca
          document propriu și se citește acum.
        </p>
      )}

      <button
        type="button"
        className={cn(buttonPrimary, "mt-3")}
        disabled={split.isPending || done}
        onClick={() => {
          split.mutate(document.id, { onSuccess: () => setDone(true) });
        }}
      >
        <Scissors className="size-4" aria-hidden />
        {split.isPending ? "Se desface…" : `Desfă în ${plan.segments.length} documente`}
      </button>

      <p className={cn("mt-2 text-xs", mutedText)}>
        Originalul nu se șterge: rămâne proba din care ies celelalte, iar fiecare bucată
        arată înapoi spre el.
      </p>
    </div>
  );
}
