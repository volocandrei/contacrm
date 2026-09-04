"""Clientul HTTP către ANAF, cu un transport fals.

**Ce se poate verifica fără certificat digital**, și se verifică aici: forma
cererilor, citirea răspunsurilor și — mai ales — cele trei ciudățenii ale
API-ului ANAF care, netratate, produc defecte tăcute:

1. **„Nu există mesaje" vine ca eroare**, nu ca listă goală. Tratat ca eroare, ar
   bloca fereastra de timp la nesfârșit și preluarea s-ar opri fără să se plângă.
2. **Refuzul de împuternicire trebuie deosebit** de o eroare oarecare: primul se
   rezolvă de client, la ANAF; al doilea se reîncearcă.
3. **Convertorul întoarce erorile cu 200.** Un „PDF" care începe cu `{` ar ajunge
   în arhivă și s-ar descoperi abia când l-ar deschide cineva.

**Ce rămâne neverificat: autorizarea propriu-zisă.** Pasul `authorize` cere
certificatul calificat prezentat de browser și nu se poate simula. Aici se
verifică doar ce facem noi cu răspunsul lui.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.domain.enums import EFacturaMessageKind
from app.services.anaf import client as anaf_client
from app.services.anaf.base import AnafAuthError, AnafError, AnafMandateError
from tests.anaf_fake import PDF, anaf_zip, invoice_xml

WINDOW_START = datetime(2026, 8, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 31, tzinfo=UTC)

TOKEN_RESPONSE = {
    "access_token": "acces",
    "refresh_token": "reimprospatare",
    "refresh_token_expires_in": 31_536_000,
}


def build(handler) -> anaf_client.AnafApiClient:
    return anaf_client.AnafApiClient(
        client_id="id-aplicatie",
        client_secret="secret-aplicatie",
        transport=httpx.MockTransport(handler),
    )


def responder(*, listing=None, download=None, convert=None, token=None):
    """Un ANAF fals care răspunde pe rutele lui, și numai pe ele."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/token"):
            return token or httpx.Response(200, json=TOKEN_RESPONSE)
        if "listaMesajePaginatieFactura" in path:
            return listing or httpx.Response(200, json={"mesaje": []})
        if "descarcare" in path:
            return download or httpx.Response(200, content=b"")
        if "transformare" in path:
            return convert or httpx.Response(200, content=PDF)
        raise AssertionError(f"rută necunoscută: {request.url}")  # pragma: no cover

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


class TestListingMessages:
    def test_the_window_and_the_company_reach_anaf(self) -> None:
        handler = responder()
        build(handler).list_messages(
            "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
        )

        listing = next(r for r in handler.seen if "listaMesaj" in r.url.path)
        query = parse_qs(urlparse(str(listing.url)).query)
        assert query["cif"] == ["14399840"]
        # Milisecunde de la epocă, în UTC: ANAF nu acceptă altă formă.
        assert query["startTime"] == [str(int(WINDOW_START.timestamp() * 1000))]
        assert query["endTime"] == [str(int(WINDOW_END.timestamp() * 1000))]

    def test_a_message_is_read_whole(self) -> None:
        handler = responder(
            listing=httpx.Response(
                200,
                json={
                    "mesaje": [
                        {
                            "id": "3001",
                            "tip": "FACTURA PRIMITA",
                            "cif": "14399840",
                            "data_creare": "202608140930",
                            "detalii": "Factura cu id_incarcare=111",
                        }
                    ]
                },
            )
        )

        page = build(handler).list_messages(
            "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
        )

        assert len(page.messages) == 1
        message = page.messages[0]
        assert message.id == "3001"
        assert message.kind is EFacturaMessageKind.RECEIVED
        assert message.created_at == datetime(2026, 8, 14, 9, 30, tzinfo=UTC)

    def test_no_messages_is_an_empty_page_not_an_error(self) -> None:
        """ANAF spune „nu există mesaje" printr-un câmp numit `eroare`."""
        handler = responder(
            listing=httpx.Response(200, json={"eroare": "Nu exista mesaje in perioada solicitata"})
        )

        page = build(handler).list_messages(
            "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
        )

        assert page.messages == ()
        assert page.has_more is False

    def test_a_missing_mandate_is_its_own_error(self) -> None:
        handler = responder(
            listing=httpx.Response(
                200, json={"eroare": "Nu aveti dreptul de consultare a mesajelor pentru cif-ul"}
            )
        )

        with pytest.raises(AnafMandateError) as caught:
            build(handler).list_messages(
                "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
            )

        # Mesajul spune ce are de făcut clientul, nu doar că a eșuat ceva.
        assert "formular 150" in str(caught.value)
        assert caught.value.retryable is False

    def test_an_unknown_message_type_is_ignored_not_guessed(self) -> None:
        handler = responder(
            listing=httpx.Response(
                200, json={"mesaje": [{"id": "9", "tip": "CEVA NOU", "cif": "14399840"}]}
            )
        )

        page = build(handler).list_messages(
            "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
        )

        assert page.messages == ()

    def test_more_pages_are_reported(self) -> None:
        handler = responder(
            listing=httpx.Response(200, json={"mesaje": [], "numar_total_pagini": 3})
        )

        page = build(handler).list_messages(
            "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
        )

        assert page.has_more is True

    def test_a_refused_token_asks_for_reauthorisation(self) -> None:
        handler = responder(listing=httpx.Response(403, json={}))

        with pytest.raises(AnafAuthError, match="certificatul"):
            build(handler).list_messages(
                "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
            )

    def test_anaf_being_down_is_retryable(self) -> None:
        handler = responder(listing=httpx.Response(503))

        with pytest.raises(AnafError) as caught:
            build(handler).list_messages(
                "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
            )

        assert caught.value.retryable is True


