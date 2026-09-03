/**
 * Surse de documente — OneDrive/SharePoint (M9) și cutia poștală (M10).
 *
 * Ecranul rezolvă cererea cabinetului: *„să îmi preia automat ce documente
 * trimit clienții, să nu mai stau eu să le descarc și să le numesc manual"*.
 * Contabilul are deja un dosar per client; aici le leagă o singură dată, iar de
 * atunci documentele intră singure, la clientul potrivit, și ies arhivate cu
 * numele standardizat.
 *
 * Trei lucruri pe care ecranul le spune cinstit:
 *
 * - **Ce lipsește din configurare**, dacă lipsește. Un buton „Conectează" care
 *   eșuează cu o eroare de la Microsoft este mai rău decât unul absent.
 * - **Un dosar fără client** este marcat ca atare, nu ascuns: documentele de
 *   acolo intră, dar ajung la verificare fără client — și e bine să se știe.
 * - **Ultima eroare**, dacă există. Un token expirat trebuie să se vadă: altfel
 *   documentele pur și simplu nu mai vin și nimeni nu află de ce.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  CircleAlert,
  CircleCheck,
  Cloud,
  CloudOff,
  FolderOpen,
  FolderPlus,
  Mail,
  LoaderCircle,
  RefreshCw,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import {
  useClients,
  useConnectDrive,
  useDisconnectDrive,
  useDriveBrowse,
  useDriveStatus,
  useMailFolders,
  useSyncDrive,
  useTrackMailFolder,
  useUntrackMailFolder,
  useTrackFolder,
  useUntrackFolder,
  useUpdateDriveFolder,
} from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DriveFolder, DriveStatus } from "@/types/domain";

export function DrivePage() {
  const { data, isLoading, error } = useDriveStatus();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Surse de documente"
        description="Dosarele din OneDrive și din email din care documentele sunt preluate automat"
      />
      <ConnectionPanel status={data} />
      {data.connected && <FoldersPanel status={data} />}
      {data.connected && <BrowsePanel status={data} />}
      {data.connected && <MailPanel status={data} />}
    </div>
  );
}

/* ─── Conexiunea ───────────────────────────────────────────────────────────── */

