import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Bell,
  CalendarClock,
  Cloud,
  Landmark,
  Link2,
  Mail,
  MessageCircle,
  MessageSquare,
  Send,
  TriangleAlert,
  Upload,
  Plug,
  type LucideIcon,
} from "lucide-react";
import { useIntakes, useReminders, useSendReminders } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { SelectFilter } from "@/components/form-controls";
import { dayLabel, formatDate, formatReferenceMonth, formatTime } from "@/lib/format";
import { buttonPrimary, iconChip, mutedText, pillClass, surface, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import { whatsappHref } from "@/lib/whatsapp";
import type { Intake, ReminderRow, ReminderStatus } from "@/types/domain";

/**
 * Cronologia recepțiilor.
 *
 * Ecranul acesta a cerut o vreme `GET /messages`, o rută care nu a existat
 * niciodată: în modul simulat mergea, în cel real rămânea gol fără să spună
 * nimic. Auditul de producție l-a înlocuit cu o explicație cinstită — că
 * sistemul nu **trimite** încă mesaje.
 *
 * Explicația rămâne adevărată, dar jumătate din cronologie exista deja în date:
 * fiecare atașament de email, fiecare fișier din OneDrive și fiecare factură din
 * SPV lasă o urmă cu expeditorul și momentul. Ecranul arată acum partea care
 * există, și spune limpede care este partea care nu.
 */
export function MessagesPage() {
  const [source, setSource] = useState("");
  const { data, isLoading, error } = useIntakes({
    pageSize: 50,
    ...(source ? { source } : {}),
  });

  const days = groupByDay(data?.items ?? []);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Mesaje"
        description="Ce a sosit de la clienți, de la cine și când"
        actions={
          data && (
            <span className={pillClass("blue")}>
              <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
              {data.total} recepții
            </span>
          )
        }
      />

      {/* Ce nu face aplicația se spune o dată, sus, nu se descoperă prin absență. */}
      <div className="flex items-start gap-3 rounded-xl border border-blue-200/70 bg-blue-50/60 px-4 py-3 text-sm text-blue-900 dark:border-blue-900/50 dark:bg-blue-950/30 dark:text-blue-200">
        <Send className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>
          Aici este <strong>ce am primit</strong>. Ce pleacă din aplicație — solicitarea de
          documente — se trimite din{" "}
          <Link to="/contabilitate/lipsa" className="font-medium underline underline-offset-2">
            Documente lipsă
          </Link>{" "}
          sau din fișa clientului. Aplicația reține <strong>că</strong> a trimis și către cine,
          nu conținutul mesajului.
        </p>
      </div>

      <Panel
        title="Recepții"
        action={
          <SelectFilter label="Sursă" value={source} onChange={setSource} options={SOURCE_OPTIONS} />
        }
        bodyClassName="p-0"
      >
        {isLoading && <LoadingState />}
        {error && <ErrorState error={error} />}
        {data && data.items.length === 0 && (
          <p className={cn("p-6 text-center text-sm", mutedText)}>
            Nimic încă. Documentele sosesc singure după ce se leagă o sursă în{" "}
            <Link
              to="/administrare/surse"
              className="font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              Administrare → Surse documente
            </Link>
            .
          </p>
        )}
        {days.map(({ key, label, items }) => (
          <section key={key}>
            {/* O cronologie fără zile este o listă. Despărțitorul răspunde la
                „azi a venit ceva?" fără să fie citită nicio oră. */}
            <h4 className="sticky top-0 z-10 flex items-center justify-between gap-2 border-y border-slate-200 bg-slate-50/95 px-4 py-1.5 text-xs font-semibold tracking-wide text-slate-600 uppercase backdrop-blur dark:border-slate-800 dark:bg-slate-900/95 dark:text-slate-400">
              {label}
              <span className={cn("font-normal normal-case", mutedText)}>
                {items.length} {items.length === 1 ? "document" : "documente"}
              </span>
            </h4>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {items.map((intake) => (
                <IntakeRow key={intake.id} intake={intake} />
              ))}
            </ul>
          </section>
        ))}
      </Panel>
    </div>
  );
}

