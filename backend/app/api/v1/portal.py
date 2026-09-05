"""Portalul clientului: singura rută publică prin care se poate **scrie** (M14).

**De ce există.** Partea cea mai grea a muncii unui cabinet nu este procesarea
documentelor, ci adunarea lor. Fiecare pas cerut clientului — să scaneze, să
atașeze, să nu depășească limita de mărime, să nu uite jumătate — este o lună
întârziată. Linkul mută efortul: clientul deschide o adresă, trage fișierele,
gata.

**Ce nu are voie să facă ruta asta, și de ce fiecare regulă există.**

- **Nu citește nimic.** Nu listează documente, nu descarcă, nu spune ce s-a
  trimis deja. Cine are linkul poate doar să adauge. Un link scurs este, în cel
  mai rău caz, un drum prin care sosesc documente nedorite — supărător, dar nu o
  scurgere de date.
- **Nu spune numele clientului.** Pagina publică arată numele **cabinetului**, ca
  omul să știe cui trimite. Un link ajuns din greșeală la altcineva n-are voie să
  spună cine este clientul.
- **Nu distinge motivele refuzului.** Token inexistent, expirat, revocat sau al
  unui client șters — toate întorc același 404. Cine încearcă linkuri nu are de ce
  să afle că unul a existat cândva.
- **Este limitată ca rată.** Restul aplicației cere o sesiune, deci un abuz are
  un nume; aici nu. Contorul stă pe token și pe adresă, iar limita este generoasă
  cât să nu deranjeze un client care trimite treizeci de facturi deodată.

Documentul intră cu clientul **deja atribuit**: apartenența vine din link, nu din
ghicit. Este a doua sursă, după e-Factura, în care nu există `UNMATCHED`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import DbSession, StorageDep, client_ip
from app.core.config import settings
from app.core.errors import AppError, ErrorCode, NotFoundError
from app.core.logging import get_logger
from app.core.rate_limit import FixedWindowLimiter
from app.domain.enums import DocumentSource
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError
from app.services.processing_queue import enqueue as enqueue_processing
from app.services.upload_links import LinkTarget, UploadLinkService

logger = get_logger(__name__)

router = APIRouter(prefix="/portal", tags=["portal"])

#: Câte fișiere poate trimite un link într-un minut. Generos: un client care
#: scanează un teanc trimite treizeci de bucăți una după alta, iar a-l opri exact
#: atunci ar fi cel mai prost moment posibil.
UPLOADS_PER_MINUTE = 60

_limiter = FixedWindowLimiter(limit=UPLOADS_PER_MINUTE)


class PortalInfoOut(ApiModel):
    """Ce vede cineva care deschide linkul, înainte să trimită ceva.

    Numele cabinetului și limitele fișierelor — nimic despre client, nimic despre
    ce s-a trimis până acum.
    """

    organization_name: str
    max_file_size_mb: int
    accepted_types: list[str]


class PortalUploadOut(ApiModel):
    """Confirmarea. Fără id-uri interne: nu are cine să le folosească."""

    filename: str
    accepted: bool
    message: str


def _target(session: Session, token: str) -> LinkTarget:
    """Unde duce linkul, sau 404.

    Același răspuns pentru inexistent, expirat, revocat sau al unui client șters:
    cine încearcă linkuri nu are de ce să afle că unul a existat cândva.
    """
    link = UploadLinkService(session).resolve(token)
    if link is None:
        raise NotFoundError("Link", token[:8])
    return link


@router.get("/{token}", response_model=PortalInfoOut)
def portal_info(session: DbSession, token: str) -> PortalInfoOut:
    """Cui îi trimiți și ce se acceptă."""
    link = _target(session, token)
    return PortalInfoOut(
        organization_name=link.organization_name,
        max_file_size_mb=settings.max_upload_size_mb,
        accepted_types=sorted(settings.allowed_mime_type_set),
    )


@router.post("/{token}", response_model=PortalUploadOut, status_code=status.HTTP_201_CREATED)
def portal_upload(
    session: DbSession,
    storage: StorageDep,
    request: Request,
    token: str,
    file: Annotated[UploadFile, File()],
) -> PortalUploadOut:
    """Primește un fișier de la client și îl duce direct la dosarul lui."""
    link = _target(session, token)
    ip = client_ip(request)

    # Contorul stă pe link, nu pe adresă: un birou întreg în spatele aceluiași IP
    # nu trebuie să se blocheze reciproc, iar un link abuzat se închide oricum.
    key = f"portal:{link.link_id}"
    decision = _limiter.blocked(key)
    if not decision.allowed:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "Prea multe fișiere trimise prea repede. Încearcă din nou într-un minut.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(decision.retry_after)},
        )
    _limiter.record(key)

    service = DocumentUploadService(session, storage)
    try:
        result = service.upload(
            organization_id=link.organization_id,
            stream=file.file,
            original_filename=file.filename or "document",
            source=DocumentSource.PORTAL,
            # Apartenența vine din link, nu din ghicit: documentul nu trece
            # niciodată prin `UNMATCHED`.
            client_id=link.client_id,
        )
    except FileValidationError as exc:
        # Motivul se spune, ca omul să știe ce să facă: un „nu a mers" fără cauză
        # îl face să reîncearce același fișier de trei ori.
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            exc.message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"file": [exc.code.value]},
        ) from exc

    UploadLinkService(session).note_use(link.link_id)

    # Urma spune că a intrat ceva prin portal, de la ce adresă, pentru ce client.
    # Autorul este linkul, nu un utilizator: nimeni nu s-a autentificat.
    AuditService(session).record(
        organization_id=link.organization_id,
        action="DOCUMENT_UPLOADED",
        entity_type="Document",
        entity_id=str(result.document.id),
        user_id=None,
        user_name="portal client",
        detail=result.document.original_filename,
        ip=ip,
    )
    session.commit()

    if not result.is_duplicate:
        enqueue_processing(session, result.document)
        session.commit()

    logger.info(
        "portal_upload",
        client_id=str(link.client_id),
        duplicate=result.is_duplicate,
    )

    if result.is_duplicate:
        return PortalUploadOut(
            filename=result.document.original_filename,
            accepted=True,
            message="Documentul fusese deja trimis. Nu este nevoie să îl retrimiți.",
        )
    return PortalUploadOut(
        filename=result.document.original_filename,
        accepted=True,
        message="Am primit documentul. Mulțumim.",
    )
