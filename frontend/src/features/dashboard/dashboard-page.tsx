import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Building2,
  CalendarClock,
  TrendingDown,
  TrendingUp,
  CircleAlert,
  CircleCheck,
  Clock,
  Copy,
  FileStack,
  Inbox,
  ShieldCheck,
  TriangleAlert,
  UserX,
  type LucideIcon,
} from "lucide-react";
import { useDashboard } from "@/api/hooks";
import { Donut, TrendArea } from "@/components/charts";
import { ErrorState, LoadingState, Panel } from "@/components/page";
import { ConfidenceBadge, DocumentStatusBadge, PeriodStatusBadge } from "@/components/status-badge";
import { DOCUMENT_STATUS_LABEL } from "@/lib/labels";
import { STATUS_ARC, statusDot } from "@/lib/status-colors";
import { formatDate, formatReferenceMonth, formatTime } from "@/lib/format";
import {
  focusRing,
  iconChip,
  mutedText,
  surface,
  surfaceInteractive,
  type Tone,
} from "@/lib/ui";
import { cn } from "@/lib/utils";
import type {
  AttentionReason,
  DashboardClosing,
  DashboardData,
  DocumentSource,
} from "@/types/domain";

/** Sub atâtea zile rămase, termenul nu mai poate fi lăsat pe săptămâna viitoare. */
const URGENT_DAYS = 7;

/** Câte stări încap în legenda inelului. Restul rămân doar în desen. */
const MAX_STATUS_ROWS = 5;

const SOURCE_LABEL: Record<DocumentSource, string> = {
  EMAIL: "Email",
  WHATSAPP: "WhatsApp",
  UPLOAD: "Încărcare",
  API: "API",
  ONEDRIVE: "OneDrive",
  EFACTURA: "e-Factura",
};

const ATTENTION_TONE: Record<AttentionReason, "danger" | "warning"> = {
  UNMATCHED_CLIENT: "danger",
  OCR_FAILED: "danger",
  LOW_CONFIDENCE: "warning",
  POSSIBLE_DUPLICATE: "warning",
  MISSING_DATE: "warning",
  STUCK_IN_PROCESSING: "danger",
  INCOMPLETE_PERIOD: "warning",
};