class TestDownloading:
    def test_the_archive_comes_back_untouched(self) -> None:
        payload = anaf_zip("3001", invoice=invoice_xml())
        handler = responder(
            download=httpx.Response(
                200, content=payload, headers={"content-type": "application/zip"}
            )
        )

        assert build(handler).download("refresh", message_id="3001") == payload

    def test_a_json_body_on_the_zip_route_is_a_refusal(self) -> None:
        """ANAF întoarce JSON pe aceeași rută pe care altfel dă o arhivă."""
        handler = responder(
            download=httpx.Response(
                200,
                content=json.dumps({"eroare": "Id-ul solicitat nu exista"}).encode(),
                headers={"content-type": "application/json"},
            )
        )

        with pytest.raises(AnafError) as caught:
            build(handler).download("refresh", message_id="3001")

        assert caught.value.retryable is False


class TestRenderingThePdf:
    def test_the_pdf_comes_back(self) -> None:
        handler = responder()

        assert build(handler).render_pdf(invoice_xml()) == PDF

    def test_the_schema_location_is_stripped_only_from_the_request(self) -> None:
        """Fișierul stocat rămâne cel primit (§16); doar cererea se curăță."""
        original = invoice_xml().replace(
            b"<cbc:ID>", b'<cbc:ID xsi:schemaLocation="urn:oasis ../UBL-Invoice-2.1.xsd">', 1
        )
        handler = responder()

        build(handler).render_pdf(original)

        sent = next(r for r in handler.seen if "transformare" in r.url.path).content
        assert b"schemaLocation" not in sent
        assert b"schemaLocation" in original

    def test_an_error_report_is_not_taken_for_a_pdf(self) -> None:
        """Convertorul întoarce erorile de validare tot cu 200."""
        handler = responder(
            convert=httpx.Response(200, json={"eroare": "Document invalid: lipseste CUI"})
        )

        with pytest.raises(AnafError, match="nu a întors un PDF"):
            build(handler).render_pdf(invoice_xml())

    def test_conversion_does_not_ask_for_a_token(self) -> None:
        """Convertorul este public: o cerere de token acolo ar fi muncă degeaba."""
        handler = responder()

        build(handler).render_pdf(invoice_xml())

        assert [r for r in handler.seen if r.url.path.endswith("/token")] == []


class TestAuthorisation:
    def test_the_authorize_address_carries_the_signed_state(self) -> None:
        url = anaf_client.authorize_url(
            client_id="id-aplicatie", redirect_uri="https://cabinet.test/anaf", state="semnat"
        )

        query = parse_qs(urlparse(url).query)
        assert query["state"] == ["semnat"]
        assert query["response_type"] == ["code"]
        # Fără el, ANAF întoarce tokenuri într-o formă pe care nu o citim.
        assert query["token_content_type"] == ["jwt"]

    def test_a_response_without_a_refresh_token_is_refused_now(self) -> None:
        """Fără el nu există sincronizare automată. Se spune acum, nu peste o oră."""
        handler = responder(token=httpx.Response(200, json={"access_token": "doar-atat"}))

        with pytest.raises(AnafAuthError, match="refresh token"):
            build(handler).exchange_code("cod", "https://cabinet.test/anaf")

    def test_the_expiry_of_the_refresh_token_is_kept(self) -> None:
        handler = responder()

        tokens = build(handler).exchange_code("cod", "https://cabinet.test/anaf")

        assert tokens.refresh_token == "reimprospatare"
        assert tokens.refresh_expires_in == 31_536_000

    def test_every_request_carries_a_user_agent(self) -> None:
        """Fără el ANAF răspunde 403, iar refuzul pare o problemă de drepturi."""
        handler = responder()

        build(handler).list_messages(
            "refresh", tax_id="14399840", start=WINDOW_START, end=WINDOW_END, limit=25
        )

        assert all(request.headers.get("user-agent") for request in handler.seen)


class TestEnvironments:
    def test_test_and_production_are_different_bases(self) -> None:
        """Un token de test nu vede nimic în producție. Confuzia costă o zi."""
        assert anaf_client.API_BASE["test"] != anaf_client.API_BASE["prod"]

    def test_an_unknown_environment_falls_back_to_production(self) -> None:
        # Configurarea este validată în `Settings`; aici doar nu inventăm o bază.
        client = anaf_client.AnafApiClient(
            client_id="x", client_secret="y", environment="inexistent"
        )
        assert client._base == anaf_client.API_BASE["prod"]
