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
          Aici este <strong>ce am primit</strong>. Trimiterea — email, WhatsApp, remindere — cere un
          provider și rămâne în Faza 2; până atunci ecranul nu pretinde că există.
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

const TEMPLATES: Array<{
  code: string;
  title: string;
  channel: string;
  Icon: LucideIcon;
  tone: Tone;
  preview: string;
}> = [
  {
    code: "DOCUMENTS_RECEIVED",
    title: "Confirmare de primire",
    channel: "Email",
    Icon: Mail,
    tone: "blue",
    preview:
      "Am recepționat și procesat {{count}} documente pentru luna {{month}}. Așteptăm {{missing}}.",
  },
  {
    code: "DOCUMENTS_RECEIVED_SHORT",
    title: "Confirmare scurtă",
    channel: "WhatsApp",
    Icon: MessageCircle,
    tone: "green",
    preview:
      "Am primit {{count}} documente pentru {{month}}. {{auto}} procesate automat, {{review}} necesită verificare.",
  },
  {
    code: "PERIOD_REMINDER",
    title: "Solicitare documente",
    channel: "Email",
    Icon: CalendarClock,
    tone: "amber",
    preview: "Vă rugăm să transmiteți documentele pentru luna {{month}} până la {{deadline}}.",
  },
];

/**
 * Șabloanele și reminderele se administrează abia când backend-ul poate trimite mesaje.
 * Nu afișăm un editor care nu are ce salva.
 */
export function TemplatesPage() {
  return (
    <div>
      <PageHeader
        title="Șabloane de notificare"
        description="Textele trimise clienților. Conținutul devine editabil odată cu backend-ul."
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
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
                <p className={cn("text-xs", mutedText)}>{template.channel}</p>
              </div>
            </div>
            {/* Textul arată ca un mesaj, nu ca un câmp de configurare — cine îl
                aprobă trebuie să vadă ce va citi clientul. */}
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

const REMINDER_RULES: Array<{ when: string; what: string; tone: Tone }> = [
  { when: "−5 zile", what: "Solicitare documente pentru luna în curs", tone: "blue" },
  { when: "Ziua termenului", what: "Ultimul apel înainte de închidere", tone: "amber" },
  { when: "+1 zi", what: "Notificare documente lipsă, cu lista lor", tone: "red" },
];

export function RemindersPage() {
  return (
    <div>
      <PageHeader
        title="Remindere"
        description="Reguli programate de urmărire a documentelor lipsă"
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Regulile planificate" className="lg:col-span-2" bodyClassName="p-0">
          <ol className="divide-y divide-slate-100 dark:divide-slate-800">
            {REMINDER_RULES.map((rule) => (
              <li key={rule.when} className="flex items-center gap-4 px-5 py-4">
                <span
                  className={cn(
                    "grid h-10 w-10 shrink-0 place-content-center rounded-xl",
                    iconChip[rule.tone],
                  )}
                >
                  <Bell className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                    {rule.what}
                  </p>
                  <p className={cn("text-xs", mutedText)}>{rule.when} față de termenul de depunere</p>
                </div>
                <span className={cn("ml-auto shrink-0", pillClass("slate"))}>oprit</span>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel title="Ce lipsește">
          <div className="space-y-3 text-sm text-slate-600 dark:text-slate-400">
            <p className="flex items-start gap-2">
              <ScrollText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <span>
                Datele există deja:{" "}
                <Link
                  to="/contabilitate/lipsa"
                  className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  Documente lipsă
                </Link>{" "}
                spune, pentru fiecare client și fiecare lună, ce anume nu a sosit.
              </span>
            </p>
            <p className="flex items-start gap-2">
              <Send className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <span>
                Lipsește <strong>trimiterea</strong> — un provider de email sau WhatsApp, adică
                Faza 2.
              </span>
            </p>
            <p className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800/60 dark:bg-amber-900/20 dark:text-amber-200">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                Trimiterea automată rămâne oprită până când regulile sunt configurate și validate de
                cabinet. Niciun mesaj nu pleacă fără audit.
              </span>
            </p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
