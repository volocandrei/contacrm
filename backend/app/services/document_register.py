"""Registrul lunii: un rând pe document, cu tot ce s-a citit din el.

**Golul pe care îl umple.** Sistemul citește data, seria, numărul, furnizorul,
CUI-ul, baza, TVA-ul și totalul — și le ținea pe ecran. Contabilul le retasta în
programul de contabilitate, câmp cu câmp, uitându-se la fișă. Extracția nu se
plătește până când numerele nu ies într-un fișier.

**Ce conține fișierul și ce nu.** Toate documentele lunii, **fără cele respinse și
fără duplicate** — un respins nu se înregistrează, iar un duplicat înregistrat a
doua oară este exact greșeala pe care detecția lui o previne. Restul intră toate,
inclusiv cele neajunse încă la aprobare, cu starea scrisă pe rând.

Alegerea aceasta este deliberată și merită motivul. Un registru care ar conține
doar documentele aprobate ar fi „curat" și ar **tăcea** despre celelalte: cine
exportă o lună cu 12 documente rămase în verificare ar primi 88 de rânduri dintr-o
sută și n-ar avea de unde ști. O omisiune tăcută într-un registru contabil se
descoperă la un control. Un rând care scrie „Necesită verificare" se vede.

**Nu se calculează nimic aici.** Nici TVA, nici totaluri, nici conversii de
monedă. Se scriu valorile citite, așa cum sunt. Un total pus de sistem ar arăta
identic cu unul citit de pe factură, iar la un control diferența contează.

Forma fișierului — separator, BOM, virgulă la zecimale — stă în `excel_csv.py`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.domain.enums import DocumentStatus
from app.domain.labels import status_label
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.services.excel_csv import day, number, render

#: Stările care nu au ce căuta într-un registru.
#:
#: `REJECTED` - documentul a fost refuzat, deci nu se înregistrează.
#: `DUPLICATE` - a fost înregistrat o dată, sub celălalt rând.
EXCLUDED: Final = (DocumentStatus.REJECTED, DocumentStatus.DUPLICATE)

HEADER: Final = (
    "Client",
    "CUI client",
    "Data",
    "Luna",
    "Tip",
    "Serie",
    "Număr",
    "Furnizor",
    "CUI furnizor",
    "Beneficiar",
    "CUI beneficiar",
    "Monedă",
    "Bază",
    "TVA",
    "Total",
    "Stare",
    "Fișier",
)


@dataclass(frozen=True, slots=True)
class RegisterRow:
    """Un document, cu câmpurile care intră în contabilitate.

    Nimic despre unde este stocat și nimic despre cât de sigur a fost sistemul
    când a citit (§73). Prima ar fi o cale de fișier scăpată într-un fișier care
    circulă pe email; a doua ar pune o probabilitate lângă o sumă, iar cine
    citește registrul nu are ce face cu ea.
    """

    client_name: str | None
    client_tax_id: str | None
    document_date: dt.date | None
    reference_month: str | None
    type_label: str | None
    series: str | None
    document_number: str | None
    supplier_name: str | None
    supplier_tax_id: str | None
    customer_name: str | None
    customer_tax_id: str | None
    currency: str | None
    subtotal: Decimal | None
    vat_amount: Decimal | None
    total_amount: Decimal | None
    status: DocumentStatus
    original_filename: str


class RegisterService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def rows(
        self,
        *,
        from_month: str | None = None,
        to_month: str | None = None,
        client_id: uuid.UUID | None = None,
    ) -> list[RegisterRow]:
        """Documentele intervalului, în ordinea în care le-ar pune un om.

        Pe client, apoi cronologic, apoi pe serie și număr. Un registru sortat
        după `id` este de necitit, iar unul sortat doar după dată amestecă
        clienții între ei.
        """
        # Izolarea pe organizație stă prima și nu este opțională (§72).
        conditions: list[ColumnElement[bool]] = [
            Document.organization_id == self.organization_id,
            # Documentele nu se șterg fizic (§62); un document șters nu are ce
            # căuta într-un registru. `soft_delete` nu are încă apelanți, dar
            # ziua în care va avea nu trebuie să fie ziua în care se descoperă
            # asta dintr-un fișier trimis mai departe.
            Document.deleted_at.is_(None),
            Document.status.not_in(EXCLUDED),
            # `is_duplicate` și starea `DUPLICATE` sunt două lucruri diferite:
            # un document poate fi marcat duplicat rămânând în starea în care
            # era. Ambele trebuie să țină documentul afară din registru.
            Document.is_duplicate.is_(False),
        ]
        # `YYYY-MM` se compară lexicografic exact ca cronologic - de asta este
        # stocat așa.
        if from_month:
            conditions.append(Document.reference_month >= from_month)
        if to_month:
            conditions.append(Document.reference_month <= to_month)
        if client_id is not None:
            conditions.append(Document.client_id == client_id)

        statement = (
            select(Document, Client.name, Client.tax_id, DocumentType.label)
            .outerjoin(Client, Document.client_id == Client.id)
            .outerjoin(DocumentType, Document.document_type_id == DocumentType.id)
            .where(*conditions)
            # `nulls_last` explicit: documentele fără client sau fără dată sunt
            # exact cele la care omul mai are de lucrat, iar la coadă se văd.
            .order_by(
                Client.name.nulls_last(),
                Document.document_date.nulls_last(),
                Document.series.nulls_last(),
                Document.document_number.nulls_last(),
            )
        )

        return [
            RegisterRow(
                client_name=client_name,
                client_tax_id=client_tax_id,
                document_date=document.document_date,
                reference_month=document.reference_month,
                type_label=type_label,
                series=document.series,
                document_number=document.document_number,
                supplier_name=document.supplier_name,
                supplier_tax_id=document.supplier_tax_id,
                customer_name=document.customer_name,
                customer_tax_id=document.customer_tax_id,
                currency=document.currency,
                subtotal=document.subtotal,
                vat_amount=document.vat_amount,
                total_amount=document.total_amount,
                status=document.status,
                original_filename=document.original_filename,
            )
            for document, client_name, client_tax_id, type_label in self.session.execute(statement)
        ]


def rows_for(entries: list[RegisterRow]) -> list[list[str]]:
    """Registrul, aplatizat în tabelul care ajunge în fișier."""
    table: list[list[str]] = [list(HEADER)]
    for row in entries:
        table.append(
            [
                row.client_name or "",
                row.client_tax_id or "",
                day(row.document_date),
                row.reference_month or "",
                row.type_label or "",
                row.series or "",
                row.document_number or "",
                row.supplier_name or "",
                row.supplier_tax_id or "",
                row.customer_name or "",
                row.customer_tax_id or "",
                row.currency or "",
                number(row.subtotal),
                number(row.vat_amount),
                number(row.total_amount),
                status_label(row.status),
                row.original_filename,
            ]
        )
    return table


def to_csv(entries: list[RegisterRow]) -> str:
    """Fișierul întreg, gata de trimis ca răspuns."""
    return render(rows_for(entries))


def filename(from_month: str | None, to_month: str | None) -> str:
    """Numele sub care ajunge fișierul pe disc.

    Poartă intervalul, ca două exporturi succesive să nu se suprascrie în
    „Descărcări" și ca peste o lună să se știe ce conține.
    """
    if not from_month and not to_month:
        return "registru-documente.csv"
    if from_month == to_month:
        return f"registru-documente-{from_month}.csv"
    return f"registru-documente-{from_month or 'inceput'}_{to_month or 'azi'}.csv"


__all__ = [
    "EXCLUDED",
    "HEADER",
    "RegisterRow",
    "RegisterService",
    "filename",
    "rows_for",
    "to_csv",
]
