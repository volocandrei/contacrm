"""Cine trimite, ales din configurare.

Un singur loc care decide, ca la stocare și la extracție: apelantul cere un
`EmailSender` și nu știe dacă în spate este SMTP sau nimic.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.mail.base import (
    EmailError,
    EmailMessage,
    EmailNotConfiguredError,
    EmailSender,
)
from app.services.mail.disabled import DisabledEmailSender
from app.services.mail.smtp import SmtpEmailSender


def build_email_sender() -> EmailSender:
    """Providerul potrivit configurării.

    Implicit **nu trimite**. O aplicație instalată fără setări de email nu are
    voie să scrie clienților din greșeală, iar un cabinet care importă o bază de
    test cu adrese reale ar face exact asta.
    """
    if settings.mail_is_configured:
        return SmtpEmailSender()
    return DisabledEmailSender()


__all__ = [
    "DisabledEmailSender",
    "EmailError",
    "EmailMessage",
    "EmailNotConfiguredError",
    "EmailSender",
    "SmtpEmailSender",
    "build_email_sender",
]