const SOURCE_OPTIONS = [
  { value: "EMAIL", label: "Email" },
  { value: "ONEDRIVE", label: "OneDrive" },
  { value: "EFACTURA", label: "e-Factura" },
  { value: "PORTAL", label: "Trimis de client" },
  { value: "WHATSAPP", label: "WhatsApp" },
];

/**
 * Sursa, cu iconiță și ton.
 *
 * Cinci etichete gri identice cereau citirea cuvântului. O factură din SPV și un
 * atașament de email nu se tratează la fel — se văd diferit înainte de a fi citite.
 */
const SOURCE_META: Record<string, { label: string; Icon: LucideIcon; tone: Tone }> = {
  EMAIL: { label: "Email", Icon: Mail, tone: "blue" },
  ONEDRIVE: { label: "OneDrive", Icon: Cloud, tone: "purple" },
  EFACTURA: { label: "e-Factura", Icon: Landmark, tone: "green" },
  WHATSAPP: { label: "WhatsApp", Icon: MessageCircle, tone: "green" },
  UPLOAD: { label: "Încărcare", Icon: Upload, tone: "slate" },
  API: { label: "API", Icon: Plug, tone: "slate" },
  PORTAL: { label: "Trimis de client", Icon: Link2, tone: "green" },
};

const UNKNOWN_SOURCE = { label: "Sursă necunoscută", Icon: Plug, tone: "slate" as Tone };

/** Ziua în care a sosit, ca text stabil: gruparea și eticheta folosesc același fus. */
function groupByDay(items: Intake[]): Array<{ key: string; label: string; items: Intake[] }> {
  const days = new Map<string, Intake[]>();
  for (const intake of items) {
    const key = formatDate(intake.receivedAt);
    const bucket = days.get(key);
    if (bucket) bucket.push(intake);
    else days.set(key, [intake]);
  }
  return [...days.entries()].map(([key, dayItems]) => ({
    key,
    label: dayLabel(dayItems[0]!.receivedAt),
    items: dayItems,
  }));
}

function IntakeRow({ intake }: { intake: Intake }) {
  const rejected = intake.status === "REJECTED";
  const meta = SOURCE_META[intake.source] ?? UNKNOWN_SOURCE;

  return (
    <li className="flex items-start gap-3 px-4 py-3 text-sm transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40">
      <span
        className={cn("grid h-9 w-9 shrink-0 place-content-center rounded-lg", iconChip[meta.tone])}
        title={meta.label}
      >
        <meta.Icon className="h-4.5 w-4.5" aria-hidden="true" />
        <span className="sr-only">{meta.label}</span>
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          {/* Documentul, când a devenit unul. O recepție respinsă nu are unde duce. */}
          {intake.documentId ? (
            <Link
              to={`/documente/verificare/${intake.documentId}`}
              className="font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              {intake.originalFilename}
            </Link>
          ) : (
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {intake.originalFilename}
            </span>
          )}
          <span className={cn("text-xs tabular-nums", mutedText)}>
            {formatTime(intake.receivedAt)}
          </span>
        </div>
        <p className={cn("text-xs", mutedText)}>de la {intake.sender ?? "expeditor necunoscut"}</p>
        {rejected && intake.rejectionReason && (
          <p className="mt-1 flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
            <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {intake.rejectionReason}
          </p>
        )}
      </div>

      <span className="shrink-0 text-xs">
        {intake.clientId ? (
          <Link
            to={`/crm/clienti/${intake.clientId}`}
            className={cn("hover:underline", mutedText)}
          >
            {intake.clientName}
          </Link>
        ) : (
          // Se spune, nu se ascunde: un document neatribuit așteaptă un om.
          <span className={pillClass("amber")}>neatribuit</span>
        )}
      </span>
    </li>
  );
}

/* ─── Șabloane ─────────────────────────────────────────────────────────────── */

