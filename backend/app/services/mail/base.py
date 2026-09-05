"""Trimiterea de email, ca seam de provider (ADR-005).

**De ce un seam și nu `smtplib` chemat direct din rută.** Aceeași lecție ca la
stocare și la OCR: providerul se schimbă (SMTP azi, Microsoft Graph mâine, un
serviciu tranzacțional poimâine), dar apelantul nu are voie să se schimbe odată
cu el. Iar testele trebuie să poată verifica **ce** s-a trimis fără să trimită
nimic nimănui.

**Ce nu face niciun provider de aici.** Nu compune mesaje. Textul vine din
`document_request.py`, unde este conținut de business, verificat de teste. Un
provider care ar adăuga o formulă de politețe ar produce, în aceeași zi, două
mesaje diferite de la același cabinet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class EmailError(Exception):
    """Ceva a împiedicat trimiterea. Poartă un mesaj citibil de un om."""


class EmailNotConfiguredError(EmailError):
    """Nu există prin ce trimite.

    Separată de restul erorilor pentru că este singura care **nu** este o
    defecțiune: cineva încă nu a pus setările. Ecranul spune ce lipsește, nu
    „a eșuat trimiterea".
    """


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Un mesaj gata de trimis.

    Doar text simplu, deliberat. Un mesaj HTML către un client se rupe în
    jumătate din clienții de email, iar solicitarea de documente este o listă —
    forma ei naturală este textul.
    """

    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    """Interfața pe care o cheamă aplicația."""

    name: str

    def send(self, message: EmailMessage) -> None:
        """Trimite, sau ridică `EmailError`.

        Nu întoarce nimic: „a plecat" este singurul rezultat de succes, iar orice
        altceva este o eroare cu motiv.
        """
        ...


__all__ = ["EmailError", "EmailMessage", "EmailNotConfiguredError", "EmailSender"]
