import { Link } from "react-router-dom";
import {
  Building2,
  CircleAlert,
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
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { ConfidenceBadge, DocumentStatusBadge, PeriodStatusBadge } from "@/components/status-badge";
import { formatReferenceMonth, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AttentionReason, DocumentSource } from "@/types/domain";

const CURRENT_MONTH = "2026-08";

const SOURCE_LABEL: Record<DocumentSource, string> = {
  EMAIL: "Email",
  WHATSAPP: "WhatsApp",
  UPLOAD: "Încărcare",
  API: "API",
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Panou principal"
        description={`Situația documentelor și a clienților pentru ${formatReferenceMonth(CURRENT_MONTH)}`}
      />

      {/* KPI (§20) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          Icon={Building2}
          tone="blue"
          label="Clienți activi"
          value={kpis.clientsActive}
          hint={`din ${kpis.clientsTotal} clienți în total`}
          to="/crm/clienti?status=ACTIVE"
        />
        <KpiCard
          Icon={Inbox}
          tone="purple"
          label="Documente primite azi"
          value={kpis.documentsToday}
          hint={`${kpis.documentsProcessing} în procesare`}
          to="/documente/inbox"
        />
        <KpiCard
          Icon={ShieldCheck}
          tone="amber"
          label="Necesită verificare"
          value={kpis.documentsNeedReview}
          hint="sub pragul de încredere configurat"
          to="/documente/verificare"
        />
        <KpiCard
          Icon={TriangleAlert}
          tone="red"
          label="Documente cu erori"
          value={kpis.documentsError}
          hint={`${kpis.documentsDuplicate} posibile duplicate`}
          to="/documente/inbox?status=ERROR"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
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
                <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">Document</th>
                    <th scope="col" className="px-4 py-3 font-medium">Client</th>
                    <th scope="col" className="px-4 py-3 font-medium">Sursă</th>
                    <th scope="col" className="px-4 py-3 font-medium">Ora</th>
                    <th scope="col" className="px-4 py-3 font-medium">Status</th>
                    <th scope="col" className="px-4 py-3 font-medium">Încredere</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {data.recentDocuments.map((doc) => (
                    <tr key={doc.id} className="transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/60">
                      <td className="px-4 py-3">
                        <Link
                          to={`/documente/verificare/${doc.id}`}
                          className="block max-w-52 truncate font-medium text-gray-900 hover:text-blue-600 dark:text-gray-100 dark:hover:text-blue-400"
                        >
                          {doc.originalFilename}
                        </Link>
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {doc.documentTypeLabel ?? "Tip neidentificat"}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                        {doc.clientName ?? (
                          <span className="text-red-600 dark:text-red-400">Neidentificat</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                        {SOURCE_LABEL[doc.source]}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">
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
            <p className="py-6 text-center text-sm text-gray-500 dark:text-gray-400">
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
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {item.title}
                      </p>
                      <p className="truncate text-xs text-gray-500 dark:text-gray-400">
                        {item.detail}
                      </p>
                      <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
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
                        className="flex gap-3 rounded-lg p-1 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/60"
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
            title={`Perioade contabile — ${formatReferenceMonth(CURRENT_MONTH)}`}
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
                    : Math.min(period.receivedCount / period.expectedCount, 1);
                return (
                  <li key={period.id}>
                    <div className="mb-1.5 flex items-center justify-between gap-3">
                      <Link
                        to={`/crm/clienti/${period.clientId}`}
                        className="truncate text-sm font-medium text-gray-900 hover:text-blue-600 dark:text-gray-100 dark:hover:text-blue-400"
                      >
                        {period.clientName}
                      </Link>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          {period.receivedCount}/{period.expectedCount} documente
                        </span>
                        <PeriodStatusBadge status={period.status} />
                      </div>
                    </div>
                    <div
                      className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
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
                                : "bg-gray-300 dark:bg-gray-600",
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
          <ol className="relative space-y-4 border-l border-gray-200 pl-4 dark:border-gray-800">
            {data.timeline.map((event) => (
              <li key={event.id} className="relative">
                <span
                  className="absolute top-1.5 -left-[21px] h-2.5 w-2.5 rounded-full bg-blue-500 ring-4 ring-white dark:ring-gray-900"
                  aria-hidden="true"
                />
                <p className="text-sm break-words text-gray-900 dark:text-gray-100">
                  {event.description}
                </p>
                <p className="mt-0.5 flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500">
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

const KPI_TONE = {
  blue: "bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400",
  purple: "bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-400",
  amber: "bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400",
  red: "bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400",
} as const;

function KpiCard({
  Icon,
  tone,
  label,
  value,
  hint,
  to,
}: {
  Icon: LucideIcon;
  tone: keyof typeof KPI_TONE;
  label: string;
  value: number;
  hint: string;
  to: string;
}) {
  return (
    <Link
      to={to}
      className="block rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md dark:border-gray-800 dark:bg-gray-900"
    >
      <div className={cn("mb-4 grid h-9 w-9 place-content-center rounded-lg", KPI_TONE[tone])}>
        <Icon className="h-5 w-5" aria-hidden="true" />
      </div>
      <h3 className="mb-1 text-sm font-medium text-gray-600 dark:text-gray-400">{label}</h3>
      <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">{value}</p>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{hint}</p>
    </Link>
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
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
          <span className="truncate text-sm text-gray-600 dark:text-gray-400">{label}</span>
        </div>
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{value}</span>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