/**
 * Mesajele pe care aplicația chiar le trimite.
 *
 * **Ce era înainte aici.** Trei șabloane inventate — o confirmare de primire, una
 * pe WhatsApp, un reminder — niciunul existent în backend. Ecranul arăta texte pe
 * care aplicația nu le trimisese niciodată, ceea ce este mai rău decât un ecran
 * gol: cine le citea credea că le poate aștepta.
 *
 * Acum sunt cele trei mesaje reale. Textul autoritar stă în backend
 * (`build_request_message` și `app/services/daily_digest.py`), iar
 * `tests/test_contract_messages.py` cade dacă frazele de aici se despart de el.
 *
 * **Al treilea pleacă singur** — reamintirea. De aceea poartă data mesajului
 * anterior: „vă reamintim" o poate scrie oricine despre orice, iar pe cine chiar
 * a trimis documentele îl enervează. Data se poate verifica.
 */
const TEMPLATES: Array<{
  code: string;
  title: string;
  channel: string;
  audience: string;
  Icon: LucideIcon;
  tone: Tone;
  preview: string;
}> = [
  {
    code: "DOCUMENT_REQUEST",
    title: "Solicitare de documente",
    channel: "Email",
    audience: "către client",
    Icon: Mail,
    tone: "blue",
    preview:
      "Pentru evidența contabilă a lunii {{luna}} mai avem nevoie de următoarele documente: " +
      "{{lista}} Vă rugăm să ni le transmiteți până la {{termen}}, " +
      "ca declarațiile să poată fi depuse la timp. " +
      "Cel mai simplu este să le încărcați direct aici, fără cont și fără parolă: {{link}}",
  },
  {
    code: "CLIENT_REMINDER",
    title: "Reamintirea documentelor",
    channel: "Email",
    audience: "către client, automat",
    Icon: Bell,
    tone: "amber",
    preview:
      "V-am scris pe {{data}} despre documentele pentru luna {{luna}}. Deocamdată nu " +
      "ne-au ajuns toate, așa că vă reamintim ce mai așteptăm: {{lista}} " +
      "Vă rugăm să ni le transmiteți până la {{termen}}, ca declarațiile să poată fi " +
      "depuse la timp.",
  },
  {
    code: "DAILY_DIGEST",
    title: "Ce aveți de făcut azi",
    channel: "Email",
    audience: "către colegii din cabinet",
    Icon: CalendarClock,
    tone: "amber",
    preview:
      "Bună dimineața, Pentru {{ziua}}: {{cifre}} — de exemplu 3 declarații nedepuse după " +
      "termen. Rândurile care ar fi zero nu se scriu deloc.",
  },
];

/**
 * Textele nu se editează încă — dar se **văd**, iar cel real se vede compus, cu
 * documentele clientului, din fișa lui: `Comunicare → Pregătește solicitarea`.
 */
export function TemplatesPage() {
  return (
    <div>
      <PageHeader
        title="Șabloane de notificare"
        description="Mesajele pe care aplicația le trimite. Textul îl compune serverul din datele lunii; nu este încă editabil din interfață."
      />

      <div className="mb-4 flex items-start gap-3 rounded-xl border border-blue-200/70 bg-blue-50/60 px-4 py-3 text-sm text-blue-900 dark:border-blue-900/50 dark:bg-blue-950/30 dark:text-blue-200">
        <Send className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>
          Solicitarea se trimite dintr-un clic din{" "}
          <Link to="/contabilitate/lipsa" className="font-medium underline underline-offset-2">
            Documente lipsă
          </Link>{" "}
          sau din fișa clientului, unde textul se vede întâi compus, cu documentele lui.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {TEMPLATES.map((template, index) => (
          <section
            key={template.code}
            className={cn(surface, "flex flex-col p-5", "rise-in", `rise-delay-${index + 1}`)}
          >
            <div className="mb-3 flex items-center gap-3">
              <span
                className={cn(
                  "grid h-10 w-10 shrink-0 place-content-center rounded-xl",
                  iconChip[template.tone],
                )}
              >
                <template.Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {template.title}
                </h3>
                <p className={cn("text-xs", mutedText)}>
                  {template.channel} · {template.audience}
                </p>
              </div>
            </div>
            {/* Textul arată ca un mesaj, nu ca un câmp de configurare — cine îl
                aprobă trebuie să vadă ce va citi destinatarul. */}
            <p className="flex-1 rounded-xl bg-slate-50 p-3 text-sm leading-relaxed text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
              <Placeholders text={template.preview} />
            </p>
            <code className="mt-3 text-[11px] text-slate-400 dark:text-slate-500">
              {template.code}
            </code>
          </section>
        ))}
      </div>
    </div>
  );
}

