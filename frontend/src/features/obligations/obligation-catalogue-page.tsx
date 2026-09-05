/**
 * Catalogul de declarații al cabinetului.
 *
 * **De ce trebuie să existe ecranul.** Ecranul de termene spune, în descrierea
 * lui, că „termenele se administrează din catalog — aplicația nu pretinde că știe
 * legea". Fără ecran, afirmația era adevărată despre cod și falsă despre ce putea
 * face omul: ruta exista, drumul către ea nu. O promisiune pe care interfața nu
 * o poate onora este mai rea decât o funcție lipsă.
 *
 * **Ce se poate schimba.** Eticheta, periodicitatea, decalajul și ziua. Codul
 * nu: el leagă depunerile deja marcate, iar redenumirea lui ar rupe istoricul
 * fără ca cineva să observe.
 *
 * **De ce sub Administrare.** Se deschide o dată, la instalare, și pe urmă doar
 * când se schimbă un termen. Meniul urmează frecvența; drumul de zi cu zi este
 * din „Termene", care are un link către aici.
 */
import { useState } from "react";
import { Check, LoaderCircle } from "lucide-react";
import { useObligationTypes, useUpdateObligationType } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { buttonPrimary, inputField, mutedText, scrollX } from "@/lib/ui";
import { cn } from "@/lib/utils";
import { OBLIGATION_FREQUENCY, type ObligationFrequency, type ObligationType } from "@/types/domain";

const FREQUENCY_LABEL: Record<ObligationFrequency, string> = {
  MONTHLY: "lunar",
  QUARTERLY: "trimestrial",
  ANNUAL: "anual",
};

export function ObligationCataloguePage() {
  const { data, isLoading, error } = useObligationTypes();
  const canManage = usePermissionCheck()("periods:manage");

  return (
    <div>
      <PageHeader
        title="Declarații"
        description="Ce depune cabinetul și când. Aplicația știe aritmetica unui calendar, nu legea — termenele sunt ale voastre."
      />

      <p className={cn("mb-4 max-w-3xl text-sm", mutedText)}>
        Valorile de pornire sunt cele uzuale, dar rămân de confirmat de un
        contabil. Ce schimbi aici se vede imediat în „Termene", fără repornire.
      </p>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <Panel bodyClassName="p-0">
          <div className={scrollX}>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase dark:border-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-3">Declarație</th>
                  <th className="px-4 py-3">Cât de des</th>
                  <th className="px-4 py-3">La câte luni</th>
                  <th className="px-4 py-3">În ce zi</th>
                  <th className="px-4 py-3">Activă</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {(data ?? []).map((type) => (
                  <Row key={type.id} type={type} canManage={canManage} />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

function Row({ type, canManage }: { type: ObligationType; canManage: boolean }) {
  const update = useUpdateObligationType();
  const [draft, setDraft] = useState<ObligationType | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const current = draft ?? type;
  const dirty = draft !== null;

  function set(changes: Partial<ObligationType>) {
    setDraft({ ...current, ...changes });
  }

  function submit() {
    setProblem(null);
    update.mutate(
      {
        id: type.id,
        // Codul nu se trimite: leagă depunerile deja marcate.
        changes: {
          label: current.label,
          frequency: current.frequency,
          monthsAfter: current.monthsAfter,
          deadlineDay: current.deadlineDay,
          isActive: current.isActive,
        },
      },
      {
        onSuccess: () => setDraft(null),
        onError: (caught) =>
          setProblem(
            caught instanceof ApiError ? caught.message : "Declarația nu a putut fi salvată.",
          ),
      },
    );
  }

  return (
    <tr className={cn(!current.isActive && "opacity-60")}>
      <td className="px-4 py-3">
        <label className="sr-only" htmlFor={`label-${type.id}`}>
          Denumirea declarației {type.code}
        </label>
        <input
          id={`label-${type.id}`}
          value={current.label}
          disabled={!canManage || update.isPending}
          onChange={(event) => set({ label: event.target.value })}
          className={cn(inputField, "h-8 w-64")}
        />
        <span className={cn("ml-2 text-xs", mutedText)}>{type.code}</span>
        {problem && (
          <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
            {problem}
          </p>
        )}
      </td>
      <td className="px-4 py-3">
        <label className="sr-only" htmlFor={`frequency-${type.id}`}>
          Cât de des se depune {type.code}
        </label>
        <select
          id={`frequency-${type.id}`}
          value={current.frequency}
          disabled={!canManage || update.isPending}
          onChange={(event) => set({ frequency: event.target.value as ObligationFrequency })}
          className={cn(inputField, "h-8")}
        >
          {OBLIGATION_FREQUENCY.map((value) => (
            <option key={value} value={value}>
              {FREQUENCY_LABEL[value]}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-3">
        <label className="sr-only" htmlFor={`months-${type.id}`}>
          La câte luni după perioadă cade termenul pentru {type.code}
        </label>
        <input
          id={`months-${type.id}`}
          type="number"
          min={0}
          max={24}
          value={current.monthsAfter}
          disabled={!canManage || update.isPending}
          onChange={(event) => set({ monthsAfter: Number(event.target.value) })}
          className={cn(inputField, "h-8 w-20 text-center")}
        />
      </td>
      <td className="px-4 py-3">
        <label className="sr-only" htmlFor={`day-${type.id}`}>
          În ce zi cade termenul pentru {type.code}
        </label>
        <input
          id={`day-${type.id}`}
          type="number"
          min={1}
          max={31}
          value={current.deadlineDay}
          disabled={!canManage || update.isPending}
          onChange={(event) => set({ deadlineDay: Number(event.target.value) })}
          className={cn(inputField, "h-8 w-20 text-center")}
        />
      </td>
      <td className="px-4 py-3">
        <label className="sr-only" htmlFor={`active-${type.id}`}>
          {type.code} se depune
        </label>
        <input
          id={`active-${type.id}`}
          type="checkbox"
          checked={current.isActive}
          disabled={!canManage || update.isPending}
          onChange={(event) => set({ isActive: event.target.checked })}
          className="h-4 w-4 rounded border-slate-300 dark:border-slate-600"
        />
      </td>
      <td className="px-4 py-3 text-right">
        {canManage && (
          <button
            type="button"
            onClick={submit}
            disabled={!dirty || update.isPending}
            className={cn(buttonPrimary, "h-8 px-3 text-xs")}
          >
            {update.isPending ? (
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            Salvează
          </button>
        )}
      </td>
    </tr>
  );
}
