import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Check, CircleCheck, Copy, TriangleAlert } from "lucide-react";
import { useDocumentRequest, useMissingDocuments, usePeriods } from "@/api/hooks";
import { MonthFilter, SelectFilter } from "@/components/form-controls";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { ProgressRing } from "@/components/charts";
import { PeriodStatusBadge } from "@/components/status-badge";
import { PERIOD_STATUS_LABEL } from "@/lib/labels";
import { buttonSecondary, divider, mutedText, pillClass, scrollX } from "@/lib/ui";
import { useFilterParams } from "@/hooks/use-filter-params";
import { currentMonth } from "@/lib/current-month";
import { dayLabel, daysSince, formatDate, formatReferenceMonth } from "@/lib/format";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { cn } from "@/lib/utils";
import { PERIOD_STATUS, type AccountingPeriod } from "@/types/domain";

export function PeriodsPage() {
  const { values, setValue } = useFilterParams({ referenceMonth: currentMonth(), status: "" });
  const { data, isLoading, error } = usePeriods({
    referenceMonth: values.referenceMonth,
    status: values.status,
  });

  return (
    <div>
      <PageHeader
        title="Perioade contabile"
        description="Stadiul colectării documentelor, per client și lună"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <MonthFilter
          label="Lună"
          value={values.referenceMonth}
          onChange={(value) => setValue("referenceMonth", value)}
          className="w-48"
        />
        <SelectFilter
          label="Status"
          allLabel="Toate statusurile"
          value={values.status}
          onChange={(value) => setValue("status", value)}
          options={PERIOD_STATUS.map((status) => ({
            value: status,
            label: PERIOD_STATUS_LABEL[status],
          }))}
          className="w-52"
        />
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data?.map((period, index) => (
            <PeriodCard key={period.id} period={period} index={index} />
          ))}
        </div>
      )}
    </div>
  );
}

