"""Preview și download: securitate, antete, streaming (§27-§30, §45).

Testele de parsare a intervalelor și de curățare a numelui nu au nevoie de bază de
date; restul rulează prin API-ul real.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DocumentStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.audit import AuditLog
from app.models.document import Document
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from app.services.document_delivery import (
    RangeNotSatisfiableError,
    content_disposition,
    parse_range,
    safe_filename,
)
from tests.conftest import requires_db

PASSWORD = "parola-de-test-123"
PDF = b"%PDF-1.7\n" + bytes(range(256)) * 8 + b"\n%%EOF"


# ── Parsarea intervalelor (fără bază de date) ────────────────────────────────


class TestRangeParsing:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("bytes=0-99", (0, 99)),
            ("bytes=100-", (100, 999)),
            ("bytes=-100", (900, 999)),
            ("bytes=0-", (0, 999)),
            ("bytes=990-2000", (990, 999)),  # capătul se limitează la fișier
        ],
    )
    def test_valid_ranges(self, header: str, expected: tuple[int, int]) -> None:
        parsed = parse_range(header, 1000)
        assert parsed is not None
        assert (parsed.start, parsed.end) == expected

    @pytest.mark.parametrize(
        "header",
        [None, "", "octeti=0-10", "bytes=abc", "bytes=", "bytes=0-10, 20-30"],
        ids=["absent", "gol", "unitate-gresita", "nenumeric", "fara-valori", "multiplu"],
    )
    def test_unparsable_ranges_serve_the_whole_file(self, header: str | None) -> None:
        """Un interval pe care nu-l înțelegem nu e o eroare: trimitem tot fișierul."""
        assert parse_range(header, 1000) is None

    @pytest.mark.parametrize("header", ["bytes=1000-1100", "bytes=2000-", "bytes=-0"])
    def test_ranges_outside_the_file_are_refused(self, header: str) -> None:
        with pytest.raises(RangeNotSatisfiableError):
            parse_range(header, 1000)

    def test_length_is_inclusive(self) -> None:
        parsed = parse_range("bytes=0-0", 1000)
        assert parsed is not None and parsed.length == 1


class TestFilenames:
    def _document(self, **kwargs: object) -> Document:
        return Document(
            id=uuid.UUID(int=7),
            organization_id=uuid.uuid4(),
            status=DocumentStatus.RECEIVED,
            source="UPLOAD",
            storage_key="k",
            mime_type="application/pdf",
            file_size=1,
            sha256_hash="a" * 64,
            received_at=datetime.now(UTC),
            **kwargs,  # type: ignore[arg-type]
        )

    def test_prefers_the_standardised_name(self) -> None:
        document = self._document(
            original_filename="scan001.pdf",
            stored_filename="2026-08-14_Facturaintrare_AlfaSRL_F1023.pdf",
        )
        assert safe_filename(document) == "2026-08-14_Facturaintrare_AlfaSRL_F1023.pdf"

    def test_falls_back_to_the_original_name(self) -> None:
        document = self._document(original_filename="factura mea.pdf")
        assert safe_filename(document) == "factura mea.pdf"

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("../../etc/passwd", "passwd"),
            ("C:\\Windows\\system32\\cmd.pdf", "cmd.pdf"),
            ('a"b.pdf', "ab.pdf"),
            ("a\x00b.pdf", "ab.pdf"),
        ],
    )
    def test_paths_and_quotes_never_reach_the_header(self, given: str, expected: str) -> None:
        """Un nume nu poate sparge antetul și nu poate purta o cale (§29)."""
        assert safe_filename(self._document(original_filename=given)) == expected

    def test_an_empty_name_gets_a_generated_one(self) -> None:
        document = self._document(original_filename="///")
        assert safe_filename(document) == f"document-{document.id}.pdf"

    def test_disposition_carries_both_ascii_and_utf8(self) -> None:
        """Fără `filename*`, un nume cu diacritice s-ar salva stricat."""
        header = content_disposition(
            self._document(original_filename="Factură Șerbănescu.pdf"), inline=False
        )
        assert header.startswith("attachment;")
        assert 'filename="' in header
        assert "filename*=UTF-8''" in header
        assert "%C8%98" in header  # Ș percent-encoded

    def test_inline_disposition_for_preview(self) -> None:
        header = content_disposition(self._document(original_filename="a.pdf"), inline=True)
        assert header.startswith("inline;")


# ── Prin API ─────────────────────────────────────────────────────────────────

pytestmark = requires_db


@pytest.fixture
def roles(db: Session) -> dict[RoleCode, Role]:
    permissions: dict[str, Permission] = {}
    for perms in ROLE_PERMISSIONS.values():
        for perm in perms:
            permissions.setdefault(perm.value, Permission(code=perm.value))
    db.add_all(permissions.values())
    db.flush()

    created: dict[RoleCode, Role] = {}
    for code, perms in ROLE_PERMISSIONS.items():
        role = Role(
            code=code.value,
            name=ROLE_LABEL[code],
            permissions=[permissions[p.value] for p in perms],
        )
        db.add(role)
        created[code] = role
    db.flush()
    return created


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


def make_user(
    db: Session, org: Organization, roles: dict[RoleCode, Role], *, email: str, role: RoleCode
) -> User:
    from app.core.security import hash_password

    user = User(
        organization_id=org.id,
        email=email,
        full_name="Ioana Marinescu",
        password_hash=hash_password(PASSWORD),
        roles=[roles[role]],
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def admin(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    return make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)


@pytest.fixture
def api_storage(api: TestClient, tmp_path: Path):  # type: ignore[no-untyped-def]
    from app.api.deps import get_storage
    from app.services.storage import LocalStorageProvider

    provider = LocalStorageProvider(tmp_path / "storage")
    api.app.dependency_overrides[get_storage] = lambda: provider  # type: ignore[attr-defined]
    return api, provider


def login(api: TestClient, email: str) -> None:
    assert (
        api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


def upload(api: TestClient, content: bytes = PDF, name: str = "factura.pdf") -> str:
    response = api.post(
        "/api/v1/documents/upload",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestPreviewAccess:
    """§45 — matricea de acces, explicit."""

    def test_unauthenticated_gets_401(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)
        api.cookies.clear()

        assert api.get(f"/api/v1/documents/{document_id}/preview").status_code == 401
        assert api.get(f"/api/v1/documents/{document_id}/download").status_code == 401

    def test_authenticated_with_permission_gets_the_file(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)

        response = api.get(f"/api/v1/documents/{document_id}/preview")
        assert response.status_code == 200
        assert response.content == PDF

    def test_a_deleted_document_is_not_found(self, api_storage, admin: User, db: Session) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)

        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.deleted_at = datetime.now(UTC)
        db.flush()

        assert api.get(f"/api/v1/documents/{document_id}/preview").status_code == 404

    def test_a_document_of_another_organization_is_not_found(  # type: ignore[no-untyped-def]
        self, api_storage, admin: User, db: Session
    ) -> None:
        """IDOR: schimbarea id-ului nu dă acces la fișierul altcuiva (§72)."""
        api, _ = api_storage
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        foreign = Document(
            organization_id=other.id,
            status=DocumentStatus.RECEIVED,
            source="UPLOAD",
            original_filename="strain.pdf",
            storage_key="organizations/x/documents/y/original/source.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256_hash="f" * 64,
            received_at=datetime.now(UTC),
        )
        db.add(foreign)
        db.flush()

        login(api, admin.email)
        assert api.get(f"/api/v1/documents/{foreign.id}/preview").status_code == 404
        assert api.get(f"/api/v1/documents/{foreign.id}/download").status_code == 404

    def test_an_unknown_id_is_not_found(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        assert api.get(f"/api/v1/documents/{uuid.uuid4()}/preview").status_code == 404

    def test_a_missing_file_does_not_leak_the_key(  # type: ignore[no-untyped-def]
        self, api_storage, admin: User, db: Session
    ) -> None:
        """Rândul există, fișierul nu: 404, fără să spunem ce cheie lipsește (§73)."""
        api, provider = api_storage
        login(api, admin.email)
        document_id = upload(api)

        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        provider.delete(document.storage_key)

        response = api.get(f"/api/v1/documents/{document_id}/preview")
        assert response.status_code == 404
        assert "organizations/" not in response.text


class TestPreviewHeaders:
    def test_serves_the_validated_content_type(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        """Nu tipul declarat de client la upload, ci cel dedus din conținut (§50)."""
        api, _ = api_storage
        login(api, admin.email)
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 512
        response = api.post(
            "/api/v1/documents/upload",
            files={"file": ("minte.pdf", io.BytesIO(jpeg), "application/pdf")},
        )
        document_id = response.json()["id"]

        preview = api.get(f"/api/v1/documents/{document_id}/preview")
        assert preview.headers["content-type"].startswith("image/jpeg")

    def test_carries_the_hardening_headers(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        """Conținut încărcat de utilizatori, servit de pe originea aplicației."""
        api, _ = api_storage
        login(api, admin.email)
        response = api.get(f"/api/v1/documents/{upload(api)}/preview")

        assert response.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["referrer-policy"] == "no-referrer"

    def test_preview_is_inline_download_is_attachment(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)

        preview = api.get(f"/api/v1/documents/{document_id}/preview")
        download = api.get(f"/api/v1/documents/{document_id}/download")
        assert preview.headers["content-disposition"].startswith("inline;")
        assert download.headers["content-disposition"].startswith("attachment;")

    def test_no_internal_path_appears_in_any_header(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        response = api.get(f"/api/v1/documents/{upload(api)}/download")
        assert "organizations/" not in str(response.headers)


class TestRangeRequests:
    def test_serves_a_partial_response(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)

        response = api.get(
            f"/api/v1/documents/{document_id}/preview", headers={"Range": "bytes=0-9"}
        )
        assert response.status_code == 206
        assert response.content == PDF[:10]
        assert response.headers["content-range"] == f"bytes 0-9/{len(PDF)}"
        assert response.headers["content-length"] == "10"

    def test_advertises_range_support(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        response = api.get(f"/api/v1/documents/{upload(api)}/preview")
        assert response.headers["accept-ranges"] == "bytes"

    def test_a_range_beyond_the_file_is_refused(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)

        response = api.get(
            f"/api/v1/documents/{document_id}/preview", headers={"Range": "bytes=99999-"}
        )
        assert response.status_code == 416
        assert response.headers["content-range"] == f"bytes */{len(PDF)}"

    def test_the_tail_of_the_file(self, api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
        api, _ = api_storage
        login(api, admin.email)
        response = api.get(
            f"/api/v1/documents/{upload(api)}/preview", headers={"Range": "bytes=-6"}
        )
        assert response.status_code == 206
        assert response.content == PDF[-6:]


class TestAuthorizationMatrix:
    def test_a_viewer_may_read_the_file(  # type: ignore[no-untyped-def]
        self, api_storage, db: Session, org: Organization, roles: dict[RoleCode, Role], admin: User
    ) -> None:
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)

        viewer = make_user(db, org, roles, email="vizitator@contacrm.test", role=RoleCode.VIEWER)
        api.cookies.clear()
        login(api, viewer.email)

        assert api.get(f"/api/v1/documents/{document_id}/preview").status_code == 200
        assert api.get(f"/api/v1/documents/{document_id}/download").status_code == 200

    def test_download_is_audited_but_preview_is_not(  # type: ignore[no-untyped-def]
        self, api_storage, admin: User, db: Session
    ) -> None:
        """Descărcarea scoate o probă din sistem; previzualizarea nu (§33)."""
        api, _ = api_storage
        login(api, admin.email)
        document_id = upload(api)

        api.get(f"/api/v1/documents/{document_id}/preview")
        assert (
            db.scalars(select(AuditLog).where(AuditLog.action == "DOCUMENT_DOWNLOADED")).all() == []
        )

        api.get(f"/api/v1/documents/{document_id}/download")
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "DOCUMENT_DOWNLOADED")).one()
        assert entry.user_id == admin.id
        assert entry.detail == "factura.pdf"


def test_no_route_accepts_a_token_in_the_query_string(api_storage, admin: User) -> None:  # type: ignore[no-untyped-def]
    """§27 — un token în URL ajunge în loguri, istoric și antete Referer."""
    api, _ = api_storage
    login(api, admin.email)
    document_id = upload(api)
    token = api.cookies.get("contacrm_access")
    assert token
    api.cookies.clear()

    response = api.get(f"/api/v1/documents/{document_id}/preview?token={token}")
    assert response.status_code == 401
