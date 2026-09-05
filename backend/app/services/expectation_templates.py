"""Profilurile de client ale cabinetului, și aplicarea lor (§19).

**Problema.** Fără așteptări configurate, checklistul lunii este gol, „Documente
lipsă" nu are ce raporta, iar fiecare lună apare completă pentru că nu i se cere
nimic. Adică tot ce s-a construit în jurul colectării — cererea, linkul,
urmărirea — nu pornește. Configurarea se făcea client cu client, bifă cu bifă.

Un cabinet cu treizeci de clienți are, în realitate, trei-patru profiluri: SRL
plătitor de TVA lunar, SRL neplătitor, PFA în sistem real. Șablonul este numele
pe care cabinetul îl dă profilului; aplicarea lui pe doisprezece clienți deodată
este diferența dintre o după-amiază și un minut.

**Șablonul nu este o legătură.** Se aplică o dată, iar rezultatul rămâne al
clientului. Cine schimbă pe urmă șablonul nu rescrie tăcut ce s-a configurat
manual după aceea: un client care ar „moșteni" la distanță ar face ca o bifă
scoasă azi să reapară peste o lună fără ca cineva să-i fi atins ecranul, iar
nimeni n-ar ști de ce raportul cere din nou un extras de cont care nu vine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import DocumentType
from app.models.period import ClientExpectation, ExpectationTemplate, ExpectationTemplateItem


def replace_expectations(
    session: Session,
    organization_id: uuid.UUID,
    client_id: uuid.UUID,
    wanted: dict[uuid.UUID, int],
) -> None:
    """Înlocuiește lista de așteptări a unui client cu cea dată.

    **De ce stă aici și nu în rută.** Se cheamă din două locuri — ecranul
    clientului și aplicarea unui șablon — iar a doua implementare ar diverge
    exact în partea tăcută: ce se întâmplă cu tipurile scoase din listă.

    Ce nu mai apare **nu se mai așteaptă**. Documentele deja primite rămân: se
    schimbă așteptarea, nu istoria.
    """
    existing = {
        row.document_type_id: row
        for row in session.scalars(
            select(ClientExpectation).where(
                ClientExpectation.organization_id == organization_id,
                ClientExpectation.client_id == client_id,
            )
        )
    }

    for type_id, minimum in wanted.items():
        row = existing.get(type_id)
        if row is None:
            session.add(
                ClientExpectation(
                    organization_id=organization_id,
                    client_id=client_id,
                    document_type_id=type_id,
                    expected_min_count=minimum,
                )
            )
        else:
            row.expected_min_count = minimum

    for type_id, row in existing.items():
        if type_id not in wanted:
            session.delete(row)
    session.flush()


@dataclass(frozen=True)
class TemplateItemView:
    """Un tip din șablon, cu codul pe care îl folosește contractul și eticheta lui."""

    document_type_code: str
    document_type_label: str
    expected_min_count: int


@dataclass(frozen=True)
class TemplateView:
    id: uuid.UUID
    name: str
    items: list[TemplateItemView]


class ExpectationTemplateService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Citire ──────────────────────────────────────────────────────────────

    def _items_of(self, template_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[TemplateItemView]]:
        """Tipurile tuturor șabloanelor, într-o singură interogare.

        Una pe șablon ar fi însemnat cinci dus-întors pentru un ecran care oricum
        le arată pe toate deodată.
        """
        if not template_ids:
            return {}

        rows = self.session.execute(
            select(ExpectationTemplateItem, DocumentType)
            .join(DocumentType, DocumentType.id == ExpectationTemplateItem.document_type_id)
            .where(ExpectationTemplateItem.template_id.in_(template_ids))
            # Aceeași ordine ca pe ecranul clientului: două liste ale acelorași
            # tipuri, sortate diferit, se compară cu degetul pe ecran.
            .order_by(DocumentType.sort_order, DocumentType.label)
        ).all()

        grouped: dict[uuid.UUID, list[TemplateItemView]] = {}
        for item, document_type in rows:
            grouped.setdefault(item.template_id, []).append(
                TemplateItemView(
                    document_type_code=document_type.code,
                    document_type_label=document_type.label,
                    expected_min_count=item.expected_min_count,
                )
            )
        return grouped

    def list_templates(self, organization_id: uuid.UUID) -> list[TemplateView]:
        templates = list(
            self.session.scalars(
                select(ExpectationTemplate)
                .where(ExpectationTemplate.organization_id == organization_id)
                .order_by(ExpectationTemplate.name)
            )
        )
        items = self._items_of([row.id for row in templates])
        return [
            TemplateView(id=row.id, name=row.name, items=items.get(row.id, [])) for row in templates
        ]

    def _row(
        self, organization_id: uuid.UUID, template_id: uuid.UUID
    ) -> ExpectationTemplate | None:
        return self.session.scalars(
            select(ExpectationTemplate).where(
                ExpectationTemplate.organization_id == organization_id,
                ExpectationTemplate.id == template_id,
            )
        ).first()

    def get(self, organization_id: uuid.UUID, template_id: uuid.UUID) -> TemplateView | None:
        row = self._row(organization_id, template_id)
        if row is None:
            return None
        return TemplateView(
            id=row.id, name=row.name, items=self._items_of([row.id]).get(row.id, [])
        )

    # ── Scriere ─────────────────────────────────────────────────────────────

    def create(
        self, organization_id: uuid.UUID, name: str, wanted: dict[uuid.UUID, int]
    ) -> TemplateView:
        template = ExpectationTemplate(organization_id=organization_id, name=name)
        self.session.add(template)
        self.session.flush()
        self._set_items(organization_id, template.id, wanted)
        return TemplateView(
            id=template.id, name=template.name, items=self._items_of([template.id])[template.id]
        )

    def replace(
        self,
        organization_id: uuid.UUID,
        template_id: uuid.UUID,
        name: str,
        wanted: dict[uuid.UUID, int],
    ) -> TemplateView | None:
        template = self._row(organization_id, template_id)
        if template is None:
            return None
        template.name = name
        self._set_items(organization_id, template.id, wanted)
        return TemplateView(
            id=template.id,
            name=template.name,
            items=self._items_of([template.id]).get(template.id, []),
        )

    def _set_items(
        self, organization_id: uuid.UUID, template_id: uuid.UUID, wanted: dict[uuid.UUID, int]
    ) -> None:
        existing = {
            row.document_type_id: row
            for row in self.session.scalars(
                select(ExpectationTemplateItem).where(
                    ExpectationTemplateItem.template_id == template_id
                )
            )
        }
        for type_id, minimum in wanted.items():
            row = existing.get(type_id)
            if row is None:
                self.session.add(
                    ExpectationTemplateItem(
                        organization_id=organization_id,
                        template_id=template_id,
                        document_type_id=type_id,
                        expected_min_count=minimum,
                    )
                )
            else:
                row.expected_min_count = minimum
        for type_id, row in existing.items():
            if type_id not in wanted:
                self.session.delete(row)
        self.session.flush()

    def delete(self, organization_id: uuid.UUID, template_id: uuid.UUID) -> bool:
        """Șterge profilul. Clienții cărora li s-a aplicat rămân neatinși.

        Este chiar consecința faptului că șablonul nu este o legătură: ce s-a
        aplicat este de-acum al clientului.
        """
        template = self._row(organization_id, template_id)
        if template is None:
            return False
        self.session.delete(template)
        self.session.flush()
        return True

    def apply(
        self, organization_id: uuid.UUID, template_id: uuid.UUID, client_ids: list[uuid.UUID]
    ) -> int:
        """Scrie așteptările șablonului peste cele ale clienților dați.

        **Înlocuiește, nu adaugă.** Un client căruia i se aplică „SRL neplătitor
        de TVA" rămâne cu exact acea listă; altfel, aplicarea a două profiluri pe
        rând ar lăsa o listă pe care n-a ales-o nimeni.

        Cine cheamă răspunde de verificarea clienților: aici nu se ajunge cu id-uri
        neverificate.
        """
        template = self._row(organization_id, template_id)
        if template is None:
            return 0

        wanted = {
            row.document_type_id: row.expected_min_count
            for row in self.session.scalars(
                select(ExpectationTemplateItem).where(
                    ExpectationTemplateItem.template_id == template_id
                )
            )
        }
        for client_id in client_ids:
            replace_expectations(self.session, organization_id, client_id, wanted)
        return len(client_ids)
