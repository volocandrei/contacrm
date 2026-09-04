/**
 * Starea unei integrări, spusă înainte de a fi citită.
 *
 * OneDrive și ANAF au aceleași trei stări — neconfigurată pe server, configurată
 * dar neconectată, conectată — și le desenau fiecare în felul lui: două panouri
 * care spun același lucru cu alte cuvinte și alte culori. Cine intră pe ecranul
 * de surse vrea să afle într-o secundă dacă documentele vin sau nu vin.
 *
 * Distincția dintre primele două stări contează: „lipsește `MS_CLIENT_ID` pe
 * server" se rezolvă de cine face deployment-ul, „nu e conectat niciun cont" se
 * rezolvă apăsând un buton. Un ecran care le confundă trimite omul greșit.
 */
import { CircleCheck, CircleSlash, TriangleAlert, type LucideIcon } from "lucide-react";
import { iconChip, mutedText, pillClass, surface, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";

export type ConnectionState = "connected" | "disconnected" | "unconfigured";

const STATE_META: Record<ConnectionState, { label: string; tone: Tone; Badge: LucideIcon }> = {
  connected: { label: "Conectat", tone: "green", Badge: CircleCheck },
  disconnected: { label: "Neconectat", tone: "slate", Badge: CircleSlash },
  unconfigured: { label: "Neconfigurat pe server", tone: "amber", Badge: TriangleAlert },
};

export function ConnectionCard({
  Icon,
  state,
  title,
  meta,
  actions,
  children,
}: {
  Icon: LucideIcon;
  state: ConnectionState;
  title: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const status = STATE_META[state];

  return (
    <section className={cn(surface, "overflow-hidden")}>
      <div className="flex flex-wrap items-center gap-4 p-5">
        <span
          className={cn(
            "grid h-14 w-14 shrink-0 place-content-center rounded-2xl",
            iconChip[state === "connected" ? "blue" : "slate"],
          )}
        >
          <Icon className="h-7 w-7" aria-hidden="true" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-semibold tracking-tight text-slate-900 dark:text-slate-100">
              {title}
            </h3>
            <span className={pillClass(status.tone)}>
              <status.Badge className="h-3.5 w-3.5" aria-hidden="true" />
              {status.label}
            </span>
          </div>
          {meta && <div className={cn("mt-0.5 text-xs", mutedText)}>{meta}</div>}
        </div>

        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>

      {children && (
        <div className="space-y-3 border-t border-slate-200 px-5 py-4 dark:border-slate-800">
          {children}
        </div>
      )}
    </section>
  );
}

/** Bandă de atenție: ce trebuie făcut, nu doar ce s-a întâmplat. */
export function Notice({
  tone,
  children,
}: {
  tone: "amber" | "red" | "slate";
  children: React.ReactNode;
}) {
  const style = {
    amber:
      "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800/60 dark:bg-amber-900/20 dark:text-amber-200",
    red: "border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-300",
    slate:
      "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-800/60 dark:text-slate-300",
  }[tone];

  return (
    <p className={cn("flex items-start gap-2 rounded-xl border px-3 py-2 text-sm", style)}>
      {tone !== "slate" && (
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      )}
      <span className="min-w-0">{children}</span>
    </p>
  );
}
