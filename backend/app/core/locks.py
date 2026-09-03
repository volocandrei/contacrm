"""Încuietori consultative pe baza de date (§21, §55, §72).

Postgres are `pg_advisory_*`: încuietori care nu blochează niciun rând, ci un
număr ales de noi. Sunt exact ce trebuie când ce vrem să serializăm nu este un
rând existent, ci **decizia de a insera unul** — cazul detecției de duplicate,
unde primul care intră trebuie să fie văzut de al doilea.

Toate cele de aici sunt `xact`: se eliberează singure la sfârșitul tranzacției,
oricum s-ar termina ea. O încuietoare de sesiune uitată deschisă ar rămâne pe
conexiunea din pool și ar bloca următorul care o primește.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _key(*parts: object) -> str:
    return ":".join(str(part) for part in parts)


def lock_content(session: Session, organization_id: uuid.UUID, sha256_hash: str) -> None:
    """Serializează încărcările **aceluiași conținut**, în aceeași organizație.

    Fără ea, două încărcări simultane ale aceluiași fișier se caută una pe alta
    înainte ca vreuna să fi comis, nu găsesc nimic, și intră amândouă ca
    documente noi. Am măsurat: din patru încărcări simultane, trei ar fi trebuit
    marcate duplicat, iar în două rulări din trei niciuna nu a fost.

    Nu serializează nimic altceva: două fișiere diferite au chei diferite și nu
    se așteaptă niciodată. Se eliberează la commit, adică exact după ce rândul
    devine vizibil pentru următorul.
    """
    session.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(_key("doc", organization_id, sha256_hash), 0)
            )
        )
    )


def try_lock_organization(session: Session, organization_id: uuid.UUID, purpose: str) -> bool:
    """Încearcă să ia dreptul de a face `purpose` pentru o organizație.

    `False` înseamnă că altcineva îl face chiar acum — nu o eroare. Un cron la
    cinci minute peste o sincronizare care durează șase pornește a doua bătaie
    peste prima; fără asta, amândouă ar citi aceleași dosare și ar cere aceleași
    fișiere.

    Nu așteaptă. Ce nu se face acum se face la bătaia următoare: fiecare dosar își
    ține propriul token delta, deci nimic nu se pierde.
    """
    acquired = session.scalar(
        select(
            func.pg_try_advisory_xact_lock(func.hashtextextended(_key(purpose, organization_id), 0))
        )
    )
    return bool(acquired)


__all__ = ["lock_content", "try_lock_organization"]
