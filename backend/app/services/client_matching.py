"""Identificarea clientului după codul fiscal de pe document (§8, §12).

Pasul „client identification" din fluxul produsului, care până acum nu exista:
fiecare document ajungea `UNMATCHED` și aștepta un om care să aleagă clientul
dintr-o listă. La un cabinet cu sute de documente pe zi, asta este cea mai
scumpă apăsare de buton din tot sistemul.

**Cum se identifică.** O factură poartă două coduri fiscale — al emitentului și al
destinatarului. Unul dintre ele este al unui client de-al cabinetului; celălalt
este al unui terț care nu ne interesează. Căutăm ambele printre clienți și
păstrăm potrivirea.

**Rolul potrivirii spune și direcția documentului.** Dacă clientul nostru apare ca
furnizor, el a emis factura — este o factură de ieșire. Dacă apare ca cumpărător,
a primit-o — este una de intrare. Extracția nu putea decide asta singură, și pe
bună dreptate: un modul care citește text nu are de unde să știe pentru cine
lucrează cabinetul. Sistemul știe, așa că decizia se ia aici.

**Când nu se poate spune, nu se spune.** Dacă ambele coduri sunt ale unor clienți
diferiți — o factură între doi clienți ai aceluiași cabinet — documentul aparține
la fel de mult amândurora, iar alegerea este a unui om. Rămâne `UNMATCHED`, ceea
ce este adevărat, nu o omisiune.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client


class MatchRole(StrEnum):
    """În ce calitate apare clientul nostru pe document."""

    # A emis documentul — deci este o factură de ieșire pentru el.
    SUPPLIER = "SUPPLIER"
    # L-a primit — deci este una de intrare.
    CUSTOMER = "CUSTOMER"


@dataclass(frozen=True, slots=True)
class ClientMatch:
    client_id: uuid.UUID
    client_name: str
    role: MatchRole
    # Codul care a produs potrivirea, normalizat. Ajunge în audit, ca operatorul
    # să vadă **de ce** a fost atribuit documentul, nu doar că a fost.
    tax_id: str


_NOISE = re.compile(r"[\s.\-/]")


def normalize_tax_id(raw: str | None) -> str:
    """`RO 14.399.840`, `ro14399840` și `14399840` sunt același cod.

    Prefixul de TVA se scoate pentru că prezența lui spune dacă firma este
    plătitoare de TVA **azi**, nu cine este firma. Aceeași companie apare cu `RO`
    pe o factură și fără pe alta, iar o potrivire ratată din cauza asta ar trimite
    documentul la un om degeaba.
    """
    if not raw:
        return ""
    cleaned = _NOISE.sub("", raw).upper()
    if cleaned.startswith("RO"):
        cleaned = cleaned[2:]
    # Zerourile din față nu fac parte din cod; `0123` și `123` sunt același CUI.
    return cleaned.lstrip("0")


class ClientMatcher:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def by_tax_ids(
        self, *, supplier_tax_id: str | None, customer_tax_id: str | None
    ) -> ClientMatch | None:
        """Clientul căruia îi aparține documentul, dacă se poate spune cu certitudine."""
        wanted = {
            normalize_tax_id(supplier_tax_id): MatchRole.SUPPLIER,
            normalize_tax_id(customer_tax_id): MatchRole.CUSTOMER,
        }
        wanted.pop("", None)
        if not wanted:
            return None

        matches = [
            ClientMatch(
                client_id=client.id,
                client_name=client.name,
                role=wanted[normalize_tax_id(client.tax_id)],
                tax_id=normalize_tax_id(client.tax_id),
            )
            for client in self._clients_with_tax_id()
            if normalize_tax_id(client.tax_id) in wanted
        ]

        if len(matches) != 1:
            # Zero: documentul nu este al niciunui client cunoscut.
            # Două: factură între doi clienți ai cabinetului — aparține amândurora,
            # deci alegerea nu este a noastră.
            return None
        return matches[0]

    def _clients_with_tax_id(self) -> list[Client]:
        """Clienții organizației care au un cod fiscal.

        Fără filtru pe status: un document poate sosi și pentru un client devenit
        inactiv, iar a-l lăsa `UNMATCHED` din cauza asta ar fi o piedică inventată.
        `SoftDeleteMixin` scoate deja din discuție clienții șterși.
        """
        return list(
            self.session.scalars(
                select(Client).where(
                    Client.organization_id == self.organization_id,
                    Client.tax_id.isnot(None),
                    Client.tax_id != "",
                    Client.deleted_at.is_(None),
                )
            ).all()
        )


# Ce tip de document rezultă din rolul în care a fost găsit clientul. Perechea
# este ambiguă doar pentru cine citește documentul; pentru cine știe al cui este
# cabinetul, nu mai este.
TYPE_BY_ROLE: dict[MatchRole, str] = {
    MatchRole.SUPPLIER: "FACTURA_IESIRE",
    MatchRole.CUSTOMER: "FACTURA_INTRARE",
}


__all__ = ["TYPE_BY_ROLE", "ClientMatch", "ClientMatcher", "MatchRole", "normalize_tax_id"]
