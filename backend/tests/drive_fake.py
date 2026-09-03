"""Un OneDrive fals, în memorie.

Nu putem chema Microsoft dintr-un test — nici din CI, nici de pe laptop. Tot ce
contează trebuie deci să poată fi exercitat prin protocolul din
`app/services/drive/base.py`, iar acesta este partenerul de dialog.

Falsul este deliberat **strict**: refuză un token greșit, numără descărcările,
respectă paginarea delta. Un fals permisiv ar face testele să treacă și
integrarea să cadă la prima cerere reală.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import UTC, datetime
from typing import BinaryIO

from app.services.drive.base import (
    DeltaPage,
    DriveAccount,
    DriveAuthError,
    DriveError,
    DriveItem,
    DriveTokens,
)

VALID_REFRESH = "refresh-token-valid"
VALID_CODE = "cod-de-consimtamant"

#: Un PDF minimal, valid pentru validarea pe octeți. Sintetic (§70).
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
NOT_A_DOCUMENT = b"doar niste text intr-un fisier .txt"


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


class FakeDriveClient:
    """Implementarea de test. Ține fișierele pe dosare, ca OneDrive-ul real."""

    def __init__(self) -> None:
        #: `item_id` al dosarului → paginile pe care le va întoarce `delta`.
        self.pages: dict[str, list[DeltaPage]] = defaultdict(list)
        #: `item_id` al fișierului → conținut.
        self.contents: dict[str, bytes] = {}
        #: Dosarele întoarse de `list_folders`, pe părinte (`None` = rădăcina).
        self.folders: dict[str | None, list[DriveItem]] = {}
        #: Ce s-a descărcat, în ordine. Testele verifică **ce nu** s-a descărcat.
        self.downloaded: list[str] = []
        #: Se pune pe `True` ca să simulăm un consimțământ retras.
        self.revoked = False
        #: Eroare temporară la delta, pentru un dosar anume.
        self.delta_fails: set[str] = set()

    # ── Pregătire ───────────────────────────────────────────────────────────

    def put_file(self, item: DriveItem, content: bytes = PDF) -> None:
        self.contents[item.id] = content

    def put_page(self, folder_item_id: str, page: DeltaPage) -> None:
        self.pages[folder_item_id].append(page)

    def put_files(self, folder_item_id: str, items: list[DriveItem], *, token: str = "delta-1"):
        """Un dosar cu fișierele lui, într-o singură pagină."""
        for item in items:
            self.put_file(item)
        self.put_page(folder_item_id, DeltaPage(items=tuple(items), delta_token=token))

    # ── Protocol ────────────────────────────────────────────────────────────

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
            scopes=("offline_access", "User.Read", "Files.Read.All"),
        )

    def account(self, refresh_token: str) -> DriveAccount:
        self._check(refresh_token)
        return DriveAccount(email="contabil@cabinet.test", display_name="Cabinet Demo")

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