export function MissingDocumentsPage() {
  const { values, setValue } = useFilterParams({ referenceMonth: currentMonth(), request: "" });
  const { data, isLoading, error } = useMissingDocuments(values.referenceMonth);
  // Solicitarea deschide un link de trimitere, deci scrie. Cine nu poate scrie
  // vede tot ecranul, fără butonul care i-ar da 403.
  const canRequest = usePermissionCheck()("documents:write");

  // Filtrarea este locală: raportul vine oricum întreg, iar o rută în plus
  // pentru trei stări derivate din câmpuri deja aduse ar fi cost fără câștig.
  const rows = (data ?? []).filter((entry) => {
    if (values.request === "never") return entry.requestedAt === null;
    if (values.request === "silent") {
      return entry.requestedAt !== null && entry.receivedThroughLink === 0;
    }
    return true;
  });

  return (
    <div>
      <PageHeader
        title="Documente lipsă"
        description="Clienți la care checklist-ul perioadei nu este acoperit"
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        {/* Ecranul cere o lună anume: „documente lipsă" nu înseamnă nimic fără ea. */}
        <MonthFilter
          label="Lună"
          value={values.referenceMonth}
          onChange={(value) => setValue("referenceMonth", value)}
          className="w-48"
        />
        {/*
          Ordinea de lucru a unui cabinet care are treizeci de clienți și o
          săptămână: mai întâi cui nu i-am cerut, apoi cine n-a răspuns. Fără
          filtrul ăsta, lista se citește de la capăt de fiecare dată.
        */}
        <SelectFilter
          label="Cerere"
          showLabel
          value={values.request}
          onChange={(value) => setValue("request", value)}
          allLabel="Toate"
          options={[
            { value: "never", label: "Necerute" },
            { value: "silent", label: "Fără răspuns" },
          ]}
          className="w-48"
        />
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : rows.length === 0 ? (
        <Panel>
          <p className="py-6 text-center text-sm text-slate-600 dark:text-slate-400">
            {(data?.length ?? 0) === 0
              ? "Toți clienții au documentele complete pentru luna selectată."
              : values.request === "never"
                ? "Tuturor clienților cu documente lipsă li s-a cerut deja."
                : "Toți clienții cărora li s-a cerut au trimis ceva."}
          </p>
        </Panel>
      ) : (
        <Panel bodyClassName="p-0">
          <div className={scrollX}>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">Client</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="px-4 py-3 font-medium">Documente lipsă</th>
                  <th scope="col" className="px-4 py-3 font-medium">Progres</th>
                  <th scope="col" className="px-4 py-3 font-medium">Cerere</th>
                  <th scope="col" className="px-4 py-3 font-medium sr-only">Solicitare</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map(({ period, missing, requestedAt, receivedThroughLink }) => (
                  <tr key={period.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/60">
                    <td className="px-4 py-3">
                      <Link
                        to={`/crm/clienti/${period.clientId}`}
                        className="font-medium text-slate-900 hover:text-blue-600 hover:underline dark:text-slate-100 dark:hover:text-blue-400"
                      >
                        {period.clientName}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <PeriodStatusBadge status={period.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {missing.map((item) => (
                          <span key={item.documentType} className={pillClass("amber")}>
                            {item.documentTypeLabel} {item.receivedCount}/{item.expectedMinCount}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        {/* Inelul spune cât s-a strâns fără să citești cifrele;
                            cifrele rămân pentru cine vrea exactitatea. */}
                        <ProgressRing
                          value={period.satisfiedCount}
                          total={period.expectedCount}
                          label={`Progres ${period.clientName}`}
                          className="h-9 w-9 shrink-0"
                        />
                        <span className={cn("tabular-nums", mutedText)}>
                          {period.satisfiedCount}/{period.expectedCount}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <RequestState requestedAt={requestedAt} received={receivedThroughLink} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      {canRequest && (
                        <CopyRequestButton
                          clientId={period.clientId}
                          clientName={period.clientName}
                          referenceMonth={period.referenceMonth}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}


/**
 * O lună a unui client.
 *
 * Bara de progres orizontală spunea același lucru, dar ocupa un rând întreg și
 * se citea abia după ce ochiul găsea cifrele de deasupra. Inelul pune procentul
 * **în** el și stă lângă nume: se vede dintr-o privire care client este strâns
 * și care nu, fără să citești nimic.
 */
function PeriodCard({ period, index }: { period: AccountingPeriod; index: number }) {
  const complete = period.expectedCount > 0 && period.satisfiedCount >= period.expectedCount;

  return (
    <Panel
      title={period.clientName}
      action={<PeriodStatusBadge status={period.status} />}
      className={cn("rise-in", RISE_DELAY[index % RISE_DELAY.length])}
    >
      <div className="flex items-start gap-5">
        <ProgressRing
          value={period.satisfiedCount}
          total={period.expectedCount}
          label={`Progres ${period.clientName}`}
          className="h-20 w-20 shrink-0"
        />

        <div className="min-w-0 flex-1">
          <div className="mb-3 flex items-baseline justify-between gap-2 text-sm">
            <span className={mutedText}>{formatReferenceMonth(period.referenceMonth)}</span>
            <span className="font-medium tabular-nums text-slate-900 dark:text-slate-100">
              {period.satisfiedCount}/{period.expectedCount}
            </span>
          </div>

          {period.checklist.length === 0 ? (
            /* Fără așteptări, luna apare mereu completă — pentru că nu i se cere
               nimic. Se spune, cu drumul către locul unde se repară. */
            <p className={cn("text-sm", mutedText)}>
              Nu s-a stabilit ce se așteaptă lunar.{" "}
              <Link
                to={`/crm/clienti/${period.clientId}`}
                className="font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Configurează
              </Link>
            </p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {period.checklist.map((item) => (
                <li key={item.documentType} className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-1.5">
                    {item.isSatisfied ? (
                      <CircleCheck
                        className="h-4 w-4 shrink-0 text-emerald-500"
                        aria-label="complet"
                      />
                    ) : (
                      <TriangleAlert
                        className="h-4 w-4 shrink-0 text-amber-500"
                        aria-label="incomplet"
                      />
                    )}
                    <span className={cn("truncate", mutedText)}>{item.documentTypeLabel}</span>
                  </span>
                  <span
                    className={cn(
                      "shrink-0 tabular-nums",
                      item.isSatisfied ? pillClass("green") : pillClass("amber"),
                    )}
                  >
                    {item.receivedCount}/{item.expectedMinCount}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <Link
        to={`/documente/arhiva?clientId=${period.clientId}&referenceMonth=${period.referenceMonth}`}
        className={cn(
          "mt-4 inline-flex items-center gap-1 border-t pt-3 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400",
          divider,
          "w-full",
        )}
      >
        {complete ? "Vezi documentele lunii" : "Vezi ce a sosit"}
        <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
      </Link>
    </Panel>
  );
}

/** Decalajele de intrare, reluate ciclic peste cardurile listei. */
const RISE_DELAY = ["", "rise-delay-1", "rise-delay-2", "rise-delay-3", "rise-delay-4"];


/** Cât rămâne pe ecran confirmarea că textul a plecat în clipboard. */
const COPIED_FEEDBACK_MS = 2000;

/**
 * Solicitarea, în clipboard.
 *
 * Aplicația știe ce lipsește și până când, dar nu poate **trimite** — asta cere
 * un provider și rămâne în Faza 2. Între „știm" și „clientul află" stătea un om
 * care recitea tabelul și rescria lista de mână, de treizeci de ori pe lună.
 * Textul iese gata scris; trimiterea rămâne a contabilului, din clientul lui de
 * email, cu semnătura lui.
 *
 * **Textul vine de la server.** A fost o vreme compus aici, ceea ce era în
 * regulă cât timp butonul ăsta era singurul care îl cerea. Din momentul în care
 * îl scrie și asistentul, două formulări ar însemna că doi clienți primesc, în
 * aceeași zi, mesaje diferite de la același cabinet.
 */
/**
 * Cererea de documente, gata de trimis — cu drumul pe care sosește răspunsul.
 *
 * **De ce apasă un buton și se întâmplă două lucruri.** Textul spune clientului
 * *ce* lipsește; linkul îi spune *cum* trimite. Separate, a doua parte se pierde:
 * omul primește o listă și rămâne cu scanatul, atașatul și limita de mărime a
 * emailului. Împreună, cererea este completă.
 *
 * Apare doar pentru cine are `documents:write` — deschiderea unui link scrie.
 * Un buton care ar arunca 403 la apăsare este mai rău decât unul care lipsește.
 */
function CopyRequestButton({
  clientId,
  clientName,
  referenceMonth,
}: {
  clientId: string;
  clientName: string;
  referenceMonth: string;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  // Prin mutație, nu direct: deschiderea linkului schimbă chiar rândul de sub
  // buton, iar ecranul trebuie să afle. Vezi `useDocumentRequest`.
  const request = useDocumentRequest();

  async function copy() {
    try {
      const { message, uploadExpiresAt } = await request.mutateAsync({
        clientId,
        referenceMonth,
      });
      await navigator.clipboard.writeText(message);
      setCopied(uploadExpiresAt);
      setFailed(false);
      setTimeout(() => setCopied(null), COPIED_FEEDBACK_MS);
    } catch {
      // Clipboard-ul cere context sigur și, în unele browsere, permisiune; iar
      // textul poate să nu vină deloc. Oricare ar fi motivul, se spune — un
      // buton care pare că a funcționat este mai rău.
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={() => void copy()}
        className={cn(buttonSecondary, "h-8 px-3 text-xs")}
        title={`Deschide un link de trimitere și copiază solicitarea pentru ${clientName}`}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {copied ? "Copiat" : "Copiază solicitarea"}
      </button>
      {copied && (
        <span className="text-xs text-emerald-700 dark:text-emerald-400">
          Cu link de trimitere, valabil până la {formatDate(copied)}
        </span>
      )}
      {failed && (
        <span role="alert" className="text-xs text-red-600 dark:text-red-400">
          Browserul nu a permis copierea.
        </span>
      )}
    </div>
  );
}


/** De la câte zile fără răspuns o cerere devine ceva de urmărit. */
const SILENT_AFTER_DAYS = 3;

/**
 * Ce s-a întâmplat cu cererea pentru rândul ăsta.
 *
 * **De ce este o coloană și nu o insignă discretă.** Un cabinet cere documentele
 * a treizeci de clienți în aceeași săptămână. Fără urmă pe ecran, peste trei zile
 * cere de două ori unuia și îl uită complet pe altul — iar uitatul nu costă timp,
 * costă o lună întârziată.
 *
 * **Ce nu spune.** Nu spune „trimis". Aplicația nu trimite (Faza 2): textul se
 * copiază și pleacă din clientul de email al contabilului, deci tot ce știe
 * sigur este că cererea a fost **pregătită**. „Cerut" ar fi o promisiune pe care
 * nimic din spate nu o acoperă.
 */
function RequestState({ requestedAt, received }: { requestedAt: string | null; received: number }) {
  if (requestedAt === null) {
    return <span className={cn("text-xs", mutedText)}>Necerut</span>;
  }

  if (received > 0) {
    return (
      <span className="text-xs text-emerald-700 dark:text-emerald-400">
        A trimis {received} {received === 1 ? "document" : "documente"}
      </span>
    );
  }

  const days = daysSince(requestedAt);
  return (
    <span className="flex flex-col text-xs">
      <span className="text-slate-700 dark:text-slate-300">Pregătit {dayLabel(requestedAt)}</span>
      {days >= SILENT_AFTER_DAYS && (
        <span className="text-amber-700 dark:text-amber-500">fără răspuns de {days} zile</span>
      )}
    </span>
  );
}
