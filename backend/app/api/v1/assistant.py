"""Asistentul din aplicație (M13).

O singură rută: pui o întrebare, primești un răspuns și, când are unde, un drum.

**Ce nu face ruta asta, deliberat.** Nu execută nicio acțiune care schimbă date.
O aprobare este un act contabil cu nume și oră în jurnal (§33) — trebuie să aibă
în spate un om care a apăsat, nu o propoziție interpretată. Asistentul propune
un link; omul îl deschide și apasă el.

**Ce se auditează.** Că cineva a întrebat ceva, și ce fel de întrebare a fost —
nu textul întrebării și nu răspunsul (§33: jurnalul spune cine/ce/când, nu
conținut). Un asistent care citește date de client fără urmă în jurnal ar fi o
gaură exact în locul în care restul aplicației este strictă.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field

from app.api.deps import CurrentUser, DbSession
from app.domain.permissions import permissions_for
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.assistant.base import AssistantContext, AssistantReply
from app.services.assistant.factory import build_assistant
from app.services.audit import AuditService

router = APIRouter(prefix="/assistant", tags=["asistent"])

#: Un mesaj de chat, nu un document. Peste atât, nu mai este o întrebare.
MAX_MESSAGE = 1000


class ChatIn(ApiModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE)


class LinkOut(ApiModel):
    label: str
    path: str


class ChatOut(ApiModel):
    text: str
    links: list[LinkOut]
    suggestions: list[str]
    #: Uneltele care au produs cifrele. Cine vrea să verifice, poate.
    used: list[str]
    #: Ce motor a răspuns: `rules` fără credențiale, altul când e configurat.
    engine: str


def _context(user: User) -> AssistantContext:
    return AssistantContext(
        organization_id=user.organization_id,
        user_id=user.id,
        user_name=user.full_name,
        # Din rol, ca la `require_permission`: lista de pe utilizator este
        # relația cu tabelul, nu vocabularul după care se decide.
        permissions=frozenset(permissions_for(user.primary_role)),
    )


@router.post("/chat", response_model=ChatOut)
def chat(session: DbSession, user: CurrentUser, payload: ChatIn) -> ChatOut:
    """Răspunde la o întrebare, în limitele rolului celui care o pune."""
    assistant = build_assistant(session)
    context = _context(user)
    reply: AssistantReply = assistant.answer(payload.message, context)

    AuditService(session).record(
        organization_id=user.organization_id,
        action="assistant.query",
        entity_type="Assistant",
        user_id=user.id,
        user_name=user.full_name,
        # Ce fel de întrebare, nu care întrebare: textul poate conține numele
        # unui client, iar jurnalul nu ține conținut.
        detail=", ".join(reply.used) or "fără potrivire",
    )
    session.commit()

    return ChatOut(
        text=reply.text,
        links=[LinkOut(label=link.label, path=link.path) for link in reply.links],
        suggestions=list(reply.suggestions),
        used=list(reply.used),
        engine=assistant.name,
    )