export function DashboardPage() {
  const { data, isLoading, error } = useDashboard();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  const { kpis } = data;
  // Luna o spune serverul, care o derivă din date. Aici scria „2026-08", sub
  // niște cifre care puteau fi din altă lună.
  const month = data.referenceMonth ? formatReferenceMonth(data.referenceMonth) : null;

  return (
    <div className="space-y-6">
      <HeroHeader month={month} kpis={kpis} trend={data.trend} />

      {/* KPI (§20) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          Icon={Building2}
          tone="blue"
          label="Clienți activi"
          value={kpis.clientsActive}
          hint={`din ${kpis.clientsTotal} clienți în total`}
          to="/crm/clienti?status=ACTIVE"
          delayClass="rise-delay-1"
        />
        <KpiCard
          Icon={Inbox}
          tone="purple"
          label="Documente primite azi"
          value={kpis.documentsToday}
          hint={`${kpis.documentsProcessing} în procesare`}
          to="/documente/inbox"
          delayClass="rise-delay-2"
        />
        <KpiCard
          Icon={ShieldCheck}
          tone="amber"
          label="Necesită verificare"
          value={kpis.documentsNeedReview}
          hint="sub pragul de încredere configurat"
          to="/documente/verificare"
          delayClass="rise-delay-3"
        />
        <KpiCard
          Icon={TriangleAlert}
          tone="red"
          label="Documente cu erori"
          value={kpis.documentsError}
          hint={`${kpis.documentsDuplicate} posibile duplicate`}
          to="/documente/inbox?status=ERROR"
          delayClass="rise-delay-4"
        />
      </div>

      {data.closing && <ClosingBand closing={data.closing} />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <StatusPanel slices={data.byStatus} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-2">
          <MiniStat
            Icon={FileStack}
            label="Clienți cu documente complete"
            value={kpis.clientsComplete}
            total={kpis.clientsActive}
          />
          <MiniStat
            Icon={TriangleAlert}
            label="Clienți cu documente lipsă"
            value={kpis.clientsMissingDocs}
            total={kpis.clientsActive}
          />
          <MiniStat
            Icon={Copy}
            label="Documente duplicate"
            value={kpis.documentsDuplicate}
            total={Math.max(kpis.documentsToday, 1)}
          />
          <MiniStat
            Icon={UserX}
            label="Client neidentificat"
            value={kpis.documentsUnmatched}
            total={Math.max(kpis.documentsToday, 1)}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Inbox documente (§52) */}
        <div className="xl:col-span-2">
          <Panel
            title="Documente recente"
            action={
              <Link
                to="/documente/inbox"
                className="shrink-0 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Vezi toate
              </Link>
            }
            bodyClassName="p-0"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">Document</th>
                    <th scope="col" className="px-4 py-3 font-medium">Client</th>
                    <th scope="col" className="px-4 py-3 font-medium">Sursă</th>
                    <th scope="col" className="px-4 py-3 font-medium">Ora</th>
                    <th scope="col" className="px-4 py-3 font-medium">Status</th>
                    <th scope="col" className="px-4 py-3 font-medium">Încredere</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {data.recentDocuments.map((doc) => (
                    <tr key={doc.id} className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60">
                      <td className="px-4 py-3">
                        <Link
                          to={`/documente/verificare/${doc.id}`}
                          className="block max-w-52 truncate font-medium text-slate-900 hover:text-blue-600 dark:text-slate-100 dark:hover:text-blue-400"
                        >
                          {doc.originalFilename}
                        </Link>
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          {doc.documentTypeLabel ?? "Tip neidentificat"}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                        {doc.clientName ?? (
                          <span className="text-red-600 dark:text-red-400">Neidentificat</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                        {SOURCE_LABEL[doc.source]}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400">
                        {formatTime(doc.receivedAt)}
                      </td>
                      <td className="px-4 py-3">
                        <DocumentStatusBadge status={doc.status} />
                      </td>
                      <td className="px-4 py-3">
                        <ConfidenceBadge confidence={doc.confidence} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        {/* Needs attention (§20) */}
        <Panel title="Necesită atenție">
          {data.attention.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
              Nimic în așteptare. Toate documentele au trecut de validare.
            </p>
          ) : (
            <ul className="space-y-3">
              {data.attention.map((item) => {
                const tone = ATTENTION_TONE[item.reason];
                const content = (
                  <>
                    <div
                      className={cn(
                        "mt-0.5 grid h-8 w-8 shrink-0 place-content-center rounded-lg",
                        tone === "danger"
                          ? "bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
                          : "bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400",
                      )}
                    >
                      <CircleAlert className="h-4 w-4" aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {item.title}
                      </p>
                      <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                        {item.detail}
                      </p>
                      <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                        {formatTime(item.occurredAt)}
                      </p>
                    </div>
                  </>
                );
                return (
                  <li key={item.id}>
                    {item.documentId ? (
                      <Link
                        to={`/documente/verificare/${item.documentId}`}
                        className="flex gap-3 rounded-lg p-1 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60"
                      >
                        {content}
                      </Link>
                    ) : (
                      <div className="flex gap-3 p-1">{content}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Perioade contabile (§19) */}
        <div className="xl:col-span-2">
          <Panel
            title={month ? `Perioade contabile — ${month}` : "Perioade contabile"}
            action={
              <Link
                to="/contabilitate/perioade"
                className="shrink-0 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Toate perioadele
              </Link>
            }
          >
            <ul className="space-y-4">
              {data.periods.map((period) => {
                const ratio =
                  period.expectedCount === 0
                    ? 0
                    : Math.min(period.satisfiedCount / period.expectedCount, 1);
                return (
                  <li key={period.id}>
                    <div className="mb-1.5 flex items-center justify-between gap-3">
                      <Link
                        to={`/crm/clienti/${period.clientId}`}
                        className="truncate text-sm font-medium text-slate-900 hover:text-blue-600 dark:text-slate-100 dark:hover:text-blue-400"
                      >
                        {period.clientName}
                      </Link>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="text-xs text-slate-500 dark:text-slate-400">
                          {period.satisfiedCount}/{period.expectedCount} așteptate
                        </span>
                        <PeriodStatusBadge status={period.status} />
                      </div>
                    </div>
                    <div
                      className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
                      role="progressbar"
                      aria-valuenow={Math.round(ratio * 100)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Progres documente ${period.clientName}`}
                    >
                      <div
                        className={cn(
                          "h-2 rounded-full transition-all",
                          ratio >= 1
                            ? "bg-green-500"
                            : ratio >= 0.6
                              ? "bg-blue-500"
                              : ratio > 0
                                ? "bg-amber-500"
                                : "bg-slate-300 dark:bg-slate-600",
                        )}
                        style={{ width: `${Math.round(ratio * 100)}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </Panel>
        </div>

        {/* Cronologie generată din evenimente reale (§54) */}
        <Panel title="Activitate recentă">
          <ol className="relative space-y-4 border-l border-slate-200 pl-4 dark:border-slate-800">
            {data.timeline.map((event) => (
              <li key={event.id} className="relative">
                <span
                  className="absolute top-1.5 -left-[21px] h-2.5 w-2.5 rounded-full bg-blue-500 ring-4 ring-white dark:ring-slate-900"
                  aria-hidden="true"
                />
                <p className="text-sm break-words text-slate-900 dark:text-slate-100">
                  {event.description}
                </p>
                <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
                  <Clock className="h-3 w-3" aria-hidden="true" />
                  {formatTime(event.occurredAt)}
                </p>
              </li>
            ))}
          </ol>
        </Panel>
      </div>
    </div>
  );
}

/**
 * Termenul lunii și cine încă nu a trimis.
 *
 * Restul panoului spune **starea**: câte documente au intrat, câte așteaptă
 * verificare. Nu spunea niciodată *cât mai e până trebuie depus* — singurul
 * lucru care dă ordinea muncii într-un cabinet. Numărul de zile schimbă ce faci
 * azi mai mult decât orice contor.
 *
 * Clienții sunt ordonați după cât le lipsește, nu alfabetic, și fiecare rând
 * duce direct la fișa lui: panoul spunea „3 clienți cu documente lipsă" fără să
 * spună **care**, deci cineva trebuia oricum să caute în altă parte.
 */
function ClosingBand({ closing }: { closing: DashboardClosing }) {
  const { daysLeft } = closing;
  const overdue = daysLeft < 0;
  const urgent = !overdue && daysLeft <= URGENT_DAYS;

  const tone = overdue
    ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/40"
    : urgent
      ? "border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/40"
      : "border-slate-200/80 bg-white dark:border-slate-800 dark:bg-slate-900";

  return (
    <section
      aria-label="Termenul lunii"
      className={cn("rounded-xl border p-4 shadow-sm", tone)}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-100">
          <CalendarClock className="h-5 w-5 shrink-0" aria-hidden="true" />
          {overdue
            ? `Termenul a trecut de ${Math.abs(daysLeft)} ${plural(Math.abs(daysLeft))}`
            : daysLeft === 0
              ? "Termenul este azi"
              : `Mai sunt ${daysLeft} ${plural(daysLeft)} până la termen`}
        </span>
        <span className="text-sm text-slate-600 dark:text-slate-400">
          depunere până pe {formatDate(closing.deadline)}, pentru{" "}
          {formatReferenceMonth(closing.referenceMonth)}
        </span>
      </div>

      {closing.clientsWaiting === 0 ? (
        <p className="mt-2 flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
          <CircleCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
          Toți clienții au trimis ce se aștepta de la ei.
        </p>
      ) : (
        <>
          <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">
            {closing.clientsWaiting}{" "}
            {closing.clientsWaiting === 1 ? "client nu a trimis" : "clienți nu au trimis"} tot:
          </p>
          <ul className="mt-2 space-y-1.5">
            {closing.laggards.map((laggard) => (
              <li key={laggard.clientId} className="flex flex-wrap items-baseline gap-x-2 text-sm">
                <Link
                  to={`/crm/clienti/${laggard.clientId}`}
                  className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  {laggard.clientName}
                </Link>
                <span className="text-slate-600 dark:text-slate-400">
                  {laggard.missing.join(", ")}
                  {laggard.missingCount > laggard.missing.length &&
                    ` +${laggard.missingCount - laggard.missing.length}`}
                </span>
              </li>
            ))}
          </ul>
          {closing.clientsWaiting > closing.laggards.length && (
            <Link
              to="/contabilitate/lipsa"
              className="mt-2 inline-block text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              Vezi toți cei {closing.clientsWaiting} →
            </Link>
          )}
        </>
      )}
    </section>
  );
}

/** „zi" / „zile", ca textul să nu sune a mesaj de robot. */
function plural(days: number): string {
  return days === 1 ? "zi" : "zile";
}

/**
 * Antetul panoului.
 *
 * Panoul deschidea cu un titlu și o propoziție — corect, dar mut. Primul ecran
 * după autentificare este singurul care are voie să spună dintr-o privire cum
 * stă cabinetul, iar „cum stă" înseamnă **ritm**: câte documente au intrat în
 * ultimele două săptămâni și dacă azi seamănă cu ieri.
 *
 * Graficul nu este decor. Un cabinet vede acolo lucruri pe care niciun contor
 * nu le arată: o zi în care nu a intrat nimic (a picat sincronizarea?), un vârf
 * la sfârșit de lună, o pantă care coboară de trei zile.
 */
function HeroHeader({
  month,
  kpis,
  trend,
}: {
  month: string | null;
  kpis: DashboardData["kpis"];
  trend: DashboardData["trend"];
}) {
  const received = trend.reduce((sum, day) => sum + day.count, 0);
  const yesterday = trend[trend.length - 2]?.count ?? 0;
  const today = trend[trend.length - 1]?.count ?? 0;
  const delta = today - yesterday;

  return (
    <section className="rise-in relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      {/* Pata de culoare stă în spate, la opacitate mică: dă căldură fără să
          scadă contrastul textului de deasupra. */}
      <div
        className="pointer-events-none absolute -top-24 -right-24 h-72 w-72 rounded-full bg-gradient-to-br from-blue-500/20 via-violet-500/15 to-transparent blur-2xl"
        aria-hidden="true"
      />

      <div className="relative flex flex-wrap items-end justify-between gap-6 p-6">
        <div className="min-w-0">
          <p className="text-[11px] font-medium tracking-wide text-blue-600 uppercase dark:text-blue-400">
            {month ? `Luna în lucru · ${month}` : "Nicio lună în lucru"}
          </p>
          <h2 className="mt-1 text-3xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            Panou principal
          </h2>
          <p className={cn("mt-2 max-w-xl text-sm", mutedText)}>
            {received === 0
              ? "Niciun document în ultimele două săptămâni."
              : `${received} documente în ultimele două săptămâni, ${today} azi.`}{" "}
            {kpis.documentsNeedReview > 0
              ? `${kpis.documentsNeedReview} așteaptă verificare.`
              : "Nimic nu așteaptă verificare."}
          </p>
        </div>

        <div className="flex min-w-0 flex-1 items-end justify-end gap-6">
          <div className="text-right">
            <p className="text-4xl font-semibold tracking-tight tabular-nums text-slate-900 dark:text-slate-50">
              {today}
            </p>
            <p className={cn("text-xs", mutedText)}>documente azi</p>
            {delta !== 0 && (
              <p
                className={cn(
                  "mt-1 inline-flex items-center gap-1 text-xs font-medium",
                  delta > 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-slate-500 dark:text-slate-400",
                )}
              >
                {delta > 0 ? (
                  <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <TrendingDown className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {delta > 0 ? `+${delta}` : delta} față de ieri
              </p>
            )}
          </div>

          <TrendArea
            points={trend}
            label="Documente sosite pe zi"
            className="h-20 w-full max-w-md min-w-[8rem] text-blue-500 dark:text-blue-400"
          />
        </div>
      </div>
    </section>
  );
}

function KpiCard({
  Icon,
  tone,
  label,
  value,
  hint,
  to,
  delayClass,
}: {
  Icon: LucideIcon;
  tone: Tone;
  label: string;
  value: number;
  hint: string;
  to: string;
  delayClass?: string;
}) {
  return (
    <Link
      to={to}
      className={cn("group block p-5", surfaceInteractive, focusRing, "rise-in", delayClass)}
    >
      <div className="mb-4 flex items-start justify-between">
        <div className={cn("grid h-12 w-12 place-content-center rounded-2xl", iconChip[tone])}>
          <Icon className="h-6 w-6" aria-hidden="true" />
        </div>
        {/* Săgeata apare la trecerea cursorului: cardul este un link, dar o
            săgeată permanentă pe patru carduri devine zgomot. */}
        <ArrowUpRight
          className="h-4 w-4 text-slate-300 opacity-0 transition-opacity group-hover:opacity-100 dark:text-slate-600"
          aria-hidden="true"
        />
      </div>
      <h3 className={cn("mb-1 text-sm font-medium", mutedText)}>{label}</h3>
      <p className="text-3xl font-semibold tracking-tight tabular-nums text-slate-900 dark:text-slate-50">
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>
    </Link>
  );
}

/**
 * Unde stau documentele, ca inel.
 *
 * Contorul „necesită verificare" spune un număr; inelul spune o **proporție** —
 * dacă jumătate din tot ce a intrat aşteaptă un om, asta se vede dintr-o
 * privire și nu se vede din patru contoare puse alături.
 */
function StatusPanel({ slices }: { slices: DashboardData["byStatus"] }) {
  const total = slices.reduce((sum, slice) => sum + slice.count, 0);

  return (
    <Panel title="Unde stau documentele" className="rise-in rise-delay-2">
      {total === 0 ? (
        <p className={cn("py-8 text-center text-sm", mutedText)}>Niciun document încă.</p>
      ) : (
        <div className="flex items-center gap-5">
          <Donut
            className="h-32 w-32 shrink-0"
            label="Distribuția documentelor pe stări"
            centerValue={String(total)}
            centerLabel="documente"
            slices={slices.map((slice) => ({
              label: DOCUMENT_STATUS_LABEL[slice.status],
              value: slice.count,
              className: STATUS_ARC[slice.status],
            }))}
          />
          <ul className="min-w-0 flex-1 space-y-1.5">
            {slices.slice(0, MAX_STATUS_ROWS).map((slice) => (
              <li key={slice.status} className="flex items-center gap-2 text-sm">
                <span
                  className={cn("h-2.5 w-2.5 shrink-0 rounded-full", statusDot(slice.status))}
                  aria-hidden="true"
                />
                <span className={cn("min-w-0 flex-1 truncate", mutedText)}>
                  {DOCUMENT_STATUS_LABEL[slice.status]}
                </span>
                <span className="font-medium tabular-nums text-slate-900 dark:text-slate-100">
                  {slice.count}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function MiniStat({
  Icon,
  label,
  value,
  total,
}: {
  Icon: LucideIcon;
  label: string;
  value: number;
  total: number;
}) {
  const ratio = total === 0 ? 0 : Math.min(value / total, 1);
  return (
    <div className={cn("p-4", surface)}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
          <span className={cn("truncate text-sm", mutedText)}>{label}</span>
        </div>
        <span className="text-sm font-semibold tabular-nums text-slate-900 dark:text-slate-100">
          {value}
          <span className="text-slate-400 dark:text-slate-500">/{total}</span>
        </span>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        {/* Tranziția are rost: numărul se schimbă la reîmprospătarea panoului, iar
            un salt brusc al barei se citește ca o eroare de randare. */}
        <div
          className="h-1.5 rounded-full bg-blue-500 transition-[width] duration-500 ease-out"
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  );
}
