/**
 * Vocabularul vizual al aplicației, într-un singur loc.
 *
 * **De ce există.** Aceleași trei-patru clase se repetau în peste douăzeci de
 * fișiere: `border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900`
 * apărea de peste nouă sute de ori. Consecința nu era urâțenia, ci **imposi­-
 * bilitatea de a schimba ceva**: o umbră mai blândă sau un colț mai rotund
 * însemna o căutare-înlocuire prin tot proiectul, cu riscul de a rata jumătate
 * din ecrane și de a ajunge la două aspecte diferite pentru același lucru.
 *
 * Ce stă aici nu sunt „utilitare de stil", ci **decizii**: cum arată o suprafață,
 * cât de tare se desprinde de fundal, ce înseamnă un accent de atenție. Fiecare
 * are un nume din domeniu, nu din Tailwind, tocmai ca schimbarea culorii să nu
 * ceară redenumirea nimănui.
 *
 * Nu înlocuiește Tailwind și nu introduce un al doilea sistem: sunt tot clase
 * Tailwind, compuse. Ecranele care au nevoie de ceva particular scriu clase
 * direct, ca până acum.
 */

/** Suprafața pe care stă conținutul: panouri, carduri, meniuri. */
export const surface =
  "rounded-xl border border-slate-200/80 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900";

/** Aceeași suprafață, dar care se ridică la trecerea cursorului (card cu link). */
export const surfaceInteractive = `${surface} transition-all duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md dark:hover:border-slate-700`;

/** Fundalul paginii. Un gri foarte deschis, nu alb: cardurile trebuie să se vadă. */
export const pageBackground = "bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100";

/** Linia care desparte două zone înrudite. */
export const divider = "border-slate-200 dark:border-slate-800";

/** Text secundar: descrieri, ajutor, unități de măsură. */
export const mutedText = "text-slate-500 dark:text-slate-400";

/** Inelul de focalizare. Vizibil la tastatură, invizibil la mouse. */
export const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-950";

/** Butonul pătrat cu icon din antet. */
export const iconButton = `flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100 ${focusRing}`;

/** Câmpul de introducere, în forma folosită peste tot. */
export const inputField = `h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 ${focusRing}`;

/**
 * Tonurile de accent.
 *
 * Sunt puține și au înțeles, nu doar culoare: albastru = informație, verde =
 * bine, chihlimbariu = atenție, roșu = problemă, violet = volum, gri = neutru.
 * Un ecran care alege culoarea după cum îi place ajunge să nu mai comunice
 * nimic prin ea.
 */
export type Tone = "blue" | "green" | "amber" | "red" | "purple" | "slate";

/** Pătratul colorat în care stă iconul unui card. */
export const iconChip: Record<Tone, string> = {
  blue: "bg-blue-50 text-blue-600 dark:bg-blue-500/15 dark:text-blue-400",
  green: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400",
  amber: "bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400",
  red: "bg-red-50 text-red-600 dark:bg-red-500/15 dark:text-red-400",
  purple: "bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-400",
  slate: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
};

/** Eticheta rotunjită de lângă un text: contoare, stări scurte. Se folosește prin `pillClass`. */
const pill: Record<Tone, string> = {
  blue: "bg-blue-50 text-blue-700 ring-blue-600/20 dark:bg-blue-500/15 dark:text-blue-300 dark:ring-blue-400/30",
  green:
    "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-400/30",
  amber:
    "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-400/30",
  red: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-400/30",
  purple:
    "bg-violet-50 text-violet-700 ring-violet-600/20 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-400/30",
  slate:
    "bg-slate-100 text-slate-700 ring-slate-500/20 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-400/20",
};

/** Clasa completă a unei etichete rotunjite. */
export function pillClass(tone: Tone): string {
  return `inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${pill[tone]}`;
}

/**
 * Butoanele.
 *
 * Erau scrise de mână în treisprezece locuri, iar diferențele dintre ele nu erau
 * intenționate: unul avea `disabled:opacity-50`, altul nu; unul avea inel de
 * focalizare, altul îl pierduse pe drum. Înălțimea rămâne la locul apelului — un
 * buton de antet și unul de formular nu au aceeași dimensiune —, dar ce înseamnă
 * „principal", „secundar" și „periculos" se decide într-un singur loc.
 */
const buttonBase = `inline-flex items-center justify-center gap-1.5 rounded-lg px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`;

/** Acțiunea pe care o aștepți de la ecran. De regulă, una singură pe ecran. */
export const buttonPrimary = `${buttonBase} bg-blue-600 text-white shadow-sm hover:bg-blue-700`;

/** Restul acțiunilor: se văd, dar nu strigă. */
export const buttonSecondary = `${buttonBase} border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800`;

/** Ce nu se desface ușor: deconectare, ștergere, respingere. */
export const buttonDanger = `${buttonBase} border border-slate-200 text-red-600 hover:bg-red-50 dark:border-slate-700 dark:text-red-400 dark:hover:bg-red-900/20`;
