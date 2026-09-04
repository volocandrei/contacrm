"""Ce motor răspunde, după configurare.

Același tipar ca la stocare (ADR-004) și extracție (ADR-005): interfața este
fixă, implementarea se alege dintr-o variabilă de mediu, iar restul aplicației
nu știe care a răspuns.

Implicit `rules`, care merge fără nicio credențială. Un motor de limbaj se
adaugă aici, primind aceleași unelte și aceleași limite de permisiuni.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.assistant.base import AssistantProvider
from app.services.assistant.rules import RuleAssistant

#: Lista valorilor acceptate stă în `core/config.py`, lângă celelalte, și este
#: verificată **la pornire**: un nume greșit trebuie să oprească aplicația, nu
#: să se descopere la prima întrebare pusă în chat.


def build_assistant(session: Session) -> AssistantProvider:
    if settings.assistant_provider == "rules":
        return RuleAssistant(session)
    # Nu se poate ajunge aici: validatorul din configurare respinge orice altceva
    # la pornire. Ramura există ca adăugarea unui motor nou să fie o eroare
    # vizibilă, nu o cădere tăcută în cel implicit.
    raise ValueError(f"ASSISTANT_PROVIDER necunoscut: {settings.assistant_provider!r}")
