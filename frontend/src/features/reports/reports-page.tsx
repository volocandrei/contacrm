import {
  CircleCheck,
  Copy,
  FileStack,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { useClients, useReportSummary } from "@/api/hooks";
import { Donut } from "@/components/charts";
import { MonthFilter, SelectFilter } from "@/components/form-controls";
import { ExportButton } from "@/components/export-button";
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
        actions={<ExportActions filters={values} />}
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
 * Cele două fișiere pe care le poate scoate ecranul, și de ce sunt două.
 *
 * **Registrul** are un rând pe document, cu data, seria, numărul, furnizorul,
 * CUI-ul și sumele citite din el. Este fișierul din care se lucrează mai departe
 * în programul de contabilitate — până acum numerele extrase se puteau doar citi
 * de pe ecran și retasta, câmp cu câmp. De aceea stă primul și este butonul
 * plin: raportul se consultă, registrul se folosește.
 *
 * **Raportul** are numerele de pe ecran, agregate. Se pune într-un raport intern
 * sau se trimite cuiva; nu conține niciun document.
 *
 * **Registrul declarațiilor** are un rând pe depunere: ce s-a depus, pentru
 * cine, pentru ce perioadă și de către cine. Este singurul loc din care se pot
 * vedea declarațiile fără termen de calendar — situațiile financiare interimare
 * nu apar niciodată pe ecranul de termene, fiindcă nu se nasc dintr-un calendar
 * (vezi `docs/DECLARATIONS.md`).
 *
 * **Arhiva** are documentele însele, aranjate pe client și lună, cu registrul la
 * rădăcină. Se cere când teancul întreg trebuie să plece undeva — un client care
 * pleacă, o predare de an, o cerere de la un control. Stă ultima fiindcă este
 * cea mai grea și cea mai rar cerută.
 */
function ExportActions({ filters }: { filters: Record<string, string> }) {
  return (
    <div className="flex flex-wrap items-start justify-end gap-2">
      <ExportButton
        filters={filters}
        path="/reports/register.csv"
        fallbackName="registru-documente.csv"
        label="Descarcă registrul"
        title="Un rând pe document, cu datele și sumele citite din el. Fără cele respinse și fără duplicate."
        primary
      />
      <ExportButton
        filters={filters}
        path="/reports/summary.csv"
        fallbackName="raport-documente.csv"
        label="Descarcă raportul"
        title="Numerele de pe ecran, agregate."
      />
      <ExportButton
        filters={filters}
        path="/reports/filings.csv"
        fallbackName="registru-declaratii.csv"
        label="Descarcă declarațiile"
        title="Un rând pe depunere: ce s-a depus, pentru cine, pentru ce perioadă și de către cine."
      />
      <ExportButton
        filters={filters}
        path="/reports/archive.zip"
        fallbackName="arhiva-documente.zip"
        label="Descarcă arhiva"
        title="Documentele intervalului, plus registrul, într-un singur fișier. Aranjate pe client și lună."
      />
    </div>
  );
}
