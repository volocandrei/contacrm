/**
 * WhatsApp, dintr-un clic.
 *
 * **De ce contează atât.** Clientul mic din România nu citește emailul în ziua
 * în care sosește; WhatsApp îl citește în două minute. Aplicația știe numerele
 * de mult — le folosea ca să recunoască expeditorul unui document — dar ca să
 * scrii cuiva trebuia să copiezi numărul cu ochiul din fișă în telefon.
 *
 * **Ce era greșit înainte.** Agenda avea un buton de WhatsApp care compunea
 * `wa.me/` + cifrele numărului, așa cum era scris. Pentru `+40722123456`
 * mergea; pentru `0722 123 456` — forma în care îl scrie oricine în România —
 * ieșea `wa.me/0722123456`, adică un număr fără prefix de țară și cu un zero în
 * față. WhatsApp îl refuză, iar butonul deschidea o pagină de eroare. Nu era o
 * lipsă: era un buton care părea că funcționează.
 *
 * **De ce întoarce `null` în loc de o ghicitură.** Un link stricat este mai rău
 * decât un buton absent: omul apasă, se deschide o eroare, și data viitoare nu
 * mai apasă. Când numărul nu se poate transforma într-o formă internațională
 * credibilă, ecranul arată numărul ca text și atât.
 */

/** Câte cifre are un număr internațional plauzibil, fără prefixul de ieșire. */
const MIN_DIGITS = 9;
const MAX_DIGITS = 15;

/** Prefixul României. Singurul presupus, și numai pentru numere scrise local. */
const ROMANIA = "40";

/**
 * Numărul în forma pe care o cere `wa.me`: cifre, cu prefix de țară, fără plus.
 *
 * Regulile, în ordinea în care se aplică — fiecare corespunde unei forme în care
 * chiar se scriu numerele pe o fișă de client:
 *
 * - `+40 722 123 456` sau `0040722123456` — deja internațional, se curăță doar.
 * - `40722123456` — la fel, scris fără plus.
 * - `0722 123 456` — forma locală obișnuită: zeroul din față este prefixul
 *   național de ieșire și se înlocuiește cu al țării.
 * - `722123456` — numărul fără nimic în față, cum îl dictează cineva la telefon.
 *
 * Orice altceva — prea scurt, prea lung, un interior de firmă — întoarce `null`.
 */
export function whatsappNumber(raw: string | null | undefined): string | null {
  if (!raw) return null;

  const trimmed = raw.trim();
  const international = trimmed.startsWith("+");
  let digits = trimmed.replace(/\D/g, "");

  if (!international && digits.startsWith("00")) {
    digits = digits.slice(2);
  } else if (!international && digits.startsWith("0")) {
    // Zeroul național nu se transmite peste graniță: `0722…` este `40722…`.
    digits = ROMANIA + digits.slice(1);
  } else if (!international && digits.length === MIN_DIGITS && digits.startsWith("7")) {
    digits = ROMANIA + digits;
  }

  if (digits.length < MIN_DIGITS || digits.length > MAX_DIGITS) return null;
  return digits;
}

/**
 * Adresa care deschide conversația, cu mesajul deja scris când există unul.
 *
 * **Textul rămâne netrimis.** `wa.me` deschide conversația cu mesajul pregătit
 * în câmpul de scris; ce pleacă hotărăște omul, apăsând el butonul verde. Este
 * exact diferența dintre a-i pune unealta în mână și a scrie în locul lui —
 * aplicația nu trimite singură pe WhatsApp și nu are cum să afle dacă a plecat.
 */
export function whatsappHref(
  raw: string | null | undefined,
  text?: string | null,
): string | null {
  const number = whatsappNumber(raw);
  if (number === null) return null;
  const base = `https://wa.me/${number}`;
  return text ? `${base}?text=${encodeURIComponent(text)}` : base;
}
