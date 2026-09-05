"""Citirea documentelor fotografiate, cu un model care vede (ADR-005).

**Ce apără testele de aici.** Un document fotografiat nu are strat de text:
providerul local întoarce, corect, gol, iar documentul ajunge la verificare cu
toate câmpurile libere. Poza este exact ce trimit clienții prin linkul de
încărcare — deci exact documentele pe care mașina nu le putea citi deloc.

**Nu putem chema un model din niciun test**: cere cheie, rețea și bani, iar
răspunsul nu este determinist. Ca la ANAF și Microsoft Graph, partea care vorbește
cu exteriorul este subțire și se exercită prin protocolul HTTP, cu un transport
fals. Ce se verifică aici este **contractul**: ce i se trimite modelului, ce se
face cu ce răspunde, și ce se întâmplă când nu răspunde.

**În ordinea gravității:**

1. **Nu se crede mai mult decât poate.** Încrederea raportată de un model este o
   afirmație, nu o măsurătoare. Plafonată sub pragul de aprobare automată, ea nu
   poate împinge singură un document peste ochiul unui om.
2. **Nu decide tipul.** O factură nu-și spune direcția; aceea se rezolvă la
   identificarea clientului. Tipul îl scot regulile din textul citit.
3. **Un model căzut se vede.** `OCR_FAILED` este vizibil și reprocesabil; o
   degradare tăcută în „n-a avut ce citi" ar fi arătat ca o poză ilizibilă, iar
   o cheie greșită ar fi trecut luni neobservată.
4. **Local întâi.** Un document care se poate citi în cabinet nu pleacă nicăieri.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import httpx
import pytest

from app.domain.enums import FieldSource
from app.services.extraction.base import (
    ExtractedValue,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)
from app.services.extraction.hybrid import HybridExtractionProvider, read_nothing
from app.services.extraction.vision import (
    MAX_BYTES,
    MAX_CONFIDENCE,
    PROMPT_VERSION,
    VisionExtractionProvider,
)

KNOWN = frozenset({"FACTURA_INTRARE", "FACTURA_IESIRE", "CHITANTA", "BON_FISCAL"})

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
PDF = b"%PDF-1.7\n" + b"0" * 200 + b"\n%%EOF"


class FakeVision:
    """Modelul care vede, fals. Strict: verifică ce i se trimite."""

    def __init__(self, reply: dict[str, Any] | None = None, *, status: int = 200) -> None:
        self.reply = reply
        self.status = status
        self.requests: list[dict[str, Any]] = []
        self.offline = False

    def transport(self) -> httpx.BaseTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("rețea căzută", request=request)

        assert request.headers.get("x-api-key"), "cheia nu a fost trimisă"
        assert request.headers.get("anthropic-version"), "versiunea nu a fost trimisă"

        body = json.loads(request.content)
        # Fără unealtă forțată, modelul poate răspunde în text liber — iar atunci
        # n-avem ce citi și documentul s-ar marca degeaba ca eșuat.
        assert body["tool_choice"]["type"] == "tool", "unealta nu a fost forțată"
        assert body["system"], "modelul a fost chemat fără instrucțiuni"
        self.requests.append(body)

        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "nu acum"}})
        return httpx.Response(200, json=self.reply)


def read(text: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Răspunsul API-ului, în forma exactă a unui bloc `tool_use`."""
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_fake",
                "name": "document_citit",
                "input": {"text": text, "fields": fields or {}},
            }
        ],
    }


def provider(fake: FakeVision) -> VisionExtractionProvider:
    return VisionExtractionProvider(
        api_key="cheie-de-test",
        model="claude-sonnet-5",
        known_type_codes=KNOWN,
        transport=fake.transport(),
    )


def source(payload: bytes = JPEG, mime_type: str = "image/jpeg") -> ExtractionInput:
    return ExtractionInput(
        stream=io.BytesIO(payload),
        mime_type=mime_type,
        original_filename="poza.jpg",
        sha256="a" * 64,
    )


# ── Ce trimite ───────────────────────────────────────────────────────────────


