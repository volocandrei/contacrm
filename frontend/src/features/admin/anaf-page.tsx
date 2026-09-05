/**
 * e-Factura — preluarea facturilor din SPV-ul ANAF (M11).
 *
 * De la 1 iulie 2024 factura electronică este obligatorie între firme, deci
 * partea covârșitoare a facturilor unui cabinet nu mai vine pe email, ci stă în
 * SPV-ul fiecărui client. Ecranul ăsta le aduce singure, cu **toate trei
 * fișierele**: XML-ul, arhiva ANAF cu sigiliul de acceptare și PDF-ul oficial.
 *
 * Patru lucruri pe care ecranul le spune cinstit, pentru că altfel cineva ar
 * aștepta facturi care nu vin:
 *
 * - **Autorizarea cere certificatul digital**, la propriu, în browser. Nu se
 *   poate face de pe server și nu se poate automatiza. Se spune înainte de
 *   apăsare, nu după ce eșuează.
 * - **Certificatul singur nu deschide nimic.** Fiecare client trebuie să depună
 *   împuternicirea în SPV (formularul 150). Fără ea, ANAF nu întoarce o eroare —
 *   întoarce **gol**, ceea ce e mai rău. Refuzul apare pe rândul clientului.
 * - **Când expiră autorizarea.** ANAF o dă pe un an; reînnoirea cere iar
 *   certificatul. Se anunță din timp, nu se descoperă prin tăcere.
 * - **`test` sau `prod`.** Sunt baze complet separate la ANAF: un token de test
 *   nu vede nimic în producție. Confuzia costă o zi de căutat.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  CircleAlert,
  FileCheck2,
  LoaderCircle,
  Landmark,
  Plus,
  RefreshCw,
  Trash2,
  Unplug,
} from "lucide-react";
import {
  useAddAnafMandate,
  useAnafStatus,
  useClients,
  useConnectAnaf,
  useDisconnectAnaf,
  useRemoveAnafMandate,
  useSyncAnaf,
  useUpdateAnafMandate,
} from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ConnectionCard, Notice } from "@/components/connection-card";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { formatDateTime } from "@/lib/format";
import { buttonDanger, buttonPrimary, buttonSecondary, inputField, scrollX } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { AnafMandate, AnafStatus } from "@/types/domain";

/** Sub atâtea zile rămase, reînnoirea nu mai poate fi lăsată pe săptămâna viitoare. */
const EXPIRY_WARNING_DAYS = 30;

export function AnafPage() {
  const { data, isLoading, error } = useAnafStatus();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="e-Factura"
        description="Facturile electronice, preluate automat din SPV-ul ANAF"
      />
      <ConnectionPanel status={data} />
      {data.connected && <MandatesPanel status={data} />}
      {data.connected && <AddMandatePanel status={data} />}
    </div>
  );
}

/* ─── Conexiunea ───────────────────────────────────────────────────────────── */

function daysUntil(moment: string): number {
  return Math.round((new Date(moment).getTime() - Date.now()) / 86_400_000);
}

