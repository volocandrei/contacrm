"""Pornirea procesării în afara ciclului cerere-răspuns (§38).

Upload-ul răspunde imediat; extracția rulează după — într-un background task din
procesul API sau, mai bine, în `app/worker.py`. În ambele cazuri cu **propria
sesiune de bază de date**.

Sesiunea separată nu este un detaliu: sesiunea cererii se închide odată cu
răspunsul, iar procesarea trebuie să-și comită singură rezultatul. Din același
motiv, o eroare aici nu are cum să strice răspunsul deja trimis — dar trebuie să
lase urmă, altfel un document ar rămâne tăcut în PROCESSING.

Limita de astăzi, spusă explicit: procesarea rulează în procesul API. Dacă procesul
cade între upload și finalul extracției, documentul rămâne în PROCESSING și are
nevoie de o reprocesare. Coada persistentă vine la M6; `process()` are deja
semnătura potrivită, deci schimbarea este de infrastructură, nu de logică.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models.document import DocumentType
from app.services.document_processing import DocumentProcessingService
from app.services.extraction.base import DocumentExtractionProvider
from app.services.extraction.efactura import EFacturaExtractionProvider
from app.services.extraction.local import LocalExtractionProvider
from app.services.extraction.mock import MockDocumentExtractionProvider
from app.services.extraction.pdf_text import PdfTextExtractionProvider
from app.services.storage import StorageProvider

logger = get_logger(__name__)


def build_extractor(known_type_codes: frozenset[str] = frozenset()) -> DocumentExtractionProvider:
    """Providerul configurat (ADR-005).

    Restul pipeline-ului nu se schimbă niciodată aici: vorbește doar cu protocolul.

    `known_type_codes` sunt tipurile **active ale organizației** (§6). Un provider
    nu are voie să propună un cod pe care cabinetul nu îl are definit: scrierea l-ar
    respinge cu `ValidationError` și ar opri procesarea unui document altfel valid.
    """
    if settings.ocr_provider == "local":
        return LocalExtractionProvider(known_type_codes=known_type_codes)
    if settings.ocr_provider == "efactura":
        return EFacturaExtractionProvider(known_type_codes=known_type_codes)
    if settings.ocr_provider == "pdf_text":
        return PdfTextExtractionProvider(known_type_codes=known_type_codes)
    if settings.ocr_provider != "mock":  # pragma: no cover — pana la Faza 2
        raise NotImplementedError(
            f"Providerul {settings.ocr_provider!r} nu este implementat încă. "
            "În development se folosește `mock`, ca niciun document să nu părăsească mașina."
        )
    return MockDocumentExtractionProvider()


def active_type_codes(session: Session, organization_id: uuid.UUID) -> frozenset[str]:
    """Codurile de tip pe care organizația chiar le are, ca să nu propunem altele."""
    codes = session.scalars(
        select(DocumentType.code).where(
            DocumentType.organization_id == organization_id,
            DocumentType.is_active.is_(True),
        )
    ).all()
    return frozenset(codes)


def run_processing(
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    storage: StorageProvider,
    *,
    idempotency_key: str | None = None,
    triggered_by: uuid.UUID | None = None,
) -> None:
    """Rulează pipeline-ul într-o tranzacție proprie.

    Nu propagă excepții: apelantul este un background task, iar răspunsul HTTP a
    plecat deja. Orice eșec neașteptat este logat și lasă documentul acolo unde a
    ajuns — o reprocesare explicită îl poate relua.
    """
    try:
        with session_scope() as session:
            extractor = build_extractor(active_type_codes(session, organization_id))
            service = DocumentProcessingService(session, storage, extractor)
            outcome = service.process(
                organization_id,
                document_id,
                idempotency_key=idempotency_key,
                triggered_by=triggered_by,
            )
        if outcome.skipped:
            logger.info(
                "processing_run_skipped",
                document_id=str(document_id),
                reason=outcome.reason,
            )
    except Exception:
        logger.exception("processing_run_crashed", document_id=str(document_id))
