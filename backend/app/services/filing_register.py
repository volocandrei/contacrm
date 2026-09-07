"""Registrul declarațiilor depuse: un rând pe depunere.

**Golul.** Aplicația știe ce s-a depus, pentru cine și de către cine — și o ținea
numai pe ecran. Un cabinet are nevoie de lista asta ca fișier în trei situații
concrete: la o verificare internă la sfârșit de an, la predarea unui client către
alt contabil, și când cineva întreabă „ce ați depus pentru noi anul acesta".
Până acum, răspunsul se compunea din memorie și capturi de ecran.

**Ce conține.** Tot ce s-a înregistrat ca depus, inclusiv declarațiile fără
calendar — vezi `docs/DECLARATIONS.md`. Acelea nu apar pe ecranul de termene,
fiindcă nu produc rânduri calculate, deci un registru care le-ar sări ar fi
singurul loc din aplicație unde s-ar fi putut vedea și nu s-ar vedea.

**Nu se calculează nimic.** Nu apare aici ce **ar fi trebuit** depus și nu s-a
depus. Registrul este o listă a faptelor înregistrate; restanțele sunt o
concluzie, se citesc pe ecranul de termene și depind de ziua în care se privesc.
Amestecate în același fișier, cele două s-ar fi citit la fel.

Forma fișierului — separator, BOM, virgulă la zecimale — stă în `excel_csv.py`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ObligationFrequency
from app.models.client import Client
from app.models.obligation import ObligationFiling, ObligationType
from app.models.user import User
from app.services.excel_csv import day, render

HEADER: Final = (
    "Client",
    "CUI client",
    "Cod",
    "Declarație",
    "Periodicitate",
    "Perioada",
    "Înregistrat la",
    "Înregistrat de",
    "Notă",
)

#: Cum se citește periodicitatea în fișier. Text, nu regulă.
FREQUENCY_LABEL: Final[dict[ObligationFrequency, str]] = {
    ObligationFrequency.MONTHLY: "lunar",
    ObligationFrequency.QUARTERLY: "trimestrial",
    ObligationFrequency.ANNUAL: "anual",
    ObligationFrequency.ON_DEMAND: "la nevoie",
}


@dataclass(frozen=True, slots=True)
class FilingRow:
    client_name: str
    client_tax_id: str | None
    code: str
    label: str
    frequency: ObligationFrequency
    period: str
    filed_at: dt.datetime
    filed_by_name: str | None
    note: str | None


class FilingRegisterService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def rows(
        self,
        *,
        from_month: str | None = None,
        to_month: str | None = None,
        client_id: uuid.UUID | None = None,
    ) -> list[FilingRow]:
        """Depunerile din interval, pe client și apoi pe perioadă.

        Intervalul se aplică **perioadei declarate**, nu zilei în care s-a apăsat
        butonul. Cine cere „2026-01 … 2026-12" întreabă ce s-a depus **pentru**
        anul acela; o depunere pentru decembrie 2025 marcată în ianuarie 2026 nu
        este a anului 2026, oricât de aproape ar fi data marcării.
        """
        query = (
            select(ObligationFiling, ObligationType, Client, User)
            .join(ObligationType, ObligationType.id == ObligationFiling.obligation_type_id)
            .join(Client, Client.id == ObligationFiling.client_id)
            .outerjoin(User, User.id == ObligationFiling.filed_by)
            .where(
                ObligationFiling.organization_id == self.organization_id,
                Client.deleted_at.is_(None),
            )
            .order_by(Client.name, ObligationFiling.period.desc(), ObligationType.code)
        )
        if from_month is not None:
            query = query.where(ObligationFiling.period >= from_month)
        if to_month is not None:
            query = query.where(ObligationFiling.period <= to_month)
        if client_id is not None:
            query = query.where(ObligationFiling.client_id == client_id)

        return [
            FilingRow(
                client_name=client.name,
                client_tax_id=client.tax_id,
                code=obligation_type.code,
                label=obligation_type.label,
                frequency=obligation_type.frequency,
                period=filing.period,
                filed_at=filing.filed_at,
                # `outerjoin`: un utilizator șters nu face depunerea să dispară.
                # Ce s-a depus rămâne depus și după ce omul pleacă din cabinet.
                filed_by_name=user.full_name if user is not None else None,
                note=filing.note,
            )
            for filing, obligation_type, client, user in self.session.execute(query).all()
        ]


def rows_for(entries: list[FilingRow]) -> list[list[str]]:
    table: list[list[str]] = [list(HEADER)]
    for row in entries:
        table.append(
            [
                row.client_name,
                row.client_tax_id or "",
                row.code,
                row.label,
                FREQUENCY_LABEL[row.frequency],
                row.period,
                day(row.filed_at.date()),
                row.filed_by_name or "",
                row.note or "",
            ]
        )
    return table


def to_csv(entries: list[FilingRow]) -> str:
    return render(rows_for(entries))


def filename(from_month: str | None, to_month: str | None) -> str:
    """Numele poartă intervalul, ca două exporturi să nu se suprascrie."""
    if not from_month and not to_month:
        return "registru-declaratii.csv"
    if from_month == to_month:
        return f"registru-declaratii-{from_month}.csv"
    return f"registru-declaratii-{from_month or 'inceput'}_{to_month or 'azi'}.csv"


__all__ = [
    "FREQUENCY_LABEL",
    "HEADER",
    "FilingRegisterService",
    "FilingRow",
    "filename",
    "rows_for",
    "to_csv",
]
