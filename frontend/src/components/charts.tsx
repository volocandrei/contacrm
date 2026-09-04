/**
 * Graficele panoului principal.
 *
 * **De ce sunt scrise de mână și nu aduse dintr-o bibliotecă.** Aplicația are
 * nevoie de exact trei forme — o arie, un inel, un cerc de progres — și de una
 * singură dintre proprietățile pentru care se aduce de obicei o bibliotecă:
 * animația. O bibliotecă de grafice ar fi adus câteva sute de kiloocteți, un al
 * doilea sistem de teme (culorile ei, nu ale noastre) și un al doilea mod de a
 * scrie accesibilitate. Trei SVG-uri costă o sută cincizeci de linii pe care le
 * putem citi.
 *
 * **Accesibilitatea nu este opțională aici.** Un grafic este o imagine: are
 * `role="img"` și un `aria-label` care spune în cuvinte ce arată desenul. Fără
 * el, un cititor de ecran anunță „grafic" și atât — adică nimic. Suita de
 * accesibilitate verifică exact asta.
 *
 * **Mișcarea se oprește când sistemul o cere.** Animațiile sunt pornite din CSS
 * și dezactivate global sub `prefers-reduced-motion` (vezi `index.css`): cine a
 * cerut mai puțină mișcare a cerut-o pentru un motiv, de obicei medical.
 */
import { useId } from "react";
import { cn } from "@/lib/utils";

/* ─── Aria de sosiri ───────────────────────────────────────────────────────── */

export type TrendPoint = { day: string; count: number };

/**
 * Câte documente au sosit pe zi.
 *
 * Se desenează pe un sistem de coordonate fix (100×40) și se întinde cu
 * `preserveAspectRatio="none"`: graficul umple lățimea cardului oricare ar fi
 * ea, fără să măsurăm nimic în JavaScript. Un `ResizeObserver` pentru o linie
 * ar fi fost muncă în plus la fiecare randare.
 */
export function TrendArea({
  points,
  label,
  className,
}: {
  points: TrendPoint[];
  label: string;
  className?: string;
}) {
  const gradientId = useId();
  const total = points.reduce((sum, point) => sum + point.count, 0);
  // `|| 1`: cu toate valorile zero, împărțirea ar da NaN și n-ar mai desena nimic.
  const peak = Math.max(...points.map((point) => point.count), 1);

  const coordinates = points.map((point, index) => {
    const x = points.length === 1 ? 0 : (index / (points.length - 1)) * 100;
    const y = 40 - (point.count / peak) * 34 - 3;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const line = `M ${coordinates.join(" L ")}`;
  const area = `${line} L 100,40 L 0,40 Z`;

  return (
    <div className={cn("relative", className)}>
      <svg
        viewBox="0 0 100 40"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label}: ${total} în ultimele ${points.length} zile, maximum ${peak} într-o zi`}
        className="h-full w-full overflow-visible"
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.28" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>

        <path d={area} fill={`url(#${gradientId})`} className="chart-fade-in" />
        <path
          d={line}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
          className="chart-draw"
        />

        {/* Ultima zi primește un punct: „azi" este singura zi despre care cineva
            se uită la grafic ca să afle ceva imediat. */}
        {coordinates.length > 0 && (
          <circle
            cx={coordinates[coordinates.length - 1]!.split(",")[0]}
            cy={coordinates[coordinates.length - 1]!.split(",")[1]}
            r="2.5"
            fill="currentColor"
            vectorEffect="non-scaling-stroke"
            className="chart-pulse"
          />
        )}
      </svg>
    </div>
  );
}

/* ─── Inelul de distribuție ────────────────────────────────────────────────── */

export type DonutSlice = { label: string; value: number; className: string };

/**
 * Distribuția pe stări.
 *
 * Feliile se desenează cu `stroke-dasharray` pe un singur cerc, nu cu arce
 * calculate: mai puțină trigonometrie, iar tranziția dintre două stări se
 * animează singură pentru că se schimbă doar lungimea liniei.
 */
export function Donut({
  slices,
  label,
  centerValue,
  centerLabel,
  className,
}: {
  slices: DonutSlice[];
  label: string;
  centerValue: string;
  centerLabel: string;
  className?: string;
}) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const radius = 42;
  const circumference = 2 * Math.PI * radius;

  // `reduce`, nu un contor reasignat în timpul randării: fiecare felie își
  // primește începutul din suma celor dinaintea ei, calculată o dată.
  const drawn = slices.reduce<Array<DonutSlice & { length: number; offset: number }>>(
    (arcs, slice) => {
      const share = total === 0 ? 0 : slice.value / total;
      const consumed = arcs.reduce((sum, arc) => sum + arc.length, 0);
      arcs.push({ ...slice, length: share * circumference, offset: consumed });
      return arcs;
    },
    [],
  );

  const spoken = slices.map((slice) => `${slice.label}: ${slice.value}`).join(", ");

  return (
    <div className={cn("relative", className)}>
      <svg viewBox="0 0 100 100" role="img" aria-label={`${label}. ${spoken}`} className="h-full w-full -rotate-90">
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth="12"
          className="stroke-slate-100 dark:stroke-slate-800"
        />
        {drawn.map((slice) => (
          <circle
            key={slice.label}
            cx="50"
            cy="50"
            r={radius}
            fill="none"
            strokeWidth="12"
            strokeLinecap="butt"
            strokeDasharray={`${slice.length} ${circumference - slice.length}`}
            strokeDashoffset={-slice.offset}
            className={cn("chart-arc transition-[stroke-dasharray] duration-700", slice.className)}
          />
        ))}
      </svg>

      {/* Cifra din mijloc este citită de aria-label-ul de mai sus, deci textul
          rămâne decorativ — altfel cititorul de ecran ar spune totul de două ori. */}
      <div
        className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"
        aria-hidden="true"
      >
        <span className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-50">
          {centerValue}
        </span>
        <span className="text-[11px] text-slate-500 dark:text-slate-400">{centerLabel}</span>
      </div>
    </div>
  );
}

/* ─── Cercul de progres ────────────────────────────────────────────────────── */

/** Cât dintr-o lună este strâns. Un inel, nu o bară: încape lângă un număr. */
export function ProgressRing({
  value,
  total,
  label,
  className,
}: {
  value: number;
  total: number;
  label: string;
  className?: string;
}) {
  const share = total === 0 ? 0 : Math.min(value / total, 1);
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const complete = share >= 1;

  return (
    <div className={cn("relative", className)}>
      <svg
        viewBox="0 0 100 100"
        role="img"
        aria-label={`${label}: ${value} din ${total}`}
        className="h-full w-full -rotate-90"
      >
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth="10"
          className="stroke-slate-100 dark:stroke-slate-800"
        />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${share * circumference} ${circumference}`}
          className={cn(
            "transition-[stroke-dasharray] duration-700 ease-out",
            complete ? "stroke-emerald-500" : "stroke-blue-500",
          )}
        />
      </svg>
      <div
        className="pointer-events-none absolute inset-0 grid place-content-center"
        aria-hidden="true"
      >
        <span className="text-xs font-semibold tabular-nums text-slate-700 dark:text-slate-200">
          {Math.round(share * 100)}%
        </span>
      </div>
    </div>
  );
}