class TestWhatItSends:
    def test_an_image_goes_as_an_image_block(self) -> None:
        fake = FakeVision(read("CHITANȚĂ nr. 5"))

        provider(fake).extract(source())

        block = fake.requests[0]["messages"][0]["content"][0]
        assert block["type"] == "image"
        assert block["source"]["media_type"] == "image/jpeg"
        assert base64.standard_b64decode(block["source"]["data"]) == JPEG

    def test_a_pdf_goes_as_a_document_block(self) -> None:
        """Un scan este PDF, nu imagine — și API-ul le primește diferit."""
        fake = FakeVision(read("FACTURĂ"))

        provider(fake).extract(source(PDF, "application/pdf"))

        block = fake.requests[0]["messages"][0]["content"][0]
        assert block["type"] == "document"
        assert block["source"]["media_type"] == "application/pdf"

    def test_a_file_too_large_is_not_sent_at_all(self) -> None:
        """Documentul este valid, doar că nu l-am citit — nu este o eroare."""
        fake = FakeVision(read("nu ar trebui cerut"))

        result = provider(fake).extract(source(b"x" * (MAX_BYTES + 1)))

        assert fake.requests == []
        assert result.ocr_text is None
        assert all(not value.is_present for value in result.fields.values())

    def test_an_unsupported_type_is_not_sent_either(self) -> None:
        fake = FakeVision(read("nu ar trebui cerut"))

        result = provider(fake).extract(source(b"PK\x03\x04", "application/zip"))

        assert fake.requests == []
        assert result.ocr_text is None


# ── Ce face cu răspunsul ─────────────────────────────────────────────────────


class TestWhatItReads:
    def test_it_keeps_the_text_and_the_fields(self) -> None:
        fake = FakeVision(
            read(
                "CHITANȚĂ nr. 128",
                {
                    "documentDate": {"value": "2026-08-14", "confidence": 0.9},
                    "totalAmount": {"value": "119.00", "confidence": 0.8},
                },
            )
        )

        result = provider(fake).extract(source())

        assert result.ocr_text == "CHITANȚĂ nr. 128"
        assert result.fields["documentDate"].value == "2026-08-14"
        assert result.fields["totalAmount"].value == "119.00"
        assert result.provider == "vision"
        assert result.prompt_version == PROMPT_VERSION

    def test_confidence_is_capped_below_automatic_approval(self) -> None:
        """Un număr afirmat de model nu trece singur peste ochiul unui om.

        `CONFIDENCE_AUTO_THRESHOLD` este 0.90: dacă modelul ar putea declara
        0.99, un cabinet cu aprobarea automată pornită ar arhiva documente pe
        care nu s-a uitat nimeni, pe baza unei cifre pe care modelul a spus-o
        pentru că așa sună, nu pentru că a numărat ceva.
        """
        fake = FakeVision(read("BON FISCAL", {"totalAmount": {"value": "50", "confidence": 1.0}}))

        result = provider(fake).extract(source())

        assert result.fields["totalAmount"].confidence == MAX_CONFIDENCE
        assert result.extraction_confidence is not None
        assert result.extraction_confidence <= MAX_CONFIDENCE

    def test_a_field_without_a_declared_confidence_does_not_look_certain(self) -> None:
        fake = FakeVision(read("CHITANȚĂ", {"documentNumber": {"value": "7"}}))

        result = provider(fake).extract(source())

        assert result.fields["documentNumber"].confidence == 0.5

    def test_every_value_is_marked_as_coming_from_a_model(self) -> None:
        """§22: ecranul de verificare colorează după proveniență."""
        fake = FakeVision(
            read("CHITANȚĂ", {"documentDate": {"value": "2026-08-14", "confidence": 0.7}})
        )

        result = provider(fake).extract(source())

        assert result.fields["documentDate"].source is FieldSource.AI
        assert result.classification_source is FieldSource.AI

    def test_an_invoice_does_not_get_a_direction(self) -> None:
        """O factură nu-și spune direcția: aceea depinde de cine e clientul nostru.

        Un model întrebat ar fi ghicit, și ar fi ghicit convingător. Aici se
        întorc ambele coduri, iar alegerea se face la identificarea clientului.
        """
        fake = FakeVision(read("FACTURĂ FISCALĂ nr. 42 din 14.08.2026"))

        result = provider(fake).extract(source())

        assert result.document_type_code is None
        assert set(result.document_type_candidates) == {"FACTURA_INTRARE", "FACTURA_IESIRE"}

    def test_the_type_comes_from_the_rules_over_the_text(self) -> None:
        fake = FakeVision(read("CHITANȚĂ\nSeria AB nr. 128"))

        result = provider(fake).extract(source())

        assert result.document_type_code == "CHITANTA"
        assert result.classification_confidence is not None
        assert result.classification_confidence <= MAX_CONFIDENCE

    def test_an_empty_value_stays_empty(self) -> None:
        """`null` de la model nu devine șir gol în câmpul unui contabil."""
        fake = FakeVision(read("CHITANȚĂ", {"supplierName": {"value": None, "confidence": 0.0}}))

        result = provider(fake).extract(source())

        assert result.fields["supplierName"].value is None
        assert result.fields["supplierName"].confidence is None


