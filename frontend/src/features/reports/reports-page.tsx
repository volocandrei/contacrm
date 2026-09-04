import { useState } from "react";
import {
  CircleCheck,
  Copy,
  Download,
  FileStack,
  LoaderCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { apiMode, fetchFile } from "@/api/client";
import { useClients, useReportSummary } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { Donut } from "@/components/charts";
import { MonthFilter, SelectFilter } from "@/components/form-controls";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { DocumentStatusBadge } from "@/components/status-badge";
import { useFilterParams } from "@/hooks/use-filter-params";
import { formatPercent, formatReferenceMonth } from "@/lib/format";
import { DOCUMENT_STATUS_LABEL } from "@/lib/labels";
import { STATUS_ARC } from "@/lib/status-colors";
import { iconChip, mutedText, surface, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { DocumentStatus, ReportBucket } from "@/types/domain";

/**
 * Rapoarte (§84).
 *
 * Agregarea se face în backend, cu SQL. Înainte, pagina cerea primele 200 de
 * documente și le număra aici — pe setul de development iese corect, pentru că
 * sunt mai puține de 200, dar la un cabinet real „rata de procesare reușită" ar
 * fi fost calculată pe o felie arbitrară și afișată ca și cum ar fi acoperit tot.
 *
 * Formularea absenței („fără client", „fără lună") se decide aici. Serverul
 * trimite `key: null` și `label: null`, pentru că el nu are de unde ști cum vrem
 * să numim lipsa — și pentru că altfel ar exista două surse pentru același text.
 */
export function ReportsPage() {
  const { values, setValue } = useFilterParams({ fromMonth: "", toMonth: "", clientId: "" });
  const { data: clientPage } = useClients({ pageSize: 200 });
  const { data, isLoading, error } = useReportSummary({
    fromMonth: values.fromMonth,
    toMonth: values.toMonth,
    clientId: values.clientId,
  });

  return (
    <div>
      <PageHeader
        title="Rapoarte"
        description="Agregări calculate în backend, peste toate documentele care trec de filtre."
        actions={<ExportButton filters={values} />}
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <MonthFilter
          label="Din luna"
          value={values.fromMonth}
          onChange={(value) => setValue("fromMonth", value)}
        />
        <MonthFilter
          label="Până în luna"
          value={values.toMonth}
          onChange={(value) => setValue("toMonth", value)}
        />
        <SelectFilter
          label="Client"
          allLabel="Toți clienții"
          value={values.clientId}
          onChange={(value) => setValue("clientId", value)}
          options={(clientPage?.items ?? []).map((client) => ({
            value: client.id,
            label: client.name,
          }))}
          className="w-64"
        />
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : !data ? null : (
        <>
          <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              Icon={FileStack}
              tone="blue"
              label="Documente"
              value={String(data.total)}
              delayClass="rise-delay-1"
            />
            <StatCard
              Icon={CircleCheck}
              tone="green"
              label="Rată de procesare reușită"
              value={data.successRate === null ? "—" : formatPercent(data.successRate)}
              hint={
                data.successRate === null
                  ? "Niciun document nu a terminat încă procesarea"
                  : `din ${data.processed} procesate`
              }
              delayClass="rise-delay-2"
            />
            <StatCard
              Icon={TriangleAlert}
              tone="red"
              label="Documente cu erori"
              value={String(data.failed)}
              delayClass="rise-delay-3"
            />
            <StatCard
              Icon={Copy}
              tone="amber"
              label="Duplicate detectate"
              value={String(data.duplicates)}
              delayClass="rise-delay-4"
            />
          </div>

          <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Panel title="Documente pe lună">
              <BarList
                items={data.byMonth}
                render={(bucket) =>
                  bucket.key === null ? "Fără lună de referință" : formatReferenceMonth(bucket.key)
                }
              />
            </Panel>
            <Panel title="Documente pe tip">
              <BarList
                items={data.byType}
                render={(bucket) => bucket.label ?? "Tip neidentificat"}
              />
            </Panel>
            <Panel
              title="Clienți după volum"
              // Lista este scurtă; numărul real nu se ascunde nicăieri.
              action={
                data.clientCount > data.byClient.length ? (
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    primii {data.byClient.length} din {data.clientCount}
                  </span>
                ) : undefined
              }
            >
              <BarList
                items={data.byClient}
                render={(bucket) => bucket.label ?? "Client neidentificat"}
              />
            </Panel>
          </div>

          <Panel title="Documente pe stare">
            {data.byStatus.length === 0 ? (
              <p className={cn("py-6 text-center text-sm", mutedText)}>Fără date</p>
            ) : (
              <div className="flex flex-wrap items-center gap-8">
                {/* Insignele spun câte sunt în fiecare stare; inelul spune ce
                    parte din întreg reprezintă fiecare — iar asta este întrebarea
                    pe care o pune cineva care deschide un raport. */}
                <Donut
                  className="h-36 w-36 shrink-0"
                  label="Distribuția documentelor pe stări"
                  centerValue={String(data.total)}
                  centerLabel="documente"
                  slices={data.byStatus.map((bucket) => ({
                    label: DOCUMENT_STATUS_LABEL[bucket.key as DocumentStatus],
                    value: bucket.count,
                    className: STATUS_ARC[bucket.key as DocumentStatus],
                  }))}
                />
                <ul className="flex flex-wrap gap-2">
                  {data.byStatus.map((bucket) => (
                    <li
                      key={bucket.key}
                      className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
                    >
                      <DocumentStatusBadge status={bucket.key as DocumentStatus} />
                      <span className="text-sm font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                        {bucket.count}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}

function StatCard({
  Icon,
  tone,
  label,
  value,
  hint,
  delayClass,
}: {
  Icon: LucideIcon;
  tone: Tone;
  label: string;
  value: string;
  hint?: string;
  delayClass?: string;
}) {
  return (
    <div className={cn("p-5", surface, "rise-in", delayClass)}>
      {/* Patru carduri cu aceeași iconiță albastră nu spuneau nimic: ochiul nu
          avea după ce să le deosebească, deci le citea pe toate. */}
      <div className={cn("mb-3 grid h-11 w-11 place-content-center rounded-2xl", iconChip[tone])}>
        <Icon className="h-5 w-5" aria-hidden="true" />
      </div>
      <p className={cn("text-sm", mutedText)}>{label}</p>
      <p className="text-3xl font-semibold tracking-tight tabular-nums text-slate-900 dark:text-slate-50">
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

function BarList({
  items,
  render,
}: {
  items: ReportBucket[];
  render: (bucket: ReportBucket) => string;
}) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <ul className="space-y-2.5">
      {items.map((item) => (
        <li key={item.key ?? "absent"}>
          <div className="mb-1 flex items-center justify-between gap-2 text-sm">
            <span className="truncate text-slate-600 dark:text-slate-400">{render(item)}</span>
            <span className="shrink-0 font-medium text-slate-900 dark:text-slate-100">
              {item.count}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            {/* Gradientul face vârful vizibil fără să fie citit: prima bară este
                cea mai lungă prin construcție, iar ochiul o găsește imediat. */}
            <div
              className="h-2 rounded-full bg-gradient-to-r from-blue-500 to-violet-500 transition-[width] duration-700 ease-out"
              style={{ width: `${(item.count / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
      {items.length === 0 && (
        <li className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">Fără date</li>
      )}
    </ul>
  );
}


/**
 * Descărcarea raportului ca fișier.
 *
 * Numerele se vedeau pe ecran și nu puteau ieși din aplicație: un cabinet care
 * trebuie să pună situația lunii într-un raport intern, sau s-o trimită cuiva,
 * le retasta.
 *
 * Nu este un `<a href>`: ruta cere autentificare, iar un token în URL este
 * interzis (§27). Se citește cu `fetch`, cu cookie-ul de sesiune la locul lui, și
 * se salvează dintr-un `blob:` — la fel ca descărcarea unui document.
 *
 * Fișierul se cere cu **aceleași filtre** ca ecranul: un export care ar acoperi
 * altceva decât ce se vede ar fi mai rău decât niciunul.
 */
function ExportButton({ filters }: { filters: Record<string, string> }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function download() {
    setProblem(null);
    if (apiMode() === "mock") {
      // Fișierul îl compune serverul, din aceleași numere ca ecranul. L-am putea
      // genera aici din ce e deja afișat, dar atunci ar exista două căi de calcul
      // pentru același raport — exact ce evită ruta.
      setProblem("În modul simulat nu există server care să compună fișierul.");
      return;
    }
    setBusy(true);
    try {
      const query = new URLSearchParams(
        Object.entries(filters).filter(([, value]) => value !== ""),
      ).toString();
      const file = await fetchFile(`/reports/summary.csv${query ? `?${query}` : ""}`);
      const url = URL.createObjectURL(file.blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = file.filename ?? "raport-documente.csv";
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        // Revocarea imediată ar putea prinde salvarea înainte să pornească.
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (caught) {
      setProblem(
        caught instanceof ApiError ? caught.message : "Raportul nu a putut fi descărcat.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={() => void download()}
        disabled={busy}
        className="flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
      >
        {busy ? (
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Download className="h-4 w-4" aria-hidden="true" />
        )}
        Descarcă CSV
      </button>
      {problem && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </div>
  );
}
