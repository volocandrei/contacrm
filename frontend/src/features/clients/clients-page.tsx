import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { useClients } from "@/api/hooks";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { ClientForm } from "@/features/clients/client-form";
import { Pagination, SearchInput, SelectFilter } from "@/components/form-controls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { ClientStatusBadge } from "@/components/status-badge";
import { useFilterParams } from "@/hooks/use-filter-params";
import { formatDateTime } from "@/lib/format";
import { iconChip, pillClass, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
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
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  const has = usePermissionCheck();
  const { data, isLoading, error } = useClients({
    q: values.q,
    status: values.status,
    page: Number(values.page) || 1,
    pageSize: 15,
  });

  return (
    <div>
      <PageHeader
        title="Clienți"
        description="Companiile administrate de cabinet"
        actions={
          // Butonul se ascunde fără permisiune, dar decizia rămâne pe server:
          // ascunderea este ergonomie, nu securitate.
          has("clients:write") && !adding ? (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Client nou
            </button>
          ) : null
        }
      />

      {adding && (
        <div className="mb-4">
          <ClientForm
            onDone={(client) => {
              setAdding(false);
              // Direct pe fișa lui: pasul următor este aproape întotdeauna
              // adăugarea contactului, adică adresa după care sosesc documentele.
              navigate(`/crm/clienti/${client.id}`);
            }}
            onCancel={() => setAdding(false)}
          />
        </div>
      )}

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
                <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">Denumire</th>
                    <th scope="col" className="px-4 py-3 font-medium">CUI</th>
                    <th scope="col" className="px-4 py-3 font-medium">Contabil</th>
                    <th scope="col" className="px-4 py-3 font-medium">Etichete</th>
                    <th scope="col" className="px-4 py-3 font-medium">Ultima interacțiune</th>
                    <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {data?.items.map((client) => (
                    <tr
                      key={client.id}
                      className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          {/* Inițialele în locul unei iconițe generice: într-o
                              listă de treizeci de firme, ochiul găsește „AC"
                              mai repede decât citește „Alfa Conta SRL". */}
                          <span
                            className={cn(
                              "grid h-9 w-9 shrink-0 place-content-center rounded-lg text-xs font-semibold",
                              iconChip[avatarTone(client.name)],
                            )}
                            aria-hidden="true"
                          >
                            {initials(client.name)}
                          </span>
                          <div className="min-w-0">
                            <Link
                              to={`/crm/clienti/${client.id}`}
                              className="font-medium text-slate-900 hover:text-blue-600 hover:underline dark:text-slate-100 dark:hover:text-blue-400"
                            >
                              {client.name}
                            </Link>
                            <div className="truncate text-xs text-slate-500 dark:text-slate-400">
                              {client.address}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-slate-600 dark:text-slate-400">
                        {client.taxId}
                      </td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                        {client.assignedAccountantName ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {client.tags.map((tag) => (
                            <span key={tag} className={pillClass("slate")}>
                              {tag}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400">
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

/** Inițialele firmei, cel mult două litere. */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((word) => /\p{L}/u.test(word))
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Tonul pastilei, derivat din nume.
 *
 * Stabil — același client are mereu aceeași culoare, deci devine recognoscibil —
 * și fără sens semantic: culoarea nu spune nimic despre client, doar îl separă
 * de vecinii lui din listă.
 */
const AVATAR_TONES: Tone[] = ["blue", "green", "amber", "purple", "red", "slate"];

function avatarTone(name: string): Tone {
  const sum = [...name].reduce((total, character) => total + character.charCodeAt(0), 0);
  return AVATAR_TONES[sum % AVATAR_TONES.length]!;
}
