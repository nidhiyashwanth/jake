import asyncio
import os
import secrets
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.services.authorization import role_allows


def _require_postgres() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("Set DATABASE_URL to a reachable PostgreSQL 16 database for integration tests")
    if "sqlite" in database_url.lower() or not database_url.lower().startswith("postgresql"):
        pytest.fail("T-01 integration tests require PostgreSQL; SQLite is not an accepted substitute")
    return database_url


def _migrate(database_url: str) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    migration_url = os.environ.get("DATABASE_ADMIN_URL", database_url)
    config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))
    command.upgrade(config, "head")


async def _login(client: httpx.AsyncClient, suffix: str, *, email: str | None = None) -> dict:
    response = await client.post(
        "/api/auth/dev-login",
        json={
            "email": email or f"owner-{suffix}@example.invalid",
            "name": f"Owner {suffix}",
            "organization_name": f"Organization {suffix}",
            "workspace_name": f"Workspace {suffix}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(login: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {login['access_token']}"}


def _make_non_superuser_engine(database_url: str):
    """Use a real non-owner role so PostgreSQL RLS is exercised, not bypassed."""

    role = f"t01_rls_{secrets.token_hex(8)}"
    password = secrets.token_hex(24)
    admin_database_url = os.environ.get("DATABASE_ADMIN_URL", database_url)
    admin_engine = create_engine(admin_database_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.exec_driver_sql(
            f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD \'{password}\''
        )
        for table in ("vendors", "audit_logs", "data_access_logs"):
            connection.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO "{role}"')
    admin_engine.dispose()
    rls_url = make_url(database_url).set(username=role, password=password)
    rls_engine = create_engine(rls_url, pool_pre_ping=True)

    def cleanup() -> None:
        rls_engine.dispose()
        cleanup_engine = create_engine(admin_database_url, pool_pre_ping=True)
        with cleanup_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        cleanup_engine.dispose()

    return rls_engine, cleanup


@pytest.mark.integration
def test_role_matrix_is_explicit_and_canonical() -> None:
    assert role_allows("owner", "member.disable")
    assert role_allows("admin", "member.invite")
    assert role_allows("builder", "document.verify")
    assert role_allows("operator", "review.update")
    assert role_allows("viewer", "vendor.read")
    assert role_allows("auditor", "audit.read")
    assert not role_allows("builder", "audit.read")
    assert not role_allows("operator", "audit.read")
    assert not role_allows("viewer", "vendor.create")
    assert not role_allows("auditor", "document.upload")
    assert role_allows("reviewer", "review.update")


@pytest.mark.integration
def test_two_workspaces_are_isolated_and_rls_is_active() -> None:
    database_url = _require_postgres()
    _migrate(database_url)
    from app.main import app

    suffix = uuid4().hex[:10]
    rls_engine = None
    cleanup_rls = None
    try:
        async def exercise() -> tuple[dict, str, dict]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                tenant_a = await _login(client, f"{suffix}-a")
                vendor_response = await client.post(
                    "/api/vendors",
                    headers=_headers(tenant_a),
                    json={"legal_name": f"Tenant A Vendor {suffix}"},
                )
                assert vendor_response.status_code == 201, vendor_response.text
                vendor_id = vendor_response.json()["id"]

                tenant_b = await _login(client, f"{suffix}-b")
                hidden = await client.get(f"/api/vendors/{vendor_id}", headers=_headers(tenant_b))
                assert hidden.status_code == 404, hidden.text
                listing = await client.get("/api/vendors", headers=_headers(tenant_b))
                assert listing.status_code == 200, listing.text
                assert vendor_id not in {item["id"] for item in listing.json()["items"]}

                visible = await client.get(f"/api/vendors/{vendor_id}", headers=_headers(tenant_a))
                assert visible.status_code == 200, visible.text
                return tenant_a, vendor_id, tenant_b

        tenant_a, vendor_id, tenant_b = asyncio.run(exercise())
        workspace_a = tenant_a["workspace"]["id"]
        workspace_b = tenant_b["workspace"]["id"]
        rls_engine, cleanup_rls = _make_non_superuser_engine(database_url)
        with rls_engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM vendors")).scalar_one() == 0
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"), {"workspace_id": workspace_a})
            assert connection.execute(text("SELECT count(*) FROM vendors WHERE id = :vendor_id"), {"vendor_id": vendor_id}).scalar_one() == 1
            connection.commit()

        with rls_engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"), {"workspace_id": workspace_b})
            with pytest.raises(SQLAlchemyError):
                connection.execute(
                    text(
                        "INSERT INTO vendors (id, workspace_id, legal_name, created_at) "
                        "VALUES (:id, :workspace_id, :legal_name, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": str(uuid4()),
                        "workspace_id": workspace_a,
                        "legal_name": f"Cross Tenant Write {suffix}",
                    },
                )

        with rls_engine.connect() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"), {"workspace_id": workspace_b})
            denied_actions = connection.execute(
                text("SELECT action FROM audit_logs WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_b},
            ).scalars().all()
            assert "data.access_denied" in denied_actions
            connection.rollback()
    finally:
        if cleanup_rls:
            cleanup_rls()


@pytest.mark.integration
def test_session_context_switch_is_scoped_and_audited() -> None:
    database_url = _require_postgres()
    _migrate(database_url)
    from app.main import app

    suffix = uuid4().hex[:10]
    rls_engine = None
    cleanup_rls = None
    try:
        async def exercise() -> tuple[dict, dict, str]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                owner_a = await _login(client, f"context-{suffix}-a")
                owner_b = await _login(client, f"context-{suffix}-b")
                invited = await client.post(
                    f"/api/workspaces/{owner_b['workspace']['id']}/members",
                    headers=_headers(owner_b),
                    json={
                        "email": owner_a["user"]["email"],
                        "name": owner_a["user"]["name"],
                        "role": "operator",
                    },
                )
                assert invited.status_code == 201, invited.text

                switched = await client.post(
                    "/api/auth/context",
                    headers=_headers(owner_a),
                    json={"workspace_id": owner_b["workspace"]["id"]},
                )
                assert switched.status_code == 200, switched.text
                assert switched.json()["workspace"]["id"] == owner_b["workspace"]["id"]
                assert switched.json()["membership"]["role"] == "operator"

                created = await client.post(
                    "/api/vendors",
                    headers=_headers(owner_a),
                    json={"legal_name": f"Context Vendor {suffix}"},
                )
                assert created.status_code == 201, created.text
                vendor_id = created.json()["id"]
                visible_to_b = await client.get("/api/vendors", headers=_headers(owner_b))
                assert visible_to_b.status_code == 200, visible_to_b.text
                assert vendor_id in {item["id"] for item in visible_to_b.json()["items"]}
                return owner_a, owner_b, vendor_id

        owner_a, owner_b, _ = asyncio.run(exercise())
        rls_engine, cleanup_rls = _make_non_superuser_engine(database_url)
        with rls_engine.connect() as connection:
            for workspace_id, expected_action in (
                (owner_a["workspace"]["id"], "auth.context_changed"),
                (owner_b["workspace"]["id"], "auth.context_activated"),
            ):
                connection.execute(
                    text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                    {"workspace_id": workspace_id},
                )
                actions = connection.execute(
                    text("SELECT action FROM audit_logs WHERE workspace_id = :workspace_id"),
                    {"workspace_id": workspace_id},
                ).scalars().all()
                assert expected_action in actions
                connection.rollback()
    finally:
        if cleanup_rls:
            cleanup_rls()


@pytest.mark.integration
def test_disabled_membership_and_revoked_session_are_rejected() -> None:
    database_url = _require_postgres()
    _migrate(database_url)
    from app.main import app

    suffix = uuid4().hex[:10]
    rls_engine = None
    cleanup_rls = None
    try:
        async def exercise() -> tuple[dict, dict, str]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                owner = await _login(client, f"members-{suffix}")
                workspace_id = owner["workspace"]["id"]
                invited = await client.post(
                    f"/api/workspaces/{workspace_id}/members",
                    headers=_headers(owner),
                    json={"email": f"viewer-{suffix}@example.invalid", "name": "Viewer", "role": "viewer"},
                )
                assert invited.status_code == 201, invited.text
                viewer = await _login(
                    client,
                    f"members-{suffix}",
                    email=f"viewer-{suffix}@example.invalid",
                )
                # The development login uses the workspace name from the suffix.
                assert viewer["role"] == "viewer"
                disabled = await client.patch(
                    f"/api/workspaces/{workspace_id}/members/{invited.json()['user_id']}",
                    headers=_headers(owner),
                    json={"disabled": True},
                )
                assert disabled.status_code == 200, disabled.text
                rejected = await client.get("/api/auth/me", headers=_headers(viewer))
                assert rejected.status_code == 403, rejected.text
                assert rejected.json()["error"]["code"] == "MEMBERSHIP_DISABLED"

                revoked = await client.post("/api/auth/logout", headers=_headers(owner))
                assert revoked.status_code == 200, revoked.text
                expired = await client.get("/api/auth/me", headers=_headers(owner))
                assert expired.status_code == 401, expired.text
                assert expired.json()["error"]["code"] == "SESSION_REVOKED"
                return owner, viewer, workspace_id

        owner, viewer, workspace_id = asyncio.run(exercise())
        rls_engine, cleanup_rls = _make_non_superuser_engine(database_url)
        with rls_engine.connect() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"), {"workspace_id": workspace_id})
            actions = connection.execute(
                text("SELECT action FROM audit_logs WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            ).scalars().all()
            assert "membership.invited" in actions
            assert "membership.updated" in actions
            assert "auth.membership_rejected" in actions
            assert "auth.logout" in actions
            connection.rollback()
    finally:
        if cleanup_rls:
            cleanup_rls()


@pytest.mark.integration
def test_auth_membership_and_sensitive_read_events_are_append_only() -> None:
    database_url = _require_postgres()
    _migrate(database_url)
    from app.main import app

    suffix = uuid4().hex[:10]
    rls_engine = None
    cleanup_rls = None
    try:
        async def exercise() -> tuple[dict, str]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                owner = await _login(client, f"audit-{suffix}")
                created = await client.post(
                    "/api/vendors",
                    headers=_headers(owner),
                    json={"legal_name": f"Audit Vendor {suffix}"},
                )
                assert created.status_code == 201, created.text
                vendor_id = created.json()["id"]
                listed = await client.get("/api/vendors", headers=_headers(owner))
                assert listed.status_code == 200, listed.text
                detail = await client.get(f"/api/vendors/{vendor_id}", headers=_headers(owner))
                assert detail.status_code == 200, detail.text
                audit = await client.get("/api/audit", headers=_headers(owner))
                assert audit.status_code == 200, audit.text
                actions = {item["action"] for item in audit.json()["items"]}
                assert {"auth.dev_login", "vendor.created"} <= actions
                return owner, vendor_id

        owner, vendor_id = asyncio.run(exercise())
        workspace_id = owner["workspace"]["id"]
        rls_engine, cleanup_rls = _make_non_superuser_engine(database_url)
        with rls_engine.connect() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"), {"workspace_id": workspace_id})
            access_count = connection.execute(
                text(
                    "SELECT count(*) FROM data_access_logs "
                    "WHERE workspace_id = :workspace_id AND artifact_id = :artifact_id"
                ),
                {"workspace_id": workspace_id, "artifact_id": vendor_id},
            ).scalar_one()
            assert access_count >= 2
            before = connection.execute(
                text("SELECT count(*) FROM audit_logs WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            ).scalar_one()
            connection.execute(text("DELETE FROM audit_logs WHERE workspace_id = :workspace_id"), {"workspace_id": workspace_id})
            after = connection.execute(
                text("SELECT count(*) FROM audit_logs WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            ).scalar_one()
            assert after == before
            connection.rollback()
    finally:
        if cleanup_rls:
            cleanup_rls()
