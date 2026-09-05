/**
 * Termenele de depunere.
 *
 * **Ce lipsea.** Aplicația avea un singur termen, global — ziua 25, folosită de
 * numărătoarea inversă a lunii. Un cabinet nu trăiește așa: un client pe TVA
 * trimestrial depune altcând decât unul pe lunar, salariile au termenul lor,
 * bilanțul altul. Consecința unui termen ratat nu este o neplăcere de interfață,
 * este o amendă la client, plătită de cabinet.
 *
 * **Cum e ordonat ecranul.** Restanțele primele, singure, cu roșu. Nu pentru că
 * sunt urgente — sunt deja pierdute — ci pentru că sunt singurele care nu se
 * rezolvă așteptând. Restul, grupat pe zi, în ordine.
 *
 * **Ce nu face.** Nu depune nimic și nu marchează singur. Depunerea se face în
 * altă parte, iar aplicația ține evidența ei; un rând bifat automat, pe baza a
 * ceva ce sistemul a dedus, ar fi exact felul de siguranță falsă care se
 * descoperă la un control.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CalendarCheck,
  Check,
  CircleAlert,
  LoaderCircle,
  SlidersHorizontal,
  Undo2,
} from "lucide-react";
import {
  useClients,
  useMarkFiled,
  useMarkManyFiled,
  useObligations,
  useUnmarkFiled,
} from "@/api/hooks";
import { ApiError } from "@/api/types";
import { SelectFilter } from "@/components/form-controls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { useFilterParams } from "@/hooks/use-filter-params";
import { daysUntil, formatDate, formatReferenceMonth } from "@/lib/format";
import { buttonSecondary, iconChip, mutedText } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { DueObligation, ObligationFrequency } from "@/types/domain";

/**
 * Cum se citește perioada acoperită.
 *
 * `period` este luna în care se **încheie** perioada. Pentru una lunară, aceea
 * este chiar luna declarată. Pentru un trimestru, „trimestrul III 2026" spune
 * ceva ce „septembrie 2026" nu spune — și cine bifează trebuie să știe exact ce
 * bifează.
 */
function periodLabel(period: string, frequency: ObligationFrequency): string {
  const year = period.slice(0, 4);
  const month = Number(period.slice(5, 7));
  if (frequency === "ANNUAL") return `anul ${year}`;
  if (frequency === "QUARTERLY") {
    const roman = ["I", "II", "III", "IV"][Math.floor((month - 1) / 3)];
    return `trimestrul ${roman} ${year}`;
  }
  return formatReferenceMonth(period);
}

