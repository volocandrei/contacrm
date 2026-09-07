/**
 * Onorariile cabinetului.
 *
 * **Ce lipsea.** Aplicația știa tot despre munca făcută pentru client și nimic
 * despre banii primiți pentru ea. Coloana aceea trăia într-un Excel separat, și
 * de aceea nu se potrivea niciodată cu lista de clienți: clientul nou intra în
 * aplicație și nu în Excel, cel plecat rămânea în Excel și nu în aplicație.
 *
 * **Ce răspunde ecranul**, în ordinea în care se pun întrebările la început de
 * lună: cât am de încasat, de la cine, și ce a rămas neîncasat din lunile
 * trecute. Restanțele vechi stau deasupra listei, ca la termene: sunt singurele
 * care nu se rezolvă așteptând.
 *
 * **Ce nu face.** Nu emite facturi și nu trimite nimic nimănui. O factură este
 * un document cu regim legal; un ecran care s-ar preface că emite una ar produce
 * hârtii fără valoare și o falsă liniște. Aici se ține ce ținea Excelul.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { CircleAlert, LoaderCircle, Play, Undo2, Wallet } from "lucide-react";
import { useFees, useGenerateFees, useMarkFeePaid, useUnmarkFeePaid } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ExportButton } from "@/components/export-button";
import { MonthFilter } from "@/components/form-controls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { useFilterParams } from "@/hooks/use-filter-params";
import { currentMonth } from "@/lib/current-month";
import { formatDate, formatMoney, formatReferenceMonth } from "@/lib/format";
import { buttonPrimary, buttonSecondary, divider, mutedText, scrollX } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { FeeArrear, FeeRow, FeeTotals } from "@/types/domain";

export function FeesPage() {
  const { values, setValue } = useFilterParams({ referenceMonth: currentMonth() });
  const canManage = usePermissionCheck()("fees:manage");
  const { data, isLoading, error } = useFees(values.referenceMonth);

  return (
    <div>
      <PageHeader
        title="Onorarii"
        description="Cât are cabinetul de încasat luna aceasta, de la cine, și ce a rămas din lunile trecute."
        actions={
          <>
            <ExportButton
              filters={{ referenceMonth: values.referenceMonth }}
              path="/fees/register.csv"
              fallbackName="onorarii.csv"
              label="Descarcă luna"
              title="Un rând pe client, cu onorariul, încasarea și numărul de documente. Se deschide în Excel."
            />
            {canManage && data && (
              <GenerateMonth referenceMonth={values.referenceMonth} rows={data.rows} />
            )}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <MonthFilter
          label="Lună"
          value={values.referenceMonth}
          onChange={(value) => setValue("referenceMonth", value)}
          className="w-48"
        />
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : !data || data.rows.length === 0 ? (
        <EmptyState
          title="Niciun client pe luna aceasta"
          description="Onorariile se stabilesc din fișa fiecărui client. Până atunci, luna nu are ce factura."
        />
      ) : (
        <div className="space-y-4">
          <Totals totals={data.totals} unpaidClients={data.unpaidClients} />

          {data.arrears.length > 0 && <Arrears arrears={data.arrears} />}

          <Panel
            title={`Luna ${formatReferenceMonth(data.referenceMonth)}`}
            bodyClassName="p-0"
            action={<span className={cn("text-xs", mutedText)}>{data.rows.length} clienți</span>}
          >
            <div className={scrollX}>
              <table className="w-full text-sm">
                <thead
                  className={cn(
                    "border-b text-left text-xs font-medium tracking-wide uppercase",
                    divider,
                    mutedText,
                  )}
                >
                  <tr>
                    <th scope="col" className="px-5 py-2.5">Client</th>
                    <th scope="col" className="px-5 py-2.5 text-right">Onorariu</th>
                    {/* Volumul stă lângă sumă, nu în alt ecran: întrebarea „cine
                        îmi dă cel mai mult de lucru pe cei mai puțini bani" se
                        pune uitându-te la amândouă deodată. */}
                    <th scope="col" className="px-5 py-2.5 text-right" title="Documente primite de la client în luna aceasta">
                      Documente
                    </th>
                    <th scope="col" className="px-5 py-2.5 text-right" title="Onorariul împărțit la numărul de documente. Nu este o măsură a efortului, dar este singura pe care o avem.">
                      lei/doc.
                    </th>
                    <th scope="col" className="px-5 py-2.5">Încasat</th>
                    <th scope="col" className="px-5 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {data.rows.map((row) => (
                    <Row
                      key={row.clientId}
                      row={row}
                      referenceMonth={data.referenceMonth}
                      canManage={canManage}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}

