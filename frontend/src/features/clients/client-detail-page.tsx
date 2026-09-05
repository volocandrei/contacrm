import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Link as LinkIcon,
  LoaderCircle,
  Pencil,
  Plus,
  StickyNote,
  Trash2,
} from "lucide-react";
import {
  useClient,
  useClientAliases,
  useClientContacts,
  useClientExpectations,
  useClientNotes,
  useClientPeriods,
  useCreateNote,
  useCreateUploadLink,
  useForgetAlias,
  useDocumentTypes,
  useDocuments,
  useRevokeUploadLink,
  useSaveExpectations,
  useUploadLinks,
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
import { avatarTone, initials } from "@/lib/avatar";
import { describeError } from "@/lib/errors";
import { buttonPrimary, buttonSecondary, focusRing, iconChip, mutedText } from "@/lib/ui";
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
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Toți clienții
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-4">
          {/* Aceeași pastilă ca în listă, mai mare. Drumul listă → fișă păstrează
              un reper vizual: ai deschis clientul pe care l-ai ochit. */}
          <span
            className={cn(
              "grid h-14 w-14 shrink-0 place-content-center rounded-2xl text-lg font-semibold",
              iconChip[avatarTone(client.name)],
            )}
            aria-hidden="true"
          >
            {initials(client.name)}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
                {client.name}
              </h2>
              <ClientStatusBadge status={client.status} />
            </div>
            <p className={cn("mt-0.5 text-sm", mutedText)}>
              {client.taxId} · {client.registrationNumber} · {client.address}
            </p>
          </div>
        </div>
        {has("clients:write") && !editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className={cn(buttonSecondary, "h-10")}
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
        className="mb-4 flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/60"
      >
        {TABS.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-medium transition-all",
              focusRing,
              // Linia subțire de sub tab se pierdea pe ecrane mari; un tab plin
              // se vede din colțul ochiului, iar celelalte rămân disponibile.
              tab === item.id
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-slate-50"
                : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200",
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

      <UploadLinkPanel clientId={clientId} />

      <LearnedSendersPanel clientId={clientId} />

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
          <p className="text-sm text-slate-500 dark:text-slate-400">Niciun contact principal definit.</p>
        )}
      </Panel>

      <Panel title="Perioada curentă">
        {currentPeriod ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                {formatReferenceMonth(currentPeriod.referenceMonth)}
              </span>
              <PeriodStatusBadge status={currentPeriod.status} />
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {currentPeriod.satisfiedCount} din {currentPeriod.expectedCount} documente așteptate
            </p>
            <ul className="space-y-1 text-xs">
              {currentPeriod.checklist.map((item) => (
                <li key={item.documentType} className="flex items-center justify-between gap-2">
                  <span className="text-slate-600 dark:text-slate-400">{item.documentTypeLabel}</span>
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
          <p className="text-sm text-slate-500 dark:text-slate-400">Nicio perioadă deschisă.</p>
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
          className="mb-4 inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          Contact nou
        </button>
      )}

    <Panel bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
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
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {contacts?.map((contact) => (
              <tr key={contact.id}>
                <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">
                  {contact.fullName}
                  {contact.isPrimary && (
                    <span className="ml-2 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                      principal
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{contact.role}</td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{contact.email ?? "—"}</td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{contact.phone ?? "—"}</td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                  {contact.whatsappNumber ?? "—"}
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
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
          <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
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
                <p className="text-xs text-slate-600 dark:text-slate-400">{item.documentTypeLabel}</p>
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
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
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
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
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data?.items.map((doc) => (
              <tr key={doc.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/60">
                <td className="px-4 py-3 whitespace-nowrap text-slate-600 dark:text-slate-400">
                  {doc.documentDate ? formatDate(doc.documentDate) : "—"}
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                  {doc.documentTypeLabel ?? "—"}
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                  {doc.supplierName ?? "—"}
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                  {doc.documentNumber ?? "—"}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-slate-900 dark:text-slate-100">
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
      <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
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
        <p className="text-sm text-slate-500 dark:text-slate-400">Nicio notă internă.</p>
      ) : (
        <ul className="space-y-3">
          {notes?.map((note) => (
            <li key={note.id} className="flex gap-3">
              <StickyNote className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <div>
                <p className="text-sm text-slate-800 dark:text-slate-200">{note.body}</p>
                <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
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
        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
      />
      {problem && (
        <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
      <div className="mt-2 flex items-center justify-end gap-3">
        <span className="text-xs text-slate-400 dark:text-slate-500">
          {body.length}/{MAX_NOTE_LENGTH}
        </span>
        <button
          type="submit"
          disabled={!body.trim() || create.isPending}
          className={cn(buttonPrimary, "h-9")}
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
      <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
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
            <li key={type.code} className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
              <input
                type="checkbox"
                id={`expect-${type.code}`}
                checked={checked}
                disabled={!editable || save.isPending}
                onChange={(event) => set(type.code, event.target.checked ? 1 : null)}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-600"
              />
              <label htmlFor={`expect-${type.code}`} className="flex-1 text-sm text-slate-800 dark:text-slate-200">
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
                    className="h-8 w-16 rounded-md border border-slate-200 px-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
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
              className="text-sm font-medium text-slate-600 hover:underline dark:text-slate-300"
            >
              Renunță
            </button>
          )}
          <button
            type="button"
            onClick={submit}
            disabled={draft === null || save.isPending}
            className={cn(buttonPrimary, "h-9")}
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
      <dt className="shrink-0 text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-right font-medium text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}


/**
 * De la ce adrese ajung documentele singure la clientul ăsta.
 *
 * **De ce se vede.** Sistemul învață din atribuirile făcute de oameni: după ce
 * cineva atribuie un document venit de la o adresă, următoarele merg singure
 * acolo. Un alias pus din greșeală ar misruta **tăcut**, lună de lună — un
 * mecanism care învață și nu poate fi corectat este mai rău decât unul care nu
 * învață deloc. De aceea lista este vizibilă și fiecare rând se poate șterge.
 *
 * Panoul nu apare cât timp nu s-a învățat nimic: un cabinet nou nu are de ce să
 * vadă o listă goală și o explicație despre ceva ce nu s-a întâmplat încă.
 */
function LearnedSendersPanel({ clientId }: { clientId: string }) {
  const { data: aliases } = useClientAliases(clientId);
  const forget = useForgetAlias(clientId);
  const has = usePermissionCheck();

  if (!aliases || aliases.length === 0) return null;

  return (
    <Panel title="Expeditori recunoscuți">
      <p className={cn("mb-3 text-xs", mutedText)}>
        Documentele venite de la adresele astea ajung singure la client. Sistemul le-a
        învățat din atribuirile voastre.
      </p>
      <ul className="space-y-2 text-sm">
        {aliases.map((alias) => (
          <li key={alias.id} className="flex items-center justify-between gap-2">
            <span className="min-w-0">
              <span className="block truncate text-slate-700 dark:text-slate-300">
                {alias.value}
              </span>
              <span className={cn("text-xs", mutedText)}>
                {alias.matchedCount === 0
                  ? "încă nefolosit"
                  : `a potrivit ${alias.matchedCount} ${
                      alias.matchedCount === 1 ? "document" : "documente"
                    }`}
              </span>
            </span>
            {has("clients:write") && (
              <button
                type="button"
                onClick={() => forget.mutate(alias.id)}
                disabled={forget.isPending}
                title={`Uită adresa ${alias.value}`}
                className={cn(
                  "shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20",
                  focusRing,
                )}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                <span className="sr-only">Uită adresa {alias.value}</span>
              </button>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}


/**
 * Linkul prin care clientul își trimite singur documentele.
 *
 * **De ce este panoul care contează cel mai mult pe ecranul ăsta.** Partea grea
 * a muncii nu este procesarea, ci adunarea: fiecare pas cerut clientului — să
 * scaneze, să atașeze, să nu depășească limita — este o lună întârziată. Linkul
 * mută efortul de unde e scump la unde e ieftin.
 *
 * **Adresa se vede o singură dată.** În bază stă doar hash-ul ei; un ecran care
 * ar putea-o reafișa ar însemna că baza o păstrează, iar atunci o bază citită de
 * altcineva ar da linkuri funcționale. De aceea butonul de copiere apare imediat
 * după creare și nu se mai întoarce.
 */
function UploadLinkPanel({ clientId }: { clientId: string }) {
  const { data: links } = useUploadLinks(clientId);
  const create = useCreateUploadLink(clientId);
  const revoke = useRevokeUploadLink(clientId);
  const has = usePermissionCheck();
  const [fresh, setFresh] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const live = (links ?? []).filter(
    (link) => !link.revokedAt && new Date(link.expiresAt) > new Date(),
  );

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setProblem("Browserul nu a permis copierea. Selectează adresa și copiaz-o manual.");
    }
  }

  return (
    <Panel title="Trimitere de către client">
      <p className={cn("mb-3 text-xs", mutedText)}>
        Un link prin care clientul își trimite documentele fără cont și fără aplicație.
        Trimite-i-l pe email sau WhatsApp.
      </p>

      {fresh && (
        <div className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30">
          <p className="mb-2 text-xs font-medium text-emerald-900 dark:text-emerald-200">
            Copiază adresa acum — nu se mai poate afișa a doua oară.
          </p>
          <code className="block truncate rounded-lg bg-white px-2 py-1.5 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {fresh}
          </code>
          <button
            type="button"
            onClick={() => void copy(fresh)}
            className={cn(buttonPrimary, "mt-2 h-8 w-full text-xs")}
          >
            {copied ? "Copiat" : "Copiază adresa"}
          </button>
        </div>
      )}

      {live.length > 0 && (
        <ul className="mb-3 space-y-2 text-sm">
          {live.map((link) => (
            <li key={link.id} className="flex items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="block text-slate-700 dark:text-slate-300">
                  Valabil până la {formatDate(link.expiresAt)}
                </span>
                <span className={cn("text-xs", mutedText)}>
                  {link.uploadCount === 0
                    ? "încă nefolosit"
                    : `${link.uploadCount} ${
                        link.uploadCount === 1 ? "document primit" : "documente primite"
                      }`}
                </span>
              </span>
              {has("clients:write") && (
                <button
                  type="button"
                  onClick={() => revoke.mutate(link.id)}
                  disabled={revoke.isPending}
                  title="Închide linkul"
                  className={cn(
                    "shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20",
                    focusRing,
                  )}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  <span className="sr-only">Închide linkul</span>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {has("clients:write") && (
        <button
          type="button"
          onClick={() =>
            create.mutate(undefined, {
              onSuccess: (link) => {
                setFresh(link.url);
                setCopied(false);
                setProblem(null);
              },
              onError: (caught) => setProblem(describeError(caught)),
            })
          }
          disabled={create.isPending}
          className={cn(buttonSecondary, "h-9 w-full")}
        >
          <LinkIcon className="h-4 w-4" aria-hidden="true" />
          {live.length > 0 ? "Încă un link" : "Deschide un link"}
        </button>
      )}

      {problem && (
        <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </Panel>
  );
}
