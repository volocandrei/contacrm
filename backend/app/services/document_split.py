"""Un teanc scanat, desfăcut în documentele lui (§8, §26, §28).

**Problema.** Clientul pune zece facturi în scanner și trimite `scan_001.pdf`.
Astăzi asta devine **un** document: un număr, un furnizor, un total — toate ale
primei facturi, restul pierdute. Contabilul le desface de mână, în alt program.

**Ce face serviciul.** Citește textul fiecărei pagini, cere granițele de la
`app/domain/pdf_split.py` — care este pur și se poate citi fără bază de date — și,
la cererea unui om, scrie fiecare bucată ca **document propriu**, cu fișierul lui.

**Trei reguli care nu se negociază.**

1. **Originalul nu se atinge niciodată.** Rămâne în stocare, rămâne descărcabil,
   rămâne proba contabilă. Se marchează „desfăcut" și iese din coada de lucru,
   dar nu se șterge și nu se rescrie. Un document contabil nu dispare pentru că
   am înțeles noi ceva despre el.
2. **Fiecare bucată știe de unde vine.** `split_from_id`, `page_from`, `page_to`.
   Peste un an, întrebarea „de unde a apărut factura asta" trebuie să aibă un
   răspuns, nu o presupunere.
3. **Nimic nu se taie singur.** Detectarea rulează și propune; tăierea o cere un
   om, după ce vede unde s-ar tăia și de ce. O factură tăiată greșit produce două
   jumătăți care arată ca documente adevărate — iar ele intră în decont.

**Ce nu se poate face aici, și se spune pe față.** Un PDF fără strat de text — o
poză, un scan brut — nu poate fi tăiat: nu există semnale de citit. Se propune un
singur segment, adică „nu am ce tăia", nu „este un singur document".
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.domain import pdf_split
from app.domain.enums import DocumentStatus
from app.models.document import Document
from app.models.user import User
from app.services.audit import AuditService
from app.services.document_upload import DocumentUploadService
from app.services.storage import ObjectNotFoundError, StorageProvider

logger = get_logger(__name__)

#: Peste atâtea pagini nu se mai citește. Un teanc de o sută de pagini este deja
#: altceva decât o zi de documente, iar citirea lui întreagă ține cererea ocupată.
MAX_PAGES = 120

#: Sub atâtea segmente nu are rost să se taie nimic: unul singur înseamnă chiar
#: documentul de acum.
MIN_SEGMENTS = 2


@dataclass(frozen=True, slots=True)
class SplitPlan:
    """Ce s-ar întâmpla dacă cineva ar apăsa. Nu s-a scris nimic."""

    segments: tuple[pdf_split.Segment, ...]
    page_count: int
    #: `False` când PDF-ul nu are strat de text. Atunci un singur segment nu
    #: înseamnă „un document", înseamnă „nu am ce citi".
    readable: bool

    @property
    def splittable(self) -> bool:
        return len(self.segments) >= MIN_SEGMENTS


class DocumentSplitService:
    def __init__(self, session: Session, storage: StorageProvider) -> None:
        self.session = session
        self.storage = storage
        self.audit = AuditService(session)

    # ── Citire ──────────────────────────────────────────────────────────────

    def plan(self, document: Document) -> SplitPlan:
        """Unde s-ar tăia teancul, și de ce. Nu scrie nimic."""
        pages = self._pages(document)
        if not pages:
            return SplitPlan(segments=(), page_count=0, readable=False)

        readable = any(text.strip() for text in pages)
        segments = pdf_split.detect(pages)
        return SplitPlan(segments=tuple(segments), page_count=len(pages), readable=readable)

    # ── Scriere ─────────────────────────────────────────────────────────────

    def split(self, document: Document, *, actor: User, ip: str | None = None) -> list[Document]:
        """Desface teancul. Întoarce documentele nou create.

        Originalul rămâne, marcat `SPLIT`: nu mai are ce fi verificat, dar rămâne
        proba din care au ieșit celelalte.
        """
        if document.mime_type != "application/pdf":
            raise ValidationError(
                "Numai un PDF poate fi desfăcut.",
                {"documentId": ["Fișierul nu este PDF."]},
            )
        if document.split_from_id is not None:
            raise ValidationError(
                "Documentul este deja o bucată dintr-un teanc desfăcut.",
                {"documentId": ["Nu se poate desface a doua oară."]},
            )

        plan = self.plan(document)
        if not plan.splittable:
            raise ValidationError(
                "Nu am găsit mai multe documente în fișier.",
                {"documentId": ["Un singur document — nu este nimic de desfăcut."]},
            )

        source = self._read(document)
        uploads = DocumentUploadService(self.session, self.storage)
        created: list[Document] = []

        for index, segment in enumerate(plan.segments, start=1):
            piece = self._extract(source, segment)
            result = uploads.upload(
                organization_id=document.organization_id,
                stream=io.BytesIO(piece),
                # Numele spune din ce a ieșit și a câta bucată este. Numele
                # standardizat vine oricum la arhivare, din datele citite.
                original_filename=self._name(document, index, segment),
                source=document.source,
                uploaded_by=actor,
                # Clientul se moștenește: teancul a venit de la cineva anume, iar
                # bucățile lui sunt tot ale lui. Ce nu se moștenește este
                # extracția — fiecare bucată se citește singură.
                client_id=document.client_id,
                received_at=document.received_at,
            )
            child = result.document
            child.split_from_id = document.id
            child.page_from = segment.page_from
            child.page_to = segment.page_to
            created.append(child)

        document.status = DocumentStatus.SPLIT
        document.review_required = False
        document.split_at = datetime.now(UTC)
        self.session.flush()

        self.audit.record(
            organization_id=document.organization_id,
            action="DOCUMENT_SPLIT",
            entity_type="Document",
            entity_id=str(document.id),
            user_id=actor.id,
            user_name=actor.full_name,
            detail=f"{len(created)} documente din {plan.page_count} pagini",
            ip=ip,
        )
        logger.info(
            "document_split",
            document_id=str(document.id),
            pieces=len(created),
            pages=plan.page_count,
        )
        return created

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _read(self, document: Document) -> bytes:
        try:
            with self.storage.open(document.storage_key) as handle:
                return handle.read()
        except ObjectNotFoundError as exc:
            raise ValidationError(
                "Fișierul documentului nu se găsește în stocare.",
                {"documentId": ["Nu se poate citi."]},
            ) from exc

    def _pages(self, document: Document) -> list[str]:
        """Textul fiecărei pagini. Lista goală înseamnă „nu este un PDF citibil"."""
        if document.mime_type != "application/pdf":
            return []
        try:
            reader = PdfReader(io.BytesIO(self._read(document)))
            return [(page.extract_text() or "") for page in reader.pages[:MAX_PAGES]]
        except (PyPdfError, ValueError):
            # Un PDF stricat nu este o eroare de server: este un fișier pe care nu
            # îl putem tăia, iar ecranul o spune.
            logger.info("split_unreadable_pdf", document_id=str(document.id))
            return []

    @staticmethod
    def _extract(source: bytes, segment: pdf_split.Segment) -> bytes:
        """Paginile segmentului, ca PDF de sine stătător."""
        reader = PdfReader(io.BytesIO(source))
        writer = PdfWriter()
        for index in range(segment.page_from - 1, segment.page_to):
            writer.add_page(reader.pages[index])
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    @staticmethod
    def _name(document: Document, index: int, segment: pdf_split.Segment) -> str:
        """Numele bucății, lizibil, cu proveniența în el.

        `scan_001.pdf` → `scan_001 (1) p1-3.pdf`. Nu ajunge niciodată într-o cale:
        cheia de stocare este generată, ca la orice document.
        """
        stem = document.original_filename.rsplit(".", 1)[0][:120]
        span = (
            f"p{segment.page_from}"
            if segment.page_from == segment.page_to
            else f"p{segment.page_from}-{segment.page_to}"
        )
        return f"{stem} ({index}) {span}.pdf"


__all__ = ["MAX_PAGES", "MIN_SEGMENTS", "DocumentSplitService", "SplitPlan"]
