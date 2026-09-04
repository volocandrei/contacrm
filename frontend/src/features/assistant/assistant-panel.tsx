/**
 * Asistentul din aplicație.
 *
 * **Ce este.** Un chat care răspunde din datele cabinetului și duce omul la
 * ecranul potrivit: „cât e de lucru?", „ce lipsește la Alfa Conta?", „când e
 * termenul?".
 *
 * **Ce nu face, deliberat.** Nu apasă butoane în locul tău. Nu aprobă, nu
 * respinge, nu trimite. O aprobare este un act contabil cu nume și oră în
 * jurnal — trebuie să aibă în spate un om care a apăsat, nu o propoziție
 * interpretată. Ce face este să propună un drum; tu îl deschizi.
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
import { ArrowRight, Bot, LoaderCircle, Send, User, X } from "lucide-react";
import { useAssistant } from "@/api/hooks";
import { describeError } from "@/lib/errors";
import { buttonPrimary, focusRing, iconChip, inputField, mutedText, surface } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { AssistantLink } from "@/types/domain";

type Turn = {
  id: number;
  role: "user" | "assistant";
  text: string;
  links?: AssistantLink[];
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
            <Bubble key={turn.id} turn={turn} onFollowUp={send} onOpen={(path) => {
              onClose();
              navigate(path);
            }} />
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
