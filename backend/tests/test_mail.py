"""Trimiterea de email, fără să plece nimic nicăieri.

`smtplib.SMTP` este înlocuit cu un dublu care reține ce i s-a dat. Se verifică
deci exact ce se poate verifica fără un server real: **ce** se trimite, în ce
ordine se fac pașii, și ce se întâmplă la fiecare fel de eșec.

*NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE* rămâne adevărat pentru ultima
verigă: că un server de mail adevărat acceptă mesajul se poate ști doar cu un
server de mail adevărat.
"""

from __future__ import annotations

import smtplib
from types import TracebackType
from typing import Any, ClassVar

import pytest

from app.services.mail import (
    DisabledEmailSender,
    EmailError,
    EmailMessage,
    EmailNotConfiguredError,
    SmtpEmailSender,
    build_email_sender,
)


class FakeSmtp:
    """Un `smtplib.SMTP` care nu deschide nicio conexiune."""

    instances: ClassVar[list[FakeSmtp]] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in_as: str | None = None
        self.sent: list[Any] = []
        self.closed = False
        FakeSmtp.instances.append(self)

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.closed = True

    def starttls(self, context: Any = None) -> None:
        del context
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        del password
        self.logged_in_as = user

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _clean() -> None:
    FakeSmtp.instances.clear()


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSmtp]:
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    return FakeSmtp


def a_message() -> EmailMessage:
    return EmailMessage(
        to="client@exemplu.test",
        subject="Documente necesare pentru august 2026",
        body="Bună ziua,\n\nMai avem nevoie de:\n- 2 facturi\n",
    )


class TestWhatGetsSent:
    def test_the_message_reaches_the_server_intact(self, smtp: type[FakeSmtp]) -> None:
        sender = SmtpEmailSender(
            host="mail.exemplu.test", port=587, user="cabinet@exemplu.test", password="secret"
        )

        sender.send(a_message())

        assert len(smtp.instances) == 1
        sent = smtp.instances[0].sent[0]
        assert sent["To"] == "client@exemplu.test"
        assert sent["Subject"] == "Documente necesare pentru august 2026"
        assert "Mai avem nevoie de" in sent.get_content()

    def test_the_sender_falls_back_to_the_account_address(self, smtp: type[FakeSmtp]) -> None:
        """`SMTP_FROM` gol este cazul obișnuit: la aproape toate serverele,
        adresa expeditor **este** contul."""
        sender = SmtpEmailSender(
            host="mail.exemplu.test", user="cabinet@exemplu.test", password="x", sender=""
        )
        sender.sender = sender.user

        sender.send(a_message())

        assert smtp.instances[0].sent[0]["From"] == "cabinet@exemplu.test"

    def test_the_subject_is_encoded_not_pasted_into_a_header(self, smtp: type[FakeSmtp]) -> None:
        """Diacriticele într-un antet trebuie codificate.

        Lipite brut, mesajul ajunge cu subiectul stricat sau respins de server —
        și este aceeași ușă prin care se injectează destinatari, dacă textul ar
        conține un sfârșit de linie.
        """
        sender = SmtpEmailSender(host="mail.exemplu.test", user="", password="")

        sender.send(
            EmailMessage(to="a@b.test", subject="Situații financiare — august", body="text")
        )

        raw = smtp.instances[0].sent[0].as_string()
        assert "Situații financiare" not in raw.split("\n\n", 1)[0]

    def test_starttls_is_used_when_asked(self, smtp: type[FakeSmtp]) -> None:
        SmtpEmailSender(host="h", user="", password="", starttls=True).send(a_message())

        assert smtp.instances[0].started_tls is True

    def test_no_login_without_a_user(self, smtp: type[FakeSmtp]) -> None:
        """Unele relee interne nu cer autentificare; un `login` cu utilizator gol
        ar fi fost refuzat de server."""
        SmtpEmailSender(host="h", user="", password="").send(a_message())

        assert smtp.instances[0].logged_in_as is None

    def test_the_connection_has_a_timeout(self, smtp: type[FakeSmtp]) -> None:
        """Fără el, un server care nu răspunde ține ocupat firul care servește o
        cerere HTTP."""
        SmtpEmailSender(host="h", user="", password="").send(a_message())

        assert smtp.instances[0].timeout is not None


class TestWhenItFails:
    def test_a_refused_login_says_which_settings_to_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Refusing(FakeSmtp):
            def login(self, user: str, password: str) -> None:
                raise smtplib.SMTPAuthenticationError(535, b"5.7.8 parola gresita")

        monkeypatch.setattr(smtplib, "SMTP", Refusing)
        sender = SmtpEmailSender(host="h", user="u", password="p")

        with pytest.raises(EmailError) as caught:
            sender.send(a_message())

        assert "SMTP_USER" in str(caught.value)
        # Răspunsul serverului poate conține fragmente din credențiale; textul
        # care ajunge la om este scris de noi.
        assert "parola gresita" not in str(caught.value)

    def test_a_dead_server_is_an_email_error_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*args: object, **kwargs: object) -> None:
            raise OSError("connection refused")

        monkeypatch.setattr(smtplib, "SMTP", explode)

        with pytest.raises(EmailError):
            SmtpEmailSender(host="h", user="", password="").send(a_message())


class TestWhenItIsNotConfigured:
    def test_the_default_provider_refuses_and_says_what_is_missing(self) -> None:
        """Nu o defecțiune: cineva încă nu a pus setările.

        Mesajul ajunge pe ecran exact așa cum este scris, deci trebuie să spună
        ce lipsește, nu că „a eșuat trimiterea".
        """
        with pytest.raises(EmailNotConfiguredError) as caught:
            DisabledEmailSender().send(a_message())

        assert "NOTIFICATIONS_ENABLED" in str(caught.value)
        assert "SMTP_" in str(caught.value)

    def test_nothing_is_sent_by_default(self) -> None:
        """O aplicație instalată fără setări nu are voie să scrie clienților.

        Un cabinet care importă o bază de test cu adrese reale ar face exact asta.
        """
        assert isinstance(build_email_sender(), DisabledEmailSender)

    def test_the_switch_alone_is_not_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Comutatorul fără server ar produce un buton care eșuează la apăsare."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "")

        assert isinstance(build_email_sender(), DisabledEmailSender)

    def test_both_together_pick_smtp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "mail.exemplu.test")

        assert isinstance(build_email_sender(), SmtpEmailSender)
