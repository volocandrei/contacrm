"""ANAF — singura parte care chiar vorbește cu ANAF.

Este deliberat subțire, ca `microsoft/graph.py` și din același motiv: **nu poate
fi testată fără certificat digital calificat.** Ce nu se poate testa trebuie să
fie mic și plictisitor. Aici se compun URL-uri, se trimit cereri și se citește
JSON; tot ce se întâmplă cu facturile stă în `sync.py` și se exercită cu un
client fals.

**Autorizarea nu se poate automatiza, prin construcție.** Pasul `authorize` se
face într-un browser care prezintă certificatul calificat (tokenul USB) înrolat
în SPV. Nu există `client_credentials`, nu există cont de serviciu: ANAF vrea o
persoană fizică identificată. După acel pas, refresh tokenul ține un an și
sincronizarea merge singură — o intervenție umană pe an.

**Trei capcane cunoscute, toate rezolvate aici:**

- ANAF refuză cererile fără `User-Agent`. O bibliotecă HTTP care nu îl trimite
  primește 403 și pare o problemă de drepturi, când este una de antet.
- „Nu există mesaje" vine ca **eroare** în corpul răspunsului, nu ca listă goală.
  Tratat ca eroare, ar bloca fereastra de timp la nesfârșit.
- Convertorul XML→PDF respinge uneori documentul din cauza atributului
  `xsi:schemaLocation`. Se scoate **doar din corpul cererii de conversie**;
  fișierul stocat rămâne cel primit, neatins.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlencode

import httpx

from app.core.logging import get_logger
from app.domain.enums import EFacturaMessageKind
from app.services.anaf.base import (
    AnafAuthError,
    AnafError,
    AnafMandateError,
    AnafTokens,
    SpvMessage,
    SpvPage,
)

logger = get_logger(__name__)

#: Autorizarea stă pe alt domeniu decât API-ul: `logincert` cere certificatul.
OAUTH: Final = "https://logincert.anaf.ro/anaf-oauth2/v1"

#: Bazele API-ului. `test` este o bază complet separată la ANAF, nu un comutator.
API_BASE: Final = {
    "prod": "https://api.anaf.ro/prod/FCTEL/rest",
    "test": "https://api.anaf.ro/test/FCTEL/rest",
}

#: Convertorul XML→PDF. Public, fără autorizare — de aceea PDF-ul poate fi refăcut
#: oricând, iar un eșec la conversie nu are voie să piardă factura.
CONVERTER: Final = "https://webservicesp.anaf.ro/prod/FCTEL/rest/transformare/FACT1"

#: Fără el, ANAF răspunde 403 și pare o problemă de împuternicire.
USER_AGENT: Final = "ContaCRM/1.0 (+integrare e-Factura)"

TIMEOUT: Final = httpx.Timeout(30.0, read=120.0)

RETRYABLE_STATUS: Final = frozenset({429, 500, 502, 503, 504})

#: ANAF numără paginile de la 1 și nu dă token de continuare.
FIRST_PAGE: Final = 1

#: Textele prin care ANAF spune „nu ai împuternicire". Se compară pe formă
#: normalizată, fără diacritice, pentru că vin inconsecvent.
_MANDATE_REFUSALS: Final = (
    "nu aveti dreptul",
    "nu are dreptul",
    "nu sunteti autorizat",
)

#: Textul prin care ANAF spune „nu am nimic pentru tine". Nu este o eroare.
_EMPTY_MARKERS: Final = ("nu exista mesaje", "nu au fost gasite")

_COMPACT_TIMESTAMP = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})$")

#: Atributul care încurcă uneori convertorul ANAF. Vezi nota din capul modulului.
_SCHEMA_LOCATION = re.compile(rb'\s+xsi:schemaLocation\s*=\s*"[^"]*"')


def authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Adresa la care se trimite administratorul, cu certificatul în calculator."""
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            # ANAF întoarce tokenuri JWT doar dacă i se cere explicit.
            "token_content_type": "jwt",
        }
    )
    return f"{OAUTH}/authorize?{query}"


