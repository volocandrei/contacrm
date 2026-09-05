"""Detecția duplicatelor (§12).

**Două strategii, cu certitudini diferite.**

`find_duplicate` compară conținutul: același SHA-256, deci nicio îndoială. Numele
fișierului nu participă - același document poate sosi de două ori cu nume
diferite, iar două documente complet diferite pot avea același nume. Rulează la
încărcare, înainte de orice citire.

`find_semantic_duplicate` compară datele de identificare: furnizor, serie, număr.
Rulează după extracție, fiindcă abia atunci există ce compara, și prinde cazul pe
care hash-ul nu-l poate vedea - aceeași factură fotografiată de două ori, sau
sosită și pe email, și prin linkul de încărcare. Octeții diferă, factura nu.

**Un duplicat nu se șterge niciodată automat.** Se păstrează, marcat, pentru că
decizia „chiar este același document?" aparține unui om. Potrivirea semantică nu
marchează nici măcar atât: se sprijină pe câmpuri citite, deci trimite documentul
la verificare și lasă decizia acolo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from app.domain.enums import DocumentStatus
from app.models.document import Document
from app.repositories.document import DocumentRepository
from app.services.client_matching import normalize_tax_id


class DuplicateMatch(StrEnum):
    """Cât de sigură este potrivirea."""

    # Același conținut, octet cu octet. Nu există dubiu.
    EXACT_CONTENT = "EXACT_CONTENT"
    # Aceleași date de identificare, conținut diferit: furnizor, serie, număr.
    SEMANTIC = "SEMANTIC"


@dataclass(frozen=True, slots=True)
class DuplicateResult:
    original: Document
    match: DuplicateMatch

    @property
    def original_id(self) -> uuid.UUID:
        return self.original.id


class DuplicateDetectionService:
    def __init__(self, session: Session) -> None:
        self.documents = DocumentRepository(session)

    def find_duplicate(
        self,
        organization_id: uuid.UUID,
        *,
        sha256_hash: str,
        exclude_id: uuid.UUID | None = None,
    ) -> DuplicateResult | None:
        """Primul document cu același conținut, din aceeași organizație.

        Căutarea nu traversează organizații: două cabinete pot avea, legitim, exact
        același document.
        """
        original = self.documents.find_by_hash(organization_id, sha256_hash, exclude_id=exclude_id)
        if original is None:
            return None
        return DuplicateResult(original=original, match=DuplicateMatch.EXACT_CONTENT)

    def find_semantic_duplicate(
        self, organization_id: uuid.UUID, document: Document
    ) -> DuplicateResult | None:
        """Același document, alți octeți.

        **Golul pe care îl umple.** Detecția pe SHA-256 vede doar fișierul identic
        bit cu bit. Aceeași factură fotografiată de două ori are octeți diferiți;
        la fel una sosită și pe email, și prin linkul de încărcare; la fel un PDF
        rescanat. Toate treceau ca documente noi, iar o factură înregistrată de
        două ori este o eroare contabilă, nu o neplăcere de interfață.

        **Cheia.** Codul fiscal al furnizorului, seria și numărul. Legal, tripletul
        identifică o factură în mod unic — de aceea nu se compară sumele: dacă
        furnizorul, seria și numărul coincid, o sumă diferită înseamnă că una
        dintre cele două a fost citită greșit, ceea ce este cu atât mai important
        de arătat cuiva.

        **Nu se restrânge la lună și nici la client.** Aceeași factură ajunsă în
        două luni sau sub doi clienți diferiți este exact cazul care merită văzut.

        **Rezultatul nu marchează nimic de la sine.** Potrivirea se sprijină pe
        câmpuri *citite*, iar un număr citit greșit ar scoate din registru un
        document bun — o omisiune tăcută. Apelantul trimite documentul la
        verificare; „chiar este același document?" rămâne o întrebare pentru om.
        """
        number = _identity(document.document_number)
        tax_id = normalize_tax_id(document.supplier_tax_id)
        if not number or not tax_id:
            # Fără furnizor sau fără număr nu există cheie. Un bon fiscal fără CUI
            # s-ar potrivi cu oricare altul, iar zece semnalări false pe zi golesc
            # de sens toate semnalările.
            return None

        series = _identity(document.series)
        for candidate in self.documents.by_supplier_tax_ids(
            organization_id, _tax_id_variants(tax_id), exclude_id=document.id
        ):
            if candidate.is_duplicate or candidate.status is DocumentStatus.REJECTED:
                # Un duplicat deja marcat arată spre originalul lui; un respins nu
                # se înregistrează. Nici unul nu este „documentul cu care seamănă".
                continue
            if normalize_tax_id(candidate.supplier_tax_id) != tax_id:
                # Variantele cerute în SQL sunt largi ca să folosească indexul.
                continue
            if _identity(candidate.document_number) != number:
                continue
            if _identity(candidate.series) != series:
                continue
            return DuplicateResult(original=candidate, match=DuplicateMatch.SEMANTIC)
        return None


def _identity(raw: str | None) -> str:
    """Seria și numărul, aduse la forma în care se pot compara.

    Spațiile și diferențele de scriere cu majuscule vin din citire, nu de pe
    document: `FCT 1042` și `fct1042` sunt aceeași factură. Zerourile din față
    **rămân**: `042` și `42` pot fi două documente într-o serie ținută prost, iar
    aici greșeala ar fi în direcția care ascunde un document adevărat.
    """
    if raw is None:
        return ""
    return "".join(raw.split()).upper()


def _tax_id_variants(normalized: str) -> list[str]:
    """Formele sub care poate sta în baza de date același cod fiscal.

    Cerute explicit, ca interogarea să rămână pe index. O normalizare făcută în
    SQL ar fi fost mai scurtă și ar fi transformat căutarea într-o parcurgere a
    tuturor documentelor organizației.
    """
    return [normalized, f"RO{normalized}"]
