"""Statusurile de domeniu.

Oglinda exactă a listelor din `frontend/src/types/domain.ts` (§53). Cele două sunt
comparate automat de `tests/test_contract_enums.py` — statusurile trăiesc într-un
singur loc conceptual, chiar dacă sunt scrise în două limbaje.

Se stochează ca text în baza de date, nu ca `ENUM` nativ: un tip enum Postgres cere
o migrare pentru fiecare valoare nouă, iar statusurile astea se vor extinde.
Constrângerea o impune aplicația, plus un CHECK în migrare.
"""

from __future__ import annotations

from enum import StrEnum


class ClientStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PROSPECT = "PROSPECT"
    SUSPENDED = "SUSPENDED"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


class TaskPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class DocumentStatus(StrEnum):
    """Definit acum pentru că `documents` apare în M5, dar contractul e deja fix."""

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    UNMATCHED = "UNMATCHED"


class DocumentSource(StrEnum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    UPLOAD = "UPLOAD"
    API = "API"
    # Dosarul din OneDrive/SharePoint al unui client, citit automat. Sursa nu spune
    # cine a pus fișierul acolo — spune de unde l-am luat noi.
    ONEDRIVE = "ONEDRIVE"
    # Spațiul Privat Virtual al ANAF: factura electronică descărcată direct de la
    # sursă. Este singura sursă în care clientul **nu se ghicește** — interogarea
    # se face pe CUI-ul lui, deci apartenența este dată de cerere, nu dedusă din
    # document.
    EFACTURA = "EFACTURA"
    # Clientul si-a trimis singur documentul, printr-un link deschis de cabinet.
    # Ca si la e-Factura, apartenenta vine din cerere, nu din ghicit: linkul stie
    # al cui este. Documentele de aici nu trec niciodata prin UNMATCHED.
    PORTAL = "PORTAL"


class EFacturaMessageKind(StrEnum):
    """Tipurile de mesaj din lista SPV, așa cum le denumește ANAF.

    Se păstrează exact cum vin, pentru că `tip` este singurul lucru care spune
    dacă factura a fost **primită** de client sau **emisă** de el. Aceeași factură
    apare la ambele părți, iar direcția schimbă complet înregistrarea contabilă.

    `ERORI FACTURA` și `MESAJ` privesc facturile trimise de noi; faza de preluare
    nu trimite nimic, deci le recunoaște ca să le poată ignora explicit — nu
    tăcut, printr-un `else`.
    """

    RECEIVED = "FACTURA PRIMITA"
    SENT = "FACTURA TRIMISA"
    ERRORS = "ERORI FACTURA"
    MESSAGE = "MESAJ"


class ProcessingJobStatus(StrEnum):
    """Starea unei cereri din coadă (`document_processing_jobs`).

    `SKIPPED` nu este o eroare: documentul a mers între timp în altă parte, deci nu
    mai e nimic de făcut, iar un `FAILED` ar umple raportul de eșecuri cu lucruri
    care n-au eșuat.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PeriodStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    COLLECTING = "COLLECTING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    PROCESSING = "PROCESSING"
    REVIEW = "REVIEW"
    FINALIZED = "FINALIZED"


# Ordinea în care sarcinile apar în interfață: ce e de făcut, înaintea ce e gata.
TASK_STATUS_ORDER: dict[TaskStatus, int] = {
    TaskStatus.TODO: 0,
    TaskStatus.IN_PROGRESS: 1,
    TaskStatus.BLOCKED: 2,
    TaskStatus.DONE: 3,
}


class FieldSource(StrEnum):
    """De unde provine valoarea unui câmp extras (§22).

    Ecranul de verificare o afișează lângă fiecare câmp: operatorul trebuie să vadă
    dacă se uită la o valoare propusă de model sau la una pe care a corectat-o el.
    O valoare corectată manual nu mai are scor de încredere.
    """

    AI = "AI"
    OCR = "OCR"
    MANUAL = "MANUAL"
    # Calculată de o regulă a sistemului, nu citită de pe document: luna contabilă
    # dedusă din data documentului (ADR-008) este singurul caz de azi. Se ține
    # separat de `AI` pentru că badge-ul „AI 83%" pe o valoare pe care modelul nu a
    # produs-o ar fi exact minciuna pe care ecranul de verificare promite să nu o spună.
    DERIVED = "DERIVED"
    EMPTY = "EMPTY"


class IntakeStatus(StrEnum):
    """Ce s-a întâmplat cu un atașament primit, independent de documentul rezultat."""

    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"


class DocumentErrorCode(StrEnum):
    """Motivul structurat al unui eșec de procesare (§53).

    Codul se persistă, nu traceback-ul: un cod se poate filtra, număra și traduce.
    """

    INVALID_FILE = "INVALID_FILE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    OCR_FAILED = "OCR_FAILED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    CLIENT_NOT_FOUND = "CLIENT_NOT_FOUND"
    STORAGE_FAILED = "STORAGE_FAILED"
    ARCHIVE_FAILED = "ARCHIVE_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Câmpurile extrase, în ordinea de citire a unei facturi. Aceeași ordine ca
# `DocumentFields` din `frontend/src/types/domain.ts`.
DOCUMENT_FIELD_NAMES: tuple[str, ...] = (
    "documentType",
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
    "referenceMonth",
)
