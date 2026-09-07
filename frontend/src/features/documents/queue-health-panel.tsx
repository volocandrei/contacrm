/**
 * Starea cozii de procesare (§7, §36).
 *
 * **Ce lipsea.** „De ce nu s-a procesat documentul urcat acum douăzeci de
 * minute?" nu avea unde să primească un răspuns. Documentul stătea în „Primit",
 * ecranul nu arăta nicio eroare — fiindcă nu era niciuna — iar singurul semn că
 * workerul murise era o coadă care creștea și pe care nu o vedea nimeni. Se
 * descoperea a doua zi, la o sută de documente neprocesate.
 *
 * **Ce se arată, și în ce ordine.** Întâi verdictul într-o propoziție, fiindcă
 * la asta se uită cineva care a deschis ecranul îngrijorat. Cifrele după. Lista
 * eșecurilor la urmă, fiindcă un eșec are un vinovat identificabil și se
 * rezolvă pe documentul lui, în timp ce o coadă blocată nu are.
 *
 * **Cifra care contează este de când așteaptă cea mai veche cerere**, nu câte
 * sunt. Treizeci de cereri într-o dimineață aglomerată sunt normale și se
 * golesc singure; una singură care așteaptă de patruzeci de minute nu are nicio
 * explicație bună — ori workerul nu rulează, ori s-a blocat.
 *
 * **Ce nu face.** Nu repornește nimic. Recuperarea are comanda ei
 * (`app.cli recover-processing`), iar reprocesarea unui document se cere de pe
 * documentul acela, unde se vede ce anume se reprocesează. Un buton care ar
 * relua totul este exact felul de acțiune pe care cineva o apasă de două ori.
 */
import { Link } from "react-router-dom";
import { CircleAlert, CircleCheck, Clock, LoaderCircle } from "lucide-react";
import { useProcessingHealth } from "@/api/hooks";
import { Panel } from "@/components/page";
import { formatDateTime } from "@/lib/format";
import { mutedText } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { QueueHealth } from "@/types/domain";

/**
 * De la cât timp de așteptare coada nu mai are o explicație bună.
 *
 * Nu este pragul de la care serverul consideră un job blocat — acela se aplică
 * unuia **pornit**. Aici este vorba de cereri care nu au pornit deloc: dacă cea
 * mai veche așteaptă de un sfert de oră, nimeni nu le ia.
 */
const PATIENCE_SECONDS = 15 * 60;

/**
 * Minutele, în românește.
 *
 * Numeralul cere „de” abia de la 20 în sus: „2 minute”, dar „20 de minute”.
 * Regula pare un moft până când panoul scrie „3 de minute” pe un ecran citit de
 * un contabil — atunci tot mesajul se citește ca scris de o mașină, iar
 * verdictul lui pierde din greutate exact când are nevoie de ea.
 */
function minutes(seconds: number): string {
  if (seconds < 60) return "sub un minut";
  const value = Math.floor(seconds / 60);
  if (value === 1) return "un minut";
  return value < 20 ? `${value} minute` : `${value} de minute`;
}

/**
 * Verdictul, într-o propoziție.
 *
 * Ordinea condițiilor este ordinea gravității: ceva blocat este mai rău decât o
 * coadă lentă, iar o coadă lentă este mai rea decât niște eșecuri — acelea au
 * cel puțin un vinovat scris.
 */
function verdict(health: QueueHealth): { tone: "bad" | "warn" | "good"; text: string } {
  if (health.stuck > 0) {
    return {
      tone: "bad",
      text:
        `${health.stuck} ${health.stuck === 1 ? "cerere a rămas" : "cereri au rămas"} pornite ` +
        "și neterminate. Procesul care le ținea a murit; se reiau cu recover-processing.",
    };
  }
  if (health.waitingSeconds !== null && health.waitingSeconds > PATIENCE_SECONDS) {
    return {
      tone: "bad",
      text: `Cea mai veche cerere așteaptă de ${minutes(health.waitingSeconds)} și nu a pornit. Cel mai probabil, procesarea nu rulează.`,
    };
  }
  if (health.queued > 0 || health.running > 0) {
    return { tone: "good", text: "Procesarea lucrează." };
  }
  if (health.failedRecently > 0) {
    return { tone: "warn", text: "Coada este goală, dar au fost eșecuri recente." };
  }
  return { tone: "good", text: "Coada este goală. Nimic în așteptare." };
}

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
      <div className="text-lg font-semibold text-slate-900 dark:text-slate-100">{value}</div>
      <div className={cn("text-xs", mutedText)}>{label}</div>
    </div>
  );
}

export function QueueHealthPanel() {
  const { data, isLoading, isError } = useProcessingHealth();

  if (isLoading) {
    return (
      <Panel className="mb-4" bodyClassName="p-4">
        <p className={cn("flex items-center gap-2 text-sm", mutedText)}>
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          Se citește starea cozii…
        </p>
      </Panel>
    );
  }

  // Un panou care spune ce nu știe. Ascuns la eroare, ar fi arătat identic cu o
  // coadă sănătoasă — adică exact opusul a ce trebuie să facă.
  if (isError || data === undefined) {
    return (
      <Panel className="mb-4" bodyClassName="p-4">
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          Starea cozii nu s-a putut citi. Asta nu înseamnă că procesarea merge.
        </p>
      </Panel>
    );
  }

  const state = verdict(data);
  const Icon = state.tone === "good" ? CircleCheck : state.tone === "warn" ? Clock : CircleAlert;

  return (
    <Panel className="mb-4" bodyClassName="p-4">
      <p
        className={cn(
          "flex items-start gap-2 text-sm font-medium",
          state.tone === "bad"
            ? "text-red-700 dark:text-red-300"
            : state.tone === "warn"
              ? "text-amber-700 dark:text-amber-300"
              : "text-slate-700 dark:text-slate-200",
        )}
        // Cine deschide ecranul îngrijorat trebuie să audă verdictul, nu cifrele.
        role={state.tone === "bad" ? "alert" : undefined}
      >
        <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        {state.text}
      </p>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Figure label="în așteptare" value={data.queued} />
        <Figure label="în lucru" value={data.running} />
        <Figure label="blocate" value={data.stuck} />
        <Figure label="eșecuri recente" value={data.failedRecently} />
      </div>

      {data.recentFailures.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-sm">
          {data.recentFailures.map((failure) => (
            <li
              key={`${failure.documentId}-${failure.attempt}`}
              className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
            >
              <Link
                to={`/documente/verificare/${failure.documentId}`}
                className="font-medium text-blue-700 hover:underline dark:text-blue-400"
              >
                {failure.originalFilename}
              </Link>
              {failure.clientName !== null && (
                <span className={cn("ml-1 text-xs", mutedText)}>· {failure.clientName}</span>
              )}
              {failure.finishedAt !== null && (
                <span className={cn("ml-1 text-xs", mutedText)}>
                  · {formatDateTime(failure.finishedAt)}
                </span>
              )}
              {/* Motivul scris, nu doar codul: „EXTRACTION_FAILED" nu spune
                  nimănui ce să facă mai departe. */}
              {failure.errorDetail !== null && (
                <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">
                  {failure.errorDetail}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
