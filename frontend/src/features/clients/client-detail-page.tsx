import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, LoaderCircle, Mail, Pencil, Phone, Plus, StickyNote } from "lucide-react";
import {
  useClient,
  useClientContacts,
  useClientExpectations,
  useClientNotes,
  useClientPeriods,
  useClients,
  useCreateNote,
  useDocumentTypes,
  useDocuments,
  useSaveExpectations,
} from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ErrorState, LoadingState, Panel } from "@/components/page";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { ClientForm, ContactForm } from "@/features/clients/client-form";
import {
  ClientStatusBadge,
  ConfidenceBadge,
  DocumentStatusBadge,
  PeriodStatusBadge,
} from "@/components/status-badge";
import { formatDate, formatDateTime, formatMoney, formatReferenceMonth } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Cât poate avea o notă. Oglindește `MAX_NOTE_LENGTH` din backend. */
const MAX_NOTE_LENGTH = 4000;

const TABS = [
  { id: "general", label: "General" },
  { id: "contacts", label: "Contacte" },
  { id: "accounting", label: "Contabilitate" },
  { id: "documents", label: "Documente" },
  { id: "communication", label: "Comunicare" },
  { id: "notes", label: "Note" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function ClientDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [tab, setTab] = useState<TabId>("general");
  const [editing, setEditing] = useState(false);
  const has = usePermissionCheck();
  const { data: client, isLoading, error } = useClient(id);

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!client) return <ErrorState error={new Error("Client inexistent.")} />;

  return (
    <div>
      <Link
        to="/crm/clienti"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-gray-500 transition-colors hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Toți clienții
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{client.name}</h2>
            <ClientStatusBadge status={client.status} />
          </div>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            {client.taxId} · {client.registrationNumber} · {client.address}
          </p>
        </div>
        {has("clients:write") && !editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            <Pencil className="h-4 w-4" aria-hidden="true" />
            Modifică
          </button>
        )}
      </div>

      {editing && (
        <div className="mb-6">
          <ClientForm
            client={client}
            onDone={() => setEditing(false)}
            onCancel={() => setEditing(false)}
          />
        </div>
      )}

      <div
        role="tablist"
        aria-label="Secțiuni client"
        className="mb-4 flex flex-wrap gap-1 border-b border-gray-200 dark:border-gray-800"
      >
        {TABS.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              tab === item.id
                ? "border-blue-500 text-blue-700 dark:text-blue-400"
                : "border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "general" && <GeneralTab clientId={id} />}
      {tab === "contacts" && <ContactsTab clientId={id} />}
      {tab === "accounting" && <AccountingTab clientId={id} />}
      {tab === "documents" && <DocumentsTab clientId={id} />}
      {tab === "communication" && <CommunicationTab clientId={id} />}
      {tab === "notes" && <NotesTab clientId={id} />}
    </div>
  );
}

