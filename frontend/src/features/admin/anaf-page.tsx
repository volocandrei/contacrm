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
  TriangleAlert,
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
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { formatDateTime } from "@/lib/format";
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
      <Panel title="Conexiunea cu ANAF">
        <div className="flex items-start gap-3 rounded-lg bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
          <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">Integrarea nu este configurată pe server.</p>
            <p className="mt-1 text-xs">
              {!status.configured && <>Lipsesc `ANAF_CLIENT_ID` și `ANAF_CLIENT_SECRET`. </>}
              {!status.encryptionReady && <>Lipsește `DRIVE_TOKEN_KEY`. </>}
              Vezi <span className="font-mono">docs/DEPLOY.md</span>.
            </p>
          </div>
        </div>
      </Panel>
    );
  }

  const remaining = status.expiresAt ? daysUntil(status.expiresAt) : null;

  return (
    <Panel title="Conexiunea cu ANAF">
      {message && (
        <p
          role="alert"
          className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300"
        >
          {message}
        </p>
      )}

      {status.connected ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-4">
            <Landmark className="h-8 w-8 shrink-0 text-blue-600" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="font-medium text-gray-900 dark:text-gray-100">
                {status.certificateHolder ?? "Certificat digital"}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                mediul <span className="font-mono">{status.environment}</span> · autorizat{" "}
                {status.connectedAt ? formatDateTime(status.connectedAt) : ""}
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
                disabled={sync.isPending || status.mandates.length === 0}
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
                <Unplug className="h-4 w-4" aria-hidden="true" />
                Deconectează
              </button>
            </div>
          </div>

          {remaining !== null && remaining <= EXPIRY_WARNING_DAYS && (
            <p
              role="alert"
              className="flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200"
            >
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                Autorizarea expiră în {remaining <= 0 ? "mai puțin de o zi" : `${remaining} zile`}.
                Reînnoirea se face de la calculatorul cu tokenul USB în port — până atunci,
                facturile continuă să vină.
              </span>
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-start gap-4">
            <Landmark className="h-8 w-8 shrink-0 text-gray-300" aria-hidden="true" />
            <div className="min-w-0 flex-1 text-sm text-gray-600 dark:text-gray-300">
              <p className="font-medium text-gray-900 dark:text-gray-100">SPV neconectat</p>
              <p className="text-xs">
                Autorizarea se face <strong>de la calculatorul cu tokenul USB în port</strong>:
                ANAF cere certificatul digital calificat înrolat în SPV. După ea, preluarea merge
                singură un an.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label
                htmlFor="anaf-holder"
                className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
              >
                Al cui este certificatul
              </label>
              <input
                id="anaf-holder"
                value={holder}
                onChange={(event) => setHolder(event.target.value)}
                placeholder="Ex. Ioana Marinescu"
                className="h-9 w-64 rounded-lg border border-gray-200 px-3 text-sm dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
              />
            </div>
            <button
              type="button"
              onClick={() => void startConnect()}
              className="flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              <Landmark className="h-4 w-4" aria-hidden="true" />
              Autorizează la ANAF
            </button>
          </div>
        </div>
      )}

      {sync.data && (
        <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700 dark:bg-gray-800/60 dark:text-gray-300">
          {sync.data.ingested === 0
            ? "Nicio factură nouă în SPV."
            : `${sync.data.ingested} facturi aduse, cu tot cu arhiva ANAF și PDF-ul oficial.`}
          {sync.data.failed > 0 && ` ${sync.data.failed} nu au putut fi preluate.`}
          {sync.data.hasMore && " Mai sunt facturi — preluarea continuă în fundal."}
        </p>
      )}
    </Panel>
  );
}

/* ─── Împuternicirile ──────────────────────────────────────────────────────── */

function MandatesPanel({ status }: { status: AnafStatus }) {
  if (status.mandates.length === 0) {
    return (
      <Panel title="Clienți cu împuternicire">
        <p className="py-6 text-center text-sm text-gray-500 dark:text-gray-400">
          Niciun client încă. Adaugă mai jos clienții care ți-au dat împuternicire în SPV.
        </p>
      </Panel>
    );
  }

  return (
    <Panel title={`Clienți cu împuternicire (${status.mandates.length})`} bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
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
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
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
    <tr className="transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/60">
      <td className="px-4 py-3">
        <span className="flex items-center gap-2 font-medium text-gray-900 dark:text-gray-100">
          <FileCheck2 className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
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
      <td className="px-4 py-3 font-mono text-gray-700 dark:text-gray-300">{mandate.taxId}</td>
      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{mandate.invoicesIngested}</td>
      <td className="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">
        {mandate.lastSyncedAt ? formatDateTime(mandate.lastSyncedAt) : "—"}
      </td>
      <td className="px-4 py-3">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
          <input
            type="checkbox"
            checked={mandate.isActive}
            disabled={update.isPending}
            onChange={(event) =>
              update.mutate({ id: mandate.id, isActive: event.target.checked })
            }
            className="h-4 w-4 rounded border-gray-300 dark:border-gray-600"
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
          className="rounded-md p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-900/20"
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
      <p className="mb-3 text-sm text-gray-600 dark:text-gray-300">
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
            className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300"
          >
            Client
          </label>
          <select
            id="anaf-client"
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
            className="h-9 w-72 rounded-lg border border-gray-200 bg-white px-2 text-sm dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
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
          className="flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
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
