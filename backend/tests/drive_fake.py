"""Un cont Microsoft fals, în memorie: OneDrive și cutia poștală.

Nu putem chema Microsoft dintr-un test — nici din CI, nici de pe laptop. Tot ce
contează trebuie deci să poată fi exercitat prin protocolul din
`app/services/microsoft/base.py`, iar acesta este partenerul de dialog.

Falsul este deliberat **strict**: refuză un token greșit, numără descărcările,
respectă paginarea delta. Un fals permisiv ar face testele să treacă și
integrarea să cadă la prima cerere reală.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import UTC, datetime
from typing import BinaryIO

from app.services.microsoft.base import (
    DeltaPage,
    DriveAccount,
    DriveAuthError,
    DriveError,
    DriveItem,
    DriveTokens,
    MailAttachment,
    MailFolderInfo,
    MailMessage,
    MailPage,
)

VALID_REFRESH = "refresh-token-valid"
VALID_CODE = "cod-de-consimtamant"

#: Un PDF minimal, valid pentru validarea pe octeți. Sintetic (§70).
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
NOT_A_DOCUMENT = b"doar niste text intr-un fisier .txt"


# ── Constructori de conținut ─────────────────────────────────────────────────


def file_item(
    item_id: str,
    name: str,
    *,
    drive_id: str = "drive-1",
    folder: str = "/Clienti/Alfa Conta SRL",
    modified: datetime | None = None,
) -> DriveItem:
    return DriveItem(
        id=item_id,
        name=name,
        path=f"{folder}/{name}",
        drive_id=drive_id,
        is_folder=False,
        size=len(PDF),
        mime_type="application/pdf",
        modified_at=modified or datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )


def folder_item(item_id: str, name: str, *, drive_id: str = "drive-1") -> DriveItem:
    return DriveItem(
        id=item_id,
        name=name,
        path=f"/Clienti/{name}",
        drive_id=drive_id,
        is_folder=True,
    )


def mail_attachment(
    attachment_id: str,
    name: str,
    *,
    size: int = 120_000,
    inline: bool = False,
) -> MailAttachment:
    return MailAttachment(
        id=attachment_id,
        name=name,
        size=size,
        content_type="application/pdf",
        is_inline=inline,
    )


def mail_message(
    message_id: str,
    sender: str,
    *,
    subject: str = "Documente luna aceasta",
    attachments: tuple[MailAttachment, ...] = (),
    received: datetime | None = None,
) -> MailMessage:
    return MailMessage(
        id=message_id,
        sender=sender,
        subject=subject,
        received_at=received or datetime(2026, 8, 14, 10, 30, tzinfo=UTC),
        attachments=attachments,
    )


class FakeDriveClient:
    """Implementarea de test, pentru amândouă sursele."""

    def __init__(self) -> None:
        # ── OneDrive ────────────────────────────────────────────────────────
        #: `item_id` al dosarului → paginile pe care le va întoarce `delta`.
        self.pages: dict[str, list[DeltaPage]] = defaultdict(list)
        #: `item_id` al fișierului → conținut.
        self.contents: dict[str, bytes] = {}
        #: Dosarele întoarse de `list_folders`, pe părinte (`None` = rădăcina).
        self.folders: dict[str | None, list[DriveItem]] = {}
        #: Eroare temporară la delta, pentru un dosar anume.
        self.delta_fails: set[str] = set()

        # ── Cutia poștală ───────────────────────────────────────────────────
        self.mail_folders: list[MailFolderInfo] = []
        self.mail_pages: dict[str, list[MailPage]] = defaultdict(list)
        self.attachment_contents: dict[str, bytes] = {}
        self.mail_delta_fails: set[str] = set()

        # ── Comun ───────────────────────────────────────────────────────────
        #: Ce s-a descărcat, în ordine. Testele verifică **ce nu** s-a descărcat.
        self.downloaded: list[str] = []
        #: Se pune pe `True` ca să simulăm un consimțământ retras.
        self.revoked = False

    # ── Pregătire ───────────────────────────────────────────────────────────

    def put_file(self, item: DriveItem, content: bytes = PDF) -> None:
        self.contents[item.id] = content

    def put_page(self, folder_item_id: str, page: DeltaPage) -> None:
        self.pages[folder_item_id].append(page)

    def put_files(
        self, folder_item_id: str, items: list[DriveItem], *, token: str = "delta-1"
    ) -> None:
        """Un dosar cu fișierele lui, într-o singură pagină."""
        for item in items:
            self.put_file(item)
        self.put_page(folder_item_id, DeltaPage(items=tuple(items), delta_token=token))

    def put_mail(self, folder_id: str, page: MailPage) -> None:
        self.mail_pages[folder_id].append(page)

    def put_attachment(self, attachment_id: str, content: bytes = PDF) -> None:
        self.attachment_contents[attachment_id] = content

    def put_messages(
        self, folder_id: str, messages: list[MailMessage], *, token: str = "mail-delta-1"
    ) -> None:
        """Un dosar de email cu mesajele lui, cu tot cu conținutul atașamentelor."""
        for message in messages:
            for attachment in message.attachments:
                self.attachment_contents.setdefault(attachment.id, PDF)
        self.put_mail(folder_id, MailPage(messages=tuple(messages), delta_token=token))

    # ── Protocol: comun ─────────────────────────────────────────────────────

    def _check(self, refresh_token: str) -> None:
        if self.revoked:
            raise DriveAuthError("Consimțământul a fost retras. Reconectează contul.")
        if refresh_token != VALID_REFRESH:
            raise DriveAuthError("Token invalid. Reconectează contul.")

    def exchange_code(self, code: str, redirect_uri: str) -> DriveTokens:
        if code != VALID_CODE:
            raise DriveAuthError("Microsoft a refuzat autentificarea: cod invalid.")
        return DriveTokens(
            access_token="access-token",
            refresh_token=VALID_REFRESH,
            scopes=("offline_access", "User.Read", "Files.Read.All", "Mail.Read"),
        )

    def account(self, refresh_token: str) -> DriveAccount:
        self._check(refresh_token)
        return DriveAccount(email="contabil@cabinet.test", display_name="Cabinet Demo")

    # ── Protocol: OneDrive ──────────────────────────────────────────────────

    def list_folders(self, refresh_token: str, *, parent_id: str | None) -> tuple[DriveItem, ...]:
        self._check(refresh_token)
        return tuple(self.folders.get(parent_id, ()))

    def delta(
        self, refresh_token: str, *, drive_id: str, item_id: str, token: str | None, limit: int
    ) -> DeltaPage:
        self._check(refresh_token)
        if item_id in self.delta_fails:
            raise DriveError("Microsoft Graph a răspuns 503.", retryable=True)

        queued = self.pages.get(item_id)
        if not queued:
            # Nimic nou. Tokenul primit se întoarce, ca în Graph.
            return DeltaPage(items=(), delta_token=token or "delta-gol")
        return queued.pop(0)

    def download(self, refresh_token: str, *, drive_id: str, item_id: str) -> BinaryIO:
        self._check(refresh_token)
        content = self.contents.get(item_id)
        if content is None:
            raise DriveError("Fișierul nu mai există.", retryable=False)
        self.downloaded.append(item_id)
        return io.BytesIO(content)

    # ── Protocol: cutia poștală ─────────────────────────────────────────────

    def list_mail_folders(self, refresh_token: str) -> tuple[MailFolderInfo, ...]:
        self._check(refresh_token)
        return tuple(self.mail_folders)

    def mail_delta(
        self, refresh_token: str, *, folder_id: str, token: str | None, limit: int
    ) -> MailPage:
        self._check(refresh_token)
        if folder_id in self.mail_delta_fails:
            raise DriveError("Microsoft Graph a răspuns 503.", retryable=True)

        queued = self.mail_pages.get(folder_id)
        if not queued:
            return MailPage(messages=(), delta_token=token or "mail-delta-gol")
        return queued.pop(0)

    def download_attachment(
        self, refresh_token: str, *, message_id: str, attachment_id: str
    ) -> BinaryIO:
        self._check(refresh_token)
        content = self.attachment_contents.get(attachment_id)
        if content is None:
            raise DriveError("Atașamentul nu mai există.", retryable=False)
        self.downloaded.append(attachment_id)
        return io.BytesIO(content)
