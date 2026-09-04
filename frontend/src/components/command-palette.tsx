/**
 * Paleta de comenzi — Ctrl+K.
 *
 * **Ce problemă rezolvă.** Aplicația are douăzeci de ecrane, iar cabinetul are
 * zeci de clienți. Drumul până la „factura de la Alfa Conta" era: bara laterală →
 * grupul potrivit → lista → filtru → căutare → rând. Cinci decizii pentru o
 * treabă care se face de treizeci de ori pe zi. Câmpul de căutare din antet nu
 * ajuta: orice ai fi scris în el, te ducea în inboxul de documente — un client
 * căutat după CUI nu avea cum să apară.
 *
 * Paleta caută **în același timp** în ecrane, clienți și documente, și te duce
 * direct la rezultat. Tastatura este suficientă de la început până la sfârșit.
 *
 * **Ce nu face.** Nu ocolește nicio permisiune: ecranele apar filtrate ca în bara
 * laterală, iar interogările de clienți și documente pornesc doar dacă rolul le
 * poate cere — altfel ar produce un 403 la fiecare tastă. Ascunderea rămâne
 * ergonomie; refuzul îl dă serverul (§32).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Building2,
  CornerDownLeft,
  FileStack,
  Search,
  type LucideIcon,
} from "lucide-react";
import { useClients, useDocuments } from "@/api/hooks";
import { useAuth } from "@/features/auth/use-auth";
import { formatDate } from "@/lib/format";
import { DOCUMENT_STATUS_LABEL } from "@/lib/labels";
import { ALL_NAV_ITEMS } from "@/lib/navigation";
import { focusRing, iconChip, mutedText, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { Permission } from "@/types/domain";

/** Sub două litere, orice căutare întoarce jumătate din bază. */
const MIN_QUERY = 2;

/** Cât așteaptă după ultima tastă înainte de a întreba serverul. */
const DEBOUNCE_MS = 200;

/** Câte rezultate pe secțiune. Paleta este un drum scurt, nu un ecran de listă. */
const PER_SECTION = 5;

type Entry = {
  id: string;
  title: string;
  subtitle?: string;
  Icon: LucideIcon;
  tone: Tone;
  path: string;
};

