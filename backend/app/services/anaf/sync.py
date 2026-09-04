"""Preluarea facturilor electronice din SPV (M11).

Asta este a doua jumătate a cererii cabinetului, după dosarele din OneDrive: *„să
îmi ia singur facturile din e-Factura, cu tot cu PDF-ul citibil și cu dovada de
la ANAF"*. Cele **trei fișiere** ale unei facturi ajung aici dintr-un singur
mesaj SPV:

- **arhiva ZIP**, exact cum a dat-o ANAF, cu sigiliul electronic înăuntru — ea
  este dovada că factura a fost acceptată;
- **XML-ul**, membru al aceleiași arhive, scos nemodificat: el este documentul
  fiscal și tot el este ce citește extracția (`domain/efactura.py`);
- **PDF-ul oficial**, obținut de la convertorul public al ANAF — singurul dintre
  cele trei care poate fi refăcut oricând, deci singurul al cărui eșec nu are
  voie să piardă factura.

Toate trei stau pe **un singur document**. Un contabil vede o factură, nu trei
fișiere; iar dacă ar fi trei documente, detectarea duplicatelor, luna contabilă
și arhivarea ar trebui să știe care dintre ele „este" factura.

**Aici clientul nu se ghicește.** La email trebuie potrivit expeditorul, la drive
dosarul; aici interogarea se face pe CUI-ul clientului, deci apartenența vine din
cerere. Este singura sursă din tot sistemul în care atribuirea nu poate greși.

Trei proprietăți pe care se sprijină restul, aceleași ca la drive și din aceleași
motive:

- **Idempotență.** `id_descarcare` este cheia: același mesaj văzut de două ori —
  pentru că fereastra s-a suprapus, pentru că cineva a apăsat „Sincronizează" —
  nu produce un al doilea document.
- **O factură eșuată nu oprește turul.** O arhivă coruptă, un XML care nu este
  factură, o descărcare picată: se notează pe intake și se trece mai departe.
- **Fereastra de timp se închide abia după ce facturile au intrat.** Închisă
  înainte, o cădere la mijloc ar face ca facturile necitite să nu mai fie văzute
  niciodată — pierderea tăcută, cea mai urâtă.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import TokenDecryptionError, decrypt
from app.core.logging import get_logger
from app.domain.enums import DocumentSource, EFacturaMessageKind, IntakeStatus
from app.models.anaf import AnafConnection, AnafMandate
from app.models.document import (
    VERSION_ANAF_PDF,
    VERSION_ANAF_ZIP,
    VERSION_MIME,
    Document,
    DocumentIntake,
    DocumentVersion,
)
from app.services.anaf.archive import AnafArchive, AnafArchiveError, unpack
from app.services.anaf.base import (
    AnafAuthError,
    AnafClient,
    AnafError,
    AnafMandateError,
    SpvMessage,
)
from app.services.audit import AuditService
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError
from app.services.processing_queue import enqueue as enqueue_processing
from app.services.storage import StorageProvider, efactura_key
from app.services.storage.base import StorageError

logger = get_logger(__name__)

#: Cât de lungă poate fi o eroare păstrată pe rând. Coloana are 512.
MAX_ERROR = 500

#: ANAF nu acceptă ferestre mai lungi de atât într-o singură cerere.
MAX_WINDOW = timedelta(days=60)

#: Cât se suprapune fereastra nouă peste cea închisă. Un mesaj apărut chiar în
#: secunda închiderii ar cădea altfel exact între două ferestre; costul
#: suprapunerii este zero, pentru că `id_descarcare` oprește orice repetare.
WINDOW_OVERLAP = timedelta(minutes=5)

#: Doar facturile ne interesează. `ERORI FACTURA` și `MESAJ` privesc trimiterea,
#: pe care faza asta nu o face — se ignoră **explicit**, nu printr-un `else`.
INVOICE_KINDS = frozenset({EFacturaMessageKind.RECEIVED, EFacturaMessageKind.SENT})

#: Ce se scrie pe document când PDF-ul oficial nu a putut fi obținut. Factura
#: există, arhiva există; lipsește doar forma tipăribilă, care se poate reface.
#:
#: Textul promite ce se întâmplă chiar — vezi `_retry_missing_pdfs`. Prima
#: variantă trimitea la „reprocesare", care nu cheamă convertorul ANAF deloc:
#: extracția citește XML-ul deja stocat. Ar fi fost o promisiune falsă scrisă pe
#: un document contabil.
PDF_MISSING = (
    "PDF-ul oficial ANAF nu a putut fi generat acum. Factura (XML) și arhiva cu "
    "sigiliul ANAF sunt salvate; PDF-ul se reia automat la o sincronizare următoare."
)

#: Câte PDF-uri lipsă se reîncearcă într-un tur. Convertorul ANAF este public și
#: uneori indisponibil, deci documentele fără PDF se pot strânge — dar nu au voie
#: să mănânce turul în care ar trebui să intre facturi noi.
PDF_RETRY_PER_RUN = 5


@dataclass(slots=True)
class MandateResult:
    """Ce s-a întâmplat cu un client într-un tur."""

    mandate_id: uuid.UUID
    tax_id: str
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    error: str | None = None
    #: Fereastra mai are pagini de citit. Turul următor continuă de la aceeași
    #: dată de început — nu se închide nimic pe jumătate.
    has_more: bool = False


@dataclass(slots=True)
class AnafSyncResult:
    """Rezultatul unui tur complet, pe o organizație."""

    mandates: list[MandateResult] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(mandate.ingested for mandate in self.mandates)

    @property
    def failed(self) -> int:
        return sum(mandate.failed for mandate in self.mandates)

    @property
    def has_more(self) -> bool:
        return any(mandate.has_more for mandate in self.mandates)


class AnafSyncService:
    """Un tur peste împuternicirile active ale unei organizații."""

    def __init__(self, session: Session, storage: StorageProvider, client: AnafClient) -> None:
        self.session = session
        self.storage = storage
        self.client = client
        self.uploads = DocumentUploadService(session, storage)
        self.audit = AuditService(session)

    # ── Turul ───────────────────────────────────────────────────────────────

    def sync_organization(self, organization_id: uuid.UUID) -> AnafSyncResult:
        """Sincronizează toate împuternicirile active. Nu aruncă: raportează."""
        result = AnafSyncResult()

        connection = self.session.scalars(
            select(AnafConnection).where(
                AnafConnection.organization_id == organization_id,
                AnafConnection.is_active.is_(True),
            )
        ).first()
        if connection is None:
            return result

        try:
            refresh_token = decrypt(connection.refresh_token)
        except TokenDecryptionError as exc:
            # Cheia s-a schimbat. Nu este o problemă a vreunui client, ci a
            # instalării: se notează pe conexiune, unde ecranul o arată o dată.
            connection.last_error = str(exc)[:MAX_ERROR]
            return result

        mandates = self.session.scalars(
            select(AnafMandate).where(
                AnafMandate.connection_id == connection.id,
                AnafMandate.is_active.is_(True),
            )
        ).all()

        for mandate in mandates:
            result.mandates.append(self._sync_mandate(mandate, refresh_token))

        # Convertorul este public, deci reluarea nu are nevoie de token: merge și
        # când certificatul a expirat, adică exact când nimic altceva nu merge.
        self._retry_missing_pdfs(organization_id)

        connection.last_sync_at = datetime.now(UTC)
        # Reautorizarea este singura problemă care aparține conexiunii: dacă apare,
        # toate împuternicirile au aceeași problemă.
        connection.last_error = next(
            (m.error for m in result.mandates if m.error and "autoriz" in m.error.lower()), None
        )
        return result

    def _window(self, mandate: AnafMandate) -> tuple[datetime, datetime]:
        """De unde până unde citim lista de mesaje pentru clientul ăsta.

        O împuternicire nouă pleacă de la `ANAF_LOOKBACK_DAYS` în urmă. Una care a
        stat oprită mai mult de 60 de zile nu poate recupera tot: ANAF nu acceptă
        ferestre mai lungi, deci se ia ce se poate, iar turul următor continuă.
        """
        end = datetime.now(UTC)
        if mandate.synced_through is None:
            start = end - timedelta(days=settings.anaf_lookback_days)
        else:
            previous = mandate.synced_through
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=UTC)
            start = previous - WINDOW_OVERLAP
        return max(start, end - MAX_WINDOW), end

    def _sync_mandate(self, mandate: AnafMandate, refresh_token: str) -> MandateResult:
        outcome = MandateResult(mandate_id=mandate.id, tax_id=mandate.tax_id)
        start, end = self._window(mandate)

        try:
            page = self.client.list_messages(
                refresh_token,
                tax_id=mandate.tax_id,
                start=start,
                end=end,
                limit=settings.anaf_sync_batch,
            )
        except AnafMandateError as exc:
            # Cazul central al integrării, și nu este al nostru: clientul nu a
            # depus împuternicirea. Se arată pe rândul lui, cu ce are de făcut.
            outcome.error = str(exc)[:MAX_ERROR]
            mandate.last_error = outcome.error
            return outcome
        except AnafAuthError as exc:
            outcome.error = str(exc)[:MAX_ERROR]
            mandate.last_error = outcome.error
            return outcome
        except AnafError as exc:
            outcome.error = str(exc)[:MAX_ERROR]
            mandate.last_error = outcome.error
            logger.warning("anaf_list_failed", tax_id=mandate.tax_id, error=str(exc))
            return outcome

        for message in page.messages:
            self._take(mandate, message, refresh_token, outcome)

        mandate.last_synced_at = datetime.now(UTC)
        mandate.last_error = None
        outcome.has_more = page.has_more
        if not page.has_more:
            # Abia acum: o factură necitită trebuie să reapară în turul următor.
            mandate.synced_through = end
        return outcome

    # ── O factură ───────────────────────────────────────────────────────────

    def _take(
        self,
        mandate: AnafMandate,
        message: SpvMessage,
        refresh_token: str,
        outcome: MandateResult,
    ) -> None:
        """Aduce o factură. Orice eșec este al ei, nu al clientului."""
        if message.kind not in INVOICE_KINDS:
            outcome.skipped += 1
            return

        if self._already_taken(mandate.organization_id, message.id):
            outcome.skipped += 1
            return

        received_at = message.created_at or datetime.now(UTC)
        intake = DocumentIntake(
            organization_id=mandate.organization_id,
            source=DocumentSource.EFACTURA,
            status=IntakeStatus.RECEIVED,
            # Cheia pe care se sprijină idempotența, și e una singură: ANAF dă
            # fiecărui mesaj un `id_descarcare` unic și stabil.
            external_message_id=message.id[:255],
            sender=f"ANAF SPV · CUI {mandate.tax_id}"[:320],
            subject=f"{message.kind.value} · {message.detail}"[:512],
            original_filename=f"{message.id}.zip"[:512],
            received_at=received_at,
            raw_payload={
                "messageId": message.id,
                "kind": message.kind.value,
                "taxId": message.tax_id,
                "detail": message.detail,
            },
        )
        self.session.add(intake)
        self.session.flush()

        try:
            payload = self.client.download(refresh_token, message_id=message.id)
        except AnafError as exc:
            self._reject(intake, f"Descărcare eșuată: {exc}")
            outcome.failed += 1
            return

        try:
            archive = unpack(payload)
        except AnafArchiveError as exc:
            # Cazul obișnuit aici nu este o arhivă stricată, ci un mesaj care nu
            # conține o factură — un raport de erori, de pildă. Motivul se
            # păstrează întreg pe intake, ca să se vadă în „Documente respinse".
            self._reject(intake, str(exc))
            outcome.failed += 1
            return

        try:
            upload = self.uploads.upload(
                organization_id=mandate.organization_id,
                stream=io.BytesIO(archive.invoice_xml),
                original_filename=archive.invoice_name,
                source=DocumentSource.EFACTURA,
                # CUI-ul interogat *este* clientul. Nimic de dedus.
                client_id=mandate.client_id,
                intake=intake,
                received_at=received_at,
            )
        except FileValidationError as exc:  # pragma: no cover — XML-ul a trecut deja parsarea
            self._reject(intake, exc.message)
            outcome.failed += 1
            return

        self._attach_files(upload.document, payload, archive)

        intake.status = IntakeStatus.DUPLICATE if upload.is_duplicate else IntakeStatus.ACCEPTED
        intake.document_id = upload.document.id
        mandate.invoices_ingested += 1
        outcome.ingested += 1

        self.audit.record(
            organization_id=mandate.organization_id,
            action="DOCUMENT_INGESTED_FROM_ANAF",
            entity_type="Document",
            entity_id=str(upload.document.id),
            # Fără utilizator: nu a apăsat nimeni nimic.
            user_id=None,
            user_name="Sistem · e-Factura",
            detail=f"{message.kind.value} · CUI {mandate.tax_id} · mesaj {message.id}",
        )

        if not upload.is_duplicate:
            enqueue_processing(self.session, upload.document)

    # ── Cele două fișiere care însoțesc XML-ul ──────────────────────────────

    def _attach_files(self, document: Document, payload: bytes, archive: AnafArchive) -> None:
        """Salvează arhiva ANAF și PDF-ul oficial lângă factură.

        Ordinea nu este întâmplătoare: **întâi arhiva**, care este dovada și nu se
        poate reface, apoi PDF-ul, care se poate. Dacă al doilea eșuează, primul
        este deja în siguranță.
        """
        self._store(document, kind=VERSION_ANAF_ZIP, name="seal", payload=payload)

        try:
            rendered = self.client.render_pdf(archive.invoice_xml)
        except AnafError as exc:
            # Convertorul ANAF este public și, uneori, indisponibil. Factura și
            # dovada ei sunt deja salvate; lipsa PDF-ului se spune pe document,
            # unde o vede un om, nu doar în log.
            logger.warning("anaf_pdf_failed", document_id=str(document.id), error=str(exc))
            document.validation_issues = [*document.validation_issues, PDF_MISSING]
            document.review_required = True
            return

        self._store(document, kind=VERSION_ANAF_PDF, name="render", payload=rendered)

    def _retry_missing_pdfs(self, organization_id: uuid.UUID) -> int:
        """Reia conversia pentru facturile rămase fără PDF oficial.

        Convertorul ANAF este public și, uneori, indisponibil. Fără pasul ăsta,
        o oră proastă a ANAF ar lăsa facturile din ea fără forma tipăribilă
        **pentru totdeauna**: reprocesarea nu cheamă convertorul — extracția
        citește XML-ul deja stocat — iar nimic altceva nu s-ar mai uita la ele.

        Se reia din XML-ul stocat, nu din arhivă: sunt aceiași octeți, iar arhiva
        nu are de ce să fie despachetată a doua oară.
        """
        pending = self.session.scalars(
            select(Document)
            .where(
                Document.organization_id == organization_id,
                Document.source == DocumentSource.EFACTURA,
                Document.deleted_at.is_(None),
                # Are dovada, dar nu are forma tipăribilă.
                Document.id.in_(
                    select(DocumentVersion.document_id).where(
                        DocumentVersion.kind == VERSION_ANAF_ZIP
                    )
                ),
                Document.id.not_in(
                    select(DocumentVersion.document_id).where(
                        DocumentVersion.kind == VERSION_ANAF_PDF
                    )
                ),
            )
            .order_by(Document.received_at)
            .limit(PDF_RETRY_PER_RUN)
        ).all()

        recovered = 0
        for document in pending:
            try:
                with self.storage.open(document.storage_key) as handle:
                    invoice_xml = handle.read()
                rendered = self.client.render_pdf(invoice_xml)
            except (AnafError, StorageError, OSError) as exc:
                # Tot indisponibil, sau fișierul lipsește. Se reia la turul
                # următor; documentul rămâne cu nota lui.
                logger.info("anaf_pdf_retry_failed", document_id=str(document.id), error=str(exc))
                continue

            self._store(document, kind=VERSION_ANAF_PDF, name="render", payload=rendered)
            document.validation_issues = [
                issue for issue in document.validation_issues if issue != PDF_MISSING
            ]
            recovered += 1
            logger.info("anaf_pdf_recovered", document_id=str(document.id))

        return recovered

    def _store(self, document: Document, *, kind: str, name: str, payload: bytes) -> None:
        """Scrie un fișier și îl înregistrează ca versiune a documentului."""
        key = efactura_key(document.organization_id, document.id, name=name)
        # Un fișier scris de o încercare a cărei tranzacție a căzut nu este
        # referit de nimic — apelantul tocmai a constatat că versiunea lipsește —
        # iar `save` refuză să suprascrie. Fără curățarea asta, reluarea ar eșua
        # la nesfârșit pe același document.
        if self.storage.exists(key):
            self.storage.delete(key)
        try:
            stored = self.storage.save(key, io.BytesIO(payload))
        except StorageError:
            # Un eșec de stocare aici nu are voie să dea înapoi factura deja
            # scrisă: XML-ul și rândul lui rămân, iar lipsa se vede în listă.
            logger.exception("anaf_file_store_failed", document_id=str(document.id), kind=kind)
            return

        self.session.add(
            DocumentVersion(
                document_id=document.id,
                version_number=self._next_version(document.id),
                kind=kind,
                storage_key=stored.key,
                sha256_hash=stored.sha256,
                file_size=stored.size,
                mime_type=VERSION_MIME[kind],
                uploaded_by=None,
                reason="Primit de la ANAF",
            )
        )
        self.session.flush()

    def _next_version(self, document_id: uuid.UUID) -> int:
        """Următorul număr liber. `version_number` este unic pe document."""
        highest = self.session.scalar(
            select(DocumentVersion.version_number)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        return (highest or 0) + 1

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _already_taken(self, organization_id: uuid.UUID, message_id: str) -> bool:
        """A mai intrat mesajul ăsta?

        Se întreabă înainte de descărcare, nu după: o factură deja preluată nu are
        de ce să mai treacă prin rețea, iar ANAF numără cererile.
        """
        existing = self.session.scalars(
            select(DocumentIntake.id).where(
                DocumentIntake.organization_id == organization_id,
                DocumentIntake.source == DocumentSource.EFACTURA,
                DocumentIntake.external_message_id == message_id[:255],
            )
        ).first()
        return existing is not None

    def _reject(self, intake: DocumentIntake, reason: str) -> None:
        intake.status = IntakeStatus.REJECTED
        intake.rejection_reason = reason[:255]
        logger.info("anaf_message_rejected", message=intake.external_message_id, reason=reason)


__all__ = ["AnafSyncResult", "AnafSyncService", "MandateResult"]
