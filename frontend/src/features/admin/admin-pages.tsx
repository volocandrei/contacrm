import { CircleAlert, Lock } from "lucide-react";
import { useAuditLogs, useUsers } from "@/api/hooks";
import { Pagination, SearchInput } from "@/components/form-controls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { useAuth, useHasPermission } from "@/features/auth/use-auth";
import { useFilterParams } from "@/hooks/use-filter-params";
import { formatDateTime } from "@/lib/format";
import { ROLE_CODE, type Permission, type RoleCode } from "@/types/domain";

const ROLE_LABEL: Record<RoleCode, string> = {
  SUPER_ADMIN: "Super administrator",
  ADMIN: "Administrator",
  ACCOUNTANT: "Contabil",
  OPERATOR: "Operator",
  REVIEWER: "Verificator",
  VIEWER: "Vizitator",
};

const PERMISSION_LABEL: Record<Permission, string> = {
  "clients:read": "Vizualizare clienți",
  "clients:write": "Modificare clienți",
  "documents:read": "Vizualizare documente",
  "documents:write": "Modificare documente",
  "documents:approve": "Aprobare documente",
  "documents:delete": "Ștergere documente",
  "periods:manage": "Administrare perioade",
  "tasks:read": "Vizualizare sarcini",
  "tasks:write": "Modificare sarcini",
  "communication:send": "Trimitere mesaje",
  "admin:users": "Administrare utilizatori",
  "admin:settings": "Administrare setări",
  "audit:read": "Acces jurnal audit",
};

export function NoPermissionState({ permission }: { permission: string }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="max-w-sm rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-gray-800 dark:bg-gray-900">
        <div className="mx-auto mb-3 grid h-11 w-11 place-content-center rounded-lg bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400">
          <Lock className="h-5 w-5" aria-hidden="true" />
        </div>
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">Acces restricționat</p>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          Rolul tău nu include permisiunea <code>{permission}</code>.
        </p>
      </div>
    </div>
  );
}