# ── Ce face când nu merge ────────────────────────────────────────────────────


class TestWhenItBreaks:
    def test_a_dead_network_fails_the_document_visibly(self) -> None:
        """`OCR_FAILED` se vede și se reprocesează.

        O degradare tăcută în „n-a avut ce citi" ar fi arătat identic cu o poză
        ilizibilă, iar o cheie greșită ar fi trecut luni întregi neobservată.
        """
        fake = FakeVision(read("nimic"))
        fake.offline = True

        with pytest.raises(ExtractionError):
            provider(fake).extract(source())

    def test_a_refusal_is_reported_without_the_body(self) -> None:
        """Corpul unei erori poate purta cheia înapoi: se loghează codul."""
        fake = FakeVision(None, status=401)

        with pytest.raises(ExtractionError, match="401"):
            provider(fake).extract(source())

    def test_a_reply_without_the_tool_is_refused(self) -> None:
        fake = FakeVision(
            {
                "id": "msg_fake",
                "type": "message",
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Nu pot citi."}],
            }
        )

        with pytest.raises(ExtractionError):
            provider(fake).extract(source())


# ── Ordinea: local întâi ─────────────────────────────────────────────────────


class Fixed:
    """Un provider care întoarce mereu același rezultat, și numără cererile."""

    def __init__(self, result: ExtractionResult) -> None:
        self.result = result
        self.calls = 0

    @property
    def name(self) -> str:
        return self.result.provider

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        self.calls += 1
        return self.result


def empty_result(provider_name: str = "local") -> ExtractionResult:
    return ExtractionResult(provider=provider_name, duration_ms=1, fields={})


def full_result(provider_name: str = "local") -> ExtractionResult:
    return ExtractionResult(
        provider=provider_name,
        duration_ms=1,
        ocr_text="FACTURĂ nr. 1",
        fields={"totalAmount": ExtractedValue(value="100", confidence=0.9)},
    )


class TestLocalFirst:
    def test_a_document_readable_here_never_leaves_the_office(self) -> None:
        """Ordinea nu este o optimizare, este o politică (R2)."""
        local, vision = Fixed(full_result()), Fixed(full_result("vision"))
        hybrid = HybridExtractionProvider(local=local, vision=vision)

        result = hybrid.extract(source(PDF, "application/pdf"))

        assert vision.calls == 0
        assert result.provider == "local"

    def test_a_photo_goes_to_the_model(self) -> None:
        local, vision = Fixed(empty_result()), Fixed(full_result("vision"))
        hybrid = HybridExtractionProvider(local=local, vision=vision)

        result = hybrid.extract(source())

        assert vision.calls == 1
        assert result.provider == "vision"

    def test_the_stream_is_rewound_before_the_second_read(self) -> None:
        """Providerul local tocmai l-a citit până la capăt."""
        seen: list[bytes] = []

        class Recording(Fixed):
            def extract(self, source: ExtractionInput) -> ExtractionResult:
                seen.append(source.stream.read())
                return super().extract(source)

        hybrid = HybridExtractionProvider(
            local=Recording(empty_result()), vision=Recording(full_result("vision"))
        )

        hybrid.extract(source())

        assert seen == [JPEG, JPEG]

    def test_a_partial_local_read_is_not_sent_anywhere(self) -> None:
        """Un câmp completat înseamnă că providerul local a înțeles documentul."""
        partial = ExtractionResult(
            provider="local",
            duration_ms=1,
            ocr_text=None,
            fields={"totalAmount": ExtractedValue(value="100", confidence=0.9)},
        )

        assert read_nothing(partial) is False
