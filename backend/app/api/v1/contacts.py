"""Agenda cabinetului: toate persoanele de contact, într-o singură cerere.

**De ce există.** Ecranul „Contacte" cerea lista de clienți și apoi, pentru
fiecare, contactele lui: un `GET /clients/{id}/contacts` per rând. La treizeci de
clienți însemnau treizeci de cereri, la două sute — două sute, toate pornite
deodată la deschiderea ecranului. Nu era doar risipă: ecranul se completa în
valuri, iar clienții fără contacte nu apăreau deloc, deci pagina putea arăta
aproape goală în timp ce bombarda serverul.

Întrebarea la care răspunde ecranul este „cu cine vorbesc la firma asta?", iar
răspunsul are nevoie și de **căutare** — după nume de persoană, după email, după
telefon, sau după numele firmei. Nimic din toate acestea nu se putea face cu
lista per client.

Citirea cere `clients:read`: contactele sunt date de client, nu un registru
separat.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_permission
from app.api.route import CommittingRoute
from app.domain.permissions import Permission
from app.models.user import User
from app.repositories.client import ClientRepository
from app.schemas.client import ContactFilters, ContactListItemOut
from app.schemas.common import PageParams, Paginated

router = APIRouter(route_class=CommittingRoute, tags=["crm"])

ContactReader = Annotated[User, require_permission(Permission.CLIENTS_READ)]


@router.get("/contacts", response_model=Paginated[ContactListItemOut])
def list_contacts(
    session: DbSession,
    user: ContactReader,
    filters: Annotated[ContactFilters, Depends()],
    page: Annotated[PageParams, Depends()],
) -> Paginated[ContactListItemOut]:
    rows, total = ClientRepository(session).all_contacts(user.organization_id, filters, page)
    return Paginated[ContactListItemOut].build(
        items=[
            ContactListItemOut(
                id=contact.id,
                client_id=contact.client_id,
                client_name=client_name,
                full_name=contact.full_name,
                role=contact.role,
                email=contact.email,
                phone=contact.phone,
                whatsapp_number=contact.whatsapp_number,
                is_primary=contact.is_primary,
                is_active=contact.is_active,
            )
            for contact, client_name in rows
        ],
        total=total,
        params=page,
    )
