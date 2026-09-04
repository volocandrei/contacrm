import { useState } from "react";
import { Link } from "react-router-dom";
import { Bell, MessageSquare, TriangleAlert } from "lucide-react";
import { useIntakes } from "@/api/hooks";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { SelectFilter } from "@/components/form-controls";
import { formatDateTime } from "@/lib/format";
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

  return (
    <div className="space-y-4">
      <PageHeader
        title="Mesaje"
        description="Ce a sosit de la clienți, de la cine și când"
      />

      <Panel>
        <p className="flex items-start gap-3 text-sm text-slate-600 dark:text-slate-400">
          <MessageSquare className="mt-0.5 h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
          <span>
            Aici este <strong>ce am primit</strong>. Trimiterea — email, WhatsApp,
            remindere — cere un provider și rămâne în Faza 2; până atunci ecranul nu
            pretinde că există.
          </span>
        </p>
      </Panel>

      <Panel
        title="Recepții"
        action={
          <SelectFilter
            label="Sursă"
            value={source}
            onChange={setSource}
            options={SOURCE_OPTIONS}
          />
        }
        bodyClassName="p-0"
      >
        {isLoading && <LoadingState />}
        {error && <ErrorState error={error} />}
        {data && data.items.length === 0 && (
          <p className="p-6 text-center text-sm text-slate-500 dark:text-slate-400">
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
        {data && data.items.length > 0 && (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.items.map((intake) => (
              <IntakeRow key={intake.id} intake={intake} />
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

const SOURCE_OPTIONS = [
  { value: "EMAIL", label: "Email" },
  { value: "ONEDRIVE", label: "OneDrive" },
  { value: "EFACTURA", label: "e-Factura" },
  { value: "WHATSAPP", label: "WhatsApp" },
];

const SOURCE_LABEL: Record<string, string> = {
  EMAIL: "Email",
  ONEDRIVE: "OneDrive",
  EFACTURA: "e-Factura",
  WHATSAPP: "WhatsApp",
  UPLOAD: "Încărcare",
  API: "API",
};

function IntakeRow({ intake }: { intake: Intake }) {
  const rejected = intake.status === "REJECTED";

  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3 text-sm">
      <span className="w-36 shrink-0 text-xs text-slate-400 dark:text-slate-500">
        {formatDateTime(intake.receivedAt)}
      </span>
      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
        {SOURCE_LABEL[intake.source] ?? intake.source}
      </span>
      <span className="min-w-0 flex-1">
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
        <span className="ml-2 text-slate-500 dark:text-slate-400">
          de la {intake.sender ?? "expeditor necunoscut"}
        </span>
        {rejected && intake.rejectionReason && (
          <span className="mt-0.5 flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
            <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {intake.rejectionReason}
          </span>
        )}
      </span>
      <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
        {intake.clientId ? (
          <Link
            to={`/crm/clienti/${intake.clientId}`}
            className="hover:underline"
          >
            {intake.clientName}
          </Link>
        ) : (
          // Se spune, nu se ascunde: un document neatribuit așteaptă un om.
          <span className="text-amber-600 dark:text-amber-400">neatribuit</span>
        )}
      </span>
    </li>
  );
}

/**
 * Șabloanele și reminderele se administrează abia când backend-ul poate trimite mesaje.
 * Nu afișăm un editor care nu are ce salva.
 */
export function TemplatesPage() {
  const templates = [
    {
      code: "DOCUMENTS_RECEIVED",
      channel: "Email",
      preview:
        "Am recepționat și procesat {{count}} documente pentru luna {{month}}. Așteptăm {{missing}}.",
    },
    {
      code: "DOCUMENTS_RECEIVED_SHORT",
      channel: "WhatsApp",
      preview:
        "Am primit {{count}} documente pentru {{month}}. {{auto}} procesate automat, {{review}} necesită verificare.",
    },
    {
      code: "PERIOD_REMINDER",
      channel: "Email",
      preview: "Vă rugăm să transmiteți documentele pentru luna {{month}} până la {{deadline}}.",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Șabloane de notificare"
        description="Textele trimise clienților. Conținutul devine editabil odată cu backend-ul."
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {templates.map((template) => (
          <Panel key={template.code} title={template.code}>
            <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">{template.channel}</p>
            <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
              {template.preview}
            </p>
          </Panel>
        ))}
      </div>
    </div>
  );
}

export function RemindersPage() {
  return (
    <div>
      <PageHeader
        title="Remindere"
        description="Reguli programate de urmărire a documentelor lipsă"
      />
      <Panel>
        <div className="flex items-start gap-3">
          <Bell className="mt-0.5 h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
          <div className="text-sm text-slate-600 dark:text-slate-400">
            <p className="mb-2">
              Datele pe care s-ar sprijini reminderele există deja: ecranul „Documente lipsă"
              spune, pentru fiecare client și fiecare lună, ce anume nu a sosit. Ce lipsește este
              trimiterea — un provider de email sau WhatsApp, adică Faza 2. Regulile planificate:
            </p>
            <ul className="ml-5 list-disc space-y-1">
              <li>cu 5 zile înainte de termen — solicitare documente;</li>
              <li>după termen — notificare documente lipsă;</li>
              <li>dezactivabile per client, cu urmă în audit.</li>
            </ul>
          </div>
        </div>
      </Panel>

      <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>
          Trimiterea automată rămâne oprită până când regulile sunt configurate și validate de
          cabinet. Niciun mesaj nu pleacă fără audit.
        </p>
      </div>
    </div>
  );
}
