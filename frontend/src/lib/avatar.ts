/**
 * Inițiale colorate, în locul unei iconițe generice.
 *
 * Într-o listă de treizeci de rânduri, ochiul găsește „AC" mai repede decât
 * citește „Alfa Conta SRL". Funcțiile au stat o vreme în ecranul de clienți; din
 * momentul în care și lista de colegi are nevoie de ele, două copii ar însemna
 * că același nume capătă culori diferite pe două ecrane — exact opusul scopului.
 */
import type { Tone } from "@/lib/ui";

/** Cel mult două litere, luate din primele două cuvinte care chiar sunt cuvinte. */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((word) => /\p{L}/u.test(word))
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Tonul pastilei, derivat din nume.
 *
 * Stabil — același nume are mereu aceeași culoare, deci devine recognoscibil —
 * și fără sens semantic: culoarea nu spune nimic despre cine e, doar îl separă
 * de vecinii din listă. De aceea nici nu contează *care* culoare iese.
 */
const AVATAR_TONES: Tone[] = ["blue", "green", "amber", "purple", "red", "slate"];

export function avatarTone(name: string): Tone {
  const sum = [...name].reduce((total, character) => total + character.charCodeAt(0), 0);
  return AVATAR_TONES[sum % AVATAR_TONES.length]!;
}
