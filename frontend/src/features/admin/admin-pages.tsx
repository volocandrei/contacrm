import {
  Check,
  CircleAlert,
  Lock,
  Minus,
  ScrollText,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useAuditLogs, useRoles, useSettings, useUsers } from "@/api/hooks";
import { Pagination, SearchInput } from "@/components/form-controls";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Panel,
  QueryBoundary,
} from "@/components/page";
import { AddUserButton, UserRow } from "@/features/admin/user-admin";
import { useAuth, useHasPermission } from "@/features/auth/use-auth";
import { useFilterParams } from "@/hooks/use-filter-params";
import { formatDateTime } from "@/lib/format";
import { PERMISSION_AREA_LABEL, PERMISSION_LABEL, ROLE_LABEL } from "@/lib/labels";
import { iconChip, mutedText, pillClass, surface, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import {
  SETTING_GROUPS,
  type Permission,
  type RoleCode,
  type SettingGroup,
} from "@/types/domain";

export function NoPermissionState({ permission }: { permission: string }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className={cn("max-w-sm p-8 text-center", surface, "rise-in")}>
        <div
          className={cn(
            "mx-auto mb-3 grid h-12 w-12 place-content-center rounded-2xl",
            iconChip.slate,
          )}
        >
          <Lock className="h-6 w-6" aria-hidden="true" />
        </div>
        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">Acces restricționat</p>
        <p className={cn("mt-1 text-xs", mutedText)}>
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

  const active = data?.filter((user) => user.isActive).length ?? 0;

  return (
    <div>
      <PageHeader
        title="Utilizatori"
        description="Conturile din organizație și rolurile lor"
        actions={<AddUserButton />}
      />

      {/* Câți sunt și câți mai pot intra: la o listă de zece rânduri se numără
          din ochi, la una de patruzeci nu. */}
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className={pillClass("blue")}>
          <Users className="h-3.5 w-3.5" aria-hidden="true" />
          {data?.length ?? 0} conturi
        </span>
        <span className={pillClass(active === (data?.length ?? 0) ? "green" : "slate")}>
          {active} active
        </span>
      </div>

      <Panel bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Nume</th>
                <th scope="col" className="px-4 py-3 font-medium">Email</th>
                <th scope="col" className="px-4 py-3 font-medium">Rol</th>
                <th scope="col" className="px-4 py-3 font-medium">Stare</th>
                <th scope="col" className="px-4 py-3 font-medium">Ultima autentificare</th>
                <th scope="col" className="px-4 py-3 font-medium sr-only">Acțiuni</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data?.map((user) => <UserRow key={user.id} user={user} />)}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

/* ─── Roluri ───────────────────────────────────────────────────────────────── */

/** Zona din aplicație, dedusă din prefixul permisiunii: `documents:approve` → `documents`. */
function areaOf(permission: Permission): string {
  return permission.split(":")[0] ?? "";
}

/**
 * Matricea rol × permisiune.
 *
 * Ecranul completa până acum **o singură coloană** — a rolului cu care ești
 * autentificat — și își recunoștea limita într-o notă de subsol. Nota era
 * cinstită și inutilă: cine deschide „Roluri" vrea să afle ce poate face un
 * operator *înainte* de a-i da rolul. `GET /roles` publică acum harta întreagă,
 * aceeași după care se ia decizia la fiecare cerere.
 */
export function RolesPage() {
  const canRead = useHasPermission("admin:users");
  const { user } = useAuth();
  const { data, isLoading, error } = useRoles();

  if (!canRead) return <NoPermissionState permission="admin:users" />;

  const roles = data ?? [];
  const permissions = Object.keys(PERMISSION_LABEL) as Permission[];
  const areas = [...new Set(permissions.map(areaOf))];

  return (
    <div>
      <PageHeader
        title="Roluri și permisiuni"
        description="Matricea de acces, așa cum o aplică serverul la fiecare cerere."
      />

      <QueryBoundary isLoading={isLoading} error={error} isEmpty={roles.length === 0}>
        <Panel bodyClassName="p-0" className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800">
                  <th
                    scope="col"
                    className="sticky left-0 z-10 bg-white px-4 py-3 text-xs font-medium tracking-wide text-slate-500 uppercase dark:bg-slate-900 dark:text-slate-400"
                  >
                    Permisiune
                  </th>
                  {roles.map((role) => {
                    const mine = role.code === user?.role;
                    return (
                      <th
                        key={role.code}
                        scope="col"
                        className={cn(
                          "px-3 py-3 text-center align-bottom",
                          mine && "bg-blue-50/70 dark:bg-blue-500/10",
                        )}
                      >
                        <span className="block text-xs font-semibold text-slate-700 dark:text-slate-200">
                          {role.label}
                        </span>
                        <span className={cn("mt-0.5 block text-[10px] tabular-nums", mutedText)}>
                          {role.permissions.length}/{permissions.length}
                        </span>
                        {/* Cine se uită la matrice se caută întâi pe sine. */}
                        {mine && (
                          <span className="mt-1 inline-block text-[10px] font-medium text-blue-600 dark:text-blue-400">
                            rolul tău
                          </span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {areas.map((area) => (
                  <PermissionArea
                    key={area}
                    area={area}
                    permissions={permissions.filter((p) => areaOf(p) === area)}
                    roles={roles}
                    currentRole={user?.role}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <p className={cn("mt-3 text-xs", mutedText)}>
          Rolurile sunt fixe: se schimbă printr-un deploy, nu din interfață. Ascunderea unui buton
          în ecran nu este o măsură de securitate — refuzul îl dă serverul.
        </p>
      </QueryBoundary>
    </div>
  );
}

function PermissionArea({
  area,
  permissions,
  roles,
  currentRole,
}: {
  area: string;
  permissions: Permission[];
  roles: Array<{ code: RoleCode; permissions: Permission[] }>;
  currentRole?: RoleCode;
}) {
  return (
    <>
      <tr className="bg-slate-50/80 dark:bg-slate-800/40">
        <th
          scope="colgroup"
          colSpan={roles.length + 1}
          className="px-4 py-1.5 text-left text-[11px] font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400"
        >
          {PERMISSION_AREA_LABEL[area] ?? area}
        </th>
      </tr>
      {permissions.map((permission) => (
        <tr
          key={permission}
          className="border-t border-slate-100 transition-colors hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40"
        >
          <th
            scope="row"
            className="sticky left-0 z-10 bg-white px-4 py-2.5 text-left font-normal text-slate-700 dark:bg-slate-900 dark:text-slate-300"
          >
            {PERMISSION_LABEL[permission]}
            <code className="ml-2 text-xs text-slate-400 dark:text-slate-500">{permission}</code>
          </th>
          {roles.map((role) => {
            const granted = role.permissions.includes(permission);
            return (
              <td
                key={role.code}
                className={cn(
                  "px-3 py-2.5 text-center",
                  role.code === currentRole && "bg-blue-50/70 dark:bg-blue-500/10",
                )}
              >
                {/* Bifa are fundal, absența nu: ochiul caută ce se poate, nu ce nu. */}
                {granted ? (
                  <span
                    className="mx-auto grid h-5 w-5 place-content-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400"
                    title={`${ROLE_LABEL[role.code]} — permis`}
                  >
                    <Check className="h-3 w-3" aria-hidden="true" />
                    <span className="sr-only">permis</span>
                  </span>
                ) : (
                  <span className="text-slate-300 dark:text-slate-700" title="fără drept">
                    <Minus className="mx-auto h-3 w-3" aria-hidden="true" />
                    <span className="sr-only">fără drept</span>
                  </span>
                )}
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}

/* ─── Jurnal audit ─────────────────────────────────────────────────────────── */

/**
 * Culoarea acțiunii, după verb.
 *
 * O sută de rânduri gri, toate la fel: ce s-a șters se citea la fel de repede ca
 * ce s-a citit. Verbul din codul acțiunii — `document.approve`, `user.deactivate`
 * — spune destul cât să separe ce merită o privire de restul.
 */
function actionTone(action: string): Tone {
  const verb = action.split(".").at(-1) ?? action;
  if (/delete|deactivate|reject|disconnect|remove/.test(verb)) return "red";
  if (/approve|create|connect|login/.test(verb)) return "green";
  if (/update|patch|assign|reprocess|password|sync/.test(verb)) return "amber";
  return "slate";
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
        actions={
          data && (
            <span className={pillClass("slate")}>
              <ScrollText className="h-3.5 w-3.5" aria-hidden="true" />
              {data.total} înregistrări
            </span>
          )
        }
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
                <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">Moment</th>
                    <th scope="col" className="px-4 py-3 font-medium">Utilizator</th>
                    <th scope="col" className="px-4 py-3 font-medium">Acțiune</th>
                    <th scope="col" className="px-4 py-3 font-medium">Entitate</th>
                    <th scope="col" className="px-4 py-3 font-medium">Detaliu</th>
                    <th scope="col" className="px-4 py-3 font-medium">IP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {data?.items.map((entry) => (
                    <tr
                      key={entry.id}
                      className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
                    >
                      <td className="px-4 py-2.5 whitespace-nowrap tabular-nums text-slate-500 dark:text-slate-400">
                        {formatDateTime(entry.at)}
                      </td>
                      <td className="px-4 py-2.5 text-slate-700 dark:text-slate-300">
                        {entry.userName}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={pillClass(actionTone(entry.action))}>{entry.action}</span>
                      </td>
                      <td className="px-4 py-2.5 text-slate-600 dark:text-slate-400">
                        {entry.entityType}
                        <span className="ml-1 text-xs text-slate-400 dark:text-slate-500">
                          {entry.entityId}
                        </span>
                      </td>
                      <td className="max-w-64 truncate px-4 py-2.5 text-slate-600 dark:text-slate-400">
                        {entry.detail ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 tabular-nums text-slate-400 dark:text-slate-500">
                        {entry.ip}
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

/* ─── Setări ───────────────────────────────────────────────────────────────── */

/**
 * Setările (§16, §73).
 *
 * Valorile vin de la server, din procesul care chiar rulează. Înainte erau
 * scrise de mână aici — `"local"`, `"0,90"`, `"mock"` — sub un banner care
 * declara că vin din variabile de mediu. Nu veneau: `STORAGE_PROVIDER=s3` în
 * producție nu ar fi schimbat nimic pe ecran.
 *
 * Backendul trimite numele variabilei de mediu, nu o etichetă. Traducerea în
 * română o face harta de mai jos: cine se uită la ecran vede și ce înseamnă, și
 * ce anume are de schimbat.
 */
const SETTING_LABEL: Record<string, string> = {
  CONFIDENCE_AUTO_THRESHOLD: "Prag aprobare automată",
  CONFIDENCE_REVIEW_THRESHOLD: "Prag verificare obligatorie",
  AUTO_APPROVE_ENABLED: "Aprobare fără verificare umană",
  MAX_PROCESSING_ATTEMPTS: "Reîncercări de procesare",
  PROCESSING_STALE_AFTER_MINUTES: "Prag de abandon (minute)",
  STORAGE_PROVIDER: "Provider de stocare",
  MAX_UPLOAD_SIZE_MB: "Dimensiune maximă upload (MB)",
  ALLOWED_MIME_TYPES: "Tipuri de fișier acceptate",
  ARCHIVE_PATTERN: "Structura arhivei",
  OCR_PROVIDER: "Provider OCR",
  AI_PROVIDER: "Provider AI",
  PROMPT_VERSION: "Versiune prompt",
  REFERENCE_PERIOD_STRATEGY: "Regula lunii contabile",
  DEFAULT_TIMEZONE: "Fus orar",
  NOTIFICATIONS_ENABLED: "Trimitere notificări",
  RETENTION_ENABLED: "Ștergere automată",
  TRUSTED_PROXY_COUNT: "Proxy-uri de încredere în față",
  ONEDRIVE: "Integrare OneDrive",
};

const GROUP_META: Record<SettingGroup, { label: string; Icon: LucideIcon; tone: Tone }> = {
  PROCESSING: { label: "Procesare și încredere", Icon: ShieldCheck, tone: "blue" },
  STORAGE: { label: "Stocare", Icon: ScrollText, tone: "purple" },
  EXTRACTION: { label: "OCR / AI", Icon: ShieldCheck, tone: "green" },
  PERIODS: { label: "Perioade contabile", Icon: ScrollText, tone: "amber" },
  NOTIFICATIONS: { label: "Notificări", Icon: ScrollText, tone: "blue" },
  RETENTION: { label: "Retenție", Icon: ScrollText, tone: "slate" },
  SECURITY: { label: "Securitate", Icon: Lock, tone: "red" },
};

/** `true`/`false` nu se citesc bine pe un ecran în română. */
function displayValue(value: string): string {
  if (value === "true") return "activat";
  if (value === "false") return "dezactivat";
  return value;
}

/** Un comutator pornit sau oprit se vede; un text „activat" se citește. */
function valueTone(value: string): Tone | null {
  if (value === "true") return "green";
  if (value === "false") return "slate";
  return null;
}

export function SettingsPage() {
  const canManage = useHasPermission("admin:settings");
  const { data, isLoading, error } = useSettings();

  if (!canManage) return <NoPermissionState permission="admin:settings" />;

  const grouped = SETTING_GROUPS.map((group) => ({
    group,
    items: (data ?? []).filter((entry) => entry.group === group),
  })).filter((section) => section.items.length > 0);

  return (
    <div>
      <PageHeader
        title="Setări"
        description="Configurarea după care rulează serverul chiar acum."
      />

      <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800/60 dark:bg-amber-900/20 dark:text-amber-200">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>
          Valorile vin din variabile de mediu și se schimbă modificând deployment-ul, nu de aici.
          Secretele, adresa bazei de date și căile de pe disc nu sunt publicate niciodată.
        </p>
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {grouped.map((section, index) => {
            const meta = GROUP_META[section.group];
            return (
              <section
                key={section.group}
                className={cn(surface, "rise-in", `rise-delay-${Math.min(index + 1, 4)}`)}
              >
                <div className="flex items-center gap-3 border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
                  <span
                    className={cn(
                      "grid h-9 w-9 shrink-0 place-content-center rounded-xl",
                      iconChip[meta.tone],
                    )}
                  >
                    <meta.Icon className="h-4.5 w-4.5" aria-hidden="true" />
                  </span>
                  <h3 className="text-sm font-semibold tracking-tight text-slate-900 dark:text-slate-100">
                    {meta.label}
                  </h3>
                </div>
                <dl className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
                  {section.items.map((item) => {
                    const tone = valueTone(item.value);
                    return (
                      <div
                        key={item.key}
                        className="flex items-start justify-between gap-3 px-5 py-2.5"
                      >
                        <dt className="text-slate-600 dark:text-slate-400">
                          {SETTING_LABEL[item.key] ?? item.key}
                          <code className="ml-2 text-xs text-slate-400 dark:text-slate-500">
                            {item.key}
                          </code>
                        </dt>
                        <dd className="shrink-0">
                          {tone ? (
                            <span className={pillClass(tone)}>{displayValue(item.value)}</span>
                          ) : (
                            <span className="font-medium tabular-nums text-slate-900 dark:text-slate-100">
                              {item.value}
                            </span>
                          )}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
