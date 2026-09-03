import { Link } from "react-router-dom";
import { Bell, Mail, MessageSquare, TriangleAlert } from "lucide-react";
import { useMessages } from "@/api/hooks";
import { SelectFilter } from "@/components/form-controls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { useFilterParams } from "@/hooks/use-filter-params";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function MessagesPage() {
  const { values, setValue } = useFilterParams({ channel: "" });
  const { data, isLoading, error } = useMessages({ channel: values.channel });

  return (
    <div>
      <PageHeader
        title="Mesaje"
        description="Comunicarea cu clienții, agregată din email și WhatsApp"
      />

      <SelectFilter
        label="Canal"
        allLabel="Toate canalele"
        value={values.channel}
        onChange={(value) => setValue("channel", value)}
        options={[
          { value: "EMAIL", label: "Email" },
          { value: "WHATSAPP", label: "WhatsApp" },
        ]}
        className="mb-4 w-48"
      />

      <Panel bodyClassName="p-0">
        {isLoading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} />
        ) : (data?.length ?? 0) === 0 ? (
          <EmptyState title="Niciun mesaj" />
        ) : (
          <ul className="divide-y divide-gray-100 dark:divide-gray-800">
            {data?.map((message) => (
              <li key={message.id} className="flex gap-3 px-5 py-3.5">
                <span
                  className={cn(
                    "mt-0.5 grid h-8 w-8 shrink-0 place-content-center rounded-lg",
                    message.direction === "INBOUND"
                      ? "bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400"
                      : "bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400",
                  )}
                >
                  {message.channel === "WHATSAPP" ? (
                    <MessageSquare className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Mail className="h-4 w-4" aria-hidden="true" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <Link
                      to={`/crm/clienti/${message.clientId}`}
                      className="text-sm font-medium text-gray-900 hover:text-blue-600 hover:underline dark:text-gray-100 dark:hover:text-blue-400"
                    >
                      {message.clientName}
                    </Link>
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      {formatDateTime(message.occurredAt)}
                    </span>
                  </div>
                  {message.subject && (
                    <p className="text-sm text-gray-700 dark:text-gray-300">{message.subject}</p>
                  )}
                  <p className="truncate text-xs text-gray-500 dark:text-gray-400">
                    {message.preview}
                    {message.attachmentCount > 0 && ` · ${message.attachmentCount} atașamente`}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
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
            <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">{template.channel}</p>
            <p className="rounded-lg bg-gray-50 p-3 text-sm text-gray-700 dark:bg-gray-800/60 dark:text-gray-300">
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
          <Bell className="mt-0.5 h-5 w-5 shrink-0 text-gray-400" aria-hidden="true" />
          <div className="text-sm text-gray-600 dark:text-gray-400">
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