/**
 * Cifrele lunii, câte o linie pe monedă.
 *
 * Adunarea leilor cu euro ar da un număr care nu înseamnă nimic, dar pe care
 * cineva l-ar citi ca pe cifra lunii.
 */
function Totals({ totals, unpaidClients }: { totals: FeeTotals[]; unpaidClients: number }) {
  if (totals.length === 0) {
    return (
      <Panel>
        <p className={cn("text-sm", mutedText)}>
          Luna nu este generată. Până atunci nu există sume de încasat, doar clienți.
        </p>
      </Panel>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {totals.map((item) => (
        <Panel key={item.currency}>
          <p className={cn("text-xs font-medium tracking-wide uppercase", mutedText)}>
            De încasat{totals.length > 1 ? ` · ${item.currency}` : ""}
          </p>
          <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            {formatMoney(item.outstanding, item.currency)}
          </p>
          <p className={cn("mt-1 text-xs", mutedText)}>
            din {formatMoney(item.billed, item.currency)} facturați ·{" "}
            {formatMoney(item.collected, item.currency)} încasați
          </p>
        </Panel>
      ))}
      <Panel>
        <p className={cn("text-xs font-medium tracking-wide uppercase", mutedText)}>
          Clienți neîncasați
        </p>
        <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          {unpaidClients}
        </p>
        <p className={cn("mt-1 text-xs", mutedText)}>peste toate monedele</p>
      </Panel>
    </div>
  );
}

/**
 * Restanțele mai vechi decât luna de pe ecran.
 *
 * Sunt singurele care nu se mai văd nicăieri altundeva: luna trece, ecranul se
 * schimbă, iar banii rămân neîncasați fără să afle cineva.
 */
function Arrears({ arrears }: { arrears: FeeArrear[] }) {
  return (
    <Panel
      title="Neîncasate din lunile trecute"
      action={
        <span className="text-xs font-medium text-red-600 dark:text-red-400">
          {arrears.length} {arrears.length === 1 ? "lună" : "luni"}
        </span>
      }
      bodyClassName="p-0"
    >
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {arrears.map((item) => (
          <li
            key={`${item.clientId}|${item.period}`}
            className="flex items-center justify-between gap-3 px-5 py-2.5"
          >
            <span className="flex min-w-0 items-center gap-2">
              <CircleAlert className="h-4 w-4 shrink-0 text-red-500" aria-hidden="true" />
              <Link
                to={`/clienti/${item.clientId}`}
                className="truncate font-medium text-slate-900 hover:underline dark:text-slate-100"
              >
                {item.clientName}
              </Link>
              <span className={cn("shrink-0 text-xs", mutedText)}>
                {formatReferenceMonth(item.period)}
              </span>
            </span>
            <span className="shrink-0 font-medium text-slate-900 tabular-nums dark:text-slate-100">
              {formatMoney(item.amount, item.currency)}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Row({
  row,
  referenceMonth,
  canManage,
}: {
  row: FeeRow;
  referenceMonth: string;
  canManage: boolean;
}) {
  return (
    <tr className="align-middle">
      <td className="px-5 py-2.5">
        <Link
          to={`/clienti/${row.clientId}`}
          className="font-medium text-slate-900 hover:underline dark:text-slate-100"
        >
          {row.clientName}
        </Link>
      </td>
      <td className="px-5 py-2.5 text-right tabular-nums">
        {row.isGenerated && row.amount !== null ? (
          <span className="font-medium text-slate-900 dark:text-slate-100">
            {formatMoney(row.amount, row.currency)}
          </span>
        ) : row.configured !== null ? (
          /* Are onorariu, dar luna nu e generată: suma se vede estompat, ca să
             se citească drept „atât va fi", nu „atât s-a facturat". */
          <span className={mutedText}>{formatMoney(row.configured, row.currency)}</span>
        ) : (
          <span className={cn("text-xs", mutedText)}>fără onorariu</span>
        )}
      </td>
      <td className="px-5 py-2.5 text-right tabular-nums text-slate-700 dark:text-slate-300">
        {row.documents || <span className={mutedText}>—</span>}
      </td>
      <td className="px-5 py-2.5 text-right tabular-nums">
        <PerDocument row={row} />
      </td>
      <td className="px-5 py-2.5">
        {row.isPaid && row.paidOn !== null ? (
          <span className="text-sm text-slate-700 dark:text-slate-300">
            {formatDate(row.paidOn)}
            {row.paidByName && <span className={cn("ml-1", mutedText)}>· {row.paidByName}</span>}
          </span>
        ) : row.isGenerated ? (
          <span className="text-sm font-medium text-amber-600 dark:text-amber-400">neîncasat</span>
        ) : (
          <span className={cn("text-sm", mutedText)}>—</span>
        )}
      </td>
      <td className="px-5 py-2.5 text-right">
        {canManage && row.isGenerated && <PaymentButton row={row} referenceMonth={referenceMonth} />}
      </td>
    </tr>
  );
}

/**
 * Cât iese onorariul pe document.
 *
 * **Nu este o măsură a efortului** — o factură cu treizeci de poziții și un bon
 * de benzină se numără la fel — dar este singura pe care cabinetul o are, și pusă
 * lângă sumă răspunde la întrebarea care altfel se pune o dată pe an, din
 * memorie: pe cine am subevaluat.
 *
 * Fără documente nu se împarte nimic: un „∞" sau un zero ar fi două feluri de a
 * minți despre o lună în care clientul n-a trimis nimic.
 */
function PerDocument({ row }: { row: FeeRow }) {
  if (!row.isGenerated || row.amount === null || row.documents === 0) {
    return <span className={mutedText}>—</span>;
  }
  const value = Number(row.amount) / row.documents;
  return (
    <span
      className="text-slate-700 dark:text-slate-300"
      title={`${formatMoney(row.amount, row.currency)} pentru ${row.documents} documente`}
    >
      {formatMoney(value.toFixed(2), row.currency)}
    </span>
  );
}

function PaymentButton({ row, referenceMonth }: { row: FeeRow; referenceMonth: string }) {
  const mark = useMarkFeePaid();
  const unmark = useUnmarkFeePaid();
  const [problem, setProblem] = useState<string | null>(null);
  const pending = mark.isPending || unmark.isPending;

  function run(action: typeof mark | typeof unmark) {
    setProblem(null);
    action.mutate(
      { clientId: row.clientId, referenceMonth },
      {
        onError: (caught) =>
          setProblem(
            caught instanceof ApiError ? caught.message : "Încasarea nu a putut fi schimbată.",
          ),
      },
    );
  }

  return (
    <span className="flex items-center justify-end gap-2">
      {problem && (
        <span role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem}
        </span>
      )}
      <button
        type="button"
        disabled={pending}
        onClick={() => run(row.isPaid ? unmark : mark)}
        /* Numele clientului în eticheta accesibilă: pe un ecran cu treizeci de
           rânduri, „Am încasat" citit de un cititor de ecran nu spune de la cine. */
        aria-label={`${row.isPaid ? "Anulează încasarea" : "Am încasat"} · ${row.clientName}`}
        className={cn(row.isPaid ? buttonSecondary : buttonPrimary, "h-8 px-2.5 text-xs")}
      >
        {pending ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : row.isPaid ? (
          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <Wallet className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {row.isPaid ? "Anulează încasarea" : "Am încasat"}
      </button>
    </span>
  );
}

/**
 * Deschide luna.
 *
 * Butonul dispare când toți clienții cu onorariu au deja rând: o acțiune care nu
 * mai are ce face este o promisiune că se întâmplă ceva.
 */
function GenerateMonth({ referenceMonth, rows }: { referenceMonth: string; rows: FeeRow[] }) {
  const generate = useGenerateFees();
  const [problem, setProblem] = useState<string | null>(null);

  const pending = rows.filter((row) => !row.isGenerated && row.configured !== null);
  if (pending.length === 0) return null;

  return (
    <span className="flex items-center gap-2">
      {problem && (
        <span role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem}
        </span>
      )}
      <button
        type="button"
        disabled={generate.isPending}
        onClick={() => {
          setProblem(null);
          generate.mutate(referenceMonth, {
            onError: (caught) =>
              setProblem(
                caught instanceof ApiError ? caught.message : "Luna nu a putut fi generată.",
              ),
          });
        }}
        className={cn(buttonPrimary, "h-9 px-3 text-sm")}
      >
        {generate.isPending ? (
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Play className="h-4 w-4" aria-hidden="true" />
        )}
        Generează luna ({pending.length})
      </button>
    </span>
  );
}
