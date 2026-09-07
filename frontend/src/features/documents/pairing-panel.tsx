/**
 * Celălalt exemplar al aceleiași facturi (§16, §17).
 *
 * **Ce rezolvă.** Aceeași factură ajunge de două ori și pe două drumuri: XML-ul
 * din SPV și PDF-ul de pe email. Sunt același document, dar niciunul nu se
 * aruncă — XML-ul are valorile exacte, PDF-ul are facsimilul. Fără legătură,
 * contabilul le potrivea cu ochiul, la fiecare factură.
 *
 * **Ce arată panoul, în ordinea în care contează.**
 *
 * 1. **Conflictul**, dacă există: aceeași factură, sume diferite. Una dintre
 *    valori este citită greșit, iar asta este cel mai important lucru de pe
 *    ecran — deci stă sus, în roșu, nu ascuns sub o potrivire „reușită".
 * 2. **Legătura existentă**, cu motivele ei și cu de cine a fost făcută.
 * 3. **Candidații**, când decizia a rămas a omului.
 *
 * Când nu există nicio pereche, panoul lipsește cu totul: majoritatea
 * documentelor nu au una, iar un rând „fără pereche" pe fiecare factură ar fi
 * zgomot pe ecranul cel mai încărcat din aplicație.
 */
import { FileText, Link2, Link2Off, TriangleAlert } from "lucide-react";
import { usePairDocument, useDocumentPairing, useUnpairDocument } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { formatMoney } from "@/lib/format";
import { buttonPrimary, mutedText, pillClass } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { DocumentDetail } from "@/types/domain";

export function PairingPanel({ document }: { document: DocumentDetail }) {
  const pairing = useDocumentPairing(document.id);
  const pair = usePairDocument();
  const unpair = useUnpairDocument();

  const data = pairing.data;
  if (!data) return null;

  const nothing = data.state === "MISSING" && !data.pairedWithId;
  if (nothing) return null;

  const conflict = data.state === "CONFLICT";
  const failure =
    pair.error instanceof ApiError
      ? pair.error.message
      : unpair.error instanceof ApiError
        ? unpair.error.message
        : null;

  return (
    <div
      className={cn(
        "mb-4 rounded-lg border p-4",
        conflict
          ? "border-rose-300 bg-rose-50 dark:border-rose-800 dark:bg-rose-900/20"
          : "border-slate-200 dark:border-slate-800",
      )}
    >
      <p className="flex items-center gap-1.5 text-sm font-medium text-slate-900 dark:text-slate-100">
        {conflict ? (
          <TriangleAlert className="size-4 text-rose-600" aria-hidden />
        ) : (
          <Link2 className="size-4" aria-hidden />
        )}
        {conflict
          ? "Același număr de factură, sume diferite"
          : data.pairedWithId
            ? "Legat cu celălalt exemplar"
            : "Ar putea fi același document"}
      </p>

      {conflict && (
        <p className="mt-1 text-xs text-rose-700 dark:text-rose-300">
          Una dintre cele două valori este citită greșit. Deschide-le pe amândouă și
          corectează-o pe cea greșită; până atunci nu se leagă nimic.
        </p>
      )}

      {data.pairedWithId && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-white px-3 py-2 text-sm dark:bg-slate-900">
          <span className="flex min-w-0 items-center gap-1.5">
            <FileText className="size-4 shrink-0 text-slate-400" aria-hidden />
            <span className="truncate text-slate-900 dark:text-slate-100">
              {data.pairedWithFilename ?? "celălalt exemplar"}
            </span>
            <span className={pillClass(data.pairedAutomatically ? "blue" : "slate")}>
              {data.pairedAutomatically ? "legat automat" : "legat manual"}
            </span>
          </span>
          <button
            type="button"
            className="text-xs text-slate-500 hover:text-rose-600"
            onClick={() => unpair.mutate(document.id)}
          >
            <Link2Off className="mr-1 inline size-3.5" aria-hidden />
            Rupe legătura
          </button>
        </div>
      )}

      {data.pairingReasons && (
        <p className={cn("mt-1 text-xs", mutedText)}>{data.pairingReasons}</p>
      )}

      {!data.pairedWithId && data.candidates.length > 0 && (
        <ul className="mt-3 space-y-2">
          {data.candidates.map((candidate) => (
            <li
              key={candidate.documentId}
              className="rounded-md bg-white px-3 py-2 text-sm dark:bg-slate-900"
            >
              <span className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="min-w-0 truncate text-slate-900 dark:text-slate-100">
                  {candidate.originalFilename}
                  {candidate.documentNumber && (
                    <span className={cn("ml-1", mutedText)}>nr. {candidate.documentNumber}</span>
                  )}
                </span>
                {candidate.total && (
                  <span className="whitespace-nowrap text-slate-600 dark:text-slate-400">
                    {formatMoney(candidate.total, "RON")}
                  </span>
                )}
              </span>
              <ul className={cn("mt-1 space-y-0.5 text-xs", mutedText)}>
                {candidate.reasons.map((reason) => (
                  <li key={reason}>· {reason}</li>
                ))}
              </ul>
              {candidate.state !== "CONFLICT" && (
                <button
                  type="button"
                  className={cn(buttonPrimary, "mt-2")}
                  disabled={pair.isPending}
                  onClick={() =>
                    pair.mutate({
                      documentId: document.id,
                      otherId: candidate.documentId,
                    })
                  }
                >
                  <Link2 className="size-4" aria-hidden />
                  Este același document
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {failure && (
        <p role="alert" className="mt-3 text-xs text-rose-600 dark:text-rose-400">
          {failure}
        </p>
      )}
    </div>
  );
}
