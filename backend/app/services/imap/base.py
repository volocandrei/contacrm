"""Ce înțelege aplicația dintr-o cutie IMAP, și ce nu.

Interfața stă separat de implementare din același motiv ca la Microsoft: testele
înlocuiesc clientul cu unul fals, iar codul de business nu trebuie să știe că în
spate există `imaplib`. Un test care ar cere o cutie poștală adevărată nu s-ar
rula niciodată.

**Atașamentele vin cu conținut cu tot**, spre deosebire de Graph, unde se descarcă
separat. Nu este o scăpare de proiectare: IMAP livrează mesajul întreg oricum, iar
o a doua cerere pentru fiecare atașament ar fi însemnat să-l descărcăm de două
ori. Prețul este că un mesaj mare stă o clipă în memorie — de aceea lotul este
mic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class ImapError(Exception):
    """Ceva n-a mers cu cutia poștală. Mesajul ajunge pe ecran, deci e în română."""


class ImapAuthError(ImapError):
    """Serverul a refuzat utilizatorul sau parola.

    Se deosebește de restul pentru că cere altceva de la om: nu „mai încearcă", ci
    „schimbă parola din setări". La Gmail și Microsoft, cel mai des înseamnă că
    s-a folosit parola contului în loc de o parolă de aplicație.
    """


@dataclass(frozen=True, slots=True)
class ImapAttachment:
    """Un atașament, cu tot cu octeții lui."""

    #: Poziția în mesaj. IMAP nu dă identificatori de atașament, iar poziția este
    #: singurul lucru stabil la o recitire a aceluiași mesaj.
    index: int
    name: str
    content: bytes
    is_inline: bool = False

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class ImapMessage:
    """Un mesaj, redus la ce contează pentru intake."""

    uid: int
    #: `Message-ID` din antet, dacă există.
    #:
    #: **De ce el și nu UID-ul.** UID-ul este unic doar în dosarul acela și doar
    #: cât timp `UIDVALIDITY` nu se schimbă. Când serverul reatribuie numerele,
    #: preluarea reia dosarul de la început — iar atunci `Message-ID` este singurul
    #: lucru care ține minte că mesajul a mai intrat o dată.
    message_id: str
    sender: str
    subject: str
    received_at: datetime | None = None
    attachments: tuple[ImapAttachment, ...] = ()


@dataclass(frozen=True, slots=True)
class ImapFetch:
    """Ce s-a citit dintr-un dosar, într-un tur."""

    messages: tuple[ImapMessage, ...] = ()
    #: `UIDVALIDITY` al dosarului acum. Schimbat față de ultima dată, UID-urile
    #: memorate nu mai înseamnă nimic.
    uid_validity: int | None = None
    #: Au mai rămas mesaje peste lot. Turul următor le ia.
    has_more: bool = False
    #: Cel mai mare UID citit acum. Zero când n-a venit nimic.
    last_uid: int = 0


@dataclass(frozen=True, slots=True)
class ImapCredentials:
    """Cum se ajunge la cutie. Parola nu ajunge niciodată în loguri (§73)."""

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    use_ssl: bool = True

    def __str__(self) -> str:
        # Fără parolă, orice s-ar întâmpla cu obiectul ăsta.
        return f"{self.username}@{self.host}:{self.port}"


class ImapClient(Protocol):
    """Ce are nevoie aplicația de la o cutie poștală. Atât, nimic mai mult."""

    def fetch(
        self,
        credentials: ImapCredentials,
        *,
        folder: str,
        since_uid: int,
        limit: int,
        uid_validity: int | None = None,
    ) -> ImapFetch:
        """Mesajele cu UID mai mare decât `since_uid`, cel mult `limit`.

        **`uid_validity` este cea de la turul trecut**, nu cea de acum. Dacă
        dosarul o are pe alta, UID-urile au fost reatribuite între timp și
        `since_uid` nu mai înseamnă nimic: dosarul se citește de la început.
        Comparația se face aici, fiindcă valoarea de acum se află abia după ce
        dosarul a fost deschis — adică prea târziu pentru cine cheamă.
        """
        ...

    def check(self, credentials: ImapCredentials, *, folder: str) -> None:
        """Se conectează și deschide dosarul. Aruncă dacă nu merge.

        Există separat de `fetch` pentru butonul de test: cine adaugă o cutie
        trebuie să afle **atunci** că parola e greșită, nu peste o zi, din faptul
        că n-a venit niciun document.
        """
        ...


__all__ = [
    "ImapAttachment",
    "ImapAuthError",
    "ImapClient",
    "ImapCredentials",
    "ImapError",
    "ImapFetch",
    "ImapMessage",
]
