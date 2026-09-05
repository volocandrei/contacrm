/**
 * Asistentul din aplicație.
 *
 * **Ce este.** Un chat care răspunde din datele cabinetului și duce omul la
 * ecranul potrivit: „cât e de lucru?", „ce lipsește la Alfa Conta?", „când e
 * termenul?".
 *
 * **Ce nu face, deliberat.** Nu apasă butoane în locul tău. O acțiune care lasă
 * urmă în jurnal trebuie să aibă în spate un om care a apăsat, nu o propoziție
 * interpretată. Ce face este să **pregătească**: un drum către ecranul potrivit,
 * sau o acțiune gata compusă — sarcina de notat, documentul de atribuit — pe
 * care o vezi scrisă în cuvinte înainte de a confirma. Aprobarea unui document
 * nu se pregătește nici măcar așa: acolo trebuie să te uiți la document.
 *
 * **Ce nu vede.** Nimic peste ce vezi tu: serverul execută fiecare întrebare cu
 * permisiunile tale. Un rol fără drept pe clienți primește un refuz, nu
 * răspunsul.
 *
 * Panoul nu navighează singur nici măcar când răspunsul are un singur link: un
 * salt neașteptat dintr-un ecran de lucru pierde ce aveai pe el.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bot, Check, LoaderCircle, Send, TriangleAlert, User, X } from "lucide-react";
import {
  useAssignClient,
  useAssistant,
  useCreateTask,
  useDocumentRequest,
} from "@/api/hooks";
import { describeError } from "@/lib/errors";
import { buttonPrimary, focusRing, iconChip, inputField, mutedText, surface } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { AssistantAction, AssistantLink } from "@/types/domain";

type Turn = {
  id: number;
  role: "user" | "assistant";
  text: string;
  links?: AssistantLink[];
  actions?: AssistantAction[];
  suggestions?: string[];
};

const GREETING: Turn = {
  id: 0,
  role: "assistant",
  text: "Întreabă-mă despre documente, clienți sau termenul lunii. Răspund din datele tale.",
  suggestions: ["cât e de lucru?", "când e termenul?", "ce documente lipsesc?"],
};

export function AssistantPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const ask = useAssistant();
  const [turns, setTurns] = useState<Turn[]>([GREETING]);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      // Întâi reținem cine a deschis panoul, apoi mutăm focalizarea — altfel
      // panoul și-ar aminti de el însuși și focalizarea s-ar pierde la închidere.
      opener.current = document.activeElement as HTMLElement | null;
      inputRef.current?.focus();
      return;
    }
    opener.current?.focus();
  }, [open]);

  // Ultimul răspuns trebuie să fie vizibil fără derulare manuală.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  if (!open) return null;

  function send(text: string) {
    const question = text.trim();
    if (!question || ask.isPending) return;

    setDraft("");
    setTurns((current) => [
      ...current,
      { id: current.length, role: "user", text: question },
    ]);

    ask.mutate(question, {
      onSuccess: (reply) =>
        setTurns((current) => [
          ...current,
          {
            id: current.length,
            role: "assistant",
            text: reply.text,
            links: reply.links,
            actions: reply.actions,
            suggestions: reply.suggestions,
          },
        ]),
      onError: (caught) =>
        setTurns((current) => [
          ...current,
          { id: current.length, role: "assistant", text: describeError(caught) },
        ]),
    });
  }

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-slate-900/20 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Asistent"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
        }}
        className={cn(
          "flex h-full w-full max-w-md flex-col border-l shadow-2xl",
          "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
        )}
      >
        <header className="flex items-center gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <span className={cn("grid h-9 w-9 place-content-center rounded-xl", iconChip.blue)}>
            <Bot className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Asistent</p>
            <p className={cn("text-xs", mutedText)}>Răspunde din datele tale. Nu apasă butoane.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Închide asistentul"
            className={cn("rounded-lg p-1.5 text-slate-400 hover:text-slate-700", focusRing)}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {turns.map((turn) => (
            <Bubble
              key={turn.id}
              turn={turn}
              onFollowUp={send}
              onOpen={(path) => {
                onClose();
                navigate(path);
              }}
            />
          ))}
          {ask.isPending && (
            <p className={cn("flex items-center gap-2 text-sm", mutedText)}>
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              Caut în date…
            </p>
          )}
          <div ref={endRef} />
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            send(draft);
          }}
          className="flex items-center gap-2 border-t border-slate-200 p-3 dark:border-slate-800"
        >
          <label htmlFor="assistant-input" className="sr-only">
            Întrebarea ta
          </label>
          <input
            id="assistant-input"
            ref={inputRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Întreabă ceva…"
            className={cn(inputField, "h-10 flex-1")}
          />
          <button
            type="submit"
            disabled={!draft.trim() || ask.isPending}
            className={cn(buttonPrimary, "h-10 px-3")}
            aria-label="Trimite întrebarea"
          >
            <Send className="h-4 w-4" aria-hidden="true" />
          </button>
        </form>
      </aside>
    </div>
  );
}

function Bubble({
  turn,
  onFollowUp,
  onOpen,
}: {
  turn: Turn;
  onFollowUp: (text: string) => void;
  onOpen: (path: string) => void;
}) {
  const mine = turn.role === "user";

  return (
    <div className={cn("flex gap-2", mine && "flex-row-reverse")}>
      <span
        className={cn(
          "grid h-7 w-7 shrink-0 place-content-center rounded-lg",
          mine ? iconChip.slate : iconChip.blue,
        )}
        aria-hidden="true"
      >
        {mine ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </span>

      <div className={cn("min-w-0 max-w-[85%] space-y-2", mine && "text-right")}>
        <p
          className={cn(
            "inline-block rounded-2xl px-3 py-2 text-sm whitespace-pre-line",
            mine
              ? "bg-blue-600 text-left text-white"
              : cn(surface, "text-slate-700 dark:text-slate-200"),
          )}
        >
          {turn.text}
        </p>

        {/* Drumurile propuse. Butoane, nu navigare automată. */}
        {turn.links && turn.links.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {turn.links.map((link) => (
              <button
                key={link.path}
                type="button"
                onClick={() => onOpen(link.path)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:text-slate-200 dark:hover:border-blue-800 dark:hover:bg-blue-950/40",
                  focusRing,
                )}
              >
                {link.label}
                <ArrowRight className="h-3 w-3" aria-hidden="true" />
              </button>
            ))}
          </div>
        )}

        {/* Propunerile. Butoane care cheamă ruta obișnuită — nimic nu s-a
            întâmplat până nu apeși. */}
        {turn.actions?.map((action) => (
          <ActionCard key={`${action.kind}-${action.label}`} action={action} />
        ))}

        {turn.suggestions && turn.suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {turn.suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => onFollowUp(suggestion)}
                className={cn(
                  "rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 transition-colors hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700",
                  focusRing,
                )}
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


/**
 * O acțiune pregătită de asistent.
 *
 * Cheamă exact ruta pe care ar fi chemat-o omul din ecran, cu aceleași
 * permisiuni și aceeași urmă în jurnal. Asistentul a compus doar corpul cererii,
 * din date pe care le-a verificat — interfața nu completează nimic.
 *
 * După confirmare butonul rămâne, dezactivat, cu ce s-a întâmplat scris pe el:
 * un buton care dispare lasă îndoiala dacă a apucat să facă ceva.
 */
function ActionCard({ action }: { action: AssistantAction }) {
  const createTask = useCreateTask();
  const assignClient = useAssignClient();
  const requestDocumentsFor = useDocumentRequest();
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const pending = busy || createTask.isPending || assignClient.isPending;

  /**
   * Deschide un link de trimitere și pune în clipboard textul cu tot cu el.
   *
   * Asistentul a scris mai sus cererea **fără** link, fiindcă el nu execută
   * nimic care schimbă date. Linkul se deschide abia acum, de aici, prin exact
   * ruta pe care ar fi chemat-o omul din ecranul „Documente lipsă" — cu
   * permisiunile lui și cu aceeași urmă în jurnal.
   */
  async function requestDocuments() {
    setBusy(true);
    try {
      const { message } = await requestDocumentsFor.mutateAsync({
        clientId: action.payload.clientId ?? "",
        referenceMonth: action.payload.referenceMonth ?? "",
      });
      await navigator.clipboard.writeText(message);
      setDone(true);
    } catch (caught) {
      // Și dacă a picat clipboard-ul, nu doar cererea: un buton care pare că a
      // funcționat, dar n-a copiat nimic, trimite omul să caute un text gol.
      setProblem(describeError(caught));
    } finally {
      setBusy(false);
    }
  }

  function confirm() {
    setProblem(null);
    const onError = (caught: unknown) => setProblem(describeError(caught));
    const onSuccess = () => setDone(true);

    if (action.kind === "request_documents") {
      void requestDocuments();
      return;
    }
    if (action.kind === "create_task") {
      createTask.mutate(
        { title: action.payload.title ?? "", assignedToId: action.payload.assignedToId ?? null },
        { onSuccess, onError },
      );
      return;
    }
    assignClient.mutate(
      { id: action.payload.documentId ?? "", clientId: action.payload.clientId ?? "" },
      { onSuccess, onError },
    );
  }

  return (
    <div className={cn(surface, "space-y-2 p-3")}>
      <p className={cn("text-xs", mutedText)}>{action.summary}</p>
      <button
        type="button"
        onClick={confirm}
        disabled={done || pending}
        className={cn(buttonPrimary, "h-9 w-full", done && "bg-emerald-600 hover:bg-emerald-600")}
      >
        {done ? (
          <>
            <Check className="h-4 w-4" aria-hidden="true" />
            {action.kind === "request_documents" ? "Copiat" : "Gata"}
          </>
        ) : (
          action.label
        )}
      </button>
      {problem && (
        <p role="alert" className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
          <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {problem}
        </p>
      )}
    </div>
  );
}
