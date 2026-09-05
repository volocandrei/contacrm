"""Citirea documentelor fotografiate sau scanate, cu un model care vede (ADR-005).

**Gaura pe care o astupă.** `pdf_text` scoate stratul de text pe care un PDF îl
poartă deja — și acoperă cazul covârșitor: facturi emise de un ERP, extrase de
cont, chitanțe tipărite. Dar un document **fotografiat** nu are strat de text.
Acolo providerul local întoarce, corect, un rezultat gol, iar documentul ajunge la
verificare cu **toate câmpurile libere**: dată, număr, furnizor, sumă, tot. Cineva
le tastează de mână, de fiecare dată.

Iar poza este exact ce trimit clienții. Un bon de benzină, o chitanță, o factură
primită pe hârtie: omul o fotografiază cu telefonul și o trimite prin linkul de
încărcare. Cu cât facem mai ușoară trimiterea, cu atât vin mai multe poze —
adică fix documentele pe care mașina nu le putea citi deloc.

**Ce face providerul ăsta.** Trimite documentul unui model care vede și îi cere
două lucruri: textul de pe el, și câmpurile pe care le poate citi cu certitudine.
Nimic mai mult.

**Ce nu face, deliberat.**

- **Nu decide tipul documentului.** Tipul îl scoate `romanian_documents` din
  textul citit, cu aceleași reguli ca la PDF-urile digitale. O factură nu-și
  spune direcția: dacă e de intrare sau de ieșire depinde de care CUI de pe ea
  aparține cabinetului, iar asta o știe sistemul, nu documentul. Un model
  întrebat ar fi ghicit, și ar fi ghicit convingător.
- **Nu se crede mai mult decât poate.** Încrederea raportată de un model este o
  afirmație, nu o măsurătoare: el spune „95%" fiindcă așa sună, nu fiindcă a
  numărat ceva. De aceea `MAX_CONFIDENCE` o plafonează sub pragul de aprobare
  automată — o cifră spusă de model nu are voie să împingă singură un document
  peste ochiul unui om.
- **Nu inventează un rezultat când nu poate.** Un fișier prea mare pentru cerere
  întoarce gol, ca providerul local: documentul este valid, doar că nu l-am citit.

**Ce iese din cabinet.** Documentul întreg pleacă la furnizorul modelului. Este o
decizie pe care un cabinet o ia explicit, nu una care se întâmplă din configurare
implicită: `OCR_PROVIDER=hybrid` trebuie scris de un om, iar fără cheie pornirea
se oprește. Providerul local rămâne implicit tocmai pentru că nu trimite nimic
nicăieri (R2).

**NEVERIFICAT CU UN MODEL REAL — CERE O CREDENȚIALĂ EXTERNĂ.** Ca la ANAF,
Microsoft Graph și asistent: partea care vorbește cu exteriorul este cât mai
subțire și se exercită în teste cu un transport fals. Prima cerere adevărată
rămâne de făcut o dată, manual, la instalare.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Final

import httpx

from app.core.logging import get_logger
from app.domain import romanian_documents as ro
from app.domain.enums import FieldSource
from app.services.extraction.base import (
    ExtractedValue,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)

logger = get_logger(__name__)

PROVIDER_NAME: Final = "vision"

API_URL: Final = "https://api.anthropic.com/v1/messages"
API_VERSION: Final = "2023-06-01"

#: Un document, nu o conversație: cererea are voie să dureze mai mult decât un
#: chat, dar nu la nesfârșit — coada de procesare așteaptă după ea.
TIMEOUT: Final = httpx.Timeout(90.0, connect=10.0)

#: Textul unui document plus câmpurile lui. O factură cu multe poziții încape.
MAX_TOKENS: Final = 4000

#: Versiunea promptului, scrisă pe fiecare document citit.
#:
#: Când formularea se schimbă, rezultatele se schimbă și ele — iar peste șase
#: luni cineva se va uita la un câmp greșit și va vrea să știe ce anume l-a
#: produs. Fără versiune, întrebarea nu are răspuns.
PROMPT_VERSION: Final = "vision-1"

#: Cât poate declara providerul, oricât de sigur s-ar spune modelul.
#:
#: `CONFIDENCE_AUTO_THRESHOLD` este 0.90 implicit, iar peste el un document se
#: poate aproba singur când cabinetul pornește aprobarea automată. Un număr pe
#: care modelul îl **afirmă** nu are voie să treacă singur peste ochiul unui om:
#: nu este o probabilitate calibrată, este o impresie exprimată în procente.
MAX_CONFIDENCE: Final = 0.85

#: Peste atât nu se trimite. Limita furnizorului este în jurul a 5 MB pe conținut
#: codificat base64, iar codificarea umflă fișierul cu o treime.
MAX_BYTES: Final = 3_500_000

IMAGE_MIME_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
PDF_MIME_TYPE: Final = "application/pdf"

#: Câmpurile pe care le cerem modelului. `documentType` lipsește pentru că îl
#: decid regulile, iar `referenceMonth` pentru că îl derivă sistemul din dată.
FIELDS: Final = (
    "documentDate",
    "series",
    "documentNumber",
    "supplierName",
    "supplierTaxId",
    "customerName",
    "customerTaxId",
    "currency",
    "subtotal",
    "vatAmount",
    "totalAmount",
)

SYSTEM_PROMPT: Final = """Ești un cititor de documente contabile românești. \
Primești poza sau scanul unui singur document și îl transcrii.

