"""Contorul de încercări, ținut acolo unde îl văd toate procesele.

**Ce lipsea.** Contorul stătea în memoria procesului de API. Pe un server cu un
singur container, asta funcționează. Pe o platformă serverless — adică fix ținta
de deploy — fiecare cerere poate nimeri altă instanță, iar platforma **pornește
instanțe noi tocmai când crește traficul**: exact ce face un atac prin
încercarea parolelor. Protecția slăbea singură, în clipa în care era nevoie de
ea.

Iar asta este chiar greșeala pe care `app/core/rate_limit.py` a fost scris ca să
o repare, cu vorbele lui: „o variabilă care promite o protecție inexistentă este
mai rea decât absența ei". Un contor per proces, pe o platformă fără procese
stabile, promite la fel de mult și apără la fel de puțin.

**De ce un rând în baza de date, și nu Redis.** Pentru că nu este nevoie de
Redis. Fereastra este de un minut, cheile sunt puține, iar scrierea se face
**numai la eșec** — o autentificare reușită nu atinge tabelul. Baza este oricum
singurul lucru pe care instanțele îl împart, ca și în cazul semnului de viață al
workerului.

**Ce nu este.** Nu este un jurnal de securitate: rândurile se rescriu și se
șterg. Cine a încercat și când se află din jurnalul de audit, care este altceva
și nu se pierde.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class RateLimitWindow(Base):
    """Câte încercări eșuate s-au strâns sub o cheie, în fereastra curentă."""

    __tablename__ = "rate_limit_windows"

    id: Mapped[uuid_pk]
    #: `domeniu|cheie` — de exemplu contul, adresa, sau tokenul de portal.
    #: Unic: fiecare cheie are un singur rând, actualizat în loc.
    key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    #: Când a început fereastra curentă. Ceasul **bazei**, nu al procesului: două
    #: instanțe cu ceasuri diferite ar fi deschis și închis ferestre diferite
    #: pentru aceeași cheie.
    #: Indexată: curățenia șterge ferestrele vechi la fiecare tur de worker,
    #: iar fără indice ar fi o scanare completă de fiecare dată.
    window_started_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    #: Câte eșecuri în fereastra asta.
    hits: Mapped[int] = mapped_column(nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<RateLimitWindow {self.key} {self.hits}>"
