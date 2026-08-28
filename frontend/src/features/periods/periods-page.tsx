import { Link } from "react-router-dom";
import { CircleCheck, TriangleAlert } from "lucide-react";
import { useMissingDocuments, usePeriods } from "@/api/hooks";
import { SelectFilter } from "@/components/form-controls";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { PeriodStatusBadge } from "@/components/status-badge";
import { useFilterParams } from "@/hooks/use-filter-params";
import { formatReferenceMonth } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PERIOD_STATUS } from "@/types/domain";

const MONTH_OPTIONS = [
  { value: "2026-08", label: "August 2026" },
  { value: "2026-07", label: "Iulie 2026" },
  { value: "2026-06", label: "Iunie 2026" },
];

const STATUS_LABEL: Record<string, string> = {
  NOT_STARTED: "Neînceput",
  COLLECTING: "În colectare",
  PARTIAL: "Parțial",
  COMPLETE: "Documente complete",
  PROCESSING: "În procesare",
  REVIEW: "Verificare",
  FINALIZED: "Finalizat",
};

export function PeriodsPage() {
  const { values, setValue } = useFilterParams({ referenceMonth: "2026-08", status: "" });
  const { data, isLoading, error } = usePeriods({
    referenceMonth: values.referenceMonth,
    status: values.status,
  });

  return (
    <div>
      <PageHeader
        title="Perioade contabile"
        description="Stadiul colectării documentelor, per client și lună"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <SelectFilter
          label="Lună"
          allLabel="Toate lunile"
          value={values.referenceMonth}
          onChange={(value) => setValue("referenceMonth", value)}
          options={MONTH_OPTIONS}
          className="w-48"
        />
        <SelectFilter
          label="Status"
          allLabel="Toate statusurile"
          value={values.status}
          onChange={(value) => setValue("status", value)}
          options={PERIOD_STATUS.map((status) => ({ value: status, label: STATUS_LABEL[status]! }))}
          className="w-52"
        />
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data?.map((period) => {
            const ratio =
              period.expectedCount === 0
                ? 0
                : Math.min(period.satisfiedCount / period.expectedCount, 1);
            return (
              <Panel
                key={period.id}
                title={period.clientName}
                action={<PeriodStatusBadge status={period.status} />}
              >
                <div className="mb-3 flex items-center justify-between gap-2 text-sm">
                  <span className="text-gray-600 dark:text-gray-400">
                    {formatReferenceMonth(period.referenceMonth)}
                  </span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {period.satisfiedCount}/{period.expectedCount} documente așteptate
                  </span>
                </div>

                <div
                  className="mb-4 h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
                  role="progressbar"
                  aria-valuenow={Math.round(ratio * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`Progres ${period.clientName}`}
                >
                  <div
                    className={cn(
                      "h-2 rounded-full",
                      ratio >= 1 ? "bg-green-500" : ratio >= 0.6 ? "bg-blue-500" : "bg-amber-500",
                    )}
                    style={{ width: `${Math.round(ratio * 100)}%` }}
                  />
                </div>

                <ul className="space-y-1.5 text-sm">
                  {period.checklist.map((item) => (
                    <li key={item.documentType} className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-gray-600 dark:text-gray-400">
                        {item.isSatisfied ? (
                          <CircleCheck
                            className="h-3.5 w-3.5 text-green-500"
                            aria-label="complet"
                          />
                        ) : (
                          <TriangleAlert
                            className="h-3.5 w-3.5 text-amber-500"
                            aria-label="incomplet"
                          />
                        )}
                        {item.documentTypeLabel}
                      </span>
                      <span className="font-medium text-gray-900 dark:text-gray-100">
                        {item.receivedCount}/{item.expectedMinCount}
                      </span>
                    </li>
                  ))}
                </ul>

                <Link
                  to={`/documente/arhiva?clientId=${period.clientId}&referenceMonth=${period.referenceMonth}`}
                  className="mt-3 inline-block text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  Vezi documentele perioadei
                </Link>
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function MissingDocumentsPage() {
  const { values, setValue } = useFilterParams({ referenceMonth: "2026-08" });
  const { data, isLoading, error } = useMissingDocuments(values.referenceMonth);

  return (
    <div>
      <PageHeader
        title="Documente lipsă"
        description="Clienți la care checklist-ul perioadei nu este acoperit"
      />

      <SelectFilter
        label="Lună"
        allLabel="August 2026"
        value={values.referenceMonth}
        onChange={(value) => setValue("referenceMonth", value)}
        options={MONTH_OPTIONS}
        className="mb-4 w-48"
      />

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : (data?.length ?? 0) === 0 ? (
        <Panel>
          <p className="py-6 text-center text-sm text-gray-600 dark:text-gray-400">
            Toți clienții au documentele complete pentru luna selectată.
          </p>
        </Panel>
      ) : (
        <Panel bodyClassName="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">Client</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="px-4 py-3 font-medium">Documente lipsă</th>
                  <th scope="col" className="px-4 py-3 font-medium">Primite</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {data?.map(({ period, missing }) => (
                  <tr key={period.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/60">
                    <td className="px-4 py-3">
                      <Link
                        to={`/crm/clienti/${period.clientId}`}
                        className="font-medium text-gray-900 hover:text-blue-600 hover:underline dark:text-gray-100 dark:hover:text-blue-400"
                      >
                        {period.clientName}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <PeriodStatusBadge status={period.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {missing.map((item) => (
                          <span
                            key={item.documentType}
                            className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-amber-200 ring-inset dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-800"
                          >
                            {item.documentTypeLabel} {item.receivedCount}/{item.expectedMinCount}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {period.satisfiedCount}/{period.expectedCount}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}
