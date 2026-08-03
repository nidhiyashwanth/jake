import asyncio
import os
from pathlib import Path
import secrets
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url

from app.services.discovery import (
    FORMULA_VERSION,
    REQUIRED_BASELINE_METRICS,
    baseline_questions,
    build_draft_graph,
    canonical_hash,
    canonical_json,
    normalize_metrics,
)


def test_canonical_hash_is_order_independent_and_questions_are_explicit() -> None:
    first = {"b": 2, "a": {"z": True, "y": [1, 2]}}
    second = {"a": {"y": [1, 2], "z": True}, "b": 2}
    assert canonical_json(first) == canonical_json(second)
    assert canonical_hash(first) == canonical_hash(second)

    metrics = normalize_metrics({"monthly volume": 10, "error_rate": 5})
    assert metrics["volume_per_month"]["unit"] == "instances/month"
    assert metrics["error_rate_pct"]["value"] == 5
    questions = baseline_questions(metrics)
    assert {item["key"] for item in questions if item["answered"]} == {"volume_per_month", "error_rate_pct"}
    assert all(item["editable"] for item in questions)


def test_sop_draft_is_reviewable_and_never_publishable() -> None:
    class ProcessStub:
        trigger_json = {"type": "email"}
        decisions_json = ["Is the document complete?"]
        outputs_json = ["Verified record"]
        exceptions_json = ["Missing certificate"]

    graph, exceptions = build_draft_graph(
        ProcessStub(),
        "Receive the document\nCheck whether the certificate is complete\nIf missing, escalate for manual review",
    )
    assert len(graph["nodes"]) == 3
    assert len(graph["edges"]) == 2
    assert graph["publishable"] is False
    assert any("Missing certificate" in item["description"] for item in exceptions)
    assert any("manual review" in item["description"] for item in exceptions)


def _require_postgres() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("Set DATABASE_URL to a reachable PostgreSQL 16 database for integration tests")
    if "sqlite" in database_url.lower() or not database_url.lower().startswith("postgresql"):
        pytest.fail("D-01 integration tests require PostgreSQL; SQLite is not an accepted substitute")
    return database_url


def _migrate(database_url: str) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