Reguli, în ordinea importanței:

1. Citește DOAR ce scrie pe document. Nu completa, nu corecta, nu deduce. Dacă un \
câmp nu se vede sau nu există pe document, lasă-l null.
2. Nu ghici. O valoare pe jumătate lizibilă se raportează cu încredere mică, nu \
se completează „cum ar trebui să fie". Un contabil corectează mai ușor un câmp gol \
decât unul greșit care pare corect.
3. Sumele se scriu cu punct zecimal și fără separator de mii: „1234.56". Datele în \
format ISO: „2026-08-14". Codurile fiscale exact cum apar, cu tot cu „RO" dacă \
este scris.
4. `supplierName` este cine a emis documentul, `customerName` cine l-a primit. \
Dacă nu poți spune cu certitudine care este care, lasă-le pe amândouă null.
5. `text` este transcrierea a tot ce se citește pe document, în ordinea de pe \
pagină. Din el se recunoaște mai târziu tipul documentului, deci titlul de sus \
(„FACTURĂ", „CHITANȚĂ", „BON FISCAL", „EXTRAS DE CONT") trebuie să apară.
6. `confidence` pentru fiecare câmp este cât de clar se vede valoarea pe imagine: \
1.0 pentru text tipărit și perfect lizibil, sub 0.5 pentru ce ai citit cu greu."""


def _tool_schema() -> dict[str, Any]:
    """Unealta prin care modelul răspunde.

    Structura forțată nu este eleganță, este garanția că răspunsul se poate citi:
    un model rugat să scrie JSON în text scrie, din când în când, JSON aproape
    valid — cu o virgulă în plus sau o explicație în față.
    """
    value = {
        "type": "object",
        "properties": {
            "value": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["value", "confidence"],
    }
    return {
        "name": "document_citit",
        "description": "Transcrierea documentului și câmpurile citite de pe el.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Tot ce se citește pe document."},
                "fields": {
                    "type": "object",
                    "properties": {name: value for name in FIELDS},
                    "required": list(FIELDS),
                },
            },
            "required": ["text", "fields"],
        },
    }


def _empty() -> ExtractedValue:
    return ExtractedValue(value=None, confidence=None, source=FieldSource.AI)


class VisionExtractionProvider:
    """Citește un document cu un model care vede imagini."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        known_type_codes: frozenset[str] = frozenset(),
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._known_type_codes = known_type_codes
        # Injectat în teste: partea care vorbește cu exteriorul se exercită cu un
        # transport fals, ca la ANAF și Microsoft Graph.
        self._transport = transport

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        started = time.monotonic()
        payload = source.stream.read()

        block = self._content_block(source.mime_type, payload)
        if block is None:
            # Nu e o eroare: documentul este valid, doar că nu l-am putut trimite.
            # Ajunge la verificare cu câmpurile goale, exact ca înainte.
            logger.info(
                "vision_skipped",
                mime_type=source.mime_type,
                size=len(payload),
                reason="unsupported" if len(payload) <= MAX_BYTES else "too_large",
            )
            return self._nothing_read(int((time.monotonic() - started) * 1000))

        body = self._ask(block)
        read = self._read_tool_result(body)
        return self._assemble(read, int((time.monotonic() - started) * 1000))

    # ── Cererea ─────────────────────────────────────────────────────────────

    def _content_block(self, mime_type: str, payload: bytes) -> dict[str, Any] | None:
        if len(payload) > MAX_BYTES:
            return None

        data = base64.standard_b64encode(payload).decode("ascii")
        if mime_type in IMAGE_MIME_TYPES:
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": mime_type, "data": data},
            }
        if mime_type == PDF_MIME_TYPE:
            return {
                "type": "document",
                "source": {"type": "base64", "media_type": PDF_MIME_TYPE, "data": data},
            }
        return None

    def _ask(self, block: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "tools": [_tool_schema()],
            # Forțat: fără asta, modelul poate răspunde în text liber, iar atunci
            # nu avem ce citi și documentul s-ar marca degeaba ca eșuat.
            "tool_choice": {"type": "tool", "name": "document_citit"},
            "messages": [
                {
                    "role": "user",
                    "content": [block, {"type": "text", "text": "Transcrie documentul."}],
                }
            ],
        }
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport) as http:
                response = http.post(
                    API_URL,
                    json=payload,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": API_VERSION,
                        "content-type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            # `ExtractionError` marchează documentul `OCR_FAILED`, adică vizibil
            # și reprocesabil. O degradare tăcută în „n-a avut ce citi" ar fi
            # arătat identic cu o poză ilizibilă, iar un model configurat greșit
            # ar fi trecut luni întregi neobservat.
            raise ExtractionError(f"Modelul nu a răspuns: {exc}") from exc

        if response.status_code >= 400:
            # Codul, nu corpul: un mesaj de eroare prost formulat poate purta
            # cheia înapoi.
            logger.warning("vision_model_error", status=response.status_code)
            raise ExtractionError(f"Modelul a refuzat cererea (HTTP {response.status_code}).")

        try:
            body: dict[str, Any] = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ExtractionError("Modelul a răspuns cu ceva ce nu este JSON.") from exc
        return body

    # ── Răspunsul ───────────────────────────────────────────────────────────

    def _read_tool_result(self, body: dict[str, Any]) -> dict[str, Any]:
        blocks = body.get("content")
        if not isinstance(blocks, list):
            raise ExtractionError("Răspunsul modelului nu are conținut.")

        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                arguments = block.get("input")
                if isinstance(arguments, dict):
                    return arguments
        raise ExtractionError("Modelul nu a completat unealta de transcriere.")

    def _assemble(self, read: dict[str, Any], duration_ms: int) -> ExtractionResult:
        text = read.get("text")
        text = text.strip() if isinstance(text, str) else ""

        raw_fields = read.get("fields")
        raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
        fields = {name: self._value(raw_fields.get(name)) for name in FIELDS}

        # Tipul îl decid regulile peste textul citit, nu modelul. O factură nu-și
        # spune direcția: aceea se rezolvă la identificarea clientului.
        document_type = ro.classify(text, known_codes=self._known_type_codes) if text else None
        candidates = ro.invoice_candidates(text, known_codes=self._known_type_codes) if text else ()

        return ExtractionResult(
            provider=PROVIDER_NAME,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            duration_ms=duration_ms,
            ocr_text=text or None,
            # Textul a fost **recunoscut** dintr-o imagine, nu citit dintr-un
            # strat digital: aici incertitudinea de recunoaștere chiar există.
            ocr_confidence=MAX_CONFIDENCE if text else None,
            document_type_code=document_type.value if document_type else None,
            classification_confidence=(
                min(document_type.confidence, MAX_CONFIDENCE) if document_type else None
            ),
            # Regula a produs tipul, dar peste un text scos de model: veriga slabă
            # este modelul, deci insigna spune AI. „OCR" ar fi promis un text citit
            # de pe document, nu unul recunoscut dintr-o poză (§22).
            classification_source=FieldSource.AI,
            document_type_candidates=candidates,
            fields=fields,
        )

    def _value(self, raw: Any) -> ExtractedValue:
        if not isinstance(raw, dict):
            return _empty()

        value = raw.get("value")
        if not isinstance(value, str) or not value.strip():
            return _empty()

        confidence = raw.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            capped = min(max(float(confidence), 0.0), MAX_CONFIDENCE)
        else:
            # Fără număr, presupunem cel mai puțin: un câmp fără încredere
            # declarată nu are voie să pară sigur.
            capped = 0.5

        return ExtractedValue(value=value.strip(), confidence=capped, source=FieldSource.AI)

    def _nothing_read(self, duration_ms: int) -> ExtractionResult:
        return ExtractionResult(
            provider=PROVIDER_NAME,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            duration_ms=duration_ms,
            ocr_text=None,
            # `0.0` ar fi însemnat „am citit foarte prost", ceea ce este altceva
            # decât „nu am citit".
            ocr_confidence=None,
            document_type_code=None,
            classification_confidence=None,
            fields={name: _empty() for name in FIELDS},
        )


__all__ = [
    "FIELDS",
    "MAX_BYTES",
    "MAX_CONFIDENCE",
    "PROMPT_VERSION",
    "PROVIDER_NAME",
    "VisionExtractionProvider",
]