type Section = { heading: string; entries: Entry[] };

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const permissions = user?.permissions ?? [];
  // Cheia de dependență: lista în sine este un vector nou la fiecare randare.
  const permissionKey = permissions.join(",");
  const can = (permission: Permission) => permissions.includes(permission);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  //: Cine a deschis paleta. La închidere focalizarea se întoarce acolo — altfel
  //: navigarea cu tastatura reîncepe din capul paginii, la fiecare căutare.
  const opener = useRef<HTMLElement | null>(null);

  const debounced = useDebounced(query.trim(), DEBOUNCE_MS);
  const searching = debounced.length >= MIN_QUERY;

  // Ecranele se filtrează local: sunt douăzeci și le știm pe toate.
  const screens = useMemo<Entry[]>(
    () =>
      ALL_NAV_ITEMS.filter((item) => !item.permission || can(item.permission))
        .filter((item) => !query.trim() || matchesLoosely(item.label, query.trim()))
        .slice(0, query.trim() ? PER_SECTION : ALL_NAV_ITEMS.length)
        .map((item) => ({
          id: `nav-${item.path}`,
          title: item.label,
          Icon: item.Icon,
          tone: "slate" as Tone,
          path: item.path,
        })),
    // `can` se reconstruiește la fiecare randare; ce contează sunt textul și
    // drepturile — de aceea dependența este cheia lor, nu funcția.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query, permissionKey],
  );

  const [clientEntries, setClientEntries] = useState<Entry[]>([]);
  const [documentEntries, setDocumentEntries] = useState<Entry[]>([]);

  const sections: Section[] = [
    { heading: "Ecrane", entries: screens },
    { heading: "Clienți", entries: searching ? clientEntries : [] },
    { heading: "Documente", entries: searching ? documentEntries : [] },
  ].filter((section) => section.entries.length > 0);

  const flat = sections.flatMap((section) => section.entries);

  // Fiecare căutare nouă repoziționează selecția pe primul rezultat: altfel
  // Enter ar deschide ce era selectat pentru textul anterior.
  useEffect(() => setActive(0), [debounced, query]);

  useEffect(() => {
    if (open) {
      // Ordinea contează: întâi reținem cine a deschis paleta, abia apoi mutăm
      // focalizarea. `autoFocus` s-ar aplica înaintea acestui efect, iar paleta
      // și-ar aminti de ea însăși.
      opener.current = document.activeElement as HTMLElement | null;
      inputRef.current?.focus();
      return;
    }
    setQuery("");
    setActive(0);
    opener.current?.focus();
  }, [open]);

  // Rândul selectat trebuie să rămână vizibil când se navighează cu tastele.
  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  function go(entry: Entry) {
    onClose();
    navigate(entry.path);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (flat.length === 0) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((index) => (index + step + flat.length) % flat.length);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const entry = flat[active];
      if (entry) go(entry);
      return;
    }
    // Focalizarea nu are voie să iasă din dialog cât timp el este deschis.
    // Paleta se conduce oricum din câmp: rezultatele se aleg cu săgețile.
    if (event.key === "Tab") event.preventDefault();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Caută în aplicație"
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-3 border-b border-slate-200 px-4 dark:border-slate-800">
          <Search className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Caută client, CUI, document sau ecran…"
            aria-label="Caută client, CUI, document sau ecran"
            role="combobox"
            aria-expanded={flat.length > 0}
            aria-controls="command-palette-results"
            // Selecția se mută cu săgețile, dar focalizarea rămâne în câmp;
            // fără asta, un cititor de ecran nu ar afla niciodată ce e selectat.
            aria-activedescendant={flat[active] ? `palette-${flat[active].id}` : undefined}
            className="h-14 w-full bg-transparent text-base text-slate-900 outline-none placeholder:text-slate-400 dark:text-slate-100"
          />
          <kbd className="hidden shrink-0 rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 sm:block dark:border-slate-700 dark:text-slate-400">
            Esc
          </kbd>
        </div>

        {/* Interogările stau în componente proprii: un rol fără `clients:read` nu
            trebuie nici măcar să pornească cererea. */}
        {searching && can("clients:read") && (
          <ClientSearch query={debounced} onResults={setClientEntries} />
        )}
        {searching && can("documents:read") && (
          <DocumentSearch query={debounced} onResults={setDocumentEntries} />
        )}

        <ul
          id="command-palette-results"
          ref={listRef}
          role="listbox"
          aria-label="Rezultate"
          className="max-h-[52vh] overflow-y-auto p-2"
        >
          {sections.map((section) => (
            <li key={section.heading}>
              <p className="px-3 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-slate-400 uppercase dark:text-slate-500">
                {section.heading}
              </p>
              <ul>
                {section.entries.map((entry) => {
                  const index = flat.indexOf(entry);
                  const selected = index === active;
                  return (
                    <li key={entry.id}>
                      <button
                        type="button"
                        id={`palette-${entry.id}`}
                        role="option"
                        aria-selected={selected}
                        data-active={selected}
                        onMouseEnter={() => setActive(index)}
                        onClick={() => go(entry)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors",
                          focusRing,
                          selected ? "bg-blue-50 dark:bg-blue-500/15" : "hover:bg-slate-50 dark:hover:bg-slate-800/60",
                        )}
                      >
                        <span
                          className={cn(
                            "grid h-8 w-8 shrink-0 place-content-center rounded-lg",
                            iconChip[entry.tone],
                          )}
                        >
                          <entry.Icon className="h-4 w-4" aria-hidden="true" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                            {entry.title}
                          </span>
                          {entry.subtitle && (
                            <span className={cn("block truncate text-xs", mutedText)}>
                              {entry.subtitle}
                            </span>
                          )}
                        </span>
                        {selected && (
                          <CornerDownLeft
                            className="h-3.5 w-3.5 shrink-0 text-blue-500"
                            aria-hidden="true"
                          />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}

          {flat.length === 0 && (
            <li className={cn("px-3 py-10 text-center text-sm", mutedText)}>
              {searching
                ? `Nimic pentru „${debounced}".`
                : `Scrie cel puțin ${MIN_QUERY} litere pentru clienți și documente.`}
            </li>
          )}
        </ul>

        <div
          className={cn(
            "flex items-center justify-between gap-3 border-t border-slate-200 px-4 py-2 text-[11px] dark:border-slate-800",
            mutedText,
          )}
        >
          <span className="flex items-center gap-3">
            <Hint keys="↑↓" what="navighează" />
            <Hint keys="Enter" what="deschide" />
            <Hint keys="Esc" what="închide" />
          </span>
          <span className="hidden sm:block">caută în ecrane, clienți și documente</span>
        </div>
      </div>
    </div>
  );
}

function Hint({ keys, what }: { keys: string; what: string }) {
  return (
    <span className="flex items-center gap-1">
      <kbd className="rounded border border-slate-200 px-1 py-0.5 font-sans dark:border-slate-700">
        {keys}
      </kbd>
      {what}
    </span>
  );
}

/* ─── Interogările ─────────────────────────────────────────────────────────── */

function ClientSearch({
  query,
  onResults,
}: {
  query: string;
  onResults: (entries: Entry[]) => void;
}) {
  const { data } = useClients({ q: query, page: 1, pageSize: PER_SECTION });

  useEffect(() => {
    onResults(
      (data?.items ?? []).map((client) => ({
        id: `client-${client.id}`,
        title: client.name,
        subtitle: client.taxId ? `CUI ${client.taxId}` : undefined,
        Icon: Building2,
        tone: "blue" as Tone,
        path: `/crm/clienti/${client.id}`,
      })),
    );
    // `onResults` este un setter de stare: stabil între randări.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  return null;
}

function DocumentSearch({
  query,
  onResults,
}: {
  query: string;
  onResults: (entries: Entry[]) => void;
}) {
  const { data } = useDocuments({ q: query, page: 1, pageSize: PER_SECTION });

  useEffect(() => {
    onResults(
      (data?.items ?? []).map((document) => ({
        id: `document-${document.id}`,
        title: document.supplierName ?? document.originalFilename,
        subtitle: [
          document.clientName,
          document.documentNumber,
          document.documentDate ? formatDate(document.documentDate) : null,
          DOCUMENT_STATUS_LABEL[document.status],
        ]
          .filter(Boolean)
          .join(" · "),
        Icon: FileStack,
        tone: "purple" as Tone,
        path: `/documente/verificare/${document.id}`,
      })),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  return null;
}

/* ─── Utilitare ────────────────────────────────────────────────────────────── */

/** Fără diacritice și fără majuscule: „Sarcini" se găsește scriind „sarc". */
function matchesLoosely(text: string, query: string): boolean {
  return normalize(text).includes(normalize(query));
}

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

/** Nu interoghează serverul la fiecare tastă. */
function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
