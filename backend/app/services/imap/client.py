"""Clientul IMAP adevărat, peste `imaplib` din biblioteca standard.

**De ce fără dependență nouă.** `imaplib` și `email` acoperă tot ce ne trebuie:
conectare TLS, căutare pe UID, descărcarea mesajului, decodarea părților. O
bibliotecă în plus ar fi adăugat o suprafață de actualizat pentru zero funcții
noi.

**Se citește, nu se scrie.** Dosarul se deschide `readonly=True`: mesajele nu se
marchează citite și nu se mută. Cutia poștală este a cabinetului; un program care
umblă prin ea își pierde dreptul de a mai fi lăsat acolo. Consecința este că nu
ne putem baza pe steagul „citit" ca să știm ce am luat — de aceea ținem minte
UID-ul.

*NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE.* Regulile de decizie sunt acoperite
de teste cu un client fals; că un server IMAP adevărat răspunde exact așa se vede
la prima cutie conectată.
"""

from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

from app.core.logging import get_logger
from app.services.imap.base import (
    ImapAttachment,
    ImapAuthError,
    ImapCredentials,
    ImapError,
    ImapFetch,
    ImapMessage,
)

logger = get_logger(__name__)

#: Cât așteptăm un server care nu răspunde. Peste atât, bătaia de cron ar depăși
#: oricum timpul maxim al platformei.
TIMEOUT_SECONDS = 30

#: `UIDVALIDITY` vine în răspunsul la `SELECT`, între paranteze drepte.
_UID_VALIDITY = re.compile(rb"UIDVALIDITY (\d+)")


