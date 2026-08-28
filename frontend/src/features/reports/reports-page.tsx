import { useMemo } from "react";
import { ChartColumn } from "lucide-react";
import { useDocuments } from "@/api/hooks";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { formatPercent, formatReferenceMonth } from "@/lib/format";

/**
 * Rapoarte MVP (§84): agregări simple peste documente.
 * Rapoartele reale vor fi calculate în backend, cu SQL, nu în interfață.
 */
export function ReportsPage() {
  const { data, isLoading, error } = useDocuments({ pageSize: 200 });

  const stats = useMemo(() => {
    const items = data?.items ?? [];
    const byMonth = new Map<string, number>();
    const byType = new Map<string, number>();
    const byClient = new Map<string, number>();

    for (const doc of items) {
      if (doc.referenceMonth) {
        byMonth.set(doc.referenceMonth, (byMonth.get(doc.referenceMonth) ?? 0) + 1);
      }
      const type = doc.documentTypeLabel ?? "Neidentificat";
      byType.set(type, (byType.get(type) ?? 0) + 1);
      const client = doc.clientName ?? "Client neidentificat";
      byClient.set(client, (byClient.get(client) ?? 0) + 1);
    }

    const processed = items.filter((d) => d.status !== "PROCESSING" && d.status !== "RECEIVED");
    const failed = items.filter((d) => d.status === "ERROR");
    const duplicates = items.filter((d) => d.isDuplicate);

    return {
      total: items.length,
      byMonth: [...byMonth.entries()].sort((a, b) => b[0].localeCompare(a[0])),
      byType: [...byType.entries()].sort((a, b) => b[1] - a[1]),
      byClient: [...byClient.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10),
      successRate: processed.length === 0 ? 0 : (processed.length - failed.length) / processed.length,
      failedCount: failed.length,
      duplicateCount: duplicates.length,
    };
  }, [data]);

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;

  return (
    <div>
      <PageHeader
        title="Rapoarte"
        description={`Agregări peste ultimele ${stats.total} documente. Rapoartele complete se vor calcula în backend.`}
      />

      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Rată de procesare reușită" value={formatPercent(stats.successRate)} />
        <StatCard label="Documente cu erori" value={String(stats.failedCount)} />
        <StatCard label="Duplicate detectate" value={String(stats.duplicateCount)} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Documente pe lună">
          <BarList
            items={stats.byMonth.map(([month, count]) => ({
              label: formatReferenceMonth(month),
              count,
            }))}
          />
        </Panel>
        <Panel title="Documente pe tip">
          <BarList items={stats.byType.map(([type, count]) => ({ label: type, count }))} />
        </Panel>
        <Panel title="Top clienți după volum">
          <BarList items={stats.byClient.map(([client, count]) => ({ label: client, count }))} />
        </Panel>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      <div className="mb-3 grid h-9 w-9 place-content-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400">
        <ChartColumn className="h-5 w-5" aria-hidden="true" />
      </div>
      <p className="text-sm text-gray-600 dark:text-gray-400">{label}</p>
      <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">{value}</p>
    </div>
  );
}

function BarList({ items }: { items: Array<{ label: string; count: number }> }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <ul className="space-y-2.5">
      {items.map((item) => (
        <li key={item.label}>
          <div className="mb-1 flex items-center justify-between gap-2 text-sm">
            <span className="truncate text-gray-600 dark:text-gray-400">{item.label}</span>
            <span className="shrink-0 font-medium text-gray-900 dark:text-gray-100">
              {item.count}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
            <div
              className="h-1.5 rounded-full bg-blue-500"
              style={{ width: `${(item.count / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
      {items.length === 0 && (
        <li className="py-4 text-center text-xs text-gray-400 dark:text-gray-500">Fără date</li>
      )}
    </ul>
  );
}