async def _login(client: httpx.AsyncClient, *, organization: str, workspace: str, email: str, name: str) -> dict:
    response = await client.post(
        "/api/auth/dev-login",
        json={
            "email": email,
            "name": name,
            "organization_name": organization,
            "workspace_name": workspace,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(login: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {login['access_token']}"}


def _make_non_superuser_engine(database_url: str):
    role = f"d01_rls_{secrets.token_hex(8)}"
    password = secrets.token_hex(24)
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.exec_driver_sql(
            f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD \'{password}\''
        )
        for table in (
            "processes",
            "process_steps",
            "process_interviews",
            "baselines",
            "baseline_metrics",
            "opportunity_scores",
        ):
            connection.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO "{role}"')
    admin_engine.dispose()
    rls_url = make_url(database_url).set(username=role, password=password)
    rls_engine = create_engine(rls_url, pool_pre_ping=True)

    def cleanup() -> None:
        rls_engine.dispose()
        cleanup_engine = create_engine(database_url, pool_pre_ping=True)
        with cleanup_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        cleanup_engine.dispose()

    return rls_engine, cleanup


def _complete_metrics() -> dict[str, float]:
    return {
        "volume_per_month": 1000,
        "minutes_p50": 30,
        "minutes_p90": 75,
        "fully_loaded_cost_per_hour": 60,
        "error_rate_pct": 5,
        "cost_per_error": 200,
        "rework_rate_pct": 10,
        "cycle_time_hours": 18,
        "headcount_touching": 4,
        "peak_backlog": 80,
        "chase_volume_per_month": 120,
        "lapse_incidents_per_month": 2,
        "audit_prep_hours_per_month": 16,
    }


@pytest.mark.integration
def test_d01_discovery_signature_scoring_tenancy_and_immutability() -> None:
    database_url = _require_postgres()
    _migrate(database_url)
    from app.main import app

    suffix = uuid4().hex[:10]
    organization = f"D01 Organization {suffix}"
    workspace = f"D01 Workspace {suffix}"
    process_id: str | None = None
    baseline_ids: list[str] = []
    score_id: str | None = None
    owner_workspace_id: str | None = None
    other_workspace_id: str | None = None
    engine = create_engine(database_url, pool_pre_ping=True)
    rls_engine = None
    cleanup_rls = None
    try:
        async def exercise() -> None:
            nonlocal process_id, score_id, owner_workspace_id, other_workspace_id
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                owner = await _login(
                    client,
                    organization=organization,
                    workspace=workspace,
                    email=f"owner-{suffix}@example.invalid",
                    name="Discovery Owner",
                )
                headers = _headers(owner)
                owner_workspace_id = owner["workspace"]["id"]
                process_response = await client.post(
                    "/api/processes",
                    headers=headers,
                    json={
                        "name": f"COI intake {suffix}",
                        "department": "Operations",
                        "system_of_record": "Compliance spreadsheet",
                        "trigger": {"type": "email", "description": "A broker document arrives"},
                        "inputs": ["COI PDF", "vendor record"],
                        "steps": [
                            {"description": "Open the certificate", "system": "Inbox", "minutes_p50": 10, "minutes_p90": 20},
                            {"description": "Check coverage and expiry", "system": "Spreadsheet", "minutes_p50": 20, "minutes_p90": 55, "is_decision": True},
                        ],
                        "decisions": ["Is coverage sufficient?"],
                        "exceptions": ["Missing additional insured endorsement"],
                        "approvals": ["Compliance manager approves exceptions"],
                        "outputs": ["Verified vendor record"],
                        "failure_modes": ["Expired policy is not escalated"],
                    },
                )
                assert process_response.status_code == 201, process_response.text
                process = process_response.json()
                process_id = process["id"]
                assert len(process["steps"]) == 2

                interview_response = await client.post(
                    f"/api/processes/{process_id}/interviews",
                    headers=headers,
                    json={
                        "source_type": "transcript",
                        "content": "Receive the document\nCheck whether the certificate is complete\nIf missing, escalate for manual review",
                    },
                )
                assert interview_response.status_code == 201, interview_response.text
                interview = interview_response.json()
                assert interview["publishable"] is False
                assert interview["draft_graph"]["nodes"]
                assert interview["baseline_questions"]
                patch_interview = await client.patch(
                    f"/api/process-interviews/{interview['id']}",
                    headers=headers,
                    json={"exception_list": [{"description": "Human-edited exception", "editable": True}]},
                )
                assert patch_interview.status_code == 200, patch_interview.text
                assert patch_interview.json()["exception_list"][0]["description"] == "Human-edited exception"

                baseline_response = await client.post(
                    f"/api/processes/{process_id}/baselines",
                    headers=headers,
                    json={"metrics": _complete_metrics(), "notes": "Sponsor review draft"},
                )
                assert baseline_response.status_code == 201, baseline_response.text
                baseline = baseline_response.json()
                baseline_ids.append(baseline["id"])
                assert baseline["status"] == "draft"
                assert set(REQUIRED_BASELINE_METRICS) <= set(baseline["metrics"])

                signed_response = await client.post(
                    f"/api/baselines/{baseline['id']}/sign",
                    headers=headers,
                    json={"signature_note": "Sponsor approved the captured baseline"},
                )
                assert signed_response.status_code == 200, signed_response.text
                signed = signed_response.json()
                assert signed["status"] == "signed"
                assert signed["signed_by"]["email"] == owner["user"]["email"]
                assert len(signed["canonical_hash"]) == 64
                assert signed["signed_at"]
                assert signed["immutable"] is True

                edited_signed = await client.patch(
                    f"/api/baselines/{baseline['id']}",
                    headers=headers,
                    json={"notes": "This must not change"},
                )
                assert edited_signed.status_code == 409
                assert edited_signed.json()["error"]["code"] == "BASELINE_IMMUTABLE"

                export_response = await client.get(f"/api/baselines/{baseline['id']}/export", headers=headers)
                assert export_response.status_code == 200, export_response.text
                assert export_response.json()["export_format"] == "ledger.baseline.v1"

                score_response = await client.post(
                    f"/api/baselines/{baseline['id']}/score",
                    headers=headers,
                    json={
                        "structure_score": 0.8,
                        "rule_clarity_score": 0.7,
                        "data_availability_score": 0.9,
                        "exception_rate": 0.1,
                        "confidence": 0.8,
                        "effort_weeks": 4,
                        "risk_multiplier": 1.5,
                        "review_rate": 0.2,
                        "review_minutes": 5,
                        "model_cost_annual": 10000,
                        "infra_cost_annual": 5000,
                    },
                )
                assert score_response.status_code == 201, score_response.text
                score = score_response.json()
                score_id = score["id"]
                assert score["formula_version"] == FORMULA_VERSION
                assert score["annual_cost"] == pytest.approx(480000)
                assert score["automatable_pct"] == pytest.approx(0.81)
                assert score["projected_savings"] == pytest.approx(361800)
                assert score["priority_score"] == pytest.approx(48240)
                assert score["component_breakdown"]["annual_cost_components"]["labor"] == pytest.approx(360000)
                assert score["input_provenance"]["structure_score"]["source"] == "score_request"

                second_baseline_response = await client.post(
                    f"/api/processes/{process_id}/baselines",
                    headers=headers,
                    json={"metrics": _complete_metrics(), "supersedes_baseline_id": baseline["id"]},
                )
                assert second_baseline_response.status_code == 201, second_baseline_response.text
                second_baseline = second_baseline_response.json()
                baseline_ids.append(second_baseline["id"])
                assert second_baseline["version"] == 2
                signed_second_response = await client.post(
                    f"/api/baselines/{second_baseline['id']}/sign", headers=headers
                )
                assert signed_second_response.status_code == 200, signed_second_response.text
                old_after_supersession = await client.get(f"/api/baselines/{baseline['id']}", headers=headers)
                assert old_after_supersession.status_code == 200
                assert old_after_supersession.json()["status"] == "superseded"
                assert old_after_supersession.json()["canonical_hash"] == signed["canonical_hash"]

                invited = await client.post(
                    f"/api/workspaces/{owner['workspace']['id']}/members",
                    headers=headers,
                    json={
                        "email": f"builder-{suffix}@example.invalid",
                        "name": "Discovery Builder",
                        "role": "builder",
                    },
                )
                assert invited.status_code == 201, invited.text
                builder = await _login(
                    client,
                    organization=organization,
                    workspace=workspace,
                    email=f"builder-{suffix}@example.invalid",
                    name="Discovery Builder",
                )
                builder_sign = await client.post(
                    f"/api/baselines/{second_baseline['id']}/sign",
                    headers=_headers(builder),
                )
                assert builder_sign.status_code == 403, builder_sign.text
                assert builder_sign.json()["error"]["code"] == "AUTHORIZATION_DENIED"

                other = await _login(
                    client,
                    organization=f"Other Organization {suffix}",
                    workspace=f"Other Workspace {suffix}",
                    email=f"other-{suffix}@example.invalid",
                    name="Other User",
                )
                other_workspace_id = other["workspace"]["id"]
                hidden = await client.get(f"/api/processes/{process_id}", headers=_headers(other))
                assert hidden.status_code == 404, hidden.text
                audit = await client.get("/api/audit", headers=headers)
                assert audit.status_code == 200, audit.text
                actions = {item["action"] for item in audit.json()["items"]}
                assert {
                    "discovery.process.created",
                    "discovery.interview.draft_created",
                    "discovery.interview.draft_updated",
                    "discovery.baseline.created",
                    "discovery.baseline.signed",
                    "discovery.baseline.exported",
                    "discovery.opportunity_scored",
                    "authorization.denied",
                } <= actions
                other_audit = await client.get("/api/audit", headers=_headers(other))
                assert other_audit.status_code == 200, other_audit.text
                assert "data.access_denied" in {item["action"] for item in other_audit.json()["items"]}

        asyncio.run(exercise())

        rls_engine, cleanup_rls = _make_non_superuser_engine(database_url)
        assert owner_workspace_id is not None
        assert other_workspace_id is not None
        with rls_engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": owner_workspace_id},
            )
            assert connection.execute(
                text("SELECT count(*) FROM processes WHERE id = :process_id"), {"process_id": process_id}
            ).scalar_one() == 1
            connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": other_workspace_id},
            )
            assert connection.execute(
                text("SELECT count(*) FROM processes WHERE id = :process_id"), {"process_id": process_id}
            ).scalar_one() == 0
            connection.rollback()

        # Triggers, rather than only the API guard, reject mutation of a signed row.
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(SQLAlchemyError):
                    connection.execute(
                        text("UPDATE baselines SET notes = 'tamper' WHERE id = :baseline_id"),
                        {"baseline_id": baseline_ids[0]},
                    )
            finally:
                transaction.rollback()
    finally:
        # Keep this test's tenant isolated but remove its D-01 rows when possible.
        if cleanup_rls:
            cleanup_rls()
        if process_id:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE baseline_metrics DISABLE TRIGGER baseline_metrics_signed_immutable"))
                connection.execute(text("ALTER TABLE baselines DISABLE TRIGGER baselines_signed_immutable"))
                if score_id:
                    connection.execute(text("DELETE FROM opportunity_scores WHERE id = :id"), {"id": score_id})
                connection.execute(text("DELETE FROM opportunity_scores WHERE process_id = :process_id"), {"process_id": process_id})
                connection.execute(text("DELETE FROM baseline_metrics WHERE baseline_id IN (SELECT id FROM baselines WHERE process_id = :process_id)"), {"process_id": process_id})
                connection.execute(text("DELETE FROM baselines WHERE process_id = :process_id"), {"process_id": process_id})
                connection.execute(text("DELETE FROM process_interviews WHERE process_id = :process_id"), {"process_id": process_id})
                connection.execute(text("DELETE FROM process_steps WHERE process_id = :process_id"), {"process_id": process_id})
                connection.execute(text("DELETE FROM processes WHERE id = :process_id"), {"process_id": process_id})
                connection.execute(text("DELETE FROM data_access_logs WHERE artifact_id = :process_id"), {"process_id": process_id})
                connection.execute(text("ALTER TABLE baselines ENABLE TRIGGER baselines_signed_immutable"))
                connection.execute(text("ALTER TABLE baseline_metrics ENABLE TRIGGER baseline_metrics_signed_immutable"))
        engine.dispose()
