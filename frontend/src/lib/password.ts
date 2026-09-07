/**
 * Ce parolă se acceptă — portul exact al lui `backend/app/domain/passwords.py`.
 *
 * **De ce trăiește în două limbaje.** Regula este una singură, dar are două
 * locuri de aplicat: serverul, care decide, și formularul, care trebuie să spună
 * **înainte** de apăsare de ce nu va merge. Fără varianta din browser, omul
 * scrie o parolă, apasă, așteaptă, și primește refuzul — de trei ori la rând,
 * fiindcă motivele vin unul câte unul.
 *
 * Ca la `filename.ts`, cele două nu au voie să se despartă în tăcere:
 * `password.test.ts` citește cazurile din fișierul Python și le rulează aici.
 *
 * **De ce NU cerem majusculă, cifră și simbol.** Este regula pe care o are toată
 * lumea și tocmai de aceea nu funcționează: obligat să pună un simbol, omul scrie
 * `Parola123!`. Ghidul NIST (SP 800-63B) recomandă invers — lungime, plus refuzul
 * parolelor evident proaste. Motivul întreg este scris în fișierul Python.
 */

/** Sub atât, o parolă furată ca hash se sparge offline. */
export const MIN_LENGTH = 12;

/** `aaaaaaaaaaaa` trece de lungime și nu apără nimic. */
export const MIN_DISTINCT = 5;

/** Sub atâtea caractere, o bucată din nume nu mai este o bucată din nume. */
const MIN_PERSONAL_FRAGMENT = 4;

function fragments(...sources: (string | null | undefined)[]): string[] {
  const found = new Set<string>();
  for (const source of sources) {
    if (!source) continue;
    const [head, domain = ""] = source.includes("@") ? source.split("@") : [source, ""];
    for (const word of `${head} ${domain}`.toLowerCase().match(/[a-z0-9]+/g) ?? []) {
      if (word.length >= MIN_PERSONAL_FRAGMENT) found.add(word);
    }
  }
  return [...found];
}

/**
 * Ce este în neregulă cu parola. Listă goală = se acceptă.
 *
 * Se întorc **toate** motivele deodată, nu primul: cine primește „prea scurtă",
 * o lungește și primește „conține numele tău" este cineva care încearcă a treia
 * oară ceva ce i se putea spune din prima.
 */
export function passwordProblems(
  password: string,
  email?: string | null,
  fullName?: string | null,
): string[] {
  const found: string[] = [];

  if (password.length < MIN_LENGTH) {
    found.push(`Parola are minimum ${MIN_LENGTH} caractere.`);
  }

  if (new Set(password).size < MIN_DISTINCT) {
    found.push(
      `Parola trebuie să conțină cel puțin ${MIN_DISTINCT} caractere diferite ` +
        "— o literă repetată nu apără nimic.",
    );
  }

  const lowered = password.toLowerCase();
  if (fragments(email, fullName).some((fragment) => lowered.includes(fragment))) {
    found.push("Parola nu are voie să conțină numele sau adresa ta de email.");
  }

  return found;
}
