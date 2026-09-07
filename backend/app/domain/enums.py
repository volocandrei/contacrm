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


class ObligationFrequency(StrEnum):
    """Cât de des se încheie perioada unei obligații de depunere.

    Nu este o clasificare fiscală, ci una de calendar: spune în ce luni se
    încheie o perioadă, deci de câte ori pe an există un termen.
    """

    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class TimelineEventKind(StrEnum):
    """Ce fel de lucru s-a întâmplat cu un client.

    Nu o clasificare de dragul ei: fiecare fel are altă iconiță și alt text pe
    ecran, iar eticheta o dă interfața. Serverul spune **ce s-a întâmplat**, nu
    cum se scrie.
    """

    DOCUMENT_RECEIVED = "DOCUMENT_RECEIVED"
    REQUEST_PREPARED = "REQUEST_PREPARED"
    REQUEST_SENT = "REQUEST_SENT"
    OBLIGATION_FILED = "OBLIGATION_FILED"
    PERIOD_CLOSED = "PERIOD_CLOSED"


# Ordinea în care sarcinile apar în interfață: ce e de făcut, înaintea ce e gata.
class SourceState(StrEnum):
    """Ce se întâmplă **acum** cu un drum de intrare a documentelor.

    Trei stări, nu cinci, fiindcă la ecranul „Surse documente" cabinetul pune o
    singură întrebare: *pot să primesc documente pe aici azi?* Restul —
    „implementat", „în roadmap", „parțial" — sunt distincții de programator, iar
    puse pe ecran fac exact ce nu trebuie: dau speranțe.
    """

    #: Merge acum. Documentele pot intra pe aici astăzi, fără să mai facă nimeni
    #: nimic. Nu înseamnă că *au* intrat — pentru asta ecranul arată și numărul.
    LIVE = "LIVE"
    #: Există în aplicație, dar cere ceva: o conectare, o cheie, o împuternicire.
    #: Ecranul spune **ce anume**, altfel „neconfigurat" este o ghicitoare.
    NEEDS_SETUP = "NEEDS_SETUP"
    #: Nu există. Se scrie pe față, cu ce ar fi nevoie ca să existe. Un rând
    #: lipsă i-ar face pe oameni să întrebe la nesfârșit; un rând care tace i-ar
    #: face să aștepte documente care nu vin niciodată.
    PLANNED = "PLANNED"


class ImportOutcome(StrEnum):
    """Ce s-ar întâmpla cu un rând dintr-un fișier de clienți importat.

    Ca și `ReminderStatus`, ecranul are nevoie de **motiv**, nu doar de rezultat:
    diferența dintre „am importat 40 din 200" și „am importat 200" trebuie să se
    poată explica rând cu rând, altfel importul se reface orbește.
    """

    #: Se creează.
    NEW = "NEW"
    #: Există deja un client cu acest CUI. Nu se atinge: fișierul poate fi vechi
    #: de un an, iar ce a tastat un om în aplicație este mai proaspăt.
    EXISTING = "EXISTING"
    #: Același CUI apare de două ori în fișier. Se ia primul.
    DUPLICATE = "DUPLICATE"
    #: Nu se poate crea — lipsește denumirea.
    INVALID = "INVALID"


class ReminderStatus(StrEnum):
    """De ce pleacă sau nu pleacă un reminder către un client.

    **Nu este o stare stocată**, ci răspunsul la o întrebare pusă azi: dacă
    aplicația ar trimite acum, ce s-ar întâmpla cu rândul acesta. Mâine poate fi
    alta, fără ca nimic să se fi schimbat în bază — a trecut o zi.

    Există ca listă cu nume tocmai pentru ca ecranul să poată arăta **motivul**.
    Un ecran care afișează numai cine primește un mesaj lasă deschisă exact
    întrebarea pe care o pune contabilul: „bine, dar pe ăsta de ce nu-l anunță?".
    """

    #: Pleacă la următoarea rulare, sau acum, dacă se apasă butonul.
    DUE = "DUE"
    #: I s-a cerut, dar prea recent. Un mesaj pe zi nu grăbește pe nimeni.
    WAITING = "WAITING"
    #: Nu i s-a cerut încă nimic. Primul mesaj este o solicitare, nu o
    #: reamintire: aplicația nu reamintește ceva ce n-a cerut niciodată.
    NOT_ASKED = "NOT_ASKED"
    #: A trimis ceva după ultimul nostru mesaj. Mai lipsește, dar omul lucrează.
    ANSWERED = "ANSWERED"
    #: A primit deja câte remindere trimite aplicația într-o lună.
    MAX_REACHED = "MAX_REACHED"
    #: A trecut termenul de depunere. De aici încolo se sună, nu se scrie.
    PAST_DEADLINE = "PAST_DEADLINE"
    #: Nu are nicio adresă de email pe fișă.
    NO_EMAIL = "NO_EMAIL"


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


class BankTransactionStatus(StrEnum):
    """Unde a ajuns o tranzacție bancară în reconciliere (§12).

    **De ce sunt șase și nu două.** „Potrivit / nepotrivit" ar fi ascuns exact
    lucrurile pe care contabilul le caută: ce a propus sistemul și el n-a
    confirmat încă, ce a hotărât un om cu mâna lui, și ce a decis cineva că nu are
    nicio factură în spate. Un comision bancar de 3 lei nu este „nepotrivit", este
    **lămurit** — iar dacă cele două arată la fel, lista de nepotrivite nu se mai
    golește niciodată și nimeni nu se mai uită la ea.
    """

    #: Nimic nu s-a potrivit, sau nimeni nu s-a uitat încă.
    UNMATCHED = "UNMATCHED"
    #: Sistemul a găsit un candidat. **Nu este o potrivire** — este o propunere
    #: care așteaptă o apăsare. Vezi `app/services/bank_matching.py` pentru de ce
    #: nimic nu se leagă singur.
    SUGGESTED = "SUGGESTED"
    #: Confirmată. Din ce a propus sistemul sau din ce a ales omul — diferența o
    #: ține `TransactionMatch.confirmed_by_id`, nu starea.
    MATCHED = "MATCHED"
    #: Fără factură în spate, și așa trebuie să rămână: comision, dobândă,
    #: transfer între conturile proprii. Iese din lista de lucru.
    IGNORED = "IGNORED"
    #: Sumele nu se închid: plătit mai mult, mai puțin, sau pe mai multe facturi
    #: care nu dau totalul. Cere un om, nu o regulă.
    NEEDS_REVIEW = "NEEDS_REVIEW"


class BankDirection(StrEnum):
    """Banii au intrat sau au ieșit.

    Se derivă din semnul sumei, nu se citește din fișier: un extras scrie uneori
    două coloane (debit/credit), alteori una cu semn, iar o singură sursă de
    adevăr este mai ieftină decât împăcarea lor la fiecare raport.
    """

    #: Bani ieșiți: plata unei facturi de la furnizor.
    DEBIT = "DEBIT"
    #: Bani intrați: încasarea unei facturi emise.
    CREDIT = "CREDIT"
