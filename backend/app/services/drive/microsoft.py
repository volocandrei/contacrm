"""Microsoft Graph — singura parte care chiar vorbește cu Microsoft.

Este deliberat subțire: construiește URL-uri, trimite cereri, citește JSON. Toată
logica — ce se face cu fișierele, cum se leagă de clienți, ce se întâmplă la
eroare — stă în `sync.py` și se testează cu un client fals.

Motivul este că partea asta **nu poate fi testată** fără credențiale reale și un
cont Microsoft. Ce nu se poate testa trebuie să fie mic și plictisitor.

**Tokenul de acces nu se stochează.** Trăiește o oră; îl cerem din refresh token
la fiecare tur și îl ținem doar în memoria procesului, cât durează sincronizarea.
Un token de acces salvat este un secret în plus de protejat, pentru nimic.

Scope-urile cerute:
  `Files.Read.All`   — citește fișierele la care are acces contul, inclusiv
                       dosarele partajate de clienți. **Doar citire**: nu avem ce
                       căuta scriind în OneDrive-ul altcuiva.
  `User.Read`        — cine este contul, ca să se vadă pe ecran.
  `offline_access`   — fără el nu primim refresh token, deci nu există
                       sincronizare automată, doar una manuală la fiecare oră.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, BinaryIO, Final
from urllib.parse import urlencode

import httpx

from app.core.logging import get_logger
from app.services.drive.base import (
    DeltaPage,
    DriveAccount,
    DriveAuthError,
    DriveError,
    DriveItem,
    DriveTokens,
)

logger = get_logger(__name__)

GRAPH: Final = "https://graph.microsoft.com/v1.0"
LOGIN: Final = "https://login.microsoftonline.com"

SCOPES: Final = ("offline_access", "User.Read", "Files.Read.All")

#: Cât așteptăm un răspuns. Descărcarea unui fișier poate dura; o listare nu.
TIMEOUT: Final = httpx.Timeout(30.0, read=120.0)

#: Coduri la care o reîncercare chiar poate reuși.
RETRYABLE_STATUS: Final = frozenset({429, 500, 502, 503, 504})


def authorize_url(*, client_id: str, tenant: str, redirect_uri: str, state: str) -> str:
    """Adresa la care se trimite administratorul ca să dea consimțământul."""
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(SCOPES),
            "state": state,
            # Forțează afișarea ecranului de cont: altfel Microsoft reconectează
            # tăcut contul deja logat în browser, iar administratorul nu are cum
            # să aleagă alt cont decât al lui.
            "prompt": "select_account",
        }
    )
    return f"{LOGIN}/{tenant}/oauth2/v2.0/authorize?{query}"


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_item(payload: dict[str, Any], *, drive_id: str) -> DriveItem:
    parent = payload.get("parentReference") or {}
    parent_path = parent.get("path") or ""
    name = str(payload.get("name") or "")
    file_info = payload.get("file") or {}

    return DriveItem(
        id=str(payload.get("id") or ""),
        name=name,
        # Graph dă calea ca `/drive/root:/Clienți/Alfa`; partea de după `:` este
        # ce recunoaște un om.
        path=f"{parent_path.split(':', 1)[-1]}/{name}".replace("//", "/"),
        drive_id=str(parent.get("driveId") or drive_id),
        is_folder="folder" in payload,
        size=int(payload.get("size") or 0),
        mime_type=file_info.get("mimeType"),
        modified_at=_parse_datetime(payload.get("lastModifiedDateTime")),
        deleted="deleted" in payload,
    )


class MicrosoftGraphClient:
    """Clientul real. Tot ce e greu de testat stă aici, și e cât mai puțin."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        tenant: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant = tenant
        # Injectabil, ca testele să poată pune un transport fals fără să atingă rețeaua.
        self._transport = transport

    # ── Autentificare ───────────────────────────────────────────────────────

    def _http(self) -> httpx.Client:
        return httpx.Client(timeout=TIMEOUT, transport=self._transport, follow_redirects=True)

    def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        url = f"{LOGIN}/{self._tenant}/oauth2/v2.0/token"
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": " ".join(SCOPES),
            **data,
        }
        try:
            with self._http() as http:
                response = http.post(url, data=payload)
        except httpx.HTTPError as exc:
            raise DriveError(f"Microsoft nu a răspuns: {exc}") from exc

        if response.status_code >= 400:
            # Corpul conține `error_description`, care este singurul lucru util
            # când consimțământul eșuează. Nu conține secretul nostru.
            detail = response.json().get("error_description", response.text)[:300]
            raise DriveAuthError(f"Microsoft a refuzat autentificarea: {detail}")

        body: dict[str, Any] = response.json()
        return body

    def exchange_code(self, code: str, redirect_uri: str) -> DriveTokens:
        body = self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        )
        refresh = body.get("refresh_token")
        if not refresh:
            # Fără `offline_access` Microsoft nu îl trimite, iar sincronizarea
            # automată ar fi imposibilă — se spune acum, nu peste o oră.
            raise DriveAuthError(
                "Microsoft nu a trimis un refresh token. Verifică scope-ul `offline_access`."
            )
        return DriveTokens(
            access_token=str(body.get("access_token") or ""),
            refresh_token=str(refresh),
            scopes=tuple(str(body.get("scope") or "").split()),
        )

    def _access_token(self, refresh_token: str) -> str:
        body = self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
        token = body.get("access_token")
        if not token:
            raise DriveAuthError("Microsoft nu a trimis un token de acces.")
        return str(token)

    # ── Cereri Graph ────────────────────────────────────────────────────────

    def _get(self, access_token: str, url: str) -> dict[str, Any]:
        try:
            with self._http() as http:
                response = http.get(url, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise DriveError(f"Microsoft Graph nu a răspuns: {exc}") from exc

        if response.status_code in {401, 403}:
            raise DriveAuthError(
                "Microsoft a refuzat accesul. Reconectează contul sau verifică permisiunile."
            )
        if response.status_code >= 400:
            raise DriveError(
                f"Microsoft Graph a răspuns {response.status_code}.",
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        body: dict[str, Any] = response.json()
        return body

    def account(self, refresh_token: str) -> DriveAccount:
        body = self._get(self._access_token(refresh_token), f"{GRAPH}/me")
        return DriveAccount(
            # Un cont de firmă are `mail`; unul personal doar `userPrincipalName`.
            email=str(body.get("mail") or body.get("userPrincipalName") or ""),
            display_name=body.get("displayName"),
        )

    def list_folders(self, refresh_token: str, *, parent_id: str | None) -> tuple[DriveItem, ...]:
        access = self._access_token(refresh_token)
        where = "root" if parent_id is None else f"items/{parent_id}"
        body = self._get(access, f"{GRAPH}/me/drive/{where}/children?$top=200")

        children = body.get("value") or []
        drive_id = str((body.get("parentReference") or {}).get("driveId") or "")
        items = (_to_item(child, drive_id=drive_id) for child in children)
        # Doar dosare: ecranul de mapare nu are ce face cu fișiere.
        return tuple(item for item in items if item.is_folder)

    def delta(
        self, refresh_token: str, *, drive_id: str, item_id: str, token: str | None, limit: int
    ) -> DeltaPage:
        access = self._access_token(refresh_token)
        # Tokenul stocat este chiar URL-ul următoarei cereri: Graph îl dă întreg,
        # iar reconstruirea lui de mână ar însemna să ghicim ce parametri a pus el.
        url = token or f"{GRAPH}/drives/{drive_id}/items/{item_id}/delta?$top={limit}"

        body = self._get(access, url)
        items = tuple(_to_item(entry, drive_id=drive_id) for entry in body.get("value") or [])

        next_link = body.get("@odata.nextLink")
        delta_link = body.get("@odata.deltaLink")
        return DeltaPage(
            items=items,
            # Cât timp mai sunt pagini, tokenul de continuat este `nextLink`; la
            # capăt, `deltaLink` este cel de păstrat pentru turul următor.
            delta_token=str(next_link or delta_link) if (next_link or delta_link) else None,
            has_more=bool(next_link),
        )

    def download(self, refresh_token: str, *, drive_id: str, item_id: str) -> BinaryIO:
        access = self._access_token(refresh_token)
        url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/content"
        try:
            with self._http() as http:
                response = http.get(url, headers={"Authorization": f"Bearer {access}"})
        except httpx.HTTPError as exc:
            raise DriveError(f"Descărcarea a eșuat: {exc}") from exc

        if response.status_code in {401, 403}:
            raise DriveAuthError("Microsoft a refuzat descărcarea. Reconectează contul.")
        if response.status_code >= 400:
            raise DriveError(
                f"Descărcarea a răspuns {response.status_code}.",
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        return io.BytesIO(response.content)


__all__ = ["GRAPH", "LOGIN", "SCOPES", "MicrosoftGraphClient", "authorize_url"]
