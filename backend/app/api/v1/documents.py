"""Rutele pentru documente (§24, §25, §26).

Contractul este cel pe care ecranele de documente și de verificare îl consumă deja
din backendul simulat. Preview și download sunt separate, în M5.4.

Nimic din răspunsuri nu conține `storage_key` sau vreo cale de filesystem (§73).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DbSession, StorageDep, client_ip, require_permission
from app.core.errors import AppError, ErrorCode, NotFoundError
from app.core.logging import get_logger
from app.domain.permissions import Permission
from app.models.audit import AuditLog
from app.models.document import Document
from app.models.user import User
from app.repositories.document import DocumentRepository, DocumentRow
from app.schemas.common import ApiModel, PageParams, Paginated
from app.schemas.document import (
    DocumentDetailOut,
    DocumentExtractionOut,
    DocumentFilters,
    DocumentHistoryEntryOut,
    DocumentListItemOut,
    DocumentOcrOut,
    DocumentTypeOut,
)
from app.services.document_delivery import (
    SECURITY_HEADERS,
    RangeNotSatisfiableError,
    content_disposition,
    parse_range,
    safe_filename,
    stored_size,
    stream,
)
from app.services.document_fields import FieldUpdate, read_fields
from app.services.document_processing import DocumentProcessingService
from app.services.document_service import ActorContext, DocumentService
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError
from app.services.processing_runner import build_extractor, run_processing
from app.services.storage import ObjectNotFoundError

logger = get_logger(__name__)

router = APIRouter(tags=["documente"])

DocumentReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]
DocumentWriter = Annotated[User, require_permission(Permission.DOCUMENTS_WRITE)]
DocumentApprover = Annotated[User, require_permission(Permission.DOCUMENTS_APPROVE)]

# Câte caractere din textul OCR ajung în ecranul de verificare. Textul complet nu
# se trimite niciodată la deschiderea unui document (§64).
OCR_PREVIEW_CHARS = 600


# ── Corpuri de cerere ────────────────────────────────────────────────────────


class FieldUpdateIn(ApiModel):
    field: str
    value: str | None = None


class UpdateFieldsIn(ApiModel):
    updates: list[FieldUpdateIn]


class AssignClientIn(ApiModel):
    client_id: uuid.UUID


class RejectIn(ApiModel):
    reason: str


class MarkDuplicateIn(ApiModel):
    duplicate_of_id: uuid.UUID | None = None


# ── Conversii către contractul frontend ──────────────────────────────────────


def to_list_item(row: DocumentRow) -> DocumentListItemOut:
    """Mapper partajat: si lista de documente, si cea per client trec prin el."""
    document = row.document
    return DocumentListItemOut(
        id=document.id,
        original_filename=document.original_filename,
        stored_filename=document.stored_filename,
        client_id=document.client_id,
        client_name=row.client_name,
        document_type_code=document.document_type.code if document.document_type else None,
        document_type_label=document.document_type.label if document.document_type else None,
        source=document.source,
        received_at=document.received_at,
        document_date=document.document_date,
        reference_month=document.reference_month,
        supplier_name=document.supplier_name,
        document_number=document.document_number,
        total_amount=None if document.total_amount is None else f"{document.total_amount:.2f}",
        currency=document.currency,
        status=document.status,
        confidence=document.confidence,
        is_duplicate=document.is_duplicate,
        review_required=document.review_required,
    )


def _history(session: DbSession, document: Document) -> list[DocumentHistoryEntryOut]:
    """Istoricul vizibil în ecranul de verificare, construit din jurnalul de audit.

    Nu există un al doilea jurnal: auditul este sursa (§33, §68).
    """
    entries = session.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "Document", AuditLog.entity_id == str(document.id))
        .order_by(AuditLog.created_at)
    ).all()
    return [
        DocumentHistoryEntryOut(
            id=entry.id,
            at=entry.created_at,
            actor=entry.user_name,
            action=entry.action,
            detail=entry.detail,
        )
        for entry in entries
    ]


def _to_detail(session: DbSession, row: DocumentRow) -> DocumentDetailOut:
    document = row.document
    base = to_list_item(row)
    preview = document.ocr_text[:OCR_PREVIEW_CHARS] if document.ocr_text else None
    return DocumentDetailOut(
        **base.model_dump(),
        mime_type=document.mime_type,
        file_size=document.file_size,
        sha256=document.sha256_hash,
        duplicate_of_id=document.duplicate_of_id,
        error_code=document.error_code,
        processing_attempts=document.processing_attempts,
        fields=read_fields(document),
        ocr=DocumentOcrOut(
            provider=document.ocr_provider,
            confidence=document.ocr_confidence,
            text_preview=preview,
        ),
        extraction=DocumentExtractionOut(
            provider=document.ai_provider,
            model=document.ai_model,
            prompt_version=document.ai_prompt_version,
            duration_ms=document.extraction_duration_ms,
        ),
        validation_issues=list(document.validation_issues or []),
        history=_history(session, document),
    )


def _fetch(session: DbSession, user: User, document_id: uuid.UUID) -> DocumentRow:
    row = DocumentRepository(session).get(user.organization_id, document_id)
    if row is None:
        raise NotFoundError("Document", document_id)
    return row


def _actor(user: User, request: Request) -> ActorContext:
    return ActorContext(
        user=user, ip=client_ip(request), user_agent=request.headers.get("User-Agent")
    )


# ── Tipuri de document ───────────────────────────────────────────────────────


@router.get("/document-types", response_model=list[DocumentTypeOut])
def list_document_types(session: DbSession, user: DocumentReader) -> list[DocumentTypeOut]:
    return [
        DocumentTypeOut(
            code=t.code,
            label=t.label,
            is_active=t.is_active,
            required_fields=list(t.required_fields or []),
        )
        for t in DocumentRepository(session).list_types(user.organization_id)
    ]


# ── Listă și detaliu ─────────────────────────────────────────────────────────


@router.get("/documents", response_model=Paginated[DocumentListItemOut])
def list_documents(
    session: DbSession,
    user: DocumentReader,
    # `Query()`, nu `Depends()`: un camp `list[...]` intr-un model legat prin
    # `Depends` nu este citit deloc din query string.
    filters: Annotated[DocumentFilters, Query()],
    page: Annotated[PageParams, Depends()],
) -> Paginated[DocumentListItemOut]:
    rows, total = DocumentRepository(session).list(user.organization_id, filters, page)
    return Paginated[DocumentListItemOut].build(
        items=[to_list_item(row) for row in rows], total=total, params=page
    )


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(
    session: DbSession, user: DocumentReader, document_id: uuid.UUID
) -> DocumentDetailOut:
    return _to_detail(session, _fetch(session, user, document_id))


# ── Upload ───────────────────────────────────────────────────────────────────


@router.post(
    "/documents/upload",
    response_model=DocumentDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    session: DbSession,
    storage: StorageDep,
    user: DocumentWriter,
    request: Request,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    client_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentDetailOut:
    """Primește un fișier și creează documentul.

    Tipul se determină din conținut, nu din `content_type` trimis de client (§50).
    Procesarea nu se face aici: workerul o preia la M5.5 (§38).
    """
    service = DocumentUploadService(session, storage)
    try:
        result = service.upload(
            organization_id=user.organization_id,
            stream=file.file,
            original_filename=file.filename or "document",
            uploaded_by=user,
            client_id=client_id,
        )
    except FileValidationError as exc:
        # Codul structurat ajunge la utilizator ca eroare de validare, nu ca 500.
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            exc.message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"file": [exc.code.value]},
        ) from exc

    document = result.document
    DocumentService(session).audit.record(
        organization_id=user.organization_id,
        action="DOCUMENT_UPLOADED",
        entity_type="Document",
        entity_id=str(document.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=document.original_filename,
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    session.flush()
    detail = _to_detail(session, _fetch(session, user, document.id))

    # OCR-ul nu se face în cerere (§38): pornește după ce răspunsul a plecat.
    # Un duplicat nu se procesează — conținutul lui este deja cunoscut.
    if not result.is_duplicate:
        # Commit **înainte** de a programa procesarea. Altfel workerul pornește pe o
        # tranzacție încă necomisă și nu găsește documentul — cursa clasică
        # „enqueue înainte de commit". Varianta complet corectă este un outbox
        # tranzacțional; până la coada persistentă (M6), commit-ul explicit aici
        # este suficient și onest: în acest punct upload-ul chiar s-a terminat.
        session.commit()
        background.add_task(run_processing, user.organization_id, document.id, storage)
    return detail


# ── Modificare și acțiuni ────────────────────────────────────────────────────


@router.patch("/documents/{document_id}", response_model=DocumentDetailOut)
def update_document(
    session: DbSession,
    user: DocumentWriter,
    request: Request,
    document_id: uuid.UUID,
    payload: UpdateFieldsIn,
) -> DocumentDetailOut:
    DocumentService(session).update_fields(
        user.organization_id,
        document_id,
        [FieldUpdate(field=u.field, value=u.value) for u in payload.updates],
        _actor(user, request),
    )
    return _to_detail(session, _fetch(session, user, document_id))


@router.post("/documents/{document_id}/assign-client", response_model=DocumentDetailOut)
def assign_client(
    session: DbSession,
    user: DocumentWriter,
    request: Request,
    document_id: uuid.UUID,
    payload: AssignClientIn,
) -> DocumentDetailOut:
    DocumentService(session).assign_client(
        user.organization_id, document_id, payload.client_id, _actor(user, request)
    )
    return _to_detail(session, _fetch(session, user, document_id))


@router.post("/documents/{document_id}/approve", response_model=DocumentDetailOut)
def approve_document(
    session: DbSession,
    user: DocumentApprover,
    request: Request,
    document_id: uuid.UUID,
) -> DocumentDetailOut:
    DocumentService(session).approve(user.organization_id, document_id, _actor(user, request))
    return _to_detail(session, _fetch(session, user, document_id))


@router.post("/documents/{document_id}/reject", response_model=DocumentDetailOut)
def reject_document(
    session: DbSession,
    user: DocumentApprover,
    request: Request,
    document_id: uuid.UUID,
    payload: RejectIn,
) -> DocumentDetailOut:
    DocumentService(session).reject(
        user.organization_id, document_id, payload.reason, _actor(user, request)
    )
    return _to_detail(session, _fetch(session, user, document_id))


@router.post("/documents/{document_id}/duplicate", response_model=DocumentDetailOut)
def mark_duplicate(
    session: DbSession,
    user: DocumentWriter,
    request: Request,
    document_id: uuid.UUID,
    payload: MarkDuplicateIn,
) -> DocumentDetailOut:
    DocumentService(session).mark_duplicate(
        user.organization_id, document_id, payload.duplicate_of_id, _actor(user, request)
    )
    return _to_detail(session, _fetch(session, user, document_id))


# ── Preview și download (§27-§30) ────────────────────────────────────────────


def _serve(
    session: DbSession,
    storage: StorageDep,
    user: User,
    document_id: uuid.UUID,
    request: Request,
    *,
    inline: bool,
) -> StreamingResponse:
    """Trunchiul comun al celor două rute.

    Autentificarea vine din cookie-ul de sesiune, la fel ca pentru orice altă rută:
    `<img>` și `<object>` nu trimit antetul `Authorization`, dar trimit cookie-ul.
    Nu există și nu trebuie să existe un token în query string (§27).
    """
    row = _fetch(session, user, document_id)
    document = row.document

    try:
        size = stored_size(storage, document)
    except ObjectNotFoundError as exc:
        # Rândul există, fișierul nu. Nu spunem ce cheie lipsește (§73).
        logger.error("document_file_missing", document_id=str(document.id))
        raise NotFoundError("Fișierul documentului", document_id) from exc

    try:
        byte_range = parse_range(request.headers.get("Range"), size)
    except RangeNotSatisfiableError:
        return StreamingResponse(
            iter(()),
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={**SECURITY_HEADERS, "Content-Range": f"bytes */{size}"},
        )

    headers = {
        **SECURITY_HEADERS,
        "Content-Disposition": content_disposition(document, inline=inline),
        "Accept-Ranges": "bytes",
    }
    if byte_range is None:
        headers["Content-Length"] = str(size)
        code = status.HTTP_200_OK
    else:
        headers["Content-Length"] = str(byte_range.length)
        headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{size}"
        code = status.HTTP_206_PARTIAL_CONTENT

    return StreamingResponse(
        stream(storage, document, byte_range=byte_range),
        status_code=code,
        # Tipul validat la upload, nu cel declarat de client (§50).
        media_type=document.mime_type,
        headers=headers,
    )


@router.get("/documents/{document_id}/preview")
def preview_document(
    session: DbSession,
    storage: StorageDep,
    user: DocumentReader,
    request: Request,
    document_id: uuid.UUID,
) -> StreamingResponse:
    """Conținutul documentului, pentru afișare în pagină.

    Nu se auditează: previzualizarea se întâmplă la fiecare deschidere de ecran, iar
    volumul ar îneca intrările care contează (§33).
    """
    return _serve(session, storage, user, document_id, request, inline=True)


@router.get("/documents/{document_id}/download")
def download_document(
    session: DbSession,
    storage: StorageDep,
    user: DocumentReader,
    request: Request,
    document_id: uuid.UUID,
) -> StreamingResponse:
    """Descărcarea documentului, cu numele standardizat (§29).

    Spre deosebire de previzualizare, descărcarea **se auditează**: este actul prin
    care o probă contabilă părăsește sistemul.
    """
    response = _serve(session, storage, user, document_id, request, inline=False)
    row = _fetch(session, user, document_id)
    DocumentService(session).audit.record(
        organization_id=user.organization_id,
        action="DOCUMENT_DOWNLOADED",
        entity_type="Document",
        entity_id=str(document_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=safe_filename(row.document),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    session.flush()
    return response


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentDetailOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def reprocess_document(
    session: DbSession,
    storage: StorageDep,
    user: DocumentWriter,
    request: Request,
    background: BackgroundTasks,
    document_id: uuid.UUID,
) -> DocumentDetailOut:
    """Reia procesarea unui document existent (§54).

    Nu creează un document nou și nu șterge istoricul: `processing_attempts` crește,
    iar corecțiile manuale rămân neatinse. Răspunde 202 — rezultatul apare când
    workerul termină.
    """
    row = _fetch(session, user, document_id)
    document = row.document

    allowed, reason = DocumentProcessingService(session, storage, build_extractor()).can_reprocess(
        document
    )
    if not allowed:
        raise AppError(ErrorCode.CONFLICT, reason or "Documentul nu poate fi reprocesat.")

    DocumentService(session).audit.record(
        organization_id=user.organization_id,
        action="DOCUMENT_REPROCESS_REQUESTED",
        entity_type="Document",
        entity_id=str(document_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"încercarea {document.processing_attempts + 1}",
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    # Ca la upload: intrarea de audit trebuie să fie vizibilă workerului.
    session.commit()

    background.add_task(
        run_processing,
        user.organization_id,
        document_id,
        storage,
        triggered_by=user.id,
    )
    return _to_detail(session, _fetch(session, user, document_id))