/** `{{count}}` colorat: se vede care bucată se completează singură. */
function Placeholders({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\{\{\w+\}\})/g).map((part, index) =>
        part.startsWith("{{") ? (
          <span
            key={index}
            className="rounded bg-blue-100 px-1 font-medium text-blue-700 dark:bg-blue-500/20 dark:text-blue-300"
          >
            {part.slice(2, -2)}
          </span>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

/* ─── Remindere ────────────────────────────────────────────────────────────── */

/**
 * Ce pleacă singur către clienți, cui, și **de ce ceilalți nu**.
 *
 * **Ce era înainte aici.** O listă de trei propoziții care explicau că aplicația
 * nu trimite nimic automat, fiindcă decizia nu fusese luată. Decizia s-a luat:
 * cabinetul a hotărât că aplicația are voie să scrie clienților lui. Din clipa
 * aceea ecranul are altă treabă — nu să explice o abținere, ci să arate ce se
 * întâmplă, înainte să se întâmple.
 *
 * **Coloana care contează este „de ce".** Un ecran care arată doar cine primește
 * un mesaj lasă deschisă exact întrebarea pe care o pune contabilul: „bine, dar
 * pe ăsta de ce nu-l anunță?". Fără răspuns scris pe rând, singura cale de a
 * afla ar fi să citească cineva codul — deci nimeni nu află, și fiecare tăcere a
 * aplicației arată ca o scăpare.
 *
 * **Butonul există deși există și ceasul.** Ora planificatorului nu se potrivește
 * cu toată lumea, iar un cabinet care tocmai a terminat de urcat documentele
 * vrea să scrie acum, nu mâine dimineață. Apasă aceleași reguli: plafonul lunar
 * și tăcerea de câteva zile rămân — altfel lista de deasupra ar fi o
 * previzualizare mincinoasă.
 */
const REMINDER_STATUS_LABEL: Record<ReminderStatus, string> = {
  DUE: "pleacă acum",
  WAITING: "așteptăm",
  NOT_ASKED: "necerut",
  ANSWERED: "a trimis ceva",
  MAX_REACHED: "a primit deja tot",
  PAST_DEADLINE: "după termen",
  NO_EMAIL: "fără email",
};

const REMINDER_STATUS_TONE: Record<ReminderStatus, Tone> = {
  DUE: "blue",
  WAITING: "slate",
  NOT_ASKED: "amber",
  ANSWERED: "green",
  MAX_REACHED: "slate",
  PAST_DEADLINE: "red",
  NO_EMAIL: "red",
};

/**
 * Ordinea rândurilor: ce pleacă acum, apoi ce cere un om, apoi restul.
 *
 * Nu alfabetic. Primul rând trebuie să fie cel despre care se ia o decizie azi;
 * clienții care n-au fost întrebați niciodată vin imediat după, fiindcă acolo
 * aplicația chiar nu poate face nimic singură și așteaptă un om.
 */
const REMINDER_ORDER: ReminderStatus[] = [
  "DUE",
  "NOT_ASKED",
  "NO_EMAIL",
  "PAST_DEADLINE",
  "WAITING",
  "ANSWERED",
  "MAX_REACHED",
];

export function RemindersPage() {
  const { data, isLoading, error } = useReminders();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;

  const rows = [...data.rows].sort(
    (a, b) =>
      REMINDER_ORDER.indexOf(a.status) - REMINDER_ORDER.indexOf(b.status) ||
      a.clientName.localeCompare(b.clientName, "ro"),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Remindere"
        description={
          data.referenceMonth
            ? `Cui îi reamintește aplicația documentele lunii ${formatReferenceMonth(data.referenceMonth)} — și de ce celorlalți nu`
            : "Cui îi reamintește aplicația documentele lipsă"
        }
        actions={<SendNow due={data.due} canSend={data.mailConfigured} />}
      />

      <Rules
        silenceDays={data.silenceDays}
        maxPerMonth={data.maxPerMonth}
        deadline={data.deadline}
        automaticEnabled={data.automaticEnabled}
        mailConfigured={data.mailConfigured}
      />

      <Panel bodyClassName="p-0">
        {rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
            Nimeni nu are documente lipsă luna aceasta. Nu e nimic de reamintit.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((row) => (
              <ReminderLine key={row.clientId} row={row} />
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/**
 * Regulile, scrise pe ecran.
 *
 * Vin de la server (`silenceDays`, `maxPerMonth`), nu sunt rescrise aici: două
 * numere diferite pentru aceeași regulă ar însemna că ecranul promite altceva
 * decât face aplicația, iar diferența s-ar vedea abia la client.
 */
function Rules({
  silenceDays,
  maxPerMonth,
  deadline,
  automaticEnabled,
  mailConfigured,
}: {
  silenceDays: number;
  maxPerMonth: number;
  deadline: string | null;
  automaticEnabled: boolean;
  mailConfigured: boolean;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Panel title="Când scrie aplicația singură" className="lg:col-span-2">
        <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-400">
          <li className="flex items-start gap-2">
            <Send className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
            <span>
              Numai cui i s-a <strong>cerut deja</strong> și n-a răspuns de{" "}
              <strong>{silenceDays} zile</strong>. Primul mesaj rămâne al omului: se trimite
              din{" "}
              <Link
                to="/contabilitate/lipsa"
                className="font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Documente lipsă
              </Link>
              .
            </span>
          </li>
          <li className="flex items-start gap-2">
            <Bell className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
            <span>
              Cel mult <strong>{maxPerMonth} pe lună</strong>. Al treilea nu aduce documente
              mai repede, aduce un client care filtrează adresa cabinetului.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
            <span>
              Niciodată după termen
              {deadline ? ` (${formatDate(deadline)})` : ""}: de acolo încolo se sună. Un mesaj
              care spune „ca să depunem la timp" după termen este o minciună.
            </span>
          </li>
        </ul>
      </Panel>

      <Panel title="Starea trimiterii">
        <div className="space-y-3 text-sm">
          <p className="flex items-start gap-2">
            <span className={pillClass(automaticEnabled ? "green" : "slate")}>
              {automaticEnabled ? "pornit" : "oprit"}
            </span>
            <span className={mutedText}>
              Trimiterea automată, o dată pe zi. Butonul „Trimite acum" merge oricum: un om
              care apasă nu face automatizare.
            </span>
          </p>
          {!mailConfigured && (
            <p className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800/60 dark:bg-amber-900/20 dark:text-amber-200">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                Nu este configurat niciun server de email, deci <strong>nu pleacă nimic</strong>.
                Lista de mai jos arată ce ar pleca. Până atunci, textul se copiază din
                „Documente lipsă", iar WhatsApp-ul de pe fiecare rând merge oricum.
              </span>
            </p>
          )}
        </div>
      </Panel>
    </div>
  );
}

/**
 * Un client, starea lui, și cele două drumuri către el.
 *
 * Exportat ca să poată fi randat singur în test: motivul de sub pastilă este
 * chiar partea utilă a ecranului, iar el nu se poate verifica din date — în
 * toate stările rândul arată la fel până la text.
 */
export function ReminderLine({ row }: { row: ReminderRow }) {
  const href = whatsappHref(row.whatsappNumber);
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
      <div className="min-w-0 flex-1">
        <Link
          to={`/crm/clienti/${row.clientId}`}
          className="truncate text-sm font-medium text-slate-900 hover:underline dark:text-slate-100"
        >
          {row.clientName}
        </Link>
        <p className={cn("text-xs", mutedText)}>
          {row.missingCount} {row.missingCount === 1 ? "tip de document" : "tipuri de documente"}
          {row.email ? ` · ${row.email}` : " · fără adresă de email"}
        </p>
      </div>

      <span className="shrink-0 text-right">
        <span className={pillClass(REMINDER_STATUS_TONE[row.status])}>
          {REMINDER_STATUS_LABEL[row.status]}
        </span>
        <span className={cn("mt-0.5 block text-xs", mutedText)}>{reason(row)}</span>
      </span>

      {/* WhatsApp-ul stă pe fiecare rând, nu doar pe cele care primesc un email:
          clientul mic citește emailul a doua zi și WhatsApp-ul în două minute,
          iar pe cel fără adresă de email ăsta este singurul drum rămas. */}
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          title={`Scrie-i pe WhatsApp lui ${row.clientName}`}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-600 transition-colors hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700 dark:border-slate-800 dark:text-slate-400 dark:hover:border-emerald-900 dark:hover:bg-emerald-950/40 dark:hover:text-emerald-300"
        >
          <MessageCircle className="h-3.5 w-3.5" aria-hidden="true" />
          WhatsApp
        </a>
      )}
    </li>
  );
}

/**
 * Rândul mic de sub pastilă: de ce starea este cea care este.
 *
 * Pastila spune *ce*, asta spune *de ce* — și fără al doilea, primul nu se poate
 * verifica. „Așteptăm" fără „i-am scris acum două zile" este o afirmație pe care
 * contabilul o poate doar crede.
 */
function reason(row: ReminderRow): string {
  const silence =
    row.daysSilent === null
      ? ""
      : row.daysSilent === 0
        ? "i-am scris azi"
        : `i-am scris acum ${row.daysSilent} ${row.daysSilent === 1 ? "zi" : "zile"}`;

  switch (row.status) {
    case "NOT_ASKED":
      return "nu i s-a cerut încă nimic";
    case "NO_EMAIL":
      return "adaugă un contact cu email pe fișă";
    case "MAX_REACHED":
      return `${row.sentCount} remindere luna asta`;
    case "PAST_DEADLINE":
      return "termenul a trecut — sună-l";
    case "ANSWERED":
      return "a trimis ceva după ultimul mesaj";
    default:
      return silence;
  }
}

/**
 * Trimite acum, cu numărul pe buton.
 *
 * Numărul nu este decor: un buton fără el se apasă din curiozitate, iar aici
 * apăsarea trimite mesaje unor oameni. Zero de trimis înseamnă niciun buton —
 * nu unul dezactivat, care ar sugera că lipsește o permisiune.
 */
function SendNow({ due, canSend }: { due: number; canSend: boolean }) {
  const send = useSendReminders();
  const [result, setResult] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  if (due === 0) return null;

  function submit() {
    setProblem(null);
    send.mutate(undefined, {
      onSuccess: (report) =>
        setResult(
          report.sent === 0
            ? "Nu a plecat niciun mesaj."
            : `${report.sent} ${report.sent === 1 ? "mesaj trimis" : "mesaje trimise"}` +
              (report.failed > 0 ? `, ${report.failed} nereușite` : ""),
        ),
      onError: (caught) =>
        setProblem(
          caught instanceof ApiError ? caught.message : "Reminderele nu au putut fi trimise.",
        ),
    });
  }

  if (result) {
    return <span className="text-sm text-emerald-700 dark:text-emerald-400">{result}</span>;
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={submit}
        disabled={send.isPending || !canSend}
        title={
          canSend
            ? `Trimite acum ${due} ${due === 1 ? "reminder" : "remindere"}`
            : "Nu este configurat niciun server de email"
        }
        className={cn(buttonPrimary, "h-9 px-4 text-sm disabled:opacity-50")}
      >
        <Send className="h-4 w-4" aria-hidden="true" />
        {send.isPending ? "Se trimit…" : `Trimite acum (${due})`}
      </button>
      {problem && (
        <span role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem}
        </span>
      )}
    </div>
  );
}
