"""Tipul de adresă de email folosit în tot API-ul.

De ce nu `pydantic.EmailStr`:

1. `EmailStr` respinge domeniile rezervate din RFC 2606 (`.test`, `.example`,
   `.invalid`, `.localhost`). Convenția proiectului este ca datele de development
   să folosească exact `.test` — deci `EmailStr` ar face imposibilă autentificarea
   cu conturile documentate în README.
2. Verificarea de livrabilitate implicită face o interogare **DNS** la fiecare
   validare. Pe ruta de login asta ar însemna o cerere de rețea per încercare —
   latență și un punct de eșec în plus, fără niciun câștig de securitate.

Aici: normalizare (trim + lowercase), lungime mărginită, sintaxă validată fără DNS,
iar domeniile rezervate sunt acceptate doar în afara producției — în producție o
adresă `.test` este aproape sigur o greșeală.
"""

from __future__ import annotations

from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, Field

from app.core.config import settings

# RFC 5321: 64 pentru partea locală + @ + 255 pentru domeniu.
MAX_EMAIL_LENGTH = 320


def normalise_email(value: str) -> str:
    candidate = value.strip()
    try:
        result = validate_email(
            candidate,
            # Fără DNS: validăm forma, nu existența cutiei poștale.
            check_deliverability=False,
            # `.test` și celelalte domenii rezervate sunt convenția noastră de development.
            test_environment=not settings.is_production,
        )
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    # Comparațiile și căutările se fac întotdeauna pe forma normalizată.
    return result.normalized.lower()


EmailAddress = Annotated[
    str,
    Field(max_length=MAX_EMAIL_LENGTH),
    AfterValidator(normalise_email),
]