export function ObligationsPage() {
  const { values, setValue } = useFilterParams({ clientId: "" });
  const canManage = usePermissionCheck()("periods:manage");
  const { data: clientPage } = useClients({ pageSize: 200 });
  const { data, isLoading, error } = useObligations(
    values.clientId ? { clientId: values.clientId } : {},
  );

  const { overdue, byDeadline } = useMemo(() => {
    const rows = data ?? [];
    const late = rows.filter((row) => row.isOverdue);
    const rest = rows.filter((row) => !row.isOverdue);

    const grouped = new Map<string, DueObligation[]>();
    for (const row of rest) {
      const bucket = grouped.get(row.deadline);
      if (bucket) bucket.push(row);
      else grouped.set(row.deadline, [row]);
    }
    return { overdue: late, byDeadline: [...grouped.entries()] };
  }, [data]);

  return (
    <div>
      <PageHeader
        title="Termene"
        description="Ce are cabinetul de depus, pentru cine, până când. Aplicația știe aritmetica unui calendar, nu legea."
        actions={
          canManage ? (
            /* Drumul către catalog stă aici, unde apare întrebarea „de ce
               termenul ăsta?". Ascuns doar în meniul de administrare, ar fi fost
               o promisiune pe care nimeni n-o găsește. */
            <Link
              to="/administrare/declaratii"
              className={cn(buttonSecondary, "h-9 px-3 text-sm")}
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
              Administrează termenele
            </Link>
          ) : undefined
        }
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <SelectFilter
          label="Client"
          allLabel="Toți clienții"
          value={values.clientId}
          onChange={(value) => setValue("clientId", value)}
          options={(clientPage?.items ?? []).map((client) => ({
            value: client.id,
            label: client.name,
          }))}
          className="w-64"
        />
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          title="Niciun termen în perioada următoare"
          description="Fie clienții nu au declarații configurate, fie catalogul este gol. Ambele se rezolvă din fișa clientului."
        />
      ) : (
        <div className="space-y-4">
          {overdue.length > 0 && (
            <Panel
              title="Restanțe"
              // Numărul în titlu: „Restanțe" singur nu spune cât de rău stai.
              action={
                <div className="flex items-center gap-3">
                  <span className="text-xs font-medium text-red-600 dark:text-red-400">
                    {overdue.length} nedepuse după termen
                  </span>
                  <MarkAllFiled rows={overdue} />
                </div>
              }
            >
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {overdue.map((row) => (
                  <Row key={rowKey(row)} row={row} />
                ))}
              </ul>
            </Panel>
          )}

          {byDeadline.map(([deadline, rows]) => (
            <Panel
              key={deadline}
              title={formatDate(deadline)}
              action={
                <div className="flex items-center gap-3">
                  <DaysLeft deadline={deadline} />
                  <MarkAllFiled rows={rows} />
                </div>
              }
            >
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((row) => (
                  <Row key={rowKey(row)} row={row} />
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Marchează tot grupul ca depus.
 *
 * **De ce pe grup și nu pe listă întreagă.** Un cabinet depune declarație cu
 * declarație: intră în SPV, depune D300 pentru toți clienții pe care îi are de
 * depus în ziua aceea, iese. Gruparea de pe ecran este chiar unitatea de lucru,
 * deci butonul stă pe ea.
 *
 * **Se trimit rândurile, nu un criteriu.** Un „toate cele de pe 25 septembrie"
 * interpretat de server ar putea prinde o declarație în plus, la o secundă
 * diferență între ce s-a afișat și ce s-a apăsat — iar „depus" este o afirmație
 * care ajunge într-o evidență contabilă.
 */
function MarkAllFiled({ rows }: { rows: DueObligation[] }) {
  const mark = useMarkManyFiled();
  const [problem, setProblem] = useState<string | null>(null);

  const open = rows.filter((row) => row.filedAt === null);
  if (open.length < 2) return null;

  function submit() {
    setProblem(null);
    mark.mutate(
      open.map((row) => ({
        clientId: row.clientId,
        obligationTypeId: row.obligationTypeId,
        period: row.period,
      })),
      {
        onSuccess: (result) => {
          if (result.failed.length > 0) {
            // Câte, și că sunt încă pe ecran: rândurile rămase nemarcate se văd
            // în listă, deci nu are rost să le enumerăm încă o dată aici.
            setProblem(`${result.failed.length} nu au putut fi marcate; au rămas în listă.`);
          }
        },
        onError: (caught) =>
          setProblem(
            caught instanceof ApiError ? caught.message : "Depunerile nu au putut fi marcate.",
          ),
      },
    );
  }

  return (
    <span className="flex items-center gap-2">
      <button
        type="button"
        onClick={submit}
        disabled={mark.isPending}
        className={cn(buttonSecondary, "h-8 px-2.5 text-xs")}
      >
        {mark.isPending ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <Check className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        Marchează toate ({open.length})
      </button>
      {problem && (
        <span role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem}
        </span>
      )}
    </span>
  );
}

function rowKey(row: DueObligation): string {
  return `${row.clientId}|${row.obligationTypeId}|${row.period}`;
}

/**
 * Câte zile au rămas.
 *
 * Se calculează din data de pe rând, nu din ceas: `isOverdue` vine de la server,
 * iar două surse pentru aceeași întrebare ar putea, într-un fus orar, să dea
 * răspunsuri diferite pe același ecran.
 */
function DaysLeft({ deadline }: { deadline: string }) {
  const days = daysUntil(deadline);

  if (days === 0) return <span className="text-xs font-medium text-amber-600">astăzi</span>;
  return (
    <span className={cn("text-xs", days <= 3 ? "font-medium text-amber-600" : mutedText)}>
      în {days} {days === 1 ? "zi" : "zile"}
    </span>
  );
}

function Row({ row }: { row: DueObligation }) {
  const mark = useMarkFiled();
  const unmark = useUnmarkFiled();
  const [problem, setProblem] = useState<string | null>(null);
  const busy = mark.isPending || unmark.isPending;

  const key = {
    clientId: row.clientId,
    obligationTypeId: row.obligationTypeId,
    period: row.period,
  };

  function toggle() {
    setProblem(null);
    const action = row.filedAt ? unmark : mark;
    action.mutate(key, {
      onError: () => setProblem("Nu s-a putut salva. Încearcă din nou."),
    });
  }

  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <span
        className={cn(
          "grid size-9 shrink-0 place-content-center rounded-lg",
          row.filedAt ? iconChip.green : row.isOverdue ? iconChip.red : iconChip.blue,
        )}
        aria-hidden="true"
      >
        {row.filedAt ? (
          <Check className="h-4 w-4" />
        ) : row.isOverdue ? (
          <CircleAlert className="h-4 w-4" />
        ) : (
          <CalendarCheck className="h-4 w-4" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
          {row.clientName}
        </p>
        <p className={cn("truncate text-xs", mutedText)}>
          {row.label} · {periodLabel(row.period, row.frequency)}
          {row.isOverdue && ` · termen ${formatDate(row.deadline)}`}
        </p>
      </div>

      <div className="flex items-center gap-2">
        {row.filedAt && (
          <span className={cn("text-xs", mutedText)}>
            depus{row.filedByName ? ` de ${row.filedByName}` : ""}
          </span>
        )}
        <button
          type="button"
          onClick={toggle}
          disabled={busy}
          className={cn(buttonSecondary, "h-8 px-2.5 text-xs")}
          /* Perioada face parte din etichetă, nu ca detaliu: același client
             are aceeași declarație în patru luni deodată, iar fără ea patru
             butoane diferite se aud identic. */
          aria-label={
            row.filedAt
              ? `Anulează depunerea ${row.code} ${periodLabel(row.period, row.frequency)} pentru ${row.clientName}`
              : `Marchează depus ${row.code} ${periodLabel(row.period, row.frequency)} pentru ${row.clientName}`
          }
        >
          {busy ? (
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : row.filedAt ? (
            <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {row.filedAt ? "Anulează" : "Marchează depus"}
        </button>
      </div>

      {problem && (
        <p role="alert" className="w-full text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </li>
  );
}
