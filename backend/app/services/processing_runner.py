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

from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.services.document_processing import DocumentProcessingService
from app.services.extraction.base import DocumentExtractionProvider
from app.services.extraction.mock import MockDocumentExtractionProvider
from app.services.storage import StorageProvider

logger = get_logger(__name__)


def build_extractor() -> DocumentExtractionProvider:
    """Providerul configurat.

    Când apar providerii reali, se ramifică aici pe `settings.ocr_provider`; restul
    pipeline-ului nu se schimbă, pentru că vorbește doar cu protocolul (ADR-005).
    """
    if settings.ocr_provider != "mock":  # pragma: no cover — pana la Faza 2
        raise NotImplementedError(
            f"Providerul {settings.ocr_provider!r} nu este implementat încă. "
            "În development se folosește `mock`, ca niciun document să nu părăsească mașina."
        )
    return MockDocumentExtractionProvider()


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
            service = DocumentProcessingService(session, storage, build_extractor())
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