def _text(raw: str | None) -> str:
    """Un antet decodat. `=?UTF-8?B?...?=` nu se arată nimănui așa cum vine."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        # Un antet stricat nu are voie să oprească preluarea unui atașament bun.
        return raw.strip()


def _address(raw: str | None) -> str:
    """Adresa dintre paranteze unghiulare, sau tot antetul dacă nu are.

    Se ia adresa goală, fără numele afișat: potrivirea pe client se face pe
    `contacts.email`, iar „Ion Popescu <ion@firma.ro>" nu s-ar potrivi cu nimic.
    """
    decoded = _text(raw)
    match = re.search(r"<([^>]+)>", decoded)
    return (match.group(1) if match else decoded).strip()


def _received_at(message: Message) -> datetime | None:
    try:
        return parsedate_to_datetime(message.get("Date", ""))
    except (TypeError, ValueError):
        # Un `Date` invalid nu invalidează mesajul. Intake-ul pune ora curentă.
        return None


def _attachments(message: Message) -> tuple[ImapAttachment, ...]:
    """Părțile care sunt fișiere, nu textul mesajului.

    Se ia orice parte care are un nume de fișier: unele programe de mail nu pun
    `Content-Disposition`, iar o factură atașată de ele ar fi fost pierdută tăcut.
    Pragul de mărime și restul filtrelor se aplică mai târziu, în partea comună.
    """
    found: list[ImapAttachment] = []
    for index, part in enumerate(message.walk()):
        if part.get_content_maintype() == "multipart":
            continue
        filename = _text(part.get_filename())
        disposition = (part.get("Content-Disposition") or "").lower()
        if not filename and "attachment" not in disposition:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            continue
        found.append(
            ImapAttachment(
                index=index,
                name=filename or f"atasament-{index}",
                content=payload,
                is_inline="inline" in disposition,
            )
        )
    return tuple(found)


class ImapMailClient:
    """Implementarea peste `imaplib`. Nu ține conexiuni deschise între apeluri."""

    def check(self, credentials: ImapCredentials, *, folder: str) -> None:
        with self._open(credentials) as connection:
            self._select(connection, folder)

    def fetch(
        self,
        credentials: ImapCredentials,
        *,
        folder: str,
        since_uid: int,
        limit: int,
        uid_validity: int | None = None,
    ) -> ImapFetch:
        with self._open(credentials) as connection:
            current = self._select(connection, folder)
            # UID-urile sunt unice doar cât timp `UIDVALIDITY` nu se schimbă. Când
            # serverul o schimbă — o restaurare, o migrare de cutie — numerele se
            # reatribuie de la capăt, iar continuarea de la `since_uid` ar sări
            # peste tot ce a venit între timp, tăcut.
            start = since_uid if uid_validity is not None and uid_validity == current else 0
            uids = self._search(connection, start)
            if not uids:
                return ImapFetch(uid_validity=current)

            batch, has_more = uids[:limit], len(uids) > limit
            messages = tuple(self._message(connection, uid) for uid in batch)
            return ImapFetch(
                messages=tuple(item for item in messages if item is not None),
                uid_validity=current,
                has_more=has_more,
                last_uid=batch[-1],
            )

    # ── Legătura ────────────────────────────────────────────────────────────

    def _open(self, credentials: ImapCredentials) -> imaplib.IMAP4:
        try:
            connection: imaplib.IMAP4 = (
                imaplib.IMAP4_SSL(credentials.host, credentials.port, timeout=TIMEOUT_SECONDS)
                if credentials.use_ssl
                else imaplib.IMAP4(credentials.host, credentials.port, timeout=TIMEOUT_SECONDS)
            )
        except OSError as exc:
            # Adresa serverului, niciodată parola (§73).
            raise ImapError(f"Nu s-a putut deschide conexiunea către {credentials.host}.") from exc

        try:
            connection.login(credentials.username, credentials.password)
        except imaplib.IMAP4.error as exc:
            connection.logout()
            raise ImapAuthError(
                "Serverul a refuzat utilizatorul sau parola. La Gmail și Microsoft "
                "este nevoie de o parolă de aplicație, nu de parola contului."
            ) from exc
        return connection

    def _select(self, connection: imaplib.IMAP4, folder: str) -> int | None:
        """Deschide dosarul, în citire, și întoarce `UIDVALIDITY`."""
        status, _ = connection.select(f'"{folder}"', readonly=True)
        if status != "OK":
            raise ImapError(f"Dosarul „{folder}” nu a putut fi deschis.")

        # `UIDVALIDITY` vine printre răspunsurile netagged ale lui SELECT.
        for line in connection.untagged_responses.get("OK", []):
            if isinstance(line, bytes):
                match = _UID_VALIDITY.search(line)
                if match:
                    return int(match.group(1))
        return None

    def _search(self, connection: imaplib.IMAP4, since_uid: int) -> list[int]:
        """UID-urile mai mari decât cel citit ultima dată.

        **De ce se filtrează și după căutare.** `UID SEARCH n:*` întoarce mereu
        cel puțin ultimul mesaj din dosar, chiar dacă UID-ul lui este mai mic
        decât `n` — este o ciudățenie a protocolului, nu a serverului. Fără
        filtrul de aici, ultimul mesaj ar fi fost recitit la fiecare tur.
        """
        # `imaplib` cere criteriul ca argumente separate; charset-ul lipsă se dă
        # ca text gol, nu ca `None`, deși ambele produc aceeași comandă.
        status, data = connection.uid("SEARCH", f"{since_uid + 1}:*")
        if status != "OK" or not data or not data[0]:
            return []
        return sorted(uid for uid in (int(item) for item in data[0].split()) if uid > since_uid)

    def _message(self, connection: imaplib.IMAP4, uid: int) -> ImapMessage | None:
        status, data = connection.uid("FETCH", str(uid), "(RFC822)")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            logger.warning("imap_fetch_failed", uid=uid)
            return None

        parsed = email.message_from_bytes(data[0][1])
        return ImapMessage(
            uid=uid,
            # Fără `Message-ID` rămâne UID-ul: mai slab, dar mai bun decât nimic.
            message_id=_text(parsed.get("Message-ID")) or f"uid-{uid}",
            sender=_address(parsed.get("From")),
            subject=_text(parsed.get("Subject")),
            received_at=_received_at(parsed),
            attachments=_attachments(parsed),
        )


__all__ = ["TIMEOUT_SECONDS", "ImapMailClient"]