def _fold(value: str) -> str:
    """Text de comparat: litere mici, fără diacritice românești."""
    lowered = value.lower()
    for source, target in (("ă", "a"), ("â", "a"), ("î", "i"), ("ș", "s"), ("ş", "s")):
        lowered = lowered.replace(source, target)
    for source, target in (("ț", "t"), ("ţ", "t")):
        lowered = lowered.replace(source, target)
    return lowered


def _millis(moment: datetime) -> int:
    """ANAF cere ferestrele în milisecunde de la epocă, în UTC."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return int(aware.astimezone(UTC).timestamp() * 1000)


def _created_at(raw: object) -> datetime | None:
    """`data_creare` vine ca `YYYYMMDDHHMM`, uneori ca ISO. Ambele, sau nimic."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    match = _COMPACT_TIMESTAMP.match(text)
    if match is not None:
        year, month, day, hour, minute = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, hour, minute, tzinfo=UTC)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _kind(raw: object) -> EFacturaMessageKind | None:
    """Tipul mesajului. Necunoscut înseamnă necunoscut, nu „factură primită"."""
    if not isinstance(raw, str):
        return None
    normalized = " ".join(_fold(raw).split())
    for member in EFacturaMessageKind:
        if _fold(member.value) == normalized:
            return member
    return None


def strip_schema_location(invoice_xml: bytes) -> bytes:
    """Scoate `xsi:schemaLocation`, **doar** pentru cererea de conversie.

    Convertorul ANAF respinge documentul când atributul indică o schemă pe care
    nu o poate rezolva. Fișierul stocat nu se atinge: §16 spune că originalul nu
    se transformă, iar aici originalul este proba unei operațiuni fiscale.
    """
    return _SCHEMA_LOCATION.sub(b"", invoice_xml)


