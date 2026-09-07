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
import { Link, useSearchParams } from "react-router-dom";
import {
  Archive,
  ArrowRight,
  AtSign,
  CircleAlert,
  CircleCheck,
  Cloud,
  CloudOff,
  FileOutput,
  FileSpreadsheet,
  FolderOpen,
  FolderPlus,
  HardDrive,
  Landmark,
  Link2,
  LoaderCircle,
  Mail,
  MessageCircle,
  Plug,
  RefreshCw,
  Trash2,
  Upload,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import {
  useClients,
  useConnectDrive,
  useDisconnectDrive,
  useDriveBrowse,
  useDocumentSources,
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
import { ConnectionCard, Notice } from "@/components/connection-card";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { formatDateTime } from "@/lib/format";
import {
  buttonDanger,
  buttonPrimary,
  buttonSecondary,
  mutedText,
  pillClass,
  scrollX,
  surface,
  iconChip,
  type Tone,
} from "@/lib/ui";
import { cn } from "@/lib/utils";
import type {
  DocumentSourceRow,
  DriveFolder,
  DriveStatus,
  SourceExport,
  SourceState,
} from "@/types/domain";

export function DrivePage() {
  const { data, isLoading, error } = useDriveStatus();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Surse de documente"
        description="Pe unde intră documentele în aplicație — și ce lipsește ca să intre pe fiecare drum"
      />

      {/* Harta întâi, configurarea după: întrebarea „pe unde pot intra
          documentele" se pune înaintea celei despre un anume dosar din OneDrive. */}
      <SourceMap />

      <ConnectionPanel status={data} />
      {data.connected && <FoldersPanel status={data} />}
      {data.connected && <BrowsePanel status={data} />}
      {data.connected && <MailPanel status={data} />}
    </div>
  );
}

/* ─── Harta drumurilor ─────────────────────────────────────────────────────── */

/**
 * Toate drumurile pe care pot intra documentele, fiecare cu cardul lui.
 *
 * **Ce era înainte.** Ecranul arăta doar OneDrive și cutia poștală Microsoft.
 * Restul drumurilor existau — încărcarea manuală, linkul de trimitere,
 * e-Factura — dar fiecare pe alt ecran, iar nicăieri nu scria lista întreagă.
 * Cine nu găsea un drum presupunea că nu există, adică exact concluzia greșită
 * despre un produs care are cinci.
 *
 * **De ce carduri și nu rânduri.** Prima formă a fost o listă: opt rânduri, unul
 * sub altul, cu pastile. Se citea ca un tabel de setări — și un tabel se
 * parcurge de sus în jos, nu se **compară**. Aici întrebarea nu este „ce scrie pe
 * rândul 4", ci „care dintre ele merg și care nu", iar la asta răspunde ochiul,
 * dintr-o privire, dacă fiecare drum are un dreptunghi al lui, o iconiță
 * recunoscută și o culoare.
 *
 * **Starea vine de la server, nu de aici.** Fiecare card se uită la configurarea
 * care rulează chiar acum și la conexiunile din bază. Scrisă în TSX, lista ar fi
 * spus „OneDrive: conectat" pentru că așa scria acolo.
 *
 * **Ce nu există arată altfel, nu doar scrie altceva.** Cardurile acelea au
 * chenar întrerupt și culoare stinsă: forma spune „nu e de aici" înainte să
 * apuce cineva să citească. Un chenar plin cu textul „nu există încă" înăuntru
 * se citește pe jumătate și se ține minte greșit.
 */
const SOURCE_STATE_LABEL: Record<SourceState, string> = {
  LIVE: "merge acum",
  NEEDS_SETUP: "de configurat",
  PLANNED: "nu există încă",
};

const SOURCE_STATE_TONE: Record<SourceState, Tone> = {
  LIVE: "green",
  NEEDS_SETUP: "amber",
  PLANNED: "slate",
};

/**
 * Iconița fiecărui drum. Ține de prezentare, deci stă aici, nu pe server.
 *
 * Sunt alese ca să fie **recunoscute**, nu ca să fie frumoase: norul pentru
 * OneDrive, plicul pentru email, clădirea publică pentru ANAF. Un cabinet caută
 * pe ecran forma pe care o știe din altă parte, nu numele nostru pentru ea.
 */
const SOURCE_ICON: Record<string, LucideIcon> = {
  UPLOAD: Upload,
  PORTAL: Link2,
  ONEDRIVE: Cloud,
  EMAIL_MICROSOFT: Mail,
  EFACTURA: Landmark,
  EMAIL_IMAP: AtSign,
  WHATSAPP: MessageCircle,
  GOOGLE_DRIVE: HardDrive,
  REGISTER_CSV: FileSpreadsheet,
  MONTH_ARCHIVE: Archive,
  FEE_REGISTER: Wallet,
  SAGA: FileOutput,
};

/** Culoarea cardului: a stării, nu a mărcii. Ecranul răspunde la „merge sau nu". */
function sourceTone(state: SourceState): Tone {
  return SOURCE_STATE_TONE[state];
}

function SourceMap() {
  const { data, isLoading, error } = useDocumentSources();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  const working = data.sources.filter((row) => row.state !== "PLANNED");
  const planned = data.sources.filter((row) => row.state === "PLANNED");

  return (
    <div className="space-y-8">
      <section>
        <SectionTitle
          title="Pe unde intră documentele"
          hint="Fiecare drum, cu starea lui de acum și câte documente au venit pe el"
          badge={
            <span className={pillClass(data.live > 0 ? "green" : "amber")}>
              {data.live} {data.live === 1 ? "drum merge acum" : "drumuri merg acum"}
            </span>
          }
        />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {working.map((row, index) => (
            <SourceCard key={row.code} row={row} index={index} />
          ))}
        </div>
      </section>

      <section>
        <SectionTitle
          title="Ce nu există încă"
          hint="Scris pe față, cu ce ar fi nevoie — ca să nu aștepte nimeni documente care nu vin"
        />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {planned.map((row, index) => (
            <SourceCard key={row.code} row={row} index={index} />
          ))}
        </div>
      </section>

      {/* Ieșirile stau pe același ecran, dar despărțite: cabinetul întreabă „ce se
          leagă cu Saga?" în aceeași propoziție cu „de unde iau facturile", iar
          două ecrane l-ar pune să caute de două ori. Amestecate, în schimb, ar
          face pe cineva să caute facturi într-un export. */}
      <section>
        <SectionTitle
          title="Ce iese din aplicație"
          hint="Fișierele pe care le duci mai departe, în Excel sau în programul de contabilitate"
        />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {data.exports.map((item, index) => (
            <ExportCard key={item.code} item={item} index={index} />
          ))}
        </div>
      </section>
    </div>
  );
}

/** Capul unei secțiuni: ce urmează și de ce, fără să ocupe un card întreg. */
function SectionTitle({
  title,
  hint,
  badge,
}: {
  title: string;
  hint: string;
  badge?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <div>
        <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
        <p className={cn("text-xs", mutedText)}>{hint}</p>
      </div>
      {badge}
    </div>
  );
}

/**
 * Un drum, ca dreptunghi de sine stătător.
 *
 * Ordinea în card urmează ordinea întrebărilor: **ce este** (iconiță și nume),
 * **merge sau nu** (pastila), **ce face** (o propoziție), **ce lipsește** (numai
 * când lipsește ceva), **cât a adus** (numărul), **unde se apasă**.
 */
function SourceCard({ row, index }: { row: DocumentSourceRow; index: number }) {
  const Icon = SOURCE_ICON[row.code] ?? Plug;
  const planned = row.state === "PLANNED";
  const tone = sourceTone(row.state);

  return (
    <article
      className={cn(
        "flex flex-col p-5",
        // Chenar întrerupt și culoare stinsă pentru ce nu există: forma spune
        // „nu e de aici" înainte să apuce cineva să citească.
        planned
          ? "rounded-xl border border-dashed border-slate-300 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-900/40"
          : surface,
        "rise-in",
        RISE_DELAY[index % RISE_DELAY.length],
      )}
    >
      <div className="mb-3 flex items-start gap-3">
        <span
          className={cn(
            "grid h-11 w-11 shrink-0 place-content-center rounded-xl",
            planned ? iconChip.slate : iconChip[tone],
          )}
          aria-hidden="true"
        >
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3
            className={cn(
              "truncate text-sm font-semibold",
              planned
                ? "text-slate-600 dark:text-slate-400"
                : "text-slate-900 dark:text-slate-100",
            )}
          >
            {row.title}
          </h3>
          <span className={cn(pillClass(tone), "mt-1")}>{SOURCE_STATE_LABEL[row.state]}</span>
        </div>

        {/* Numărul lipsește cu totul pentru drumurile care nu pot produce niciun
            document: un zero ar arăta ca o integrare stricată, nu ca una
            inexistentă. */}
        {row.documents !== null && (
          <span className="shrink-0 text-right">
            <span className="block text-2xl leading-none font-semibold tabular-nums text-slate-900 dark:text-slate-100">
              {row.documents}
            </span>
            <span className={cn("block text-[11px]", mutedText)}>
              {row.documents === 1 ? "document" : "documente"}
            </span>
          </span>
        )}
      </div>

      <p className={cn("flex-1 text-xs leading-relaxed", mutedText)}>{row.summary}</p>

      {row.detail && (
        <p className="mt-2 text-xs font-medium text-slate-700 dark:text-slate-300">{row.detail}</p>
      )}

      {/* Ce lipsește, nu doar că lipsește: „neconfigurat" fără motiv trimite omul
          să caute exact în partea greșită. */}
      {row.requirement && (
        <p
          className={cn(
            "mt-3 flex items-start gap-1.5 rounded-lg px-2.5 py-2 text-xs",
            planned
              ? "bg-slate-100 text-slate-600 dark:bg-slate-800/60 dark:text-slate-400"
              : "bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-200",
          )}
        >
          {planned ? (
            <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          ) : (
            <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          )}
          {row.requirement}
        </p>
      )}

      {row.path && (
        <Link
          to={row.path}
          className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
        >
          {row.state === "NEEDS_SETUP" ? "Configurează" : "Deschide"}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      )}
    </article>
  );
}

/** Un drum de ieșire. Card mai mic: se citește mai rar decât intrările. */
function ExportCard({ item, index }: { item: SourceExport; index: number }) {
  const Icon = SOURCE_ICON[item.code] ?? FileOutput;
  const planned = item.state === "PLANNED";

  return (
    <article
      className={cn(
        "flex flex-col p-4",
        planned
          ? "rounded-xl border border-dashed border-slate-300 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-900/40"
          : surface,
        "rise-in",
        RISE_DELAY[index % RISE_DELAY.length],
      )}
    >
      <div className="mb-2 flex items-center gap-2.5">
        <span
          className={cn(
            "grid h-9 w-9 shrink-0 place-content-center rounded-lg",
            planned ? iconChip.slate : iconChip.blue,
          )}
          aria-hidden="true"
        >
          <Icon className="h-4 w-4" />
        </span>
        <h3
          className={cn(
            "min-w-0 flex-1 truncate text-sm font-medium",
            planned ? "text-slate-600 dark:text-slate-400" : "text-slate-900 dark:text-slate-100",
          )}
        >
          {item.title}
        </h3>
      </div>
      <p className={cn("flex-1 text-xs leading-relaxed", mutedText)}>{item.summary}</p>
      {item.requirement && (
        <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-slate-100 px-2.5 py-2 text-xs text-slate-600 dark:bg-slate-800/60 dark:text-slate-400">
          <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {item.requirement}
        </p>
      )}
      {item.path && (
        <Link
          to={item.path}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
        >
          Deschide
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      )}
    </article>
  );
}

/** Decalajele de intrare, reluate ciclic peste cardurile unei grile. */
const RISE_DELAY = ["", "rise-delay-1", "rise-delay-2", "rise-delay-3", "rise-delay-4"];

/* ─── Conexiunea Microsoft ─────────────────────────────────────────────────── */

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
      <ConnectionCard
        Icon={CloudOff}
        state="unconfigured"
        title="Cont Microsoft"
        meta="Butonul de conectare lipsește pentru că ar eșua oricum."
      >
        <Notice tone="amber">
          <strong className="block">Integrarea nu este configurată pe server.</strong>
          {!status.configured && <>Lipsesc `MS_CLIENT_ID` și `MS_CLIENT_SECRET`. </>}
          {!status.encryptionReady && <>Lipsește `DRIVE_TOKEN_KEY`. </>}
          Se pun la deployment — vezi <span className="font-mono">docs/DEPLOY.md</span>.
        </Notice>
      </ConnectionCard>
    );
  }

  return (
    <ConnectionCard
      Icon={status.connected ? Cloud : CloudOff}
      state={status.connected ? "connected" : "disconnected"}
      title={status.connected ? (status.accountEmail ?? "Cont Microsoft") : "Niciun cont conectat"}
      meta={
        status.connected ? (
          <>
            {status.accountName ? `${status.accountName} · ` : ""}
            conectat {status.connectedAt ? formatDateTime(status.connectedAt) : ""}
            {status.lastSyncAt
              ? ` · ultima sincronizare ${formatDateTime(status.lastSyncAt)}`
              : " · încă nesincronizat"}
          </>
        ) : (
          <>
            Se cere acces <strong>doar la citire</strong>: nimic nu se modifică în dosarele
            clienților.
          </>
        )
      }
      actions={
        status.connected ? (
          <>
            <button
              type="button"
              onClick={() => sync.mutate(undefined)}
              disabled={
                sync.isPending ||
                (status.folders.length === 0 && status.mailFolders.length === 0)
              }
              className={cn(buttonSecondary, "h-9")}
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
              className={cn(buttonDanger, "h-9")}
            >
              <CloudOff className="h-4 w-4" aria-hidden="true" />
              Deconectează
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => void startConnect()}
            className={cn(buttonPrimary, "h-9")}
          >
            <Cloud className="h-4 w-4" aria-hidden="true" />
            Conectează OneDrive
          </button>
        )
      }
    >
      {message && <Notice tone="red">{message}</Notice>}
      {status.connected && status.lastError && <Notice tone="red">{status.lastError}</Notice>}
      {sync.data && (
        <Notice tone="slate">
          {sync.data.ingested === 0
            ? "Nimic nou în dosarele urmărite."
            : `${sync.data.ingested} documente aduse.`}
          {sync.data.failed > 0 && ` ${sync.data.failed} nu au putut fi preluate.`}
          {sync.data.hasMore && " Mai sunt fișiere — sincronizarea continuă în fundal."}
        </Notice>
      )}
    </ConnectionCard>
  );
}

