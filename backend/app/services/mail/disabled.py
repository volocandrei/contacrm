"""Providerul care nu trimite nimic, și o spune dinainte.

Este cel implicit. O aplicație instalată fără setări de email nu are voie să
producă un buton care eșuează la apăsare — mesajul de aici ajunge pe ecran exact
așa cum este scris, deci spune ce lipsește, nu că „a eșuat trimiterea".
"""

from __future__ import annotations

from app.services.mail.base import EmailMessage, EmailNotConfiguredError


class DisabledEmailSender:
    name = "disabled"

    def send(self, message: EmailMessage) -> None:
        del message
        raise EmailNotConfiguredError(
            "Trimiterea de email nu este configurată. "
            "Pune NOTIFICATIONS_ENABLED=true și setările SMTP_*, apoi repornește."
        )


__all__ = ["DisabledEmailSender"]