class AnafApiClient:
    """Clientul real. Tot ce e greu de testat stă aici, și e cât mai puțin."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        environment: str = "prod",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base = API_BASE.get(environment, API_BASE["prod"])
        # Injectabil, ca testele să poată pune un transport fals fără rețea.
        self._transport = transport

    # ── Autentificare ───────────────────────────────────────────────────────

    def _http(self) -> httpx.Client:
        return httpx.Client(
            timeout=TIMEOUT,
            transport=self._transport,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "token_content_type": "jwt",
            **data,
        }
        try:
            with self._http() as http:
                response = http.post(f"{OAUTH}/token", data=payload)
        except httpx.HTTPError as exc:
            raise AnafError(f"ANAF nu a răspuns la cererea de token: {exc}") from exc

        if response.status_code >= 400:
            # Corpul poartă motivul refuzului. Nu conține secretul nostru.
            raise AnafAuthError(f"ANAF a refuzat autorizarea: {response.text[:300]}")

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise AnafAuthError(
                "ANAF a răspuns cu ceva ce nu este JSON la cererea de token."
            ) from exc
        return body

    def exchange_code(self, code: str, redirect_uri: str) -> AnafTokens:
        body = self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        )
        refresh = body.get("refresh_token")
        if not refresh:
            # Fără el nu există sincronizare automată, doar una manuală lângă
            # tokenul USB. Se spune acum, nu peste o oră.
            raise AnafAuthError("ANAF nu a trimis un refresh token.")
        expires = body.get("refresh_token_expires_in") or body.get("expires_in")
        return AnafTokens(
            access_token=str(body.get("access_token") or ""),
            refresh_token=str(refresh),
            refresh_expires_in=int(expires) if isinstance(expires, int | str) and expires else None,
        )

    def _access_token(self, refresh_token: str) -> str:
        body = self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
        token = body.get("access_token")
        if not token:
            raise AnafAuthError(
                "ANAF nu a trimis un token de acces. Autorizează din nou cu certificatul."
            )
        return str(token)

    # ── Cereri ──────────────────────────────────────────────────────────────

    def _request(self, access_token: str, url: str) -> httpx.Response:
        try:
            with self._http() as http:
                response = http.get(url, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise AnafError(f"ANAF nu a răspuns: {exc}") from exc

        if response.status_code in {401, 403}:
            raise AnafAuthError(
                "ANAF a refuzat accesul. Autorizează din nou cabinetul cu certificatul digital."
            )
        if response.status_code >= 400:
            raise AnafError(
                f"ANAF a răspuns {response.status_code}.",
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        return response

    def list_messages(
        self,
        refresh_token: str,
        *,
        tax_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> SpvPage:
        query = urlencode(
            {
                "startTime": _millis(start),
                "endTime": _millis(end),
                "cif": tax_id,
                "pagina": FIRST_PAGE,
            }
        )
        url = f"{self._base}/listaMesajePaginatieFactura?{query}"
        response = self._request(self._access_token(refresh_token), url)

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise AnafError(
                f"ANAF a răspuns cu ceva ce nu este JSON: {response.text[:200]}"
            ) from exc

        problem = body.get("eroare")
        if isinstance(problem, str) and problem.strip():
            folded = _fold(problem)
            if any(marker in folded for marker in _MANDATE_REFUSALS):
                raise AnafMandateError(tax_id)
            if any(marker in folded for marker in _EMPTY_MARKERS):
                # Nu este o eroare: este răspunsul „nimic nou". Fereastra de timp
                # trebuie să se închidă, altfel s-ar reciti la infinit.
                return SpvPage()
            raise AnafError(f"ANAF: {problem[:300]}")

        raw = body.get("mesaje")
        entries = raw if isinstance(raw, list) else []
        messages: list[SpvMessage] = []
        for entry in entries[:limit]:
            if not isinstance(entry, dict):
                continue
            identifier = str(entry.get("id") or "").strip()
            kind = _kind(entry.get("tip"))
            if not identifier or kind is None:
                # Un tip pe care nu îl cunoaștem nu se ghicește. Rămâne necitit,
                # și se vede în log — mai bine decât înregistrat greșit.
                logger.info("anaf_message_ignored", tip=str(entry.get("tip"))[:64])
                continue
            messages.append(
                SpvMessage(
                    id=identifier,
                    kind=kind,
                    tax_id=str(entry.get("cif") or tax_id),
                    created_at=_created_at(entry.get("data_creare")),
                    detail=str(entry.get("detalii") or "")[:500],
                )
            )

        pages = body.get("numar_total_pagini")
        more_pages = isinstance(pages, int) and pages > FIRST_PAGE
        return SpvPage(messages=tuple(messages), has_more=more_pages or len(entries) > limit)

    def download(self, refresh_token: str, *, message_id: str) -> bytes:
        url = f"{self._base}/descarcare?id={message_id}"
        response = self._request(self._access_token(refresh_token), url)

        # La refuz, ANAF întoarce JSON pe aceeași rută pe care altfel dă un ZIP.
        if "json" in response.headers.get("content-type", "").lower():
            try:
                problem = str(response.json().get("eroare") or "")
            except ValueError:  # pragma: no cover — corp inconsistent
                problem = response.text[:200]
            if any(marker in _fold(problem) for marker in _MANDATE_REFUSALS):
                raise AnafAuthError(f"ANAF: {problem[:300]}")
            raise AnafError(f"ANAF nu a dat arhiva: {problem[:300]}", retryable=False)

        return response.content

    def render_pdf(self, invoice_xml: bytes) -> bytes:
        """Conversia oficială. Fără autorizare, deci fără refresh token."""
        try:
            with self._http() as http:
                response = http.post(
                    CONVERTER,
                    content=strip_schema_location(invoice_xml),
                    headers={"Content-Type": "text/plain"},
                )
        except httpx.HTTPError as exc:
            raise AnafError(f"Convertorul ANAF nu a răspuns: {exc}") from exc

        if response.status_code >= 400:
            raise AnafError(
                f"Convertorul ANAF a răspuns {response.status_code}.",
                retryable=response.status_code in RETRYABLE_STATUS,
            )

        # La document invalid, convertorul întoarce JSON cu erorile de validare,
        # tot cu 200. Un „PDF" care începe cu `{` ar ajunge în arhivă și s-ar
        # descoperi abia când l-ar deschide cineva.
        if not response.content.startswith(b"%PDF"):
            raise AnafError(
                f"Convertorul ANAF nu a întors un PDF: {response.text[:300]}", retryable=False
            )
        return response.content


__all__ = ["API_BASE", "AnafApiClient", "authorize_url", "strip_schema_location"]
