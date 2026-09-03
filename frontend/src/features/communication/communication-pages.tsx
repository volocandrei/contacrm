import { Link } from "react-router-dom";
import { Bell, MessageSquare, TriangleAlert } from "lucide-react";
import { PageHeader, Panel } from "@/components/page";

export function MessagesPage() {
  return (
    <div>
      <PageHeader
        title="Mesaje"
        description="Comunicarea cu clienții, agregată din email și WhatsApp"
      />
      <Panel>
        <div className="flex items-start gap-3">
          <MessageSquare className="mt-0.5 h-5 w-5 shrink-0 text-gray-400" aria-hidden="true" />
          <div className="text-sm text-gray-600 dark:text-gray-400">
            <p className="mb-2">
              Cronologia mesajelor cere ca sistemul să și <strong>trimită</strong>, nu doar să
              primească — adică un provider de email sau WhatsApp, Faza 2. Până atunci nu
              inventăm un ecran care nu are ce arăta.
            </p>
            <p className="mb-2">Ce există deja și chiar funcționează:</p>
            <ul className="ml-5 list-disc space-y-1">
              <li>
                atașamentele trimise de clienți pe email devin documente automat, la clientul
                expeditorului — se configurează în{" "}
                <Link
                  to="/administrare/surse"
                  className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  Administrare → Surse documente
                </Link>
                ;
              </li>
              <li>
                ce a sosit, de la cine și când se vede în{" "}
                <Link
                  to="/documente/inbox"
                  className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  Inbox documente
                </Link>
                , cu sursa fiecărui document.
              </li>
            </ul>
          </div>
        </div>
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
