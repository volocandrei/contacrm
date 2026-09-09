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

from fastapi import APIRouter, status
from pydantic import Field

from app.api.deps import CurrentUser, DbSession
from app.api.route import CommittingRoute
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.domain.permissions import permissions_for
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.assistant.base import AssistantContext, AssistantError, AssistantReply
from app.services.assistant.factory import build_assistant
from app.services.assistant.rules import RuleAssistant
from app.services.audit import AuditService
from app.services.rate_limit import SharedWindowLimiter

logger = get_logger(__name__)

router = APIRouter(route_class=CommittingRoute, prefix="/assistant", tags=["asistent"])

#: Un mesaj de chat, nu un document. Peste atât, nu mai este o întrebare.
MAX_MESSAGE = 1000

#: Câte întrebări pune un om într-un minut. Douăzeci este peste ce apucă cineva
#: să scrie și să citească; sub asta ar deranja pe cine caută repede două lucruri
#: unul după altul.
#:
#: **De ce există.** Cu `ASSISTANT_PROVIDER=anthropic`, fiecare întrebare pleacă
#: la un furnizor care se plătește la apel, iar o întrebare poate costa până la
#: trei runde de unelte. Restul aplicației nu are nevoie de contor — o sută de
#: documente încărcate de un contabil sunt exact munca lui — dar aici o filă
#: lăsată cu un `setInterval` sau un script care greșește bucla cheltuiește bani
#: reali, tăcut, până la sfârșitul lunii.
#:
#: Contorul stă pe utilizator, nu pe adresă: un cabinet întreg în spatele
#: aceluiași IP nu trebuie să se blocheze reciproc. Ca și la autentificare, este
#: **împărțit de toate instanțele** — altfel plafonul de cheltuială s-ar înmulți
#: cu numărul de instanțe, adică ar dispărea tocmai când se cheltuiește mai mult.
QUESTIONS_PER_MINUTE = 20

_limiter = SharedWindowLimiter(scope="assistant", limit=QUESTIONS_PER_MINUTE)


class ChatIn(ApiModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE)


class LinkOut(ApiModel):
    label: str
    path: str


class ActionOut(ApiModel):
    """O acțiune pregătită. Interfața o arată ca buton; nimic nu se execută aici."""

    kind: str
    label: str
    summary: str
    payload: dict[str, str]


class ChatOut(ApiModel):
    text: str
    links: list[LinkOut]
    actions: list[ActionOut]
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


#: Ce se adaugă în față când modelul nu a răspuns și a preluat motorul local.
FALLBACK_NOTE = "Modelul nu a răspuns; am folosit motorul local."


@router.post("/chat", response_model=ChatOut)
def chat(session: DbSession, user: CurrentUser, payload: ChatIn) -> ChatOut:
    """Răspunde la o întrebare, în limitele rolului celui care o pune.

    **Când modelul cade, nu cade și chatul.** Un asistent care afișează „eroare"
    la o pană de rețea a furnizorului devine, în ziua aceea, un buton mort — iar
    întrebările pe care le acoperă motorul local sunt tocmai cele frecvente.
    Preluarea se **spune**: o degradare tăcută ar face ca o zi cu răspunsuri mai
    scurte să pară un capriciu al aplicației.
    """
    decision = _limiter.blocked(str(user.id))
    if not decision.allowed:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "Prea multe întrebări prea repede. Încearcă din nou într-un minut.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(decision.retry_after)},
        )
    _limiter.record(str(user.id))

    assistant = build_assistant(session)
    context = _context(user)
    engine = assistant.name

    try:
        reply: AssistantReply = assistant.answer(payload.message, context)
    except AssistantError as exc:
        logger.warning("assistant_fallback", engine=engine, reason=str(exc))
        local = RuleAssistant(session)
        reply = local.answer(payload.message, context)
        reply = AssistantReply(
            text=f"{FALLBACK_NOTE}\n{reply.text}",
            links=reply.links,
            actions=reply.actions,
            suggestions=reply.suggestions,
            used=reply.used,
        )
        engine = local.name

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
        actions=[
            ActionOut(
                kind=action.kind,
                label=action.label,
                summary=action.summary,
                payload=action.payload,
            )
            for action in reply.actions
        ],
        suggestions=list(reply.suggestions),
        used=list(reply.used),
        engine=engine,
    )
