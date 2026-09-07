"""O cutie poștală falsă, ca testele să nu ceară un server IMAP.

Aceeași idee ca `drive_fake.py`: implementează protocolul din
`app/services/imap/base.py` și atât. Ce verifică testele nu este `imaplib` —
acela este cod al bibliotecii standard — ci **deciziile noastre**: ce este
document, cine este clientul, ce se întâmplă la a doua citire a aceluiași mesaj,
ce se întâmplă când serverul reatribuie UID-urile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.services.imap.base import (
    ImapAttachment,
    ImapAuthError,
    ImapCredentials,
    ImapError,
    ImapFetch,
    ImapMessage,
)

#: Un PDF minim, dar peste pragul de mărime — ca să treacă de filtrul de logo-uri.
PDF_BYTES = b"%PDF-1.7\n" + b"0" * 9000 + b"\n%%EOF"

#: Sub prag: exact ce este logo-ul dintr-o semnătură de email.
LOGO_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def message(
    uid: int,
    *,
    sender: str = "contact@alfa.test",
    message_id: str | None = None,
    subject: str = "Facturi luna trecută",
    attachments: tuple[ImapAttachment, ...] | None = None,
) -> ImapMessage:
    """Un mesaj cu o factură atașată, dacă nu se cere altceva."""
    return ImapMessage(
        uid=uid,
        message_id=message_id or f"<mesaj-{uid}@alfa.test>",
        sender=sender,
        subject=subject,
        received_at=datetime(2026, 9, 3, 9, 30, tzinfo=UTC),
        attachments=attachments
        if attachments is not None
        else (ImapAttachment(index=1, name="factura.pdf", content=PDF_BYTES),),
    )


@dataclass
class FakeImapClient:
    """Ține mesajele în memorie și răspunde ca un server care se poartă frumos."""

    messages: list[ImapMessage] = field(default_factory=list)
    uid_validity: int = 1000
    #: Pornit, orice apel aruncă — cazul parolei schimbate între timp.
    auth_fails: bool = False
    #: Pornit, serverul răspunde dar dosarul nu se deschide.
    fails: bool = False
    #: Ce a cerut ultima oară sincronizarea. Testele se uită la el ca să verifice
    #: că reluarea pornește de unde trebuie.
    last_since_uid: int | None = None
    checked: list[str] = field(default_factory=list)

    def check(self, credentials: ImapCredentials, *, folder: str) -> None:
        self._guard()
        self.checked.append(f"{credentials.username}/{folder}")

    def fetch(
        self,
        credentials: ImapCredentials,
        *,
        folder: str,
        since_uid: int,
        limit: int,
        uid_validity: int | None = None,
    ) -> ImapFetch:
        self._guard()
        # Regula pe care o respectă și serverul adevărat: UID-urile memorate nu
        # mai înseamnă nimic dacă `UIDVALIDITY` s-a schimbat.
        start = since_uid if uid_validity is not None and uid_validity == self.uid_validity else 0
        self.last_since_uid = start

        fresh = sorted(
            (item for item in self.messages if item.uid > start), key=lambda item: item.uid
        )
        batch, has_more = fresh[:limit], len(fresh) > limit
        return ImapFetch(
            messages=tuple(batch),
            uid_validity=self.uid_validity,
            has_more=has_more,
            last_uid=batch[-1].uid if batch else 0,
        )

    def _guard(self) -> None:
        if self.auth_fails:
            raise ImapAuthError("Serverul a refuzat utilizatorul sau parola.")
        if self.fails:
            raise ImapError("Dosarul nu a putut fi deschis.")


__all__ = ["LOGO_BYTES", "PDF_BYTES", "FakeImapClient", "message"]
