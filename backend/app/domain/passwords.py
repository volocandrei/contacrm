"""Ce parolă se acceptă, și de ce tocmai atât.

**Ce apără parola asta.** Contul unui contabil deschide documentele financiare
ale tuturor clienților lui. Nu este contul unui forum: cine intră vede facturi,
CUI-uri, sume și adrese ale unor firme reale, iar cabinetul răspunde pentru ele.

**De ce NU cerem majusculă, cifră și simbol.** Este regula pe care o are toată
lumea și tocmai de aceea nu funcționează: obligat să pună un simbol, omul scrie
`Parola123!`, iar obligat s-o schimbe trimestrial scrie `Parola124!`. Rezultatul
este o parolă scurtă, previzibilă și scrisă pe un post-it. Ghidul NIST (SP
800-63B) recomandă de mai mulți ani exact invers: **lungime**, plus refuzul
parolelor evident proaste — și nimic altceva impus.

Așa că aici sunt trei reguli, fiecare cu o pagubă concretă în spate:

1. **Cel puțin 12 caractere.** Sub atât, o parolă furată ca hash se sparge offline.
   Argon2id face fiecare încercare scumpă, dar nu imposibilă.
2. **Cel puțin 5 caractere diferite.** `aaaaaaaaaaaa` are doisprezece caractere și
   nicio valoare. La fel `123412341234`. Regula de lungime singură le acceptă pe
   amândouă.
3. **Să nu conțină propriul nume sau adresa de email.** `ioana.marinescu` este
   primul lucru pe care îl încearcă cineva care are lista de utilizatori — iar
   lista de utilizatori se află din orice email trimis de cabinet.

Ce **nu** face fișierul acesta, deliberat: nu ține o listă de parole comune. Ar
însemna un fișier de câteva sute de kiloocteți în repository, ținut la zi de
nimeni. Locul acelei verificări este un serviciu extern de tip „have i been
pwned", și rămâne o îmbunătățire de după livrare, nu una pe jumătate acum.
"""

from __future__ import annotations

import re

#: Sub atât, o parolă furată ca hash se sparge offline.
MIN_LENGTH = 12

#: `aaaaaaaaaaaa` trece de lungime și nu apără nimic.
MIN_DISTINCT = 5

#: Sub atâtea caractere, o bucată din nume nu mai este o bucată din nume: „Ion"
#: apare în „raportion" fără ca cineva să fi vrut asta.
_MIN_PERSONAL_FRAGMENT = 4

_WORD = re.compile(r"[a-z0-9]+")


class PasswordTooWeakError(ValueError):
    """Parola nu trece. `reasons` sunt spuse omului, în ordinea în care le poate repara."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(" ".join(reasons))
        self.reasons = reasons


def _fragments(*sources: str | None) -> set[str]:
    """Bucățile personale care nu au ce căuta într-o parolă.

    Din `ioana.marinescu@cabinet.ro` ies `ioana`, `marinescu` și `cabinet` — nu
    `ro`, care este prea scurt ca să însemne ceva.
    """
    found: set[str] = set()
    for source in sources:
        if not source:
            continue
        head = source.split("@", 1)[0] if "@" in source else source
        domain = source.split("@", 1)[1] if "@" in source else ""
        for word in _WORD.findall(f"{head} {domain}".lower()):
            if len(word) >= _MIN_PERSONAL_FRAGMENT:
                found.add(word)
    return found


def problems(password: str, *, email: str | None = None, full_name: str | None = None) -> list[str]:
    """Ce este în neregulă cu parola. Listă goală = se acceptă.

    Se întorc **toate** motivele deodată, nu primul: cine primește „prea scurtă",
    o lungește și primește „conține numele tău" este cineva care încearcă a treia
    oară ceva ce i se putea spune din prima.
    """
    found: list[str] = []

    if len(password) < MIN_LENGTH:
        found.append(f"Parola are minimum {MIN_LENGTH} caractere.")

    if len(set(password)) < MIN_DISTINCT:
        found.append(
            f"Parola trebuie să conțină cel puțin {MIN_DISTINCT} caractere diferite "
            "— o literă repetată nu apără nimic."
        )

    lowered = password.lower()
    if any(fragment in lowered for fragment in _fragments(email, full_name)):
        found.append("Parola nu are voie să conțină numele sau adresa ta de email.")

    return found


def ensure_strong(password: str, *, email: str | None = None, full_name: str | None = None) -> None:
    """Aceeași verificare, dar care oprește drumul. Ridică `PasswordTooWeakError`."""
    found = problems(password, email=email, full_name=full_name)
    if found:
        raise PasswordTooWeakError(found)


__all__ = [
    "MIN_DISTINCT",
    "MIN_LENGTH",
    "PasswordTooWeakError",
    "ensure_strong",
    "problems",
]
