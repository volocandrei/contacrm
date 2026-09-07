"""Pe unde intră documentele în aplicație — toate drumurile, într-un singur loc.

**Întrebarea la care răspunde.** Un cabinet care se uită la aplicație pune, în
primele cinci minute, aceeași întrebare: *cum ajung documentele înăuntru?*
Răspunsul era împrăștiat — OneDrive și cutia poștală pe un ecran, e-Factura pe
altul, încărcarea manuală în inbox, linkul de trimitere pe fișa clientului — și
nicăieri nu scria întreg. Cine nu găsea un drum presupunea că nu există.

**Catalogul stă pe server, nu în interfață.** Starea fiecărui drum se calculează
din configurarea care rulează chiar acum și din conexiunile din bază. Scrisă în
TSX, ar fi fost o listă de speranțe: ecranul ar fi spus „OneDrive: conectat"
pentru că așa scria acolo, nu pentru că ar fi fost.

**Trei stări și niciun eufemism** (`SourceState`): merge acum, cere ceva, nu
există. Un drum care nu există se scrie pe față — altfel cineva așteaptă luni de
zile documente care nu vin, și abia atunci întreabă.

**Numărul de documente lângă fiecare drum.** O integrare conectată care n-a adus
niciodată nimic arată exact ca una care merge. Contorul este singurul lucru care
le deosebește, și el vine din documentele reale, nu din starea conexiunii.

**Și ce iese, nu doar ce intră.** Cabinetul nu ține minte că exportul e „altă
categorie": întreabă „ce se leagă cu Saga?" în aceeași propoziție cu „de unde
iau facturile". Ecranul răspunde la amândouă, dar nu le amestecă: sunt două
liste, iar a doua spune limpede că este ieșire.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import encryption_available
from app.domain.enums import DocumentSource, SourceState
from app.models.anaf import AnafConnection, AnafMandate
from app.models.microsoft import DriveFolder, MailFolder, MicrosoftConnection
from app.repositories.document import DocumentRepository


class SourceCode(StrEnum):
    """Drumurile, ca identificatori stabili pentru interfață.

    **Nu se suprapun peste `DocumentSource`.** Acela spune de unde a venit un
    document care există deja; ăsta enumeră drumurile pe care le poate lua unul
    care încă n-a venit — inclusiv pe cele care nu există încă și nu vor produce
    niciodată vreun document.
    """

    UPLOAD = "UPLOAD"
    PORTAL = "PORTAL"
    ONEDRIVE = "ONEDRIVE"
    EMAIL_MICROSOFT = "EMAIL_MICROSOFT"
    EFACTURA = "EFACTURA"
    EMAIL_IMAP = "EMAIL_IMAP"
    WHATSAPP = "WHATSAPP"
    GOOGLE_DRIVE = "GOOGLE_DRIVE"


@dataclass(frozen=True, slots=True)
class DocumentSourceView:
    """Un drum de intrare, așa cum îl vede cine se uită la ecran."""

    code: SourceCode
    title: str
    #: O propoziție: ce face, în termenii cabinetului, nu ai noștri.
    summary: str
    state: SourceState
    #: Ce lipsește, când starea nu este `LIVE`. Fără el, „neconfigurat" nu spune
    #: nimănui ce are de făcut.
    requirement: str | None
    #: Unde se configurează sau de unde se folosește. Un drum despre care afli că
    #: există, dar nu și de unde se pornește, este tot un drum pe care nu-l iei.
    path: str | None
    #: Câte documente au intrat pe aici. Nulă pentru drumurile care încă nu pot
    #: produce niciunul — un zero ar fi arătat ca o integrare care nu merge.
    documents: int | None
    #: Detaliul care contează pentru drumul acesta: câte dosare urmărite, câte
    #: împuterniciri, ce adresă. Gol când nu are ce spune.
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ExportView:
    """Un drum de ieșire. Aceeași formă, ca ecranul să nu inventeze alta."""

    code: str
    title: str
    summary: str
    state: SourceState
    requirement: str | None
    path: str | None


#: Ce iese din aplicație. Separat de intrări, dar pe același ecran: cabinetul
#: întreabă „ce se leagă cu Saga?" în aceeași propoziție cu „de unde iau
#: facturile", iar două ecrane l-ar pune să caute de două ori.
EXPORTS: Final[tuple[ExportView, ...]] = (
    ExportView(
        code="REGISTER_CSV",
        title="Registrul lunii, ca fișier",
        summary="Toate documentele unei luni, în Excel — se deschide oriunde.",
        state=SourceState.LIVE,
        requirement=None,
        path="/rapoarte",
    ),
    ExportView(
        code="MONTH_ARCHIVE",
        title="Arhiva unei luni",
        summary="Documentele lunii, într-un singur fișier, cu numele standardizate.",
        state=SourceState.LIVE,
        requirement=None,
        path="/contabilitate/perioade",
    ),
    ExportView(
        code="FEE_REGISTER",
        title="Onorariile lunii",
        summary="Cine cât plătește și cine a plătit, pentru cine emite facturile.",
        state=SourceState.LIVE,
        requirement=None,
        path="/crm/onorarii",
    ),
    ExportView(
        code="SAGA",
        title="Export către Saga",
        summary="Notele contabile, în forma pe care o importă Saga direct.",
        state=SourceState.PLANNED,
        # Motivul stă în docs/SAGA.md: un fișier cu coloane deduse ori nu se
        # importă, ori se importă strâmb — și în al doilea caz nu observă nimeni.
        requirement=(
            "Un fișier pe care Saga îl importă azi, ca exemplu. Forma exactă nu se "
            "poate deduce, iar un export ghicit se importă strâmb fără să spună nimeni."
        ),
        path=None,
    ),
)


class DocumentSourceService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def sources(self) -> list[DocumentSourceView]:
        """Toate drumurile, cu starea de acum și cu ce a intrat pe fiecare."""
        counts = DocumentRepository(self.session).count_by_source(self.organization_id)
        microsoft = self._microsoft()
        anaf = self._anaf()

        return [
            self._upload(counts),
            self._portal(counts),
            self._onedrive(microsoft, counts),
            self._microsoft_mail(microsoft, counts),
            self._efactura(anaf, counts),
            *self._planned(),
        ]

    # ── Drumurile care merg fără să configureze nimeni nimic ────────────────

    def _upload(self, counts: dict[DocumentSource, int]) -> DocumentSourceView:
        return DocumentSourceView(
            code=SourceCode.UPLOAD,
            title="Încărcare din aplicație",
            summary="Trageți fișierele în fereastră. Merge și cu douăzeci deodată.",
            state=SourceState.LIVE,
            requirement=None,
            path="/documente/inbox",
            documents=counts.get(DocumentSource.UPLOAD, 0),
        )

    def _portal(self, counts: dict[DocumentSource, int]) -> DocumentSourceView:
        """Linkul de trimitere. Drumul cu cel mai mare efect și cel mai mic cost.

        Nu cere nici cont de la client, nici integrare de la cabinet — de aceea
        merge din prima zi, spre deosebire de toate celelalte de mai jos.
        """
        return DocumentSourceView(
            code=SourceCode.PORTAL,
            title="Link de trimitere pentru client",
            summary=(
                "Clientul deschide o adresă și trage fișierele. Fără cont, fără parolă, "
                "fără aplicație de instalat."
            ),
            state=SourceState.LIVE,
            requirement=None,
            path="/contabilitate/lipsa",
            documents=counts.get(DocumentSource.PORTAL, 0),
            detail="Se deschide din fișa clientului sau odată cu solicitarea de documente.",
        )

    # ── Microsoft ───────────────────────────────────────────────────────────

    def _microsoft(self) -> MicrosoftConnection | None:
        return self.session.scalars(
            select(MicrosoftConnection).where(
                MicrosoftConnection.organization_id == self.organization_id
            )
        ).first()

    def _microsoft_requirement(self) -> str | None:
        """Ce lipsește ca Microsoft să poată fi conectat, în ordinea în care se rezolvă."""
        if not (settings.ms_client_id and settings.ms_client_secret):
            return "Lipsesc MS_CLIENT_ID și MS_CLIENT_SECRET din configurare."
        if not encryption_available():
            return "Lipsește DRIVE_TOKEN_KEY: fără ea tokenul nu poate fi păstrat criptat."
        return None

    def _onedrive(
        self, connection: MicrosoftConnection | None, counts: dict[DocumentSource, int]
    ) -> DocumentSourceView:
        missing = self._microsoft_requirement()
        tracked = self._count(DriveFolder) if connection else 0
        if missing is None and connection is not None and tracked > 0:
            state, requirement = SourceState.LIVE, None
        else:
            state = SourceState.NEEDS_SETUP
            requirement = missing or (
                "Contul Microsoft nu este conectat."
                if connection is None
                else "Niciun dosar urmărit: leagă un dosar de un client."
            )
        return DocumentSourceView(
            code=SourceCode.ONEDRIVE,
            title="OneDrive / SharePoint",
            summary="Dosarul în care clientul își pune documentele, citit singur.",
            state=state,
            requirement=requirement,
            path="/administrare/surse",
            documents=counts.get(DocumentSource.ONEDRIVE, 0),
            detail=self._plural(tracked, "dosar urmărit", "dosare urmărite"),
        )

    def _microsoft_mail(
        self, connection: MicrosoftConnection | None, counts: dict[DocumentSource, int]
    ) -> DocumentSourceView:
        missing = self._microsoft_requirement()
        tracked = self._count(MailFolder) if connection else 0
        if missing is None and connection is not None and tracked > 0:
            state, requirement = SourceState.LIVE, None
        else:
            state = SourceState.NEEDS_SETUP
            requirement = missing or (
                "Contul Microsoft nu este conectat."
                if connection is None
                else "Niciun dosar de email urmărit."
            )
        return DocumentSourceView(
            code=SourceCode.EMAIL_MICROSOFT,
            title="Email — Microsoft 365 / Outlook",
            summary="Atașamentele din cutia poștală a cabinetului, luate automat.",
            state=state,
            requirement=requirement,
            path="/administrare/surse",
            documents=counts.get(DocumentSource.EMAIL, 0),
            detail=self._plural(tracked, "dosar de email urmărit", "dosare de email urmărite"),
        )

    # ── ANAF ────────────────────────────────────────────────────────────────

    def _anaf(self) -> AnafConnection | None:
        return self.session.scalars(
            select(AnafConnection).where(AnafConnection.organization_id == self.organization_id)
        ).first()

    def _efactura(
        self, connection: AnafConnection | None, counts: dict[DocumentSource, int]
    ) -> DocumentSourceView:
        """Singura sursă în care clientul nu se ghicește: interogarea e pe CUI-ul lui."""
        mandates = self._count(AnafMandate) if connection else 0
        if not (settings.anaf_client_id and settings.anaf_client_secret):
            state = SourceState.NEEDS_SETUP
            requirement = "Lipsesc ANAF_CLIENT_ID și ANAF_CLIENT_SECRET din configurare."
        elif connection is None:
            state = SourceState.NEEDS_SETUP
            requirement = "Autorizarea cere certificatul digital, în browser. Nu se automatizează."
        elif mandates == 0:
            state = SourceState.NEEDS_SETUP
            # Fără împuternicire ANAF nu dă eroare, dă **gol** — ceea ce e mai rău.
            requirement = "Niciun client împuternicit: fiecare depune formularul 150 în SPV."
        else:
            state, requirement = SourceState.LIVE, None
        return DocumentSourceView(
            code=SourceCode.EFACTURA,
            title="e-Factura — SPV ANAF",
            summary=("Facturile electronice, luate direct de la sursă, cu XML, sigiliu și PDF."),
            state=state,
            requirement=requirement,
            path="/administrare/e-factura",
            documents=counts.get(DocumentSource.EFACTURA, 0),
            detail=self._plural(mandates, "client împuternicit", "clienți împuterniciți"),
        )

    # ── Ce nu există ────────────────────────────────────────────────────────

    def _planned(self) -> list[DocumentSourceView]:
        """Drumurile care nu există, scrise pe față.

        **De ce apar deloc.** Un rând lipsă îi face pe oameni să întrebe la
        nesfârșit dacă se poate; unul care tace îi face să aștepte documente care
        nu vin. Scris aici, fiecare spune și ce ar fi nevoie ca să existe — adică
        exact ce trebuie hotărât, nu programat.
        """
        return [
            DocumentSourceView(
                code=SourceCode.EMAIL_IMAP,
                title="Email — orice cutie poștală (IMAP)",
                summary=(
                    "Gmail, Yahoo, cutia de la găzduire. Astăzi merge doar Microsoft 365, "
                    "iar cabinetele mici rareori sunt acolo."
                ),
                state=SourceState.PLANNED,
                requirement=(
                    "De construit. Nu cere nicio hotărâre de business — doar adresa, "
                    "parola de aplicație și serverul cutiei."
                ),
                path=None,
                documents=None,
            ),
            DocumentSourceView(
                code=SourceCode.WHATSAPP,
                title="WhatsApp",
                summary=(
                    "Pozele de bonuri, direct din conversație. Aplicația poate deschide "
                    "azi o conversație cu mesajul scris, dar nu poate primi nimic pe acolo."
                ),
                state=SourceState.PLANNED,
                requirement=(
                    "Un cont WhatsApp Business și un număr aprobat de Meta. Este o "
                    "înregistrare de firmă, nu o setare."
                ),
                path=None,
                documents=None,
            ),
            DocumentSourceView(
                code=SourceCode.GOOGLE_DRIVE,
                title="Google Drive",
                summary="Același lucru ca OneDrive, pentru cabinetele care lucrează pe Google.",
                state=SourceState.PLANNED,
                requirement="De construit, plus un proiect Google Cloud cu OAuth aprobat.",
                path=None,
                documents=None,
            ),
        ]

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _count(self, model: type[DriveFolder] | type[MailFolder] | type[AnafMandate]) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.organization_id == self.organization_id)
            )
            or 0
        )

    @staticmethod
    def _plural(count: int, one: str, many: str) -> str | None:
        if count == 0:
            return None
        return f"{count} {one if count == 1 else many}"


__all__ = [
    "EXPORTS",
    "DocumentSourceService",
    "DocumentSourceView",
    "ExportView",
    "SourceCode",
]
