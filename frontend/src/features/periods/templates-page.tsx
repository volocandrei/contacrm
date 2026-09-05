/**
 * Șabloane de așteptări: profilurile de client ale cabinetului.
 *
 * **De ce există ecranul ăsta.** Fără așteptări configurate, checklistul lunii
 * este gol, „Documente lipsă" nu are ce raporta, iar fiecare lună apare completă
 * pentru că nu i se cere nimic. Adică tot ce ține de colectare — cererea, linkul
 * de trimitere, urmărirea — nu pornește. Configurarea se făcea client cu client,
 * bifă cu bifă; un cabinet cu treizeci de clienți are, în realitate, trei-patru
 * profiluri.
 *
 * **Șablonul nu este o legătură.** Se aplică o dată, iar rezultatul rămâne al
 * clientului. Scrie asta pe ecran, nu doar în cod: altfel cineva schimbă
 * profilul crezând că actualizează doisprezece clienți, și nu se întâmplă nimic.
 */
import { useState } from "react";
import { Check, ClipboardList, Plus, Trash2, Users } from "lucide-react";
import {
  useApplyExpectationTemplate,
  useClients,
  useCreateExpectationTemplate,
  useDeleteExpectationTemplate,
  useDocumentTypes,
  useExpectationTemplates,
  useSaveExpectationTemplate,
} from "@/api/hooks";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { describeError } from "@/lib/errors";
import {
  buttonPrimary,
  buttonSecondary,
  focusRing,
  inputField,
  mutedText,
  surface,
} from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { ExpectationTemplate } from "@/types/domain";

/** Câți clienți încap într-o singură aplicare. Aceeași limită ca pe server. */
const MAX_CLIENTS_PER_APPLY = 200;

type Draft = {
  id: string | null;
  name: string;
  counts: Record<string, number>;
};

const EMPTY: Draft = { id: null, name: "", counts: {} };

function toDraft(template: ExpectationTemplate): Draft {
  return {
    id: template.id,
    name: template.name,
    counts: Object.fromEntries(
      template.expectations.map((item) => [
        item.documentTypeCode,
        item.expectedMinCount,
      ]),
    ),
  };
}