function GeneralTab({ clientId }: { clientId: string }) {
  const { data: client } = useClient(clientId);
  const { data: contacts } = useClientContacts(clientId);
  const { data: periods } = useClientPeriods(clientId);

  const primary = contacts?.find((contact) => contact.isPrimary);
  const currentPeriod = periods?.[0];

  if (!client) return null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Panel title="Date generale">
        <dl className="space-y-2 text-sm">
          <Row label="Denumire" value={client.name} />
          <Row label="CUI" value={client.taxId} />
          <Row label="Reg. com." value={client.registrationNumber} />
          <Row label="Adresă" value={client.address} />
          <Row label="Contabil alocat" value={client.assignedAccountantName ?? "—"} />
          <Row label="Client din" value={formatDate(client.createdAt)} />
        </dl>
      </Panel>

      <Panel title="Contact principal">
        {primary ? (
          <dl className="space-y-2 text-sm">
            <Row label="Nume" value={primary.fullName} />
            <Row label="Rol" value={primary.role} />
            <Row label="Email" value={primary.email ?? "—"} />
            <Row label="Telefon" value={primary.phone ?? "—"} />
            <Row label="WhatsApp" value={primary.whatsappNumber ?? "—"} />
          </dl>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">Niciun contact principal definit.</p>
        )}
      </Panel>

      <Panel title="Perioada curentă">
        {currentPeriod ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {formatReferenceMonth(currentPeriod.referenceMonth)}
              </span>
              <PeriodStatusBadge status={currentPeriod.status} />
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              {currentPeriod.satisfiedCount} din {currentPeriod.expectedCount} documente așteptate
            </p>
            <ul className="space-y-1 text-xs">
              {currentPeriod.checklist.map((item) => (
                <li key={item.documentType} className="flex items-center justify-between gap-2">
                  <span className="text-gray-600 dark:text-gray-400">{item.documentTypeLabel}</span>
                  <span
                    className={cn(
                      "font-medium",
                      item.isSatisfied
                        ? "text-green-600 dark:text-green-400"
                        : "text-amber-600 dark:text-amber-400",
                    )}
                  >
                    {item.receivedCount}/{item.expectedMinCount}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">Nicio perioadă deschisă.</p>
        )}
      </Panel>
    </div>
  );
}

function ContactsTab({ clientId }: { clientId: string }) {
  const { data: contacts, isLoading } = useClientContacts(clientId);
  const has = usePermissionCheck();
  // `null` = niciun formular; `""` = unul nou; un id = modificarea aceluia.
  const [editing, setEditing] = useState<string | null>(null);
  if (isLoading) return <LoadingState />;

  const target = editing ? contacts?.find((contact) => contact.id === editing) : undefined;

  return (
    <>
      {editing !== null && (
        <div className="mb-4">
          <ContactForm
            clientId={clientId}
            contact={target}
            onDone={() => setEditing(null)}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}

      {has("clients:write") && editing === null && (
        <button
          type="button"
          onClick={() => setEditing("")}
          className="mb-4 inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          Contact nou
        </button>
      )}

    <Panel bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Nume</th>
              <th scope="col" className="px-4 py-3 font-medium">Rol</th>
              <th scope="col" className="px-4 py-3 font-medium">Email</th>
              <th scope="col" className="px-4 py-3 font-medium">Telefon</th>
              <th scope="col" className="px-4 py-3 font-medium">WhatsApp</th>
              <th scope="col" className="px-4 py-3 font-medium">Stare</th>
              <th scope="col" className="px-4 py-3 font-medium">
                <span className="sr-only">Acțiuni</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {contacts?.map((contact) => (
              <tr key={contact.id}>
                <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                  {contact.fullName}
                  {contact.isPrimary && (
                    <span className="ml-2 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                      principal
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{contact.role}</td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{contact.email ?? "—"}</td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{contact.phone ?? "—"}</td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {contact.whatsappNumber ?? "—"}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {contact.isActive ? "Activ" : "Inactiv"}
                </td>
                <td className="px-4 py-3 text-right">
                  {has("clients:write") && (
                    <button
                      type="button"
                      onClick={() => setEditing(contact.id)}
                      className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                    >
                      Modifică
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </Panel>
    </>
  );
}

function AccountingTab({ clientId }: { clientId: string }) {
  const { data: periods, isLoading } = useClientPeriods(clientId);
  if (isLoading) return <LoadingState />;

  return (
    <div className="space-y-4">
      <ExpectationsPanel clientId={clientId} />
      {periods?.map((period) => (
        <Panel
          key={period.id}
          title={formatReferenceMonth(period.referenceMonth)}
          action={<PeriodStatusBadge status={period.status} />}
        >
          <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">
            {period.receivedCount} documente primite · {period.satisfiedCount}/{period.expectedCount} așteptate
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {period.checklist.map((item) => (
              <div
                key={item.documentType}
                className={cn(
                  "rounded-lg border p-3",
                  item.isSatisfied
                    ? "border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-900/20"
                    : "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-900/20",
                )}
              >
                <p className="text-xs text-gray-600 dark:text-gray-400">{item.documentTypeLabel}</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {item.receivedCount}/{item.expectedMinCount}
                </p>
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </div>
  );
}

function DocumentsTab({ clientId }: { clientId: string }) {
  const { data, isLoading } = useDocuments({ clientId, pageSize: 25 });
  if (isLoading) return <LoadingState />;

  return (
    <Panel bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Dată</th>
              <th scope="col" className="px-4 py-3 font-medium">Tip</th>
              <th scope="col" className="px-4 py-3 font-medium">Furnizor</th>
              <th scope="col" className="px-4 py-3 font-medium">Număr</th>
              <th scope="col" className="px-4 py-3 font-medium">Total</th>
              <th scope="col" className="px-4 py-3 font-medium">Status</th>
              <th scope="col" className="px-4 py-3 font-medium">Încredere</th>
              <th scope="col" className="px-4 py-3 font-medium">Acțiune</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {data?.items.map((doc) => (
              <tr key={doc.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/60">
                <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                  {doc.documentDate ? formatDate(doc.documentDate) : "—"}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {doc.documentTypeLabel ?? "—"}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {doc.supplierName ?? "—"}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {doc.documentNumber ?? "—"}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-gray-900 dark:text-gray-100">
                  {doc.totalAmount ? formatMoney(doc.totalAmount, doc.currency ?? "RON") : "—"}
                </td>
                <td className="px-4 py-3">
                  <DocumentStatusBadge status={doc.status} />
                </td>
                <td className="px-4 py-3">
                  <ConfidenceBadge confidence={doc.confidence} />
                </td>
                <td className="px-4 py-3">
                  <Link
                    to={`/documente/verificare/${doc.id}`}
                    className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                  >
                    Deschide
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function CommunicationTab({ clientId }: { clientId: string }) {
  // Fila arăta o cronologie de mesaje pe care backendul nu o are: în modul real
  // cererea răspundea 404, iar ecranul rămânea gol, fără să spună nimic. Până
  // când sistemul chiar trimite mesaje (Faza 2), arătăm ce știm cu adevărat.
  return (
    <Panel title="Comunicare">
      <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">
        Cronologia mesajelor apare odată cu trimiterea automată (Faza 2). Ce a sosit deja de la
        acest client — pe email sau din dosarul lui de OneDrive — se vede în documentele lui.
      </p>
      <Link
        to={`/documente/inbox?clientId=${clientId}`}
        className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
      >
        Vezi documentele primite
      </Link>
    </Panel>
  );
}

function NotesTab({ clientId }: { clientId: string }) {
  const { data: notes, isLoading } = useClientNotes(clientId);
  if (isLoading) return <LoadingState />;

  return (
    <Panel title="Note interne">
      <NoteComposer clientId={clientId} />
      {notes?.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">Nicio notă internă.</p>
      ) : (
        <ul className="space-y-3">
          {notes?.map((note) => (
            <li key={note.id} className="flex gap-3">
              <StickyNote className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
              <div>
                <p className="text-sm text-gray-800 dark:text-gray-200">{note.body}</p>
                <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
                  {note.authorName} · {formatDateTime(note.createdAt)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/**
 * Scrierea unei notițe.
 *
 * Lista de note exista de la M4, fără nimic care să scrie în ea — un CRM în care
 * nu poți consemna „am vorbit cu clientul, aduce actele vineri". Aici se repară.
 *
 * Nu există modificare și nu există ștergere, deliberat: o notă este o
 * consemnare, iar una care se poate rescrie nu mai este una. Când cineva
 * greșește, scrie următoarea.
 */
function NoteComposer({ clientId }: { clientId: string }) {
  const create = useCreateNote(clientId);
  const can = usePermissionCheck();
  const [body, setBody] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  // Ascunderea este ergonomie; refuzul îl dă serverul, la fiecare cerere (§31).
  if (!can("clients:write")) return null;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setProblem(null);
    create.mutate(body, {
      onSuccess: () => setBody(""),
      onError: (caught) =>
        setProblem(caught instanceof ApiError ? caught.message : "Nota nu a putut fi salvată."),
    });
  }

  return (
    <form onSubmit={submit} className="mb-4">
      <label htmlFor="note-body" className="sr-only">
        Notă internă
      </label>
      <textarea
        id="note-body"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        rows={3}
        maxLength={MAX_NOTE_LENGTH}
        placeholder="Ce s-a discutat, ce a promis clientul, ce rămâne de urmărit…"
        className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
      />
      {problem && (
        <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
      <div className="mt-2 flex items-center justify-end gap-3">
        <span className="text-xs text-gray-400 dark:text-gray-500">
          {body.length}/{MAX_NOTE_LENGTH}
        </span>
        <button
          type="submit"
          disabled={!body.trim() || create.isPending}
          className="flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
        >
          {create.isPending ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <StickyNote className="h-4 w-4" aria-hidden="true" />
          )}
          Adaugă nota
        </button>
      </div>
    </form>
  );
}

/**
 * Ce se așteaptă lunar de la client.
 *
 * Piesa care lipsea din tot lanțul de contabilitate: checklistul fiecărei luni,
 * ecranul „Documente lipsă" și starea perioadei se derivă **din lista asta**,
 * care exista în baza de date de la M6 fără niciun drum prin care s-o scrie
 * cineva. Pe o instalare nouă, consecința era tăcută: fiecare lună apărea
 * completă, pentru că nu i se cerea nimic.
 *
 * Se trimite lista întreagă, nu diferențe: ecranul arată toate tipurile deodată,
 * iar ce trimite înapoi este starea de după.
 */
function ExpectationsPanel({ clientId }: { clientId: string }) {
  const { data: expectations, isLoading } = useClientExpectations(clientId);
  const { data: types } = useDocumentTypes();
  const save = useSaveExpectations(clientId);
  const can = usePermissionCheck();

  const [draft, setDraft] = useState<Record<string, number> | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  if (isLoading) return <LoadingState />;

  const editable = can("periods:manage");
  const current: Record<string, number> =
    draft ??
    Object.fromEntries((expectations ?? []).map((item) => [item.documentTypeCode, item.expectedMinCount]));

  function set(code: string, value: number | null) {
    const next = { ...current };
    if (value === null) delete next[code];
    else next[code] = value;
    setDraft(next);
  }

  function submit() {
    setProblem(null);
    save.mutate(
      Object.entries(current).map(([documentTypeCode, expectedMinCount]) => ({
        documentTypeCode,
        expectedMinCount,
      })),
      {
        onSuccess: () => setDraft(null),
        onError: (caught) =>
          setProblem(
            caught instanceof ApiError ? caught.message : "Așteptările nu au putut fi salvate.",
          ),
      },
    );
  }

  return (
    <Panel title="Ce așteptăm lunar de la client">
      <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">
        După lista asta se construiește checklistul fiecărei luni și raportul
        „Documente lipsă". Un client fără nicio bifă apare mereu complet, pentru că
        nu i se cere nimic.
      </p>

      {problem && (
        <p role="alert" className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300">
          {problem}
        </p>
      )}

      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(types ?? []).map((type) => {
          const expected = current[type.code];
          const checked = expected !== undefined;
          return (
            <li key={type.code} className="flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2 dark:border-gray-800">
              <input
                type="checkbox"
                id={`expect-${type.code}`}
                checked={checked}
                disabled={!editable || save.isPending}
                onChange={(event) => set(type.code, event.target.checked ? 1 : null)}
                className="h-4 w-4 rounded border-gray-300 dark:border-gray-600"
              />
              <label htmlFor={`expect-${type.code}`} className="flex-1 text-sm text-gray-800 dark:text-gray-200">
                {type.label}
              </label>
              {checked && (
                <>
                  <label className="sr-only" htmlFor={`expect-count-${type.code}`}>
                    Câte {type.label} pe lună
                  </label>
                  <input
                    id={`expect-count-${type.code}`}
                    type="number"
                    min={1}
                    max={999}
                    value={expected}
                    disabled={!editable || save.isPending}
                    onChange={(event) => set(type.code, Math.max(1, Number(event.target.value) || 1))}
                    className="h-8 w-16 rounded-md border border-gray-200 px-2 text-sm dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
                  />
                </>
              )}
            </li>
          );
        })}
      </ul>

      {editable && (
        <div className="mt-3 flex items-center justify-end gap-3">
          {draft !== null && (
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="text-sm font-medium text-gray-600 hover:underline dark:text-gray-300"
            >
              Renunță
            </button>
          )}
          <button
            type="button"
            onClick={submit}
            disabled={draft === null || save.isPending}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            {save.isPending && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
            Salvează așteptările
          </button>
        </div>
      )}
    </Panel>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="text-right font-medium text-gray-900 dark:text-gray-100">{value}</dd>
    </div>
  );
}

export function ContactsPage() {
  const { data } = useClients({ pageSize: 200 });
  return (
    <div>
      <h2 className="mb-6 text-2xl font-bold text-gray-900 dark:text-gray-100">Contacte</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data?.items.map((client) => (
          <ClientContactsCard key={client.id} clientId={client.id} clientName={client.name} />
        ))}
      </div>
    </div>
  );
}

function ClientContactsCard({ clientId, clientName }: { clientId: string; clientName: string }) {
  const { data: contacts } = useClientContacts(clientId);
  if (!contacts || contacts.length === 0) return null;

  return (
    <Panel title={clientName}>
      <ul className="space-y-3">
        {contacts.map((contact) => (
          <li key={contact.id} className="text-sm">
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {contact.fullName}
              <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                {contact.role}
              </span>
            </p>
            <p className="flex flex-wrap items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
              {contact.email && (
                <span className="flex items-center gap-1">
                  <Mail className="h-3 w-3" aria-hidden="true" />
                  {contact.email}
                </span>
              )}
              {contact.phone && (
                <span className="flex items-center gap-1">
                  <Phone className="h-3 w-3" aria-hidden="true" />
                  {contact.phone}
                </span>
              )}
            </p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
