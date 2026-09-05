"""Trimiterea prin SMTP.

**De ce SMTP înaintea altor drumuri.** Orice cabinet are deja un cont de email;
SMTP merge cu el fără consimțământ OAuth, fără aplicație înregistrată, fără nimic
de aprobat de un administrator. Microsoft Graph ar refolosi conexiunea existentă
pentru OneDrive și inbox, dar cere un scope nou și o reautorizare — deci este al
doilea provider, nu primul.

**Ce este scris cu grijă aici.**

- **Antetele nu primesc niciodată text necontrolat.** `Subject` trece prin
  `email.message.EmailMessage`, care îl codifică; adresa este validată înainte.
  Un `\\r\\n` strecurat într-un antet este cum se injectează destinatari.
- **Timeout explicit.** Fără el, un server de mail care nu răspunde ține firul
  ocupat până când îl întrerupe altcineva — iar aici firul este cel care
  răspunde unei cereri HTTP.
- **Parola nu ajunge în niciun mesaj de eroare.** `smtplib` pune uneori
  răspunsul serverului în excepție; textul care ajunge la utilizator este scris
  de noi.

*NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE.* Codul este acoperit de teste care
înlocuiesc `smtplib.SMTP`, deci se verifică **ce** trimite și cum se poartă la
eroare. Că un server real acceptă mesajul se poate ști doar cu un server real.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage as MimeMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.services.mail.base import EmailError, EmailMessage

logger = get_logger(__name__)

#: Cât așteptăm un server de mail. Peste atât, cererea HTTP care așteaptă
#: trimiterea a devenit oricum inutilizabilă.
TIMEOUT_SECONDS = 20


def _build(message: EmailMessage, sender: str) -> MimeMessage:
    mime = MimeMessage()
    mime["From"] = sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime.set_content(message.body)
    return mime


class SmtpEmailSender:
    name = "smtp"

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        sender: str | None = None,
        starttls: bool | None = None,
    ) -> None:
        self.host = settings.smtp_host if host is None else host
        self.port = settings.smtp_port if port is None else port
        self.user = settings.smtp_user if user is None else user
        self.password = settings.smtp_password if password is None else password
        self.sender = settings.mail_sender_address if sender is None else sender
        self.starttls = settings.smtp_starttls if starttls is None else starttls

    def send(self, message: EmailMessage) -> None:
        mime = _build(message, self.sender)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=TIMEOUT_SECONDS) as server:
                if self.starttls:
                    server.starttls(context=ssl.create_default_context())
                if self.user:
                    server.login(self.user, self.password)
                server.send_message(mime)
        except smtplib.SMTPAuthenticationError as exc:
            # Motivul contează pentru cine repară configurarea, dar răspunsul
            # serverului poate conține fragmente din credențiale.
            logger.error("smtp_auth_failed", host=self.host)
            raise EmailError(
                "Serverul de email a refuzat autentificarea. Verifică SMTP_USER și SMTP_PASSWORD."
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("smtp_send_failed", host=self.host, error=type(exc).__name__)
            raise EmailError(
                "Mesajul nu a putut fi trimis. Serverul de email nu a răspuns sau l-a respins."
            ) from exc

        # Destinatarul, nu conținutul: jurnalul spune cine a primit, nu ce (§52).
        logger.info("email_sent", provider=self.name, to=message.to)


__all__ = ["SmtpEmailSender"]
