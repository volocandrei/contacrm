"""Contractul cu Spațiul Privat Virtual al ANAF.

Aceeași disciplină ca la stocare (ADR-004), extracție (ADR-005) și Microsoft
Graph: serviciul de sincronizare nu știe niciodată că în spate stau URL-uri
`api.anaf.ro`. Vorbește doar cu protocolul de aici.

Motivul este iarăși testabilitatea, dar aici este mai ascuțit decât oriunde:
**nu putem chema ANAF din niciun test.** Autorizarea cere un certificat digital
calificat prezentat fizic de browser, iar mediul de test al ANAF îl cere la fel.
Deci tot ce contează — idempotența, atribuirea clientului, fereastra de timp,
tratarea împuternicirii lipsă — trebuie să poată fi exercitat cu o implementare
falsă. Ce rămâne neverificat este strict clientul HTTP, care este deliberat
subțire: compune URL-uri și citește JSON.

**Ce nu face acest strat, deliberat:** nu trimite facturi. `/upload` și
`stareMesaj` există în API și nu sunt implementate aici. A trimite o factură în
numele unui client înseamnă a emite un document fiscal — altă răspundere decât a
citi unul deja emis, și nu se strecoară într-o funcție de preluare.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.enums import EFacturaMessageKind


@dataclass(frozen=True, slots=True)
class SpvMessage:
    """Un mesaj din lista SPV. Nu este încă o factură — este anunțul ei."""

    #: `id_descarcare`. Cheia cu care se descarcă arhiva **și** cheia de
    #: idempotență: același id nu produce niciodată un al doilea document.
    id: str
    kind: EFacturaMessageKind
    #: CUI-ul pentru care a fost întors mesajul, așa cum îl declară ANAF.
    tax_id: str
    created_at: datetime | None = None
    #: Textul liber al ANAF („Factura cu id_incarcare=… emisa de cif_emitent=…").
    #: Se păstrează pentru audit; nu se parsează, pentru că nu are format promis.
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SpvPage:
    """Ce a întors o interogare a listei, pentru o fereastră de timp."""

    messages: tuple[SpvMessage, ...] = ()
    #: Mai sunt pagini în aceeași fereastră. Turul următor le ia — fereastra nu
    #: se închide (`synced_through` nu avansează) până nu s-au citit toate.
    has_more: bool = False


@dataclass(frozen=True, slots=True)
class AnafTokens:
    """Ce întoarce ANAF după autorizarea cu certificat."""

    access_token: str
    refresh_token: str
    #: Câte secunde mai trăiește refresh tokenul. ANAF îl dă valabil un an;
    #: ecranul anunță din timp, ca reînnoirea să nu fie descoperită prin tăcere.
    refresh_expires_in: int | None = None


class AnafError(Exception):
    """ANAF nu a putut răspunde. Poartă dacă merită reîncercat."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class AnafAuthError(AnafError):
    """Certificatul nu mai autorizează: trebuie reautorizat un om.

    Se ține separat pentru că nicio reîncercare nu o rezolvă, iar remediul nu
    este tehnic: cineva trebuie să bage din nou tokenul USB în calculator.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class AnafMandateError(AnafError):
    """Nu avem dreptul să consultăm mesajele acestui CUI.

    Este eroarea centrală a integrării și **nu este a noastră**: clientul nu a
    depus împuternicirea în SPV, sau a expirat. Privește un singur client, deci
    nu oprește ceilalți, și nu se reîncearcă — se arată pe rândul lui, cu ce are
    de făcut cabinetul.
    """

    def __init__(self, tax_id: str) -> None:
        super().__init__(
            f"ANAF nu ne dă dreptul să citim mesajele CUI-ului {tax_id}. "
            "Clientul trebuie să depună împuternicirea în SPV (formular 150) "
            "pentru certificatul cabinetului.",
            retryable=False,
        )
        self.tax_id = tax_id


@runtime_checkable
class AnafClient(Protocol):
    """Ce trebuie să știe orice implementare a SPV-ului."""

    def exchange_code(self, code: str, redirect_uri: str) -> AnafTokens:
        """Schimbă codul primit după autorizare pe tokenuri."""
        ...

    def list_messages(
        self,
        refresh_token: str,
        *,
        tax_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> SpvPage:
        """Mesajele unui CUI dintr-o fereastră de timp.

        Fereastra este închisă la ambele capete pentru că ANAF nu dă tokenuri de
        continuare: singurul mod de a nu reciti tot este să ținem noi până unde
        am ajuns.
        """
        ...

    def download(self, refresh_token: str, *, message_id: str) -> bytes:
        """Arhiva ZIP a unui mesaj, exact cum o dă ANAF.

        `bytes`, nu flux, spre deosebire de OneDrive: aici arhiva este mică prin
        construcție — două fișiere XML — și trebuie oricum ținută întreagă ca să
        poată fi despachetată și stocată nemodificată.
        """
        ...

    def render_pdf(self, invoice_xml: bytes) -> bytes:
        """Factura în forma tipăribilă oficială a ANAF.

        Singura operație din integrare care **nu** cere autorizare: convertorul
        ANAF este public. Practic asta înseamnă că PDF-ul poate fi refăcut oricând
        din XML, deci un eșec aici nu are voie să piardă factura.
        """
        ...


__all__ = [
    "AnafAuthError",
    "AnafClient",
    "AnafError",
    "AnafMandateError",
    "AnafTokens",
    "SpvMessage",
    "SpvPage",
]
