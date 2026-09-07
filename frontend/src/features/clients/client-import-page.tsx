/**
 * Lista de clienți, dintr-un fișier.
 *
 * **Ecranul care decide dacă aplicația se încearcă sau nu.** Un cabinet are între
 * treizeci și trei sute de clienți, iar lista lor există deja undeva: într-un
 * Excel, în exportul din programul vechi, în tabelul contabilului-șef. Până acum
 * singurul drum înăuntru era formularul, client cu client. Nimeni nu tastează
 * două sute de firme ca să vadă dacă un program e bun de ceva — deci nimeni nu
 * ajungea să vadă.
 *
 * **Doi pași, nu unul.** Primul citește fișierul și nu atinge nimic; al doilea
 * scrie. Un import care creează tăcut două sute de clienți la prima apăsare este
 * mai rău decât niciunul: dacă fișierul era greșit, nimeni nu-i mai poate
 * deosebi de cei buni, iar ștergerea lor cere exact munca pe care importul o
 * economisea.
 *
 * **Se arată rândurile cu probleme, nu toate.** O listă de două sute de rânduri
 * verzi nu se citește, iar cine o derulează caută oricum exact ce nu intră. Cine
 * vrea totuși tot, apasă.
 */
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, FileUp, TriangleAlert, Upload } from "lucide-react";
import { useImportClients } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ExportButton } from "@/components/export-button";
import { PageHeader, Panel } from "@/components/page";
import { usePermissionCheck } from "@/features/auth/use-auth";
import { buttonPrimary, buttonSecondary, mutedText, pillClass, surface, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { ImportOutcome, ImportPlan, ImportRow } from "@/types/domain";

const OUTCOME_LABEL: Record<ImportOutcome, string> = {
  NEW: "client nou",
  EXISTING: "există deja",
  DUPLICATE: "repetat în fișier",
  INVALID: "nu se poate importa",
};

const OUTCOME_TONE: Record<ImportOutcome, Tone> = {
  NEW: "green",
  EXISTING: "slate",
  DUPLICATE: "amber",
  INVALID: "red",
};

export function ClientImportPage() {
  const has = usePermissionCheck();
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const importer = useImportClients();
  const input = useRef<HTMLInputElement>(null);

  function run(chosen: File, apply: boolean) {
    setProblem(null);
    importer.mutate(
      { file: chosen, apply },
      {
        onSuccess: setPlan,
        onError: (caught) =>
          setProblem(
            caught instanceof ApiError ? caught.message : "Fișierul nu a putut fi citit.",
          ),
      },
    );
  }

  function choose(chosen: File | null) {
    setPlan(null);
    setProblem(null);
    setFile(chosen);
    if (chosen) run(chosen, false);
  }

  if (!has("clients:write")) {
    // Ascunderea este ergonomie, nu securitate: refuzul îl dă serverul (§32).
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Importul de clienți este al administratorului.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Importă clienți"
        description="Lista pe care o ai deja, într-un fișier — nu tastată de la capăt"
        actions={
          <Link to="/crm/clienti" className={cn(buttonSecondary, "h-10")}>
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Înapoi la clienți
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Fișierul" className="lg:col-span-2">
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={(event) => choose(event.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            onClick={() => input.current?.click()}
            className={cn(
              surface,
              "flex w-full flex-col items-center gap-2 border-dashed p-8 text-sm transition-colors hover:border-blue-300 hover:bg-blue-50/40 dark:hover:border-blue-900 dark:hover:bg-blue-950/20",
            )}
          >
            <FileUp className="h-8 w-8 text-slate-400" aria-hidden="true" />
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {file ? file.name : "Alege un fișier CSV"}
            </span>
            <span className={cn("text-xs", mutedText)}>
              {file ? "Apasă pentru a alege altul" : "Salvat din Excel ca CSV"}
            </span>
          </button>

          {problem && (
            <p
              role="alert"
              className="mt-3 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200"
            >
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {problem}
            </p>
          )}
        </Panel>

        <Panel title="Ce coloane trebuie">
          <p className={cn("mb-3 text-sm", mutedText)}>
            Doar <strong>Denumire</strong> este obligatorie. Restul — CUI, adresă, email, telefon,
            WhatsApp — intră dacă există. Antetul se recunoaște și scris altfel: „Nume", „CIF",
            „Reg com".
          </p>
          {/* Modelul există pentru că altfel prima încercare eșuează pe antet, iar
              a doua nu mai are loc: omul închide ecranul și scrie de mână. */}
          <ExportButton
            filters={{}}
            path="/clients/import/template.csv"
            fallbackName="model-clienti.csv"
            label="Descarcă modelul"
            title="Descarcă un fișier cu antetul corect și un rând de exemplu"
          />
          <p className={cn("mt-3 text-xs", mutedText)}>
            Fără CUI, documentele din e-Factura nu se leagă singure de client. Fără email, clientul
            nu poate primi solicitări sau remindere.
          </p>
        </Panel>
      </div>

      {plan && (
        <Result
          plan={plan}
          pending={importer.isPending}
          onApply={() => file && run(file, true)}
        />
      )}
    </div>
  );
}

/**
 * Ce s-ar întâmpla, sau ce s-a întâmplat.
 *
 * Aceleași cifre în ambele stări, deliberat: cine a apăsat trebuie să poată
 * compara ce i s-a promis cu ce a ieșit, fără să țină minte.
 */
function Result({
  plan,
  pending,
  onApply,
}: {
  plan: ImportPlan;
  pending: boolean;
  onApply: () => void;
}) {
  const [all, setAll] = useState(false);
  const problems = plan.rows.filter((row) => row.outcome !== "NEW" || row.warning);
  const shown = all ? plan.rows : problems;

  return (
    <Panel
      title={plan.dryRun ? "Ce s-ar întâmpla" : "Ce s-a întâmplat"}
      action={
        plan.dryRun && plan.created > 0 ? (
          <button
            type="button"
            onClick={onApply}
            disabled={pending}
            className={cn(buttonPrimary, "h-9 px-4 text-sm disabled:opacity-50")}
          >
            <Upload className="h-4 w-4" aria-hidden="true" />
            {pending ? "Se importă…" : `Importă ${plan.created}`}
          </button>
        ) : undefined
      }
    >
      <div className="mb-4 flex flex-wrap gap-4 text-sm">
        <Figure
          count={plan.created}
          label={plan.dryRun ? "de importat" : "importați"}
          tone="green"
        />
        <Figure count={plan.existing} label="există deja" tone="slate" />
        <Figure count={plan.duplicates} label="repetați în fișier" tone="amber" />
        <Figure count={plan.invalid} label="nu se pot importa" tone="red" />
      </div>

      {!plan.dryRun && (
        <p className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200">
          Gata. Clienții existenți nu au fost modificați:{" "}
          <Link to="/crm/clienti" className="font-medium underline underline-offset-2">
            vezi lista
          </Link>
          .
        </p>
      )}

      {shown.length === 0 ? (
        <p className={cn("text-sm", mutedText)}>Toate rândurile intră fără probleme.</p>
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {shown.map((row) => (
            <Row key={row.line} row={row} />
          ))}
        </ul>
      )}

      {problems.length !== plan.rows.length && (
        <button
          type="button"
          onClick={() => setAll((value) => !value)}
          className="mt-3 text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
        >
          {all ? "Arată doar ce are nevoie de atenție" : `Arată toate cele ${plan.rows.length} rânduri`}
        </button>
      )}
    </Panel>
  );
}

function Figure({ count, label, tone }: { count: number; label: string; tone: Tone }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">
        {count}
      </span>
      <span className={pillClass(tone)}>{label}</span>
    </span>
  );
}

function Row({ row }: { row: ImportRow }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
      {/* Numărul rândului, ca să-l poată găsi în Excel. Fără el, „rândul stricat"
          este o afirmație pe care omul nu o poate urmări nicăieri. */}
      <span className={cn("w-12 shrink-0 text-right text-xs tabular-nums", mutedText)}>
        {row.line}
      </span>
      <span className="min-w-0 flex-1 truncate text-slate-900 dark:text-slate-100">
        {row.name || <span className={mutedText}>(fără denumire)</span>}
        {row.taxId && <span className={cn("ml-2 text-xs", mutedText)}>{row.taxId}</span>}
      </span>
      <span className={pillClass(OUTCOME_TONE[row.outcome])}>{OUTCOME_LABEL[row.outcome]}</span>
      {(row.note ?? row.warning) && (
        <span className={cn("w-full pl-16 text-xs", mutedText)}>{row.note ?? row.warning}</span>
      )}
    </li>
  );
}