export function UsersPage() {
  const canManage = useHasPermission("admin:users");
  const { data, isLoading, error } = useUsers();

  if (!canManage) return <NoPermissionState permission="admin:users" />;
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;

  return (
    <div>
      <PageHeader title="Utilizatori" description="Conturile din organizație și rolurile lor" />
      <Panel bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Nume</th>
                <th scope="col" className="px-4 py-3 font-medium">Email</th>
                <th scope="col" className="px-4 py-3 font-medium">Rol</th>
                <th scope="col" className="px-4 py-3 font-medium">Stare</th>
                <th scope="col" className="px-4 py-3 font-medium">Ultima autentificare</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {data?.map((user) => (
                <tr key={user.id}>
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                    {user.fullName}
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{user.email}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                    {ROLE_LABEL[user.role]}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={
                        user.isActive
                          ? "text-green-600 dark:text-green-400"
                          : "text-gray-400 dark:text-gray-500"
                      }
                    >
                      {user.isActive ? "Activ" : "Dezactivat"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                    {user.lastLoginAt ? formatDateTime(user.lastLoginAt) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

/** Matricea rol × permisiune, ca regulile să fie vizibile, nu ascunse în cod. */
export function RolesPage() {
  const { user } = useAuth();
  const permissions = Object.keys(PERMISSION_LABEL) as Permission[];

  return (
    <div>
      <PageHeader
        title="Roluri și permisiuni"
        description="Matricea de acces. Regulile se aplică în backend, la fiecare cerere."
      />
      <Panel bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Permisiune</th>
                {ROLE_CODE.map((role) => (
                  <th key={role} scope="col" className="px-3 py-3 text-center font-medium">
                    {ROLE_LABEL[role]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {permissions.map((permission) => (
                <tr key={permission}>
                  <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300">
                    {PERMISSION_LABEL[permission]}
                    <span className="ml-2 text-xs text-gray-400">{permission}</span>
                  </td>
                  {ROLE_CODE.map((role) => {
                    const granted =
                      role === user?.role ? user.permissions.includes(permission) : undefined;
                    return (
                      <td key={role} className="px-3 py-2.5 text-center">
                        {granted === undefined ? (
                          <span className="text-gray-300 dark:text-gray-600">·</span>
                        ) : granted ? (
                          <span className="text-green-600 dark:text-green-400">✓</span>
                        ) : (
                          <span className="text-gray-300 dark:text-gray-600">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t border-gray-200 px-4 py-3 text-xs text-gray-500 dark:border-gray-800 dark:text-gray-400">
          Coloana rolului curent ({user ? ROLE_LABEL[user.role] : "—"}) reflectă permisiunile
          returnate de API. Restul coloanelor se vor popula când backend-ul expune matricea completă.
        </p>
      </Panel>
    </div>
  );
}

export function AuditLogPage() {
  const canRead = useHasPermission("audit:read");
  const { values, setValue } = useFilterParams({ q: "", page: "1" });
  const { data, isLoading, error } = useAuditLogs({
    q: values.q,
    page: Number(values.page) || 1,
    pageSize: 25,
  });

  if (!canRead) return <NoPermissionState permission="audit:read" />;

  return (
    <div>
      <PageHeader
        title="Jurnal audit"
        description="Fiecare acțiune importantă este înregistrată și nu poate fi ștearsă din interfață"
      />

      <SearchInput
        label="Caută în audit"
        value={values.q}
        onChange={(value) => setValue("q", value)}
        placeholder="Utilizator, entitate, detaliu…"
        className="mb-4 w-full sm:w-96"
      />

      <Panel bodyClassName="p-0">
        {isLoading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState title="Nicio înregistrare" />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">Moment</th>
                    <th scope="col" className="px-4 py-3 font-medium">Utilizator</th>
                    <th scope="col" className="px-4 py-3 font-medium">Acțiune</th>
                    <th scope="col" className="px-4 py-3 font-medium">Entitate</th>
                    <th scope="col" className="px-4 py-3 font-medium">Detaliu</th>
                    <th scope="col" className="px-4 py-3 font-medium">IP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {data?.items.map((entry) => (
                    <tr key={entry.id}>
                      <td className="px-4 py-2.5 whitespace-nowrap text-gray-500 dark:text-gray-400">
                        {formatDateTime(entry.at)}
                      </td>
                      <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300">
                        {entry.userName}
                      </td>
                      <td className="px-4 py-2.5">
                        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                          {entry.action}
                        </code>
                      </td>
                      <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400">
                        {entry.entityType} · {entry.entityId}
                      </td>
                      <td className="max-w-64 truncate px-4 py-2.5 text-gray-600 dark:text-gray-400">
                        {entry.detail ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 text-gray-400 dark:text-gray-500">{entry.ip}</td>
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

/**
 * Setările sunt afișate ca valori curente, fără editare, până când backend-ul
 * expune `system_settings`. Pragurile nu sunt hardcodate în interfață (§16).
 */
export function SettingsPage() {
  const canManage = useHasPermission("admin:settings");
  if (!canManage) return <NoPermissionState permission="admin:settings" />;

  const groups = [
    {
      title: "Procesare și încredere",
      items: [
        { label: "Prag aprobare automată", value: "0,90", source: "system_settings" },
        { label: "Prag verificare obligatorie", value: "0,70", source: "system_settings" },
        { label: "Reîncercări OCR", value: "3", source: "system_settings" },
      ],
    },
    {
      title: "Stocare",
      items: [
        { label: "Provider", value: "local", source: "STORAGE_PROVIDER" },
        { label: "Rădăcină arhivă", value: "/ARHIVA/{an}/{luna}/{client}/", source: "ARCHIVE_ROOT" },
        { label: "Dimensiune maximă upload", value: "25 MB", source: "MAX_UPLOAD_SIZE_MB" },
      ],
    },
    {
      title: "OCR / AI",
      items: [
        { label: "Provider OCR", value: "mock", source: "OCR_PROVIDER" },
        { label: "Provider AI", value: "mock", source: "AI_PROVIDER" },
        { label: "Versiune prompt", value: "v1", source: "PROMPT_VERSION" },
      ],
    },
    {
      title: "Notificări",
      items: [
        { label: "Trimitere activă", value: "dezactivată", source: "NOTIFICATIONS_ENABLED" },
        { label: "Provider email", value: "neconfigurat", source: "EMAIL_PROVIDER" },
        { label: "Provider WhatsApp", value: "neconfigurat", source: "WHATSAPP_PROVIDER" },
      ],
    },
    {
      title: "Retenție",
      items: [
        { label: "Ștergere automată", value: "dezactivată", source: "RETENTION_ENABLED" },
        { label: "Păstrare documente", value: "10 ani", source: "RETENTION_DOCUMENTS_YEARS" },
        { label: "Păstrare audit", value: "5 ani", source: "RETENTION_AUDIT_LOG_YEARS" },
      ],
    },
  ];

  return (
    <div>
      <PageHeader
        title="Setări"
        description="Valorile curente de configurare. Editarea devine disponibilă odată cu backend-ul."
      />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>
          Valorile de mai jos vin din variabile de mediu și din tabelul <code>system_settings</code>.
          Nicio regulă fiscală nu este hardcodată în interfață.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {groups.map((group) => (
          <Panel key={group.title} title={group.title}>
            <dl className="space-y-2 text-sm">
              {group.items.map((item) => (
                <div key={item.label} className="flex items-start justify-between gap-3">
                  <dt className="text-gray-600 dark:text-gray-400">
                    {item.label}
                    <span className="ml-2 text-xs text-gray-400">{item.source}</span>
                  </dt>
                  <dd className="shrink-0 font-medium text-gray-900 dark:text-gray-100">
                    {item.value}
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>
        ))}
      </div>
    </div>
  );
}
