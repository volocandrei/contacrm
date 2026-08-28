"""Schemele de autentificare.

`CurrentUserOut` este forma exactă a lui `CurrentUser` din
`frontend/src/types/domain.ts`. Frontend-ul o consumă direct din `/auth/login` și
`/me`, deci orice câmp adăugat aici trebuie adăugat și acolo.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.domain.permissions import Permission, RoleCode
from app.schemas.common import ApiModel


class LoginRequest(ApiModel):
    email: EmailStr
    # Lungimea maximă oprește un DoS prin parole uriașe date lui Argon2.
    password: str = Field(min_length=1, max_length=1024)


class CurrentUserOut(ApiModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    role: RoleCode
    permissions: list[Permission]
    organization_id: uuid.UUID
    organization_name: str


class UserSummaryOut(ApiModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    role: RoleCode
    is_active: bool
    last_login_at: datetime | None


class LogoutResponse(ApiModel):
    ok: bool = True
