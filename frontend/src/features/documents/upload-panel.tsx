/**
 * Încărcarea manuală a documentelor — drumul prin care un document intră azi.
 *
 * Fluxul produsului începe cu email și WhatsApp, dar amândouă sunt Faza 2. Până
 * atunci aplicația nu avea **niciun** mod prin care un utilizator să bage un
 * document în sistem: exista ruta `POST /documents/upload`, dar numai un script
 * o putea folosi. Restul aplicației — verificare, aprobare, arhivare — se
 * sprijinea pe date semănate.
 *
 * Trei decizii merită scrise:
 *
 * **Fișierele se trimit unul câte unul.** Un operator selectează un teanc întreg,
 * iar douăzeci de cereri deodată nu ajung mai repede: se bat pe aceeași conexiune
 * și, în spatele unei platforme serverless, se lovesc de limite. Secvențial,
 * fiecare rând își primește răspunsul la rândul lui, iar operatorul vede unde s-a
 * ajuns.
 *
 * **Un eșec nu oprește lotul.** Al treilea fișier respins nu are voie să ascundă
 * că primele două au intrat. Fiecare fișier își poartă propriul rezultat, cu
 * motivul concret venit de la server — „au eșuat 3 fișiere" nu ajută pe nimeni.
 *
 * **Nu verificăm nimic aici.** Tipul și dimensiunea le stabilește serverul: tipul
 * din primii octeți, nu din ce declară browserul (§50), iar limita din
 * configurarea lui. O a doua copie a regulilor în interfață s-ar despărți tăcut
 * de cea adevărată, și atunci ecranul ar refuza fișiere pe care serverul le
 * acceptă — sau, mai rău, invers.
 */
import { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CircleAlert, CircleCheck, Loader2, Upload } from "lucide-react";
import { useClients, useUploadDocument } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { Panel } from "@/components/page";
import { cn } from "@/lib/utils";

type Outcome =
  | { state: "pending" }
  | { state: "done"; documentId: string }
  | { state: "failed"; message: string };

type Row = {
  /** Numele nu este unic într-un lot; cheia de randare trebuie să fie. */
  key: string;
  filename: string;
  outcome: Outcome;
};

let rowCounter = 0;

/** Ce spunem când cererea eșuează fără ca serverul să apuce să răspundă. */
const NETWORK_FAILURE = "Încărcarea nu a ajuns la server. Verifică legătura și încearcă din nou.";

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return NETWORK_FAILURE;
}

export function UploadPanel() {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [dragging, setDragging] = useState(false);
  const [clientId, setClientId] = useState("");
  const upload = useUploadDocument();

  const { data: clientsPage } = useClients({ pageSize: 200, status: "ACTIVE" });

  async function send(files: File[]) {
    if (files.length === 0) return;

    const fresh: Row[] = files.map((file) => {
      rowCounter += 1;
      return { key: `u-${rowCounter}`, filename: file.name, outcome: { state: "pending" } };
    });
    setRows((current) => [...fresh, ...current]);

    function settle(key: string, outcome: Outcome) {
      setRows((current) => current.map((row) => (row.key === key ? { ...row, outcome } : row)));
    }

    for (const [index, file] of files.entries()) {
      const key = fresh[index]!.key;
      try {
        const document = await upload.mutateAsync({
          file,
          clientId: clientId || undefined,
        });
        settle(key, { state: "done", documentId: document.id });
      } catch (error) {
        settle(key, { state: "failed", message: messageFor(error) });
      }
    }
  }

  const busy = rows.some((row) => row.outcome.state === "pending");

  return (
    <Panel className="mb-4" bodyClassName="p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label
          htmlFor={inputId}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void send(Array.from(event.dataTransfer.files));
          }}
          className={cn(
            "flex flex-1 cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed px-4 py-5 text-sm transition-colors",
            dragging
              ? "border-blue-500 bg-blue-50 dark:bg-blue-950/40"
              : "border-gray-300 hover:border-gray-400 dark:border-gray-700 dark:hover:border-gray-600",
          )}
        >
          <Upload className="h-5 w-5 shrink-0 text-gray-400" aria-hidden="true" />
          <span className="text-gray-600 dark:text-gray-300">
            <span className="font-medium text-gray-900 dark:text-gray-100">
              Încarcă documente
            </span>{" "}
            — trage fișierele aici sau apasă pentru a alege
          </span>
        </label>

        <label className="text-sm sm:w-56">
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">
            Client (opțional)
          </span>
          <select
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
            className="h-9 w-full rounded-lg border border-gray-200 bg-white px-2 text-sm dark:border-gray-700 dark:bg-gray-900"
          >
            {/* Gol este alegerea corectă implicit: sistemul identifică singur
                clientul din codul fiscal citit de pe document. Selecția e pentru
                cazul în care operatorul știe deja al cui este teancul. */}
            <option value="">Se identifică automat</option>
            {(clientsPage?.items ?? []).map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <input
        id={inputId}
        ref={inputRef}
        type="file"
        multiple
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          // Câmpul se golește ca același fișier să poată fi ales din nou după o
          // încercare eșuată; altfel `change` nu s-ar mai declanșa.
          event.target.value = "";
          void send(files);
        }}
      />

      {rows.length > 0 && (
        <ul
          className="mt-3 space-y-1.5 text-sm"
          aria-live="polite"
          aria-busy={busy}
          aria-label="Rezultatul încărcărilor"
        >
          {rows.map((row) => (
            <li
              key={row.key}
              className="flex items-start gap-2 rounded-lg bg-gray-50 px-3 py-2 dark:bg-gray-800/60"
            >
              {row.outcome.state === "pending" && (
                <Loader2
                  className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-gray-400"
                  aria-hidden="true"
                />
              )}
              {row.outcome.state === "done" && (
                <CircleCheck
                  className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600"
                  aria-hidden="true"
                />
              )}
              {row.outcome.state === "failed" && (
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden="true" />
              )}

              <span className="min-w-0 flex-1">
                <span className="block truncate text-gray-900 dark:text-gray-100">
                  {row.filename}
                </span>
                {row.outcome.state === "pending" && (
                  <span className="text-xs text-gray-500">Se încarcă…</span>
                )}
                {row.outcome.state === "failed" && (
                  <span role="alert" className="text-xs text-red-600 dark:text-red-400">
                    {row.outcome.message}
                  </span>
                )}
                {row.outcome.state === "done" && (
                  <span className="text-xs text-gray-500">
                    Încărcat — se procesează.{" "}
                    <Link
                      to={`/documente/verificare/${row.outcome.documentId}`}
                      className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                    >
                      Deschide
                    </Link>
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
