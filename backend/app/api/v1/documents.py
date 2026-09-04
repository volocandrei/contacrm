"""Rutele pentru documente (§24, §25, §26).

Contractul este cel pe care ecranele de documente și de verificare îl consumă deja
din backendul simulat. Preview și download sunt separate, în M5.4.

Nimic din răspunsuri nu conține `storage_key` sau vreo cale de filesystem (§73).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Literal

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
from pydantic import Field
from sqlalchemy import select

from app.api.deps import DbSession, StorageDep, client_ip, require_permission
from app.core.config import settings
from app.core.errors import AppError, ErrorCode, ForbiddenError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.document_actions import available_actions, reprocess_check
from app.domain.permissions import Permission, permissions_for
from app.models.audit import AuditLog
from app.models.document import VERSION_KINDS, Document, DocumentVersion
from app.models.user import User
from app.repositories.document import DocumentRepository, DocumentRow
from app.schemas.common import ApiModel, PageParams, Paginated
from app.schemas.document import (
    DocumentDetailOut,
    DocumentExtractionOut,
    DocumentFileOut,
    DocumentFilters,
    DocumentHistoryEntryOut,
    DocumentListItemOut,
    DocumentOcrOut,
    DocumentTypeOut,
)
from app.services.document_archive import DocumentArchiveService
from app.services.document_delivery import (
    CHUNK_SIZE,
    SECURITY_HEADERS,
    RangeNotSatisfiableError,
    companion_filename,
    content_disposition,
    disposition_for,
    parse_range,
    safe_filename,
    stored_size,
    stream,
)
from app.services.document_fields import FieldUpdate, read_fields
from app.services.document_processing import DocumentProcessingService
from app.services.document_service import ActorContext, DocumentService, approval_blockers
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError
from app.services.processing_queue import enqueue as enqueue_processing
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

# Cât de mare poate fi un lot. O acțiune în masă rămâne o cerere HTTP: peste
# atâtea documente, cererea durează mai mult decât are răbdare cineva, iar
# operatorul nu mai știe ce s-a întâmplat.
MAX_BULK_IDS = 200

# Peste acest prag, un job rămas `RUNNING` aparține unui proces care a murit;
# o cerere nouă de reprocesare îl readuce în coadă.
STALE_AFTER = timedelta(minutes=settings.processing_stale_after_minutes)


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


def _files(session: DbSession, document: Document) -> list[DocumentFileOut]:
    """Fișierele documentului, în ordinea în care au apărut.

    Se întoarce goală când nu există decât originalul: acolo lista ar fi un
    element care duce unde duce deja butonul de descărcare.
    """
    versions = session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_number)
    ).all()
    if len(versions) < 2:
        return []
    return [
        DocumentFileOut(
            id=version.id,
            kind=version.kind,
            label=VERSION_KINDS.get(version.kind, version.kind),
            mime_type=version.mime_type,
            file_size=version.file_size,
            created_at=version.created_at,
        )
        for version in versions
    ]


def _to_detail(session: DbSession, user: User, row: DocumentRow) -> DocumentDetailOut:
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
        available_actions=available_actions(
            document.status,
            permissions_for(user.primary_role),
            processing_attempts=document.processing_attempts,
            max_attempts=settings.max_processing_attempts,
        ),
        approval_blockers=approval_blockers(document),
        # De ce nu se poate reprocesa, când nu se poate: altfel butonul dispare fără
        # explicație, iar documentul pare pur și simplu uitat.
        reprocess_blocked_reason=reprocess_check(
            document.status,
            document.processing_attempts,
            max_attempts=settings.max_processing_attempts,
        )[1],
        history=_history(session, document),
        files=_files(session, document),
    )


def _detail(session: DbSession, user: User, document_id: uuid.UUID) -> DocumentDetailOut:
    return _to_detail(session, user, _fetch(session, user, document_id))


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


# Declarată **înaintea** lui `/documents/{document_id}`: altfel FastAPI ar încerca
# să citească „next-review" ca UUID și ar răspunde 422.
@router.get("/documents/next-review", response_model=DocumentDetailOut | None)
def next_review_document(
    session: DbSession,
    user: DocumentReader,
    after: uuid.UUID | None = None,
) -> DocumentDetailOut | None:
    """Următorul document care așteaptă un om (§31).

    Coada este cronologică: cel mai vechi primul, pentru că un document uitat la
    coada listei este exact cel care blochează o declarație. `after` scoate din
    coadă documentul tocmai închis, ca operatorul să nu revină pe el.

    Răspunde `null` — nu 404 — când coada este goală: „nu mai e nimic de făcut"
    este un răspuns valid, nu o eroare.
    """
    row = DocumentRepository(session).next_for_review(user.organization_id, exclude=after)
    return None if row is None else _to_detail(session, user, row)


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(
    session: DbSession, user: DocumentReader, document_id: uuid.UUID
) -> DocumentDetailOut:
    return _detail(session, user, document_id)


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
    # `clientId`, nu `client_id`: restul contractului este camelCase în ambele
    # direcții, iar un singur câmp de formular scris altfel ar fi exact genul de
    # excepție pe care nimeni nu o ține minte.
    client_id: Annotated[uuid.UUID | None, Form(alias="clientId")] = None,
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
    detail = _detail(session, user, document.id)

    # OCR-ul nu se face în cerere (§38): pornește după ce răspunsul a plecat.
    # Un duplicat nu se procesează — conținutul lui este deja cunoscut.
    if not result.is_duplicate:
        # Cererea de procesare se scrie în aceeași tranzacție cu documentul (§38):
        # ori se comit amândouă, ori niciunul. Fără outbox, un proces care cade
        # între commit și pornirea taskului ar lăsa documentul tăcut în `RECEIVED`.
        job = enqueue_processing(session, document, stale_after=STALE_AFTER)
        # Commit înainte de a porni taskul: acesta lucrează pe propria sesiune și
        # trebuie să vadă rândurile. Dacă moare oricum, jobul rămâne `PENDING` și
        # `app.cli recover-processing` îl reia.
        session.commit()
        background.add_task(
            run_processing,
            user.organization_id,
            document.id,
            storage,
            idempotency_key=job.idempotency_key,
        )
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
    return _detail(session, user, document_id)


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
    return _detail(session, user, document_id)


@router.post("/documents/{document_id}/approve", response_model=DocumentDetailOut)
def approve_document(
    session: DbSession,
    storage: StorageDep,
    user: DocumentApprover,
    request: Request,
    document_id: uuid.UUID,
) -> DocumentDetailOut:
    """Aprobă **și arhivează** documentul (§10, §11).

    Cele două se întâmplă în aceeași tranzacție: dacă arhivarea eșuează, aprobarea
    se dă înapoi odată cu ea. Nu există stare intermediară în care documentul este
    aprobat, dar nu se găsește nicăieri în arhivă.
    """
    DocumentService(session).approve(
        user.organization_id,
        document_id,
        _actor(user, request),
        archiver=DocumentArchiveService(session, storage),
    )
    return _detail(session, user, document_id)


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
    return _detail(session, user, document_id)


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
    return _detail(session, user, document_id)


# ── Acțiuni în masă (§26) ────────────────────────────────────────────────────


class BulkPayloadIn(ApiModel):
    """Ce se face cu fiecare document din listă."""

    action: Literal["approve", "reject", "assignClient", "markDuplicate", "reprocess"]
    reason: str | None = None
    client_id: uuid.UUID | None = None


class BulkIn(ApiModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_IDS)
    payload: BulkPayloadIn


class BulkFailureOut(ApiModel):
    id: uuid.UUID
    message: str


class BulkResultOut(ApiModel):
    succeeded: list[uuid.UUID]
    failed: list[BulkFailureOut]


@router.post("/documents/bulk", response_model=BulkResultOut)
def bulk_documents(
    session: DbSession,
    storage: StorageDep,
    user: DocumentWriter,
    request: Request,
    background: BackgroundTasks,
    payload: BulkIn,
) -> BulkResultOut:
    """Aceeași acțiune peste mai multe documente.

    **Fiecare document este propria tranzacție.** Un lot de cincizeci în care al
    treilea eșuează nu are voie să anuleze primele două: operatorul a apăsat un
    buton, dar a luat cincizeci de decizii. Rezultatul spune exact ce a mers și ce
    nu, cu motivul — un „au eșuat 7 documente" fără să spună care este inutilizabil.

    Permisiunea se verifică pe acțiune, nu pe rută: `approve` și `reject` cer
    `documents:approve`, pe care un OPERATOR nu îl are.
    """
    _assert_may(user, payload.payload.action)

    succeeded: list[uuid.UUID] = []
    failed: list[BulkFailureOut] = []
    to_process: list[tuple[uuid.UUID, str]] = []

    for document_id in payload.ids:
        savepoint = session.begin_nested()
        try:
            job_key = _apply_bulk(session, storage, user, request, document_id, payload.payload)
            savepoint.commit()
            succeeded.append(document_id)
            if job_key is not None:
                to_process.append((document_id, job_key))
        except AppError as exc:
            savepoint.rollback()
            failed.append(BulkFailureOut(id=document_id, message=_describe(exc)))
        except Exception:
            savepoint.rollback()
            logger.exception("bulk_action_crashed", document_id=str(document_id))
            failed.append(
                BulkFailureOut(id=document_id, message="Eroare neașteptată la procesare.")
            )

    if to_process:
        session.commit()
        for document_id, job_key in to_process:
            background.add_task(
                run_processing,
                user.organization_id,
                document_id,
                storage,
                idempotency_key=job_key,
                triggered_by=user.id,
            )

    return BulkResultOut(succeeded=succeeded, failed=failed)


def _describe(error: AppError) -> str:
    """Mesajul plus motivele concrete.

    „Documentul nu poate fi aprobat" nu ajută pe nimeni: exact detaliile spun *ce*
    lipsește, iar într-un lot de cincizeci ele sunt singurul mod în care operatorul
    poate repara ceva.
    """
    details = getattr(error, "details", None)
    if not details:
        return error.message
    reasons = [reason for values in details.values() for reason in values]
    if not reasons:
        return error.message
    return f"{error.message} " + " ".join(reasons)


def _assert_may(user: User, action: str) -> None:
    needed = (
        Permission.DOCUMENTS_APPROVE
        if action in {"approve", "reject"}
        else Permission.DOCUMENTS_WRITE
    )
    if needed not in permissions_for(user.primary_role):
        raise ForbiddenError()


def _apply_bulk(
    session: DbSession,
    storage: StorageDep,
    user: User,
    request: Request,
    document_id: uuid.UUID,
    payload: BulkPayloadIn,
) -> str | None:
    """Execută o acțiune. Întoarce cheia jobului dacă a fost programată o procesare."""
    service = DocumentService(session)
    actor = _actor(user, request)
    row = _fetch(session, user, document_id)

    match payload.action:
        case "approve":
            service.approve(
                user.organization_id,
                document_id,
                actor,
                archiver=DocumentArchiveService(session, storage),
            )
        case "reject":
            if not (payload.reason or "").strip():
                raise ValidationError(
                    "Motivul respingerii este obligatoriu.", {"reason": ["Câmp obligatoriu."]}
                )
            service.reject(user.organization_id, document_id, payload.reason or "", actor)
        case "assignClient":
            if payload.client_id is None:
                raise ValidationError(
                    "Clientul este obligatoriu.", {"clientId": ["Câmp obligatoriu."]}
                )
            service.assign_client(user.organization_id, document_id, payload.client_id, actor)
        case "markDuplicate":
            service.mark_duplicate(user.organization_id, document_id, None, actor)
        case "reprocess":
            service.begin_reprocessing(user.organization_id, document_id, actor)
            job = enqueue_processing(session, row.document, stale_after=STALE_AFTER)
            return job.idempotency_key
    return None


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


@router.get("/documents/{document_id}/files/{file_id}")
def download_document_file(
    session: DbSession,
    storage: StorageDep,
    user: DocumentReader,
    request: Request,
    document_id: uuid.UUID,
    file_id: uuid.UUID,
) -> StreamingResponse:
    """Un fișier care însoțește documentul — arhiva ANAF sau PDF-ul oficial.

    Contează mai ales pentru arhiva cu sigiliul ANAF: la un control, ea este
    dovada că factura a fost acceptată, iar spre deosebire de PDF nu se poate
    reface. Se auditează, ca orice ieșire a unei probe contabile din sistem.

    Fișierul se caută **prin document**, nu direct după id: altfel identificatorul
    unei versiuni ar deschide fișiere din altă organizație (§72).
    """
    row = _fetch(session, user, document_id)
    version = session.scalars(
        select(DocumentVersion).where(
            DocumentVersion.id == file_id, DocumentVersion.document_id == row.document.id
        )
    ).first()
    if version is None:
        raise NotFoundError("Fișierul documentului", file_id)

    try:
        chunks = storage.iter_chunks(version.storage_key, CHUNK_SIZE)
    except ObjectNotFoundError as exc:
        # Rândul există, fișierul nu. Nu spunem ce cheie lipsește (§73).
        logger.error("document_file_missing", document_id=str(document_id), kind=version.kind)
        raise NotFoundError("Fișierul documentului", file_id) from exc

    name = companion_filename(row.document, kind=version.kind, mime_type=version.mime_type)
    DocumentService(session).audit.record(
        organization_id=user.organization_id,
        action="DOCUMENT_FILE_DOWNLOADED",
        entity_type="Document",
        entity_id=str(document_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=name,
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    session.flush()

    return StreamingResponse(
        chunks,
        media_type=version.mime_type,
        headers={
            **SECURITY_HEADERS,
            "Content-Disposition": disposition_for(name, inline=False),
            "Content-Length": str(version.file_size),
        },
    )


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

    DocumentService(session).begin_reprocessing(
        user.organization_id, document_id, _actor(user, request)
    )
    job = enqueue_processing(session, document, stale_after=STALE_AFTER)

    # Ca la upload: starea și jobul trebuie să fie vizibile workerului.
    session.commit()

    background.add_task(
        run_processing,
        user.organization_id,
        document_id,
        storage,
        idempotency_key=job.idempotency_key,
        triggered_by=user.id,
    )
    return _detail(session, user, document_id)
