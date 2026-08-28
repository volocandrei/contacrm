import { Link } from "react-router-dom";
import { useClients } from "@/api/hooks";
import { Pagination, SearchInput, SelectFilter } from "@/components/form-controls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { ClientStatusBadge } from "@/components/status-badge";
import { useFilterParams } from "@/hooks/use-filter-params";
import { formatDateTime } from "@/lib/format";
import { CLIENT_STATUS } from "@/types/domain";

const STATUS_LABEL: Record<string, string> = {
  ACTIVE: "Activ",
  INACTIVE: "Inactiv",
  PROSPECT: "Prospect",
  SUSPENDED: "Suspendat",
};

const DEFAULTS = { q: "", status: "", page: "1" };

export function ClientsPage() {
  const { values, setValue } = useFilterParams(DEFAULTS);
  const { data, isLoading, error } = useClients({
    q: values.q,
    status: values.status,
    page: Number(values.page) || 1,
    pageSize: 15,
  });

  return (
    <div>
      <PageHeader title="Clienți" description="Companiile administrate de cabinet" />

      <div className="mb-4 flex flex-wrap gap-2">
        <SearchInput
          label="Caută clienți"
          value={values.q}
          onChange={(value) => setValue("q", value)}
          placeholder="Denumire, CUI, adresă…"
          className="w-full sm:w-80"
        />
        <SelectFilter
          label="Status"
          allLabel="Toate statusurile"
          value={values.status}
          onChange={(value) => setValue("status", value)}
          options={CLIENT_STATUS.map((status) => ({ value: status, label: STATUS_LABEL[status]! }))}
          className="w-44"
        />
      </div>

      <Panel bodyClassName="p-0">
        {isLoading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState title="Niciun client" description="Ajustează filtrele de căutare." />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">Denumire</th>
                    <th scope="col" className="px-4 py-3 font-medium">CUI</th>
                    <th scope="col" className="px-4 py-3 font-medium">Contabil</th>
                    <th scope="col" className="px-4 py-3 font-medium">Etichete</th>
                    <th scope="col" className="px-4 py-3 font-medium">Ultima interacțiune</th>
                    <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {data?.items.map((client) => (
                    <tr
                      key={client.id}
                      className="transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/60"
                    >
                      <td className="px-4 py-3">
                        <Link
                          to={`/crm/clienti/${client.id}`}
                          className="font-medium text-gray-900 hover:text-blue-600 hover:underline dark:text-gray-100 dark:hover:text-blue-400"
                        >
                          {client.name}
                        </Link>
                        <div className="text-xs text-gray-500 dark:text-gray-400">{client.address}</div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                        {client.taxId}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                        {client.assignedAccountantName ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {client.tags.map((tag) => (
                            <span
                              key={tag}
                              className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-300"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">
                        {client.lastInteractionAt ? formatDateTime(client.lastInteractionAt) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <ClientStatusBadge status={client.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data && (
              <Pagination
                page={data.page}
                totalPages={data.totalPages}
                total={data.total}
                pageSize={data.pageSize}
                onPageChange={(page) => setValue("page", String(page))}
              />
            )}
          </>
        )}
      </Panel>
    </div>
  );
}
