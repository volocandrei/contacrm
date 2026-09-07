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
  ScrollText,
  Send,
  TriangleAlert,
  Upload,
  Plug,
  type LucideIcon,
} from "lucide-react";
import { useIntakes } from "@/api/hooks";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { SelectFilter } from "@/components/form-controls";
import { dayLabel, formatDate, formatTime } from "@/lib/format";
import { iconChip, mutedText, pillClass, surface, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { Intake } from "@/types/domain";

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
 * Acum sunt cele două mesaje reale. Textul autoritar stă în backend
 * (`build_request_message` și `app/services/daily_digest.py`), iar
 * `tests/test_contract_messages.py` cade dacă frazele de aici se despart de el.
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
 * Ce pleacă azi din aplicație, și ce nu.
 *
 * **Ce era înainte aici.** Trei „reguli planificate", fiecare cu o pastilă
 * „oprit". Se citeau ca niște reguli care există și doar așteaptă să fie pornite
 * — dar nu exista nici regula, nici comutatorul. Iar panoul de alături scria că
 * lipsește „un provider de email, adică Faza 2", ceea ce nu mai este adevărat de
 * când solicitarea chiar pleacă din aplicație. Un ecran care subestimează ce
 * poate produsul ascunde exact funcția pe care cabinetul o caută.
 *
 * Distincția care contează nu este între „pornit" și „oprit", ci între **ce
 * pleacă la apăsarea unui om** și **ce ar pleca singur**. Prima jumătate există.
 * A doua nu, și nu din lipsă de cod: un mesaj trimis automat, în numele
 * cabinetului, unui client, este o decizie care se ia o dată, explicit, de
 * cabinet — nu de aplicație.
 */
const WHAT_LEAVES: Array<{ what: string; where: string; to: string; tone: Tone }> = [
  {
    what: "Solicitarea de documente, către un client",
    where: "Fișa clientului → Comunicare",
    to: "/crm/clienti",
    tone: "blue",
  },
  {
    what: "Solicitarea către toți clienții cărora le lipsește ceva",
    where: "Documente lipsă → Cere la toți",
    to: "/contabilitate/lipsa",
    tone: "blue",
  },
  {
    what: "Rezumatul zilei, către colegii din cabinet",
    where: "Automat, o dată pe zi, dacă a fost pornit",
    to: "/administrare/setari",
    tone: "green",
  },
];

export function RemindersPage() {
  return (
    <div>
      <PageHeader
        title="Remindere"
        description="Ce pleacă din aplicație și la ce apăsare"
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Ce pleacă azi" className="lg:col-span-2" bodyClassName="p-0">
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {WHAT_LEAVES.map((row) => (
              <li key={row.what} className="flex items-center gap-4 px-5 py-4">
                <span
                  className={cn(
                    "grid h-10 w-10 shrink-0 place-content-center rounded-xl",
                    iconChip[row.tone],
                  )}
                >
                  <Send className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                    {row.what}
                  </p>
                  <Link
                    to={row.to}
                    className={cn("text-xs hover:underline", mutedText)}
                  >
                    {row.where}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Ce nu pleacă singur">
          <div className="space-y-3 text-sm text-slate-600 dark:text-slate-400">
            <p className="flex items-start gap-2">
              <Bell className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <span>
                <strong>Niciun mesaj automat către clienți.</strong> Datele ar ajunge:{" "}
                <Link
                  to="/contabilitate/lipsa"
                  className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  Documente lipsă
                </Link>{" "}
                știe cine n-a trimis și de câte zile.
              </span>
            </p>
            <p className="flex items-start gap-2">
              <ScrollText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <span>
                Ce lipsește nu este codul, ci <strong>decizia</strong>: un mesaj trimis
                automat, în numele cabinetului, unui client, se hotărăște o dată și
                explicit — de cabinet, nu de aplicație.
              </span>
            </p>
            <p className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800/60 dark:bg-amber-900/20 dark:text-amber-200">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                Chiar și ce pleacă la apăsare are nevoie de un server de email
                configurat. Fără el, textul se copiază și se trimite de mână, iar
                rândul rămâne „Pregătit", nu „Trimis".
              </span>
            </p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