/* ─── Dosarele urmărite ────────────────────────────────────────────────────── */

function FoldersPanel({ status }: { status: DriveStatus }) {
  if (status.folders.length === 0) {
    return (
      <Panel title="Dosare urmărite">
        <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
          Niciun dosar urmărit încă. Alege mai jos dosarele clienților.
        </p>
      </Panel>
    );
  }

  return (
    <Panel title={`Dosare urmărite (${status.folders.length})`} bodyClassName="p-0">
      <div className={scrollX}>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Dosar</th>
              <th scope="col" className="px-4 py-3 font-medium">Client</th>
              <th scope="col" className="px-4 py-3 font-medium">Documente</th>
              <th scope="col" className="px-4 py-3 font-medium">Ultima sincronizare</th>
              <th scope="col" className="px-4 py-3 font-medium sr-only">Acțiuni</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
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
    <tr className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60">
      <td className="px-4 py-3">
        <span className="flex items-center gap-2 font-medium text-slate-900 dark:text-slate-100">
          <FolderOpen className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
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
            "h-9 w-56 rounded-lg border bg-white px-2 text-sm dark:bg-slate-950 dark:text-slate-100",
            folder.clientId
              ? "border-slate-200 dark:border-slate-700"
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
      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{folder.filesIngested}</td>
      <td className="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400">
        {folder.lastSyncedAt ? formatDateTime(folder.lastSyncedAt) : "—"}
      </td>
      <td className="px-4 py-3 text-right">
        <button
          type="button"
          onClick={() => untrack.mutate(folder.id)}
          disabled={untrack.isPending}
          aria-label={`Nu mai urmări ${folder.path}`}
          className="rounded-md p-2 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-900/20"
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
            {index > 0 && <span className="text-slate-300">/</span>}
            <button
              type="button"
              onClick={() => setTrail(trail.slice(0, index + 1))}
              disabled={index === trail.length - 1}
              className="rounded px-1 text-blue-600 hover:underline disabled:text-slate-600 disabled:no-underline dark:text-blue-400 dark:disabled:text-slate-300"
            >
              {step.name}
            </button>
          </span>
        ))}
      </nav>

      {error ? (
        <ErrorState error={error} />
      ) : isLoading ? (
        <p className="flex items-center gap-2 py-6 text-sm text-slate-500">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          Se citesc dosarele…
        </p>
      ) : (data ?? []).length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
          Niciun subdosar aici.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {(data ?? []).map((item) => (
            <li key={item.itemId} className="flex items-center gap-3 py-2">
              <button
                type="button"
                onClick={() => setTrail([...trail, { id: item.itemId, name: item.name }])}
                className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm text-slate-900 hover:text-blue-600 dark:text-slate-100 dark:hover:text-blue-400"
              >
                <FolderOpen className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
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
                  className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
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
        <ul className="mb-4 divide-y divide-slate-100 dark:divide-slate-800">
          {status.mailFolders.map((folder) => (
            <li key={folder.id} className="flex items-center gap-3 py-2">
              <Mail className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                  {folder.displayName}
                </span>
                <span className="text-xs text-slate-500 dark:text-slate-400">
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
                className="rounded-md p-2 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-900/20"
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
        <p className="flex items-center gap-2 py-4 text-sm text-slate-500">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          Se citesc dosarele…
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {(available ?? []).map((item) => (
            <li key={item.folderId} className="flex items-center gap-3 py-2">
              <Mail className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <span className="min-w-0 flex-1 text-sm text-slate-900 dark:text-slate-100">
                {item.displayName}
                <span className="ml-2 text-xs text-slate-500">{item.totalItems} mesaje</span>
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
                  className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
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