export function ExpectationTemplatesPage() {
  const { data: templates, isLoading, error } = useExpectationTemplates();
  const [draft, setDraft] = useState<Draft | null>(null);
  const canManage = usePermissionCheck()("periods:manage");

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;

  const list = templates ?? [];

  return (
    <div>
      <PageHeader
        title="Șabloane de așteptări"
        description="Profilurile de client ale cabinetului, aplicate pe mai mulți deodată"
      />

      <p className={cn("mb-4 max-w-3xl text-sm", mutedText)}>
        Un client fără nicio așteptare configurată apare mereu complet, pentru
        că nu i se cere nimic — iar „Documente lipsă" nu are ce raporta despre
        el. Șablonul scrie lista o dată, pe câți clienți alegi.
      </p>

      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <Panel title="Profiluri">
          {list.length === 0 ? (
            <p className={cn("py-4 text-sm", mutedText)}>
              Niciun profil încă. Cel mai simplu: configurează un client cum
              trebuie, apoi salvează-l ca șablon din fișa lui.
            </p>
          ) : (
            <ul className="space-y-1">
              {list.map((template) => (
                <li key={template.id}>
                  <button
                    type="button"
                    onClick={() => setDraft(toDraft(template))}
                    className={cn(
                      "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-800",
                      draft?.id === template.id &&
                        "bg-slate-100 dark:bg-slate-800",
                      focusRing,
                    )}
                  >
                    <span className="block text-sm font-medium text-slate-900 dark:text-slate-100">
                      {template.name}
                    </span>
                    <span className={cn("text-xs", mutedText)}>
                      {template.expectations.length}{" "}
                      {template.expectations.length === 1
                        ? "tip de document"
                        : "tipuri de document"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {canManage && (
            <button
              type="button"
              onClick={() => setDraft({ ...EMPTY })}
              className={cn(buttonSecondary, "mt-3 h-9 w-full")}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Profil nou
            </button>
          )}
        </Panel>

        {draft ? (
          <TemplateEditor
            key={draft.id ?? "nou"}
            draft={draft}
            onDraft={setDraft}
            onDone={() => setDraft(null)}
            canManage={canManage}
          />
        ) : (
          <Panel>
            <p className={cn("py-10 text-center text-sm", mutedText)}>
              Alege un profil din stânga, sau creează unul.
            </p>
          </Panel>
        )}
      </div>
    </div>
  );
}

function TemplateEditor({
  draft,
  onDraft,
  onDone,
  canManage,
}: {
  draft: Draft;
  onDraft: (draft: Draft) => void;
  onDone: () => void;
  canManage: boolean;
}) {
  const { data: types } = useDocumentTypes();
  const create = useCreateExpectationTemplate();
  const save = useSaveExpectationTemplate();
  const remove = useDeleteExpectationTemplate();
  const [problem, setProblem] = useState<string | null>(null);

  const expectations = Object.entries(draft.counts).map(
    ([documentTypeCode, expectedMinCount]) => ({
      documentTypeCode,
      expectedMinCount,
    }),
  );
  const pending = create.isPending || save.isPending || remove.isPending;

  function set(code: string, value: number | null) {
    const counts = { ...draft.counts };
    if (value === null) delete counts[code];
    else counts[code] = value;
    onDraft({ ...draft, counts });
  }

  function submit() {
    setProblem(null);
    const onError = (caught: unknown) => setProblem(describeError(caught));
    if (draft.id === null) {
      create.mutate(
        { name: draft.name, expectations },
        { onSuccess: (saved) => onDraft(toDraft(saved)), onError },
      );
      return;
    }
    save.mutate(
      { id: draft.id, name: draft.name, expectations },
      { onSuccess: (saved) => onDraft(toDraft(saved)), onError },
    );
  }

  return (
    <div className="space-y-4">
      <Panel title={draft.id === null ? "Profil nou" : "Profilul"}>
        <label
          htmlFor="template-name"
          className="mb-1 block text-sm text-slate-700 dark:text-slate-300"
        >
          Nume
        </label>
        <input
          id="template-name"
          value={draft.name}
          disabled={!canManage || pending}
          onChange={(event) => onDraft({ ...draft, name: event.target.value })}
          placeholder="SRL plătitor de TVA lunar"
          className={cn(inputField, "mb-4 w-full max-w-md")}
        />

        <p className={cn("mb-3 text-sm", mutedText)}>
          Ce se așteaptă lunar de la un client cu profilul ăsta.
        </p>

        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(types ?? []).map((type) => {
            const expected = draft.counts[type.code];
            const checked = expected !== undefined;
            return (
              <li
                key={type.code}
                className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
              >
                <input
                  type="checkbox"
                  id={`tpl-${type.code}`}
                  checked={checked}
                  disabled={!canManage || pending}
                  onChange={(event) =>
                    set(type.code, event.target.checked ? 1 : null)
                  }
                  className="h-4 w-4 rounded border-slate-300 dark:border-slate-600"
                />
                <label
                  htmlFor={`tpl-${type.code}`}
                  className="flex-1 text-sm text-slate-800 dark:text-slate-200"
                >
                  {type.label}
                </label>
                {checked && (
                  <>
                    <label
                      className="sr-only"
                      htmlFor={`tpl-count-${type.code}`}
                    >
                      Câte {type.label} pe lună
                    </label>
                    <input
                      id={`tpl-count-${type.code}`}
                      type="number"
                      min={1}
                      value={expected}
                      disabled={!canManage || pending}
                      onChange={(event) =>
                        set(type.code, Math.max(1, Number(event.target.value)))
                      }
                      className={cn(inputField, "h-8 w-16 text-center")}
                    />
                  </>
                )}
              </li>
            );
          })}
        </ul>

        {problem && (
          <p
            role="alert"
            className="mt-3 text-sm text-red-600 dark:text-red-400"
          >
            {problem}
          </p>
        )}

        {canManage && (
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={
                pending || !draft.name.trim() || expectations.length === 0
              }
              className={cn(buttonPrimary, "h-9")}
            >
              <Check className="h-4 w-4" aria-hidden="true" />
              {draft.id === null ? "Creează profilul" : "Salvează"}
            </button>
            {draft.id !== null && (
              <button
                type="button"
                onClick={() =>
                  remove.mutate(draft.id!, {
                    onSuccess: onDone,
                    onError: (caught) => setProblem(describeError(caught)),
                  })
                }
                disabled={pending}
                className={cn(
                  buttonSecondary,
                  "h-9 text-red-600 dark:text-red-400",
                )}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                Șterge profilul
              </button>
            )}
          </div>
        )}

        {draft.id !== null && (
          <p className={cn("mt-3 text-xs", mutedText)}>
            Clienții cărora li s-a aplicat deja rămân neatinși: șablonul se
            aplică o dată, iar lista devine a lor. Ca să-i actualizezi, aplică
            profilul din nou.
          </p>
        )}
      </Panel>

      {draft.id !== null && canManage && (
        <ApplyPanel templateId={draft.id} templateName={draft.name} />
      )}
    </div>
  );
}

/**
 * Aplicarea pe clienți.
 *
 * **Înlocuiește, nu adaugă**, iar asta se scrie pe ecran: un contabil care crede
 * că adaugă un tip de document ar șterge, fără să vrea, tot ce configurase manual.
 */
function ApplyPanel({
  templateId,
  templateName,
}: {
  templateId: string;
  templateName: string;
}) {
  const { data: page } = useClients({
    pageSize: MAX_CLIENTS_PER_APPLY,
    status: "ACTIVE",
  });
  const apply = useApplyExpectationTemplate();
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState<number | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const all = page?.items ?? [];
  const shown = all.filter((client) =>
    client.name.toLowerCase().includes(search.toLowerCase()),
  );

  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
    setApplied(null);
  }

  return (
    <Panel title="Aplică pe clienți">
      <p className={cn("mb-3 text-sm", mutedText)}>
        Fiecare client ales rămâne cu <strong>exact</strong> lista profilului.
        Ce avea configurat înainte se înlocuiește, nu se adaugă.
      </p>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="apply-search">
          Caută client
        </label>
        <input
          id="apply-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Caută client"
          className={cn(inputField, "w-56")}
        />
        <button
          type="button"
          onClick={() => {
            setChosen(new Set(shown.map((client) => client.id)));
            setApplied(null);
          }}
          className={cn(buttonSecondary, "h-9")}
        >
          <Users className="h-4 w-4" aria-hidden="true" />
          Alege tot ce se vede ({shown.length})
        </button>
        {chosen.size > 0 && (
          <button
            type="button"
            onClick={() => {
              setChosen(new Set());
              setApplied(null);
            }}
            className={cn(buttonSecondary, "h-9")}
          >
            Golește selecția
          </button>
        )}
      </div>

      <ul
        className={cn(surface, "mb-3 max-h-72 space-y-1 overflow-y-auto p-2")}
      >
        {shown.map((client) => (
          <li key={client.id}>
            <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800">
              <input
                type="checkbox"
                checked={chosen.has(client.id)}
                onChange={() => toggle(client.id)}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-600"
              />
              <span className="text-slate-800 dark:text-slate-200">
                {client.name}
              </span>
            </label>
          </li>
        ))}
        {shown.length === 0 && (
          <li className={cn("px-2 py-4 text-sm", mutedText)}>
            Niciun client activ găsit.
          </li>
        )}
      </ul>

      <button
        type="button"
        disabled={chosen.size === 0 || apply.isPending}
        onClick={() => {
          setProblem(null);
          apply.mutate(
            { id: templateId, clientIds: [...chosen] },
            {
              onSuccess: (result) => {
                setApplied(result.applied);
                setChosen(new Set());
              },
              onError: (caught) => setProblem(describeError(caught)),
            },
          );
        }}
        className={cn(buttonPrimary, "h-9")}
      >
        <ClipboardList className="h-4 w-4" aria-hidden="true" />
        Aplică „{templateName}" pe {chosen.size}{" "}
        {chosen.size === 1 ? "client" : "clienți"}
      </button>

      {applied !== null && (
        <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">
          Gata: {applied}{" "}
          {applied === 1 ? "client configurat" : "clienți configurați"}.
        </p>
      )}
      {problem && (
        <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </Panel>
  );
}
