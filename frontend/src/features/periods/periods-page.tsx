import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  CircleCheck,
  Copy,
  LoaderCircle,
  MessageCircle,
  Send,
  TriangleAlert,
} from "lucide-react";
import {
  useDocumentRequest,
  useMissingDocuments,
  usePeriods,
  useSendDocumentRequest,
  useSendRequests,
} from "@/api/hooks";
import type { MissingDocumentsEntry } from "@/api/endpoints";
import { ApiError } from "@/api/types";
import { MonthFilter, SelectFilter } from "@/components/form-controls";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { ProgressRing } from "@/components/charts";
import { PeriodStatusBadge } from "@/components/status-badge";
import { PERIOD_STATUS_LABEL } from "@/lib/labels";
import { buttonPrimary, buttonSecondary, divider, mutedText, pillClass, scrollX } from "@/lib/ui";
import { useFilterParams } from "@/hooks/use-filter-params";
import { currentMonth } from "@/lib/current-month";
import { dayLabel, daysSince, formatDate, formatReferenceMonth } from "@/lib/format";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { whatsappHref } from "@/lib/whatsapp";
import { cn } from "@/lib/utils";
import {
  PERIOD_STATUS,
  type AccountingPeriod,
  type SendRequestsResult,
} from "@/types/domain";

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
        <>
          {canRequest && <SendToAll rows={rows} referenceMonth={values.referenceMonth} />}
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
                {/* Cheia este clientul, nu perioada: clientul care n-a trimis nimic
                    apare aici — este chiar cel căruia îi lipsește tot — dar el nu
                    are perioadă în bază, deci `period.id` este `null`. Toate acele
                    rânduri primeau aceeași cheie absentă, iar React le poate
                    recicla greșit la reordonare. Un rând pe client pe lună, deci
                    `clientId` este unic prin construcție. */}
                {rows.map(({ period, missing, requestedAt, notifiedAt, receivedThroughLink }) => (
                  <tr
                    key={period.clientId}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/60"
                  >
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
                      <RequestState
                        requestedAt={requestedAt}
                        notifiedAt={notifiedAt}
                        received={receivedThroughLink}
                      />
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
        </>
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
 * Aplicația știe ce lipsește și până când. Între „știm" și „clientul află" stătea
 * un om care recitea tabelul și rescria lista de mână, de treizeci de ori pe lună.
 * Textul iese gata scris, iar de la M17 poate și pleca din aplicație — dar numai
 * cu un server de email configurat. Fără el, drumul rămas este copierea, iar
 * trimiterea rămâne a contabilului, din clientul lui de email, cu semnătura lui.
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

      <SendRequestButton
        clientId={clientId}
        clientName={clientName}
        referenceMonth={referenceMonth}
      />

      <WhatsAppRequestButton
        clientId={clientId}
        clientName={clientName}
        referenceMonth={referenceMonth}
      />
    </div>
  );
}

/**
 * Trimite solicitarea din aplicație, în loc s-o copieze.
 *
 * **De ce stă lângă „Copiază", nu în locul lui.** Un cabinet fără SMTP
 * configurat — cazul până când cineva pune setările — trebuie să poată lucra
 * exact ca înainte. Iar unul cu SMTP configurat are zile în care vrea să scrie
 * altceva în mesaj și îl copiază oricum.
 *
 * **Ce se întâmplă când nu este configurat.** Serverul răspunde cu ce lipsește,
 * iar textul acela ajunge pe ecran neschimbat. Nu „a eșuat trimiterea": nimic nu
 * s-a stricat, doar nu i s-a spus aplicației prin ce să trimită.
 */
function SendRequestButton({
  clientId,
  clientName,
  referenceMonth,
}: {
  clientId: string;
  clientName: string;
  referenceMonth: string;
}) {
  const send = useSendDocumentRequest();
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  function submit() {
    setProblem(null);
    send.mutate(
      { clientId, referenceMonth },
      {
        onSuccess: (result) => setSentTo(result.sentTo),
        onError: (caught) =>
          setProblem(
            caught instanceof ApiError ? caught.message : "Solicitarea nu a putut fi trimisă.",
          ),
      },
    );
  }

  if (sentTo) {
    return (
      <span className="text-xs text-emerald-700 dark:text-emerald-400">Trimis la {sentTo}</span>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={submit}
        disabled={send.isPending}
        className={cn(buttonSecondary, "h-8 px-3 text-xs")}
        title={`Trimite solicitarea prin email către ${clientName}`}
      >
        {send.isPending ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <Send className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        Trimite pe email
      </button>
      {problem && (
        <span role="alert" className="max-w-64 text-right text-xs text-red-600 dark:text-red-400">
          {problem}
        </span>
      )}
    </>
  );
}



/**
 * Aceeași solicitare, pe WhatsApp.
 *
 * **De ce merită un al treilea buton.** Clientul mic din România citește emailul
 * a doua zi, dacă îl citește; WhatsApp-ul îl citește în două minute. Aplicația
 * știa numerele de mult — le folosea ca să recunoască expeditorul unui document
 * —, dar ca să-i scrii cuiva trebuia să copiezi textul, să deschizi telefonul și
 * să cauți contactul. Trei pași pentru un mesaj deja scris.
 *
 * **Mesajul nu pleacă singur.** Se deschide conversația cu textul pregătit în
 * câmpul de scris; ce pleacă hotărăște omul. Este exact diferența dintre a-i
 * pune unealta în mână și a scrie în locul lui — iar aplicația nu are cum să
 * afle dacă mesajul a plecat, deci nu scrie nicăieri că s-a trimis.
 *
 * **De ce compune înainte să deschidă.** Textul poartă linkul de trimitere, iar
 * linkul se deschide pe server. Butonul face deci exact ce face „Copiază", plus
 * destinația.
 *
 * **De ce există și varianta cu încă un clic.** Fereastra se deschide după ce
 * răspunde serverul, iar unele browsere blochează asta. Blocat, butonul ar fi
 * părut că nu face nimic — cea mai proastă stare posibilă. Atunci apare un link
 * obișnuit, pe care omul îl apasă el.
 */
function WhatsAppRequestButton({
  clientId,
  clientName,
  referenceMonth,
}: {
  clientId: string;
  clientName: string;
  referenceMonth: string;
}) {
  const request = useDocumentRequest();
  const [fallback, setFallback] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function open() {
    setProblem(null);
    try {
      const { message, whatsappNumber } = await request.mutateAsync({
        clientId,
        referenceMonth,
      });
      const href = whatsappHref(whatsappNumber, message);
      if (!href) {
        // Numărul lipsește sau nu poate fi un număr de telefon. Se spune, în loc
        // să se deschidă o pagină de eroare a WhatsApp-ului.
        setProblem("Clientul nu are un număr de WhatsApp pe fișă.");
        return;
      }
      if (window.open(href, "_blank", "noopener,noreferrer") === null) {
        setFallback(href);
      }
    } catch (caught) {
      setProblem(
        caught instanceof ApiError ? caught.message : "Solicitarea nu a putut fi compusă.",
      );
    }
  }

  if (fallback) {
    return (
      <a
        href={fallback}
        target="_blank"
        rel="noreferrer noopener"
        className={cn(buttonSecondary, "h-8 px-3 text-xs")}
      >
        <MessageCircle className="h-3.5 w-3.5" aria-hidden="true" />
        Deschide WhatsApp
      </a>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void open()}
        disabled={request.isPending}
        className={cn(buttonSecondary, "h-8 px-3 text-xs")}
        title={`Deschide conversația pe WhatsApp cu ${clientName}, cu solicitarea scrisă`}
      >
        {request.isPending ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <MessageCircle className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        Pe WhatsApp
      </button>
      {problem && (
        <span role="alert" className="max-w-64 text-right text-xs text-red-600 dark:text-red-400">
          {problem}
        </span>
      )}
    </>
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
 * **De ce două cuvinte diferite.** „Trimis" apare doar când mesajul chiar a
 * plecat din aplicație — ceea ce serverul știe, fiindcă el l-a trimis. Când a
 * fost doar copiat, scrie „Pregătit": aplicația nu are de unde ști dacă omul
 * l-a și lipit într-un email, iar „Trimis" ar fi acolo o promisiune pe care
 * nimic din spate nu o acoperă.
 */
function RequestState({
  requestedAt,
  notifiedAt,
  received,
}: {
  requestedAt: string | null;
  notifiedAt: string | null;
  received: number;
}) {
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

  const days = daysSince(notifiedAt ?? requestedAt);
  return (
    <span className="flex flex-col text-xs">
      <span className="text-slate-700 dark:text-slate-300">
        {notifiedAt ? `Trimis ${dayLabel(notifiedAt)}` : `Pregătit ${dayLabel(requestedAt)}`}
      </span>
      {days >= SILENT_AFTER_DAYS && (
        <span className="text-amber-700 dark:text-amber-500">fără răspuns de {days} zile</span>
      )}
    </span>
  );
}


/**
 * Cererea către toți clienții din listă, dintr-o acțiune.
 *
 * **De ce există.** Un cabinet cere documentele a treizeci de clienți în aceeași
 * săptămână. Unul câte unul, asta înseamnă treizeci de deschideri de fișă — iar
 * partea grea a muncii nu este procesarea documentelor, ci adunarea lor.
 *
 * **De ce confirmă înainte.** Un email plecat nu se retrage. Ecranul spune
 * exact câți clienți primesc și cum se numesc, iar butonul care trimite este al
 * doilea, nu primul.
 *
 * **Ce trimite serverul.** Exact id-urile de aici, nu „toți cei care se
 * potrivesc". Un „tuturor" interpretat de server ar putea scrie, la o diferență
 * de o secundă între ce s-a afișat și ce s-a apăsat, unui client în plus.
 */
function SendToAll({
  rows,
  referenceMonth,
}: {
  rows: MissingDocumentsEntry[];
  referenceMonth: string;
}) {
  const send = useSendRequests();
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<SendRequestsResult | null>(null);

  // Cei cărora nu li s-a cerut încă. Ceilalți au primit deja un mesaj în luna
  // asta; a-l trimite din nou, în masă, este exact felul în care un cabinet
  // ajunge să fie filtrat ca spam.
  const targets = rows.filter((row) => row.requestedAt === null);

  if (targets.length === 0) return null;

  function submit() {
    setProblem(null);
    send.mutate(
      { referenceMonth, clientIds: targets.map((row) => row.period.clientId) },
      {
        onSuccess: (outcome) => {
          setResult(outcome);
          setConfirming(false);
        },
        onError: (caught) => {
          setProblem(
            caught instanceof ApiError ? caught.message : "Solicitările nu au putut fi trimise.",
          );
          setConfirming(false);
        },
      },
    );
  }

  if (result) {
    return (
      <Panel title="Ce s-a trimis">
        <p className="text-sm text-slate-700 dark:text-slate-300">
          {result.sent.length} {result.sent.length === 1 ? "solicitare trimisă" : "solicitări trimise"}
          {result.failed.length > 0 && `, ${result.failed.length} nu au plecat`}.
        </p>
        {result.failed.length > 0 && (
          /* Care, nu doar câte: „au eșuat 7" fără nume obligă cabinetul să le ia
             pe toate la rând ca să afle. */
          <ul className="mt-2 space-y-1 text-sm text-red-700 dark:text-red-400">
            {result.failed.map((row) => (
              <li key={row.clientId}>
                {rows.find((entry) => entry.period.clientId === row.clientId)?.period.clientName ??
                  row.clientId}
                : {row.message}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    );
  }

  return (
    <div className="mb-4">
      {confirming ? (
        <Panel title={`Trimiți ${targets.length} ${targets.length === 1 ? "solicitare" : "solicitări"}?`}>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Fiecare client primește lista lui de documente lipsă și un link de
            trimitere. Un email plecat nu se retrage.
          </p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {targets.map((row) => (
              <li key={row.period.clientId} className={pillClass("blue")}>
                {row.period.clientName}
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={submit}
              disabled={send.isPending}
              className={cn(buttonPrimary, "h-9")}
            >
              {send.isPending && (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              )}
              Trimite acum
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-sm font-medium text-slate-600 hover:underline dark:text-slate-300"
            >
              Renunță
            </button>
          </div>
        </Panel>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className={cn(buttonPrimary, "h-9")}
        >
          <Send className="h-4 w-4" aria-hidden="true" />
          Trimite solicitarea la {targets.length}{" "}
          {targets.length === 1 ? "client" : "clienți"}
        </button>
      )}
      {problem && (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </div>
  );
}