function ConnectionPanel({ status }: { status: AnafStatus }) {
  const [params, setParams] = useSearchParams();
  const connect = useConnectAnaf();
  const disconnect = useDisconnectAnaf();
  const sync = useSyncAnaf();
  const [message, setMessage] = useState<string | null>(null);
  const [holder, setHolder] = useState("");

  // ANAF întoarce browserul aici, cu codul în adresă. Îl schimbăm pe tokenuri
  // printr-o cerere obișnuită — cu cookie-ul de sesiune la locul lui — și curățăm
  // adresa imediat: un cod de autorizare nu are ce căuta în istoricul browserului.
  const code = params.get("code");
  const state = params.get("state");

  useEffect(() => {
    if (!code || !state) return;
    setParams({}, { replace: true });
    connect.mutate(
      { code, state, holder: sessionStorage.getItem("anaf-holder") ?? undefined },
      {
        onError: (caught) =>
          setMessage(
            caught instanceof ApiError ? caught.message : "Autorizarea nu a putut fi finalizată.",
          ),
      },
    );
    // Doar la întoarcerea de la ANAF; `connect` se schimbă la fiecare randare.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, state]);

  async function startConnect() {
    setMessage(null);
    // Eticheta certificatului este scrisă înainte de plecare, iar la întoarcere
    // pagina este alta: o ținem cât durează drumul dus-întors, nimic mai mult.
    sessionStorage.setItem("anaf-holder", holder.trim());
    try {
      const { authorizeUrl } = await import("@/api/endpoints").then((m) => m.anaf.authorize());
      window.location.href = authorizeUrl;
    } catch (caught) {
      setMessage(caught instanceof ApiError ? caught.message : "Nu s-a putut porni autorizarea.");
    }
  }

  if (!status.configured || !status.encryptionReady) {
    return (
      <ConnectionCard
        Icon={Landmark}
        state="unconfigured"
        title="Conexiunea cu ANAF"
        meta="Butonul de autorizare lipsește pentru că ar eșua oricum."
      >
        <Notice tone="amber">
          <strong className="block">Integrarea nu este configurată pe server.</strong>
          {!status.configured && <>Lipsesc `ANAF_CLIENT_ID` și `ANAF_CLIENT_SECRET`. </>}
          {!status.encryptionReady && <>Lipsește `DRIVE_TOKEN_KEY`. </>}
          Se pun la deployment — vezi <span className="font-mono">docs/DEPLOY.md</span>.
        </Notice>
      </ConnectionCard>
    );
  }

  const remaining = status.expiresAt ? daysUntil(status.expiresAt) : null;

  return (
    <ConnectionCard
      Icon={Landmark}
      state={status.connected ? "connected" : "disconnected"}
      title={
        status.connected
          ? (status.certificateHolder ?? "Certificat digital")
          : "SPV neconectat"
      }
      meta={
        status.connected ? (
          <>
            mediul <span className="font-mono">{status.environment}</span> · autorizat{" "}
            {status.connectedAt ? formatDateTime(status.connectedAt) : ""}
            {status.lastSyncAt
              ? ` · ultima sincronizare ${formatDateTime(status.lastSyncAt)}`
              : " · încă nesincronizat"}
          </>
        ) : (
          <>
            Autorizarea se face <strong>de la calculatorul cu tokenul USB în port</strong>: ANAF
            cere certificatul digital calificat înrolat în SPV. După ea, preluarea merge singură
            un an.
          </>
        )
      }
      actions={
        status.connected && (
          <>
            <button
              type="button"
              onClick={() => sync.mutate(undefined)}
              disabled={sync.isPending || status.mandates.length === 0}
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
              <Unplug className="h-4 w-4" aria-hidden="true" />
              Deconectează
            </button>
          </>
        )
      }
    >
      {message && <Notice tone="red">{message}</Notice>}
      {status.connected && status.lastError && <Notice tone="red">{status.lastError}</Notice>}

      {/* Expirarea se anunță din timp: descoperită prin tăcere, înseamnă o lună
          de facturi care pur și simplu nu au venit. */}
      {status.connected && remaining !== null && remaining <= EXPIRY_WARNING_DAYS && (
        <Notice tone="amber">
          Autorizarea expiră în {remaining <= 0 ? "mai puțin de o zi" : `${remaining} zile`}.
          Reînnoirea se face de la calculatorul cu tokenul USB în port — până atunci, facturile
          continuă să vină.
        </Notice>
      )}

      {!status.connected && (
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label
              htmlFor="anaf-holder"
              className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300"
            >
              Al cui este certificatul
            </label>
            <input
              id="anaf-holder"
              value={holder}
              onChange={(event) => setHolder(event.target.value)}
              placeholder="Ex. Ioana Marinescu"
              className={cn(inputField, "w-64")}
            />
          </div>
          <button
            type="button"
            onClick={() => void startConnect()}
            className={cn(buttonPrimary, "h-9")}
          >
            <Landmark className="h-4 w-4" aria-hidden="true" />
            Autorizează la ANAF
          </button>
        </div>
      )}

      {sync.data && (
        <Notice tone="slate">
          {sync.data.ingested === 0
            ? "Nicio factură nouă în SPV."
            : `${sync.data.ingested} facturi aduse, cu tot cu arhiva ANAF și PDF-ul oficial.`}
          {sync.data.failed > 0 && ` ${sync.data.failed} nu au putut fi preluate.`}
          {sync.data.hasMore && " Mai sunt facturi — preluarea continuă în fundal."}
        </Notice>
      )}
    </ConnectionCard>
  );
}

/* ─── Împuternicirile ──────────────────────────────────────────────────────── */

function MandatesPanel({ status }: { status: AnafStatus }) {
  if (status.mandates.length === 0) {
    return (
      <Panel title="Clienți cu împuternicire">
        <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
          Niciun client încă. Adaugă mai jos clienții care ți-au dat împuternicire în SPV.
        </p>
      </Panel>
    );
  }

  return (
    <Panel title={`Clienți cu împuternicire (${status.mandates.length})`} bodyClassName="p-0">
      <div className={scrollX}>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">
                Client
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                CUI
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Facturi
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Ultima sincronizare
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Stare
              </th>
              <th scope="col" className="px-4 py-3 font-medium sr-only">
                Acțiuni
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {status.mandates.map((mandate) => (
              <MandateRow key={mandate.id} mandate={mandate} />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function MandateRow({ mandate }: { mandate: AnafMandate }) {
  const update = useUpdateAnafMandate();
  const remove = useRemoveAnafMandate();

  return (
    <tr className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60">
      <td className="px-4 py-3">
        <span className="flex items-center gap-2 font-medium text-slate-900 dark:text-slate-100">
          <FileCheck2 className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
          {mandate.clientName}
        </span>
        {mandate.lastError && (
          <span
            role="alert"
            className="mt-1 flex items-start gap-1.5 text-xs text-red-600 dark:text-red-400"
          >
            <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {mandate.lastError}
          </span>
        )}
      </td>
      <td className="px-4 py-3 font-mono text-slate-700 dark:text-slate-300">{mandate.taxId}</td>
      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{mandate.invoicesIngested}</td>
      <td className="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400">
        {mandate.lastSyncedAt ? formatDateTime(mandate.lastSyncedAt) : "—"}
      </td>
      <td className="px-4 py-3">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
          <input
            type="checkbox"
            checked={mandate.isActive}
            disabled={update.isPending}
            onChange={(event) =>
              update.mutate({ id: mandate.id, isActive: event.target.checked })
            }
            className="h-4 w-4 rounded border-slate-300 dark:border-slate-600"
          />
          {mandate.isActive ? "Activă" : "Oprită"}
        </label>
      </td>
      <td className="px-4 py-3 text-right">
        <button
          type="button"
          onClick={() => remove.mutate(mandate.id)}
          disabled={remove.isPending}
          aria-label={`Șterge împuternicirea pentru ${mandate.clientName}`}
          className="rounded-md p-2 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-900/20"
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" />
        </button>
      </td>
    </tr>
  );
}

/* ─── Adăugarea unui client ────────────────────────────────────────────────── */

function AddMandatePanel({ status }: { status: AnafStatus }) {
  const { data: clientsPage } = useClients({ pageSize: 200, status: "ACTIVE" });
  const add = useAddAnafMandate();
  const [clientId, setClientId] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const taken = new Set(status.mandates.map((mandate) => mandate.clientId));
  const available = (clientsPage?.items ?? []).filter((client) => !taken.has(client.id));

  function submit() {
    if (!clientId) return;
    setMessage(null);
    add.mutate(clientId, {
      onSuccess: () => setClientId(""),
      onError: (caught) =>
        setMessage(
          caught instanceof ApiError ? caught.message : "Împuternicirea nu a putut fi adăugată.",
        ),
    });
  }

  return (
    <Panel title="Adaugă un client">
      <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">
        Adaugă aici clienții care au depus <strong>împuternicirea în SPV</strong> (formularul 150)
        pentru certificatul cabinetului. Rândul nu creează dreptul — spune doar pentru ce CUI să
        întrebăm. Dacă împuternicirea nu există la ANAF, prima sincronizare o va spune, pe rândul
        clientului.
      </p>

      {message && (
        <p
          role="alert"
          className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300"
        >
          {message}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label
            htmlFor="anaf-client"
            className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300"
          >
            Client
          </label>
          <select
            id="anaf-client"
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
            className="h-9 w-72 rounded-lg border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            <option value="">— alege clientul —</option>
            {available.map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
                {client.taxId ? ` · ${client.taxId}` : " · fără CUI"}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={!clientId || add.isPending}
          className={cn(buttonPrimary, "h-9")}
        >
          {add.isPending ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Plus className="h-4 w-4" aria-hidden="true" />
          )}
          Adaugă împuternicirea
        </button>
      </div>
    </Panel>
  );
}