function ConnectionPanel({ status }: { status: DriveStatus }) {
  const [params, setParams] = useSearchParams();
  const connect = useConnectDrive();
  const disconnect = useDisconnectDrive();
  const sync = useSyncDrive();
  const [message, setMessage] = useState<string | null>(null);

  // Microsoft întoarce browserul aici, cu codul în adresă. Îl schimbăm pe tokenuri
  // printr-o cerere obișnuită — cu cookie-ul de sesiune la locul lui — și curățăm
  // adresa imediat: un cod de consimțământ nu are ce căuta în istoricul browserului.
  const code = params.get("code");
  const state = params.get("state");

  useEffect(() => {
    if (!code || !state) return;
    setParams({}, { replace: true });
    connect.mutate(
      { code, state },
      {
        onError: (caught) =>
          setMessage(
            caught instanceof ApiError ? caught.message : "Conectarea nu a putut fi finalizată.",
          ),
      },
    );
    // Doar la întoarcerea de la Microsoft; `connect` se schimbă la fiecare randare.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, state]);

  async function startConnect() {
    setMessage(null);
    try {
      const { authorizeUrl } = await import("@/api/endpoints").then((m) => m.drive.authorize());
      window.location.href = authorizeUrl;
    } catch (caught) {
      setMessage(caught instanceof ApiError ? caught.message : "Nu s-a putut porni conectarea.");
    }
  }

  if (!status.configured || !status.encryptionReady) {
    return (
      <Panel title="Cont Microsoft">
        <div className="flex items-start gap-3 rounded-lg bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
          <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">Integrarea nu este configurată pe server.</p>
            <p className="mt-1 text-xs">
              {!status.configured && <>Lipsesc `MS_CLIENT_ID` și `MS_CLIENT_SECRET`. </>}
              {!status.encryptionReady && <>Lipsește `DRIVE_TOKEN_KEY`. </>}
              Vezi <span className="font-mono">docs/DEPLOY.md</span>.
            </p>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Cont Microsoft">
      {message && (
        <p role="alert" className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300">
          {message}
        </p>
      )}

      {status.connected ? (
        <div className="flex flex-wrap items-center gap-4">
          <Cloud className="h-8 w-8 shrink-0 text-blue-600" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-gray-900 dark:text-gray-100">{status.accountEmail}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {status.accountName ? `${status.accountName} · ` : ""}
              conectat {status.connectedAt ? formatDateTime(status.connectedAt) : ""}
              {status.lastSyncAt
                ? ` · ultima sincronizare ${formatDateTime(status.lastSyncAt)}`
                : " · încă nesincronizat"}
            </p>
            {status.lastError && (
              <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
                {status.lastError}
              </p>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => sync.mutate(undefined)}
              disabled={
                sync.isPending ||
                (status.folders.length === 0 && status.mailFolders.length === 0)
              }
              className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
            >
              <RefreshCw
                className={cn("h-4 w-4", sync.isPending && "animate-spin")}
                aria-hidden="true"
              />
              Sincronizează acum
            </button>
            <button
              type="button"
              onClick={() => disconnect.mutate(undefined)}
              disabled={disconnect.isPending}
              className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-gray-700 dark:hover:bg-red-900/20"
            >
              <CloudOff className="h-4 w-4" aria-hidden="true" />
              Deconectează
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-4">
          <CloudOff className="h-8 w-8 shrink-0 text-gray-300" aria-hidden="true" />
          <div className="min-w-0 flex-1 text-sm text-gray-600 dark:text-gray-300">
            <p className="font-medium text-gray-900 dark:text-gray-100">Niciun cont conectat</p>
            <p className="text-xs">
              Conectează contul Microsoft al cabinetului. Se cere acces{" "}
              <strong>doar la citire</strong>: nimic nu se modifică în dosarele clienților.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void startConnect()}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <Cloud className="h-4 w-4" aria-hidden="true" />
            Conectează OneDrive
          </button>
        </div>
      )}

      {sync.data && (
        <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700 dark:bg-gray-800/60 dark:text-gray-300">
          {sync.data.ingested === 0
            ? "Nimic nou în dosarele urmărite."
            : `${sync.data.ingested} documente aduse.`}
          {sync.data.failed > 0 && ` ${sync.data.failed} nu au putut fi preluate.`}
          {sync.data.hasMore && " Mai sunt fișiere — sincronizarea continuă în fundal."}
        </p>
      )}
    </Panel>
  );
}

/* ─── Dosarele urmărite ────────────────────────────────────────────────────── */

function FoldersPanel({ status }: { status: DriveStatus }) {
  if (status.folders.length === 0) {
    return (
      <Panel title="Dosare urmărite">
        <p className="py-6 text-center text-sm text-gray-500 dark:text-gray-400">
          Niciun dosar urmărit încă. Alege mai jos dosarele clienților.
        </p>
      </Panel>
    );
  }

  return (
    <Panel title={`Dosare urmărite (${status.folders.length})`} bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Dosar</th>
              <th scope="col" className="px-4 py-3 font-medium">Client</th>
              <th scope="col" className="px-4 py-3 font-medium">Documente</th>
              <th scope="col" className="px-4 py-3 font-medium">Ultima sincronizare</th>
              <th scope="col" className="px-4 py-3 font-medium sr-only">Acțiuni</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {status.folders.map((folder) => (
              <FolderRow key={folder.id} folder={folder} />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function FolderRow({ folder }: { folder: DriveFolder }) {
  const update = useUpdateDriveFolder();
  const untrack = useUntrackFolder();
  const { data: clientsPage } = useClients({ pageSize: 200, status: "ACTIVE" });

  return (
    <tr className="transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/60">
      <td className="px-4 py-3">
        <span className="flex items-center gap-2 font-medium text-gray-900 dark:text-gray-100">
          <FolderOpen className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
          {folder.path}
        </span>
        {folder.lastError && (
          <span role="alert" className="mt-1 block text-xs text-red-600 dark:text-red-400">
            {folder.lastError}
          </span>
        )}
      </td>
      <td className="px-4 py-3">
        <label className="sr-only" htmlFor={`client-${folder.id}`}>
          Client pentru {folder.path}
        </label>
        <select
          id={`client-${folder.id}`}
          value={folder.clientId ?? ""}
          disabled={update.isPending}
          onChange={(event) =>
            update.mutate({ id: folder.id, clientId: event.target.value || null })
          }
          className={cn(
            "h-9 w-56 rounded-lg border bg-white px-2 text-sm dark:bg-gray-950 dark:text-gray-100",
            folder.clientId
              ? "border-gray-200 dark:border-gray-700"
              : // Fără client, documentele intră dar ajung `UNMATCHED`. Se vede.
                "border-amber-300 dark:border-amber-700",
          )}
        >
          <option value="">— fără client, verificare manuală —</option>
          {(clientsPage?.items ?? []).map((client) => (
            <option key={client.id} value={client.id}>
              {client.name}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{folder.filesIngested}</td>
      <td className="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">
        {folder.lastSyncedAt ? formatDateTime(folder.lastSyncedAt) : "—"}
      </td>
      <td className="px-4 py-3 text-right">
        <button
          type="button"
          onClick={() => untrack.mutate(folder.id)}
          disabled={untrack.isPending}
          aria-label={`Nu mai urmări ${folder.path}`}
          className="rounded-md p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-900/20"
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" />
        </button>
      </td>
    </tr>
  );
}

/* ─── Răsfoirea drive-ului ─────────────────────────────────────────────────── */

function BrowsePanel({ status }: { status: DriveStatus }) {
  // Firimiturile de navigare. Rădăcina este `undefined`, ca în Graph.
  const [trail, setTrail] = useState<Array<{ id: string | undefined; name: string }>>([
    { id: undefined, name: "OneDrive" },
  ]);
  const current = trail[trail.length - 1]!;
  const { data, isLoading, error } = useDriveBrowse(current.id, status.connected);
  const track = useTrackFolder();

  return (
    <Panel title="Alege dosarele clienților">
      <nav aria-label="Cale" className="mb-3 flex flex-wrap items-center gap-1 text-sm">
        {trail.map((step, index) => (
          <span key={`${step.id ?? "root"}-${index}`} className="flex items-center gap-1">
            {index > 0 && <span className="text-gray-300">/</span>}
            <button
              type="button"
              onClick={() => setTrail(trail.slice(0, index + 1))}
              disabled={index === trail.length - 1}
              className="rounded px-1 text-blue-600 hover:underline disabled:text-gray-600 disabled:no-underline dark:text-blue-400 dark:disabled:text-gray-300"
            >
              {step.name}
            </button>
          </span>
        ))}
      </nav>

      {error ? (
        <ErrorState error={error} />
      ) : isLoading ? (
        <p className="flex items-center gap-2 py-6 text-sm text-gray-500">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          Se citesc dosarele…
        </p>
      ) : (data ?? []).length === 0 ? (
        <p className="py-6 text-center text-sm text-gray-500 dark:text-gray-400">
          Niciun subdosar aici.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100 dark:divide-gray-800">
          {(data ?? []).map((item) => (
            <li key={item.itemId} className="flex items-center gap-3 py-2">
              <button
                type="button"
                onClick={() => setTrail([...trail, { id: item.itemId, name: item.name }])}
                className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm text-gray-900 hover:text-blue-600 dark:text-gray-100 dark:hover:text-blue-400"
              >
                <FolderOpen className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
                <span className="truncate">{item.name}</span>
              </button>

              {item.isTracked ? (
                <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  <CircleCheck className="h-4 w-4" aria-hidden="true" />
                  urmărit
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    track.mutate({
                      driveId: item.driveId,
                      itemId: item.itemId,
                      path: item.path,
                    })
                  }
                  disabled={track.isPending}
                  className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
                >
                  <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
                  Urmărește
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {track.error && (
        <p role="alert" className="mt-3 flex items-start gap-2 text-sm text-red-600 dark:text-red-400">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {track.error instanceof ApiError ? track.error.message : "Dosarul nu a putut fi adăugat."}
        </p>
      )}
    </Panel>
  );
}

/* ─── Cutia poștală ────────────────────────────────────────────────────────── */

/**
 * Dosarele de email urmărite.
 *
 * Diferența față de dosarele de drive este spusă pe ecran, nu presupusă: aici nu
 * există coloană „Client", pentru că într-o cutie poștală intră toți clienții
 * deodată. Clientul îl dă **expeditorul**, potrivit pe contactele din CRM — deci
 * ce trebuie ținut la zi sunt adresele de contact, nu o mapare de dosare.
 */
function MailPanel({ status }: { status: DriveStatus }) {
  const { data: available, isLoading, error } = useMailFolders(status.connected);
  const track = useTrackMailFolder();
  const untrack = useUntrackMailFolder();

  return (
    <Panel title="Dosare de email urmărite">
      <p className="mb-4 flex items-start gap-2 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-900 dark:bg-blue-900/20 dark:text-blue-200">
        <Mail className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span>
          Aici clientul îl dă <strong>expeditorul</strong>, nu dosarul: adresa de pe mesaj se
          caută printre contactele clienților. Un expeditor necunoscut nu oprește nimic —
          atașamentul intră și ajunge la verificare neatribuit.
        </span>
      </p>

      {status.mailFolders.length > 0 && (
        <ul className="mb-4 divide-y divide-gray-100 dark:divide-gray-800">
          {status.mailFolders.map((folder) => (
            <li key={folder.id} className="flex items-center gap-3 py-2">
              <Mail className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                  {folder.displayName}
                </span>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {folder.filesIngested} documente ·{" "}
                  {folder.lastSyncedAt
                    ? `ultima sincronizare ${formatDateTime(folder.lastSyncedAt)}`
                    : "încă nesincronizat"}
                </span>
                {folder.lastError && (
                  <span role="alert" className="block text-xs text-red-600 dark:text-red-400">
                    {folder.lastError}
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => untrack.mutate(folder.id)}
                disabled={untrack.isPending}
                aria-label={`Nu mai urmări ${folder.displayName}`}
                className="rounded-md p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-900/20"
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {error ? (
        <ErrorState error={error} />
      ) : isLoading ? (
        <p className="flex items-center gap-2 py-4 text-sm text-gray-500">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          Se citesc dosarele…
        </p>
      ) : (
        <ul className="divide-y divide-gray-100 dark:divide-gray-800">
          {(available ?? []).map((item) => (
            <li key={item.folderId} className="flex items-center gap-3 py-2">
              <Mail className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
              <span className="min-w-0 flex-1 text-sm text-gray-900 dark:text-gray-100">
                {item.displayName}
                <span className="ml-2 text-xs text-gray-500">{item.totalItems} mesaje</span>
              </span>
              {item.isTracked ? (
                <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  <CircleCheck className="h-4 w-4" aria-hidden="true" />
                  urmărit
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    track.mutate({ folderId: item.folderId, displayName: item.displayName })
                  }
                  disabled={track.isPending}
                  className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
                >
                  <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
                  Urmărește
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
