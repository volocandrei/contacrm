"""Contorul de încercări eșuate, împărțit de toate instanțele.

**Ce repară.** `app/core/rate_limit.py` ține contorul în memoria procesului și
spune singur unde nu funcționează: „pe o platformă care pornește un proces per
cerere nu limitează nimic". Platforma de deploy este exact aceea. Mai rău,
serverless-ul **pornește instanțe noi când crește traficul** — adică fix ce
produce un atac prin încercarea parolelor: cu cât se încearcă mai tare, cu atât
se împarte contorul în mai multe bucăți.

Ceea ce ne întoarce la propoziția din care s-a născut modulul acela: „o variabilă
care promite o protecție inexistentă este mai rea decât absența ei". Un contor
per proces, pe o platformă fără procese stabile, promite la fel de mult.

**De ce nu Redis.** Pentru că nu este nevoie: fereastra este de un minut, cheile
sunt puține, iar scrierea se face **numai la eșec** — o autentificare reușită nu
atinge tabelul. Baza este oricum singurul lucru pe care instanțele îl împart.

**De ce tranzacție proprie.** Refuzul la autentificare se ridică drept eroare de
aplicație, iar `CommittingRoute` nu confirmă tranzacția când ruta ridică ceva.
Un eșec numărat în sesiunea cererii s-ar da înapoi odată cu ea — adică exact
încercările pe care trebuie să le ținem minte s-ar șterge singure.

**Ce nu face.** Nu înlocuiește limitarea de la marginea rețelei. Un atac
distribuit, cu o adresă nouă la fiecare încercare, trece pe lângă orice contor
per cheie — acela se oprește la firewall. Ce apără aici este cazul obișnuit:
multe parole pe un cont, sau o parolă pe multe conturi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import ColumnElement, case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.rate_limit import WINDOW_SECONDS, Decision
from app.models.rate_limit import RateLimitWindow

logger = get_logger(__name__)

#: După cât timp o fereastră închisă nu mai spune nimic și se poate șterge.
#: Mult peste fereastră, deliberat: rândurile sunt mici, iar ștergerea prea
#: agresivă ar face curățenie mai des decât ar folosi cuiva.
FORGET_AFTER_SECONDS: Final = 3600


def _age() -> ColumnElement[float]:
    """Vechimea ferestrei, în secunde, **calculată de bază**.

    Nu de proces: două instanțe cu ceasuri diferite ar fi deschis și închis
    ferestre diferite pentru aceeași cheie, iar limita ar fi depins de NTP.
    """
    return cast(
        ColumnElement[float],
        func.extract("epoch", func.now() - RateLimitWindow.window_started_at),
    )


# Nu `frozen`: pragurile se coboară în teste, ca limitele reale să nu ceară
# zeci de cereri pentru a fi verificate.
@dataclass(slots=True)
class SharedWindowLimiter:
    """Aceleași două operații ca `FixedWindowLimiter`, dar cu contorul în bază.

    `blocked` se pune **înaintea** încercării, `record` **după**, și numai dacă a
    eșuat. Separarea nu este un moft: o singură metodă ar fi trebuit să numere și
    reușitele, iar atunci un contabil care se autentifică des ar fi fost refuzat
    pentru că știe parola.
    """

    #: Ce se numără. Intră în cheie, deci două domenii nu se calcă.
    scope: str
    limit: int

    @property
    def enabled(self) -> bool:
        """Zero sau negativ înseamnă „fără limită", nu „blochează tot".

        Aceeași alegere ca la contorul din proces: o configurare greșită nu are
        voie să închidă autentificarea pentru toată lumea.
        """
        return self.limit > 0

    def _key(self, key: str) -> str:
        return f"{self.scope}|{key}"[:512]

    def blocked(self, key: str) -> Decision:
        """Este cheia peste prag chiar acum? Nu modifică nimic.

        **Lasă să treacă dacă baza nu răspunde.** Un refuz aici ar transforma o
        clipire a bazei într-o pană de autentificare pentru tot cabinetul, iar
        pasul următor oricum are nevoie de bază și va eșua cu eroarea potrivită.
        """
        if not self.enabled:
            return Decision(allowed=True)

        try:
            with session_scope() as session:
                row = session.execute(
                    select(RateLimitWindow.hits, _age()).where(
                        RateLimitWindow.key == self._key(key)
                    )
                ).first()
        except Exception:
            logger.exception("rate_limit_read_failed", scope=self.scope)
            return Decision(allowed=True)

        if row is None:
            return Decision(allowed=True)

        hits, age = row
        if age is None or float(age) >= WINDOW_SECONDS or hits < self.limit:
            return Decision(allowed=True)

        remaining = WINDOW_SECONDS - float(age)
        return Decision(allowed=False, retry_after=max(1, int(remaining) + 1))

    def record(self, key: str) -> None:
        """Înregistrează un eșec, într-o tranzacție proprie.

        Fereastra se deschide din nou dacă cea veche a expirat — totul într-o
        singură instrucțiune, ca două instanțe care greșesc în aceeași clipă să
        nu piardă niciun eșec.

        **Un eșec aici nu are voie să oprească cererea.** Contorul este o măsură
        de precauție, nu răspunsul cerut; dacă baza clipește, autentificarea
        merge mai departe și eșecul acesta nu se numără.
        """
        if not self.enabled:
            return

        expired = _age() >= WINDOW_SECONDS
        statement = (
            insert(RateLimitWindow)
            .values(key=self._key(key), window_started_at=func.now(), hits=1)
            .on_conflict_do_update(
                index_elements=[RateLimitWindow.key],
                set_={
                    "hits": case((expired, 1), else_=RateLimitWindow.hits + 1),
                    "window_started_at": case(
                        (expired, func.now()), else_=RateLimitWindow.window_started_at
                    ),
                },
            )
        )
        try:
            with session_scope() as session:
                session.execute(statement)
        except Exception:
            logger.exception("rate_limit_write_failed", scope=self.scope)

    def reset(self) -> None:
        """Golește contorul domeniului. Pentru teste; nu are apelant în producție."""
        try:
            with session_scope() as session:
                session.execute(
                    delete(RateLimitWindow).where(RateLimitWindow.key.startswith(f"{self.scope}|"))
                )
        except Exception:  # fără bază nu există contor de golit
            logger.debug("rate_limit_reset_skipped", scope=self.scope)


def forget_old(session: Session) -> int:
    """Șterge ferestrele care nu mai spun nimic. Chemată din turul workerului.

    Fără ea, tabelul ar crește cu un rând per adresă care a greșit vreodată o
    parolă — mic, dar fără capăt.
    """
    result = session.execute(delete(RateLimitWindow).where(_age() >= FORGET_AFTER_SECONDS))
    return cast(CursorResult[Any], result).rowcount or 0


__all__ = ["FORGET_AFTER_SECONDS", "SharedWindowLimiter", "forget_old"]
