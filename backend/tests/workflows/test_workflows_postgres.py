import asyncio
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("Set DATABASE_URL to a reachable PostgreSQL 16 database for workflow integration tests")
    if "sqlite" in value.lower() or not value.lower().startswith("postgresql"):
        pytest.fail("Workflow integration tests require PostgreSQL; SQLite is not an accepted substitute")
    return value


def _migrate(database_url: str) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    migration_url = os.environ.get("DATABASE_ADMIN_URL", database_url)
    config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))
    command.upgrade(config, "head")


async def _login(client: httpx.AsyncClient, suffix: str) -> dict:
    response = await client.post(
        "/api/auth/dev-login",
        json={
            "email": f"w01-owner-{suffix}@example.invalid",
            "name": f"W01 Owner {suffix}",
            "organization_name": f"W01 Organization {suffix}",
            "workspace_name": f"W01 Workspace {suffix}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(login: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {login['access_token']}"}


def _workflow_nodes(prompt_key: str, model_key: str) -> list[dict]:
    return [
        {"key": "trigger", "type": "trigger", "label": "Document received", "config": {"event": "document.received"}},
        {"key": "fetch_doc", "type": "fetch", "label": "Fetch document", "config": {"input": "trigger", "source": "upload", "resource": "document"}},
        {"key": "parse_doc", "type": "parse", "label": "Parse document", "config": {"input": "fetch_doc", "schema": {"type": "object"}}},
        {
            "key": "llm_extract",
            "type": "llm",
            "label": "Extract fields",
            "config": {
                "input": "parse_doc",
                "prompt_key": prompt_key,
                "model_config_key": model_key,
                "output_schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            },
        },
        {"key": "approve", "type": "approve", "label": "Human approval", "config": {"input": "llm_extract", "reason": "Review result"}},
    ]


def _workflow_edges() -> list[dict]:
    return [
        {"from_node": "trigger", "to_node": "fetch_doc"},
        {"from_node": "fetch_doc", "to_node": "parse_doc"},
        {"from_node": "parse_doc", "to_node": "llm_extract"},
        {"from_node": "llm_extract", "to_node": "approve"},
    ]


@pytest.mark.integration
def test_workflow_form_edit_graph_publish_gate_and_database_immutability() -> None:
    database_url = _database_url()
    _migrate(database_url)
    from app.main import app

    suffix = uuid4().hex[:10]

    async def exercise() -> tuple[dict, dict, dict, dict]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            owner = await _login(client, suffix)
            headers = _headers(owner)
            prompt = await client.post(
                "/api/prompts",
                headers=headers,
                json={
                    "key": f"w01.prompt.{suffix}",
                    "body": "Extract the compliance fields as JSON.",
                    "variables": ["document"],
                    "output_schema": {"type": "object", "properties": {"status": {"type": "string"}}},
                },
            )
            assert prompt.status_code == 201, prompt.text
            model = await client.post(
                "/api/model-configs",
                headers=headers,
                json={"key": f"w01.model.{suffix}", "provider": "test-provider", "model_id": "structured-v1", "params": {"temperature": 0}},
            )
            assert model.status_code == 201, model.text
            prompt_key = prompt.json()["key"]
            model_key = model.json()["key"]
            created = await client.post(
                "/api/workflows",
                headers=headers,
                json={"name": f"COI workflow {suffix}", "nodes": _workflow_nodes(prompt_key, model_key), "edges": _workflow_edges()},
            )
            assert created.status_code == 201, created.text
            workflow = created.json()["workflow"]
            version = created.json()["version"]
            assert created.json()["validation"]["valid"] is True
            assert version["status"] == "draft"
            assert version["definition_hash"]

            graph = await client.get(f"/api/workflows/{workflow['id']}/versions/1/graph", headers=headers)
            assert graph.status_code == 200, graph.text
            assert graph.json()["read_only"] is True
            assert {node["id"] for node in graph.json()["nodes"]} == {node["key"] for node in _workflow_nodes(prompt_key, model_key)}
            assert any(edge["source"] == "trigger" and edge["target"] == "fetch_doc" for edge in graph.json()["edges"])

            blocked = await client.post(f"/api/workflows/{workflow['id']}/versions/1/publish", headers=headers)
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["error"]["code"] == "EVALUATION_REQUIRED"
            assert blocked.json()["error"]["details"]["failure_reasons"]

            failed_eval = await client.post(
                f"/api/workflows/{workflow['id']}/versions/1/evaluations",
                headers=headers,
                json={"definition_hash": version["definition_hash"], "passed": False, "failure_reasons": ["false-auto rate exceeded"], "metrics": {"false_auto": 0.08}, "evaluator": "e01-fixture"},
            )
            assert failed_eval.status_code == 201, failed_eval.text
            blocked_again = await client.post(f"/api/workflows/{workflow['id']}/versions/1/publish", headers=headers)
            assert blocked_again.status_code == 409, blocked_again.text
            assert blocked_again.json()["error"]["code"] == "EVALUATION_FAILED"
            assert blocked_again.json()["error"]["details"]["failure_reasons"] == ["false-auto rate exceeded"]

            passed_eval = await client.post(
                f"/api/workflows/{workflow['id']}/versions/1/evaluations",
                headers=headers,
                json={"definition_hash": version["definition_hash"], "passed": True, "failure_reasons": [], "metrics": {"false_auto": 0.01}, "evaluator": "e01-fixture"},
            )
            assert passed_eval.status_code == 201, passed_eval.text
            published = await client.post(f"/api/workflows/{workflow['id']}/versions/1/publish", headers=headers)
            assert published.status_code == 200, published.text
            assert published.json()["version"]["status"] == "published"
            assert published.json()["version"]["immutable_hash"] == version["definition_hash"]

            edit_published = await client.patch(
                f"/api/workflows/{workflow['id']}/versions/1",
                headers=headers,
                json={"nodes": _workflow_nodes(prompt_key, model_key)},
            )
            assert edit_published.status_code == 409, edit_published.text

            draft = await client.post(
                f"/api/workflows/{workflow['id']}/versions",
                headers=headers,
                json={"source_version": 1},
            )
            assert draft.status_code == 201, draft.text
            draft_version = draft.json()["version"]
            assert draft_version["version"] == 2
            cyclic_edges = _workflow_edges() + [{"from_node": "approve", "to_node": "trigger"}]
            cyclic = await client.patch(
                f"/api/workflows/{workflow['id']}/versions/2",
                headers=headers,
                json={"edges": cyclic_edges},
            )
            assert cyclic.status_code == 200, cyclic.text
            validation = await client.post(f"/api/workflows/{workflow['id']}/versions/2/validate", headers=headers)
            assert validation.status_code == 200, validation.text
            assert validation.json()["valid"] is False
            assert any(issue["code"] == "DAG_CYCLE" for issue in validation.json()["issues"])
            return owner, workflow, version, draft_version

    owner, workflow, version, draft_version = asyncio.run(exercise())
    engine = create_engine(os.environ.get("DATABASE_ADMIN_URL", database_url), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            published_status = connection.execute(
                text("SELECT status FROM workflow_versions WHERE id = :id"), {"id": version["id"]}
            ).scalar_one()
            assert published_status == "published"
        with pytest.raises(Exception, match="published workflow versions are immutable"):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE workflow_versions SET spec_json = spec_json WHERE id = :id"), {"id": version["id"]}
                )
        with pytest.raises(Exception, match="children of published workflow versions are immutable"):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE workflow_nodes SET label = label WHERE workflow_version_id = :id"), {"id": version["id"]}
                )
        with pytest.raises(Exception, match="workflow evaluation results are immutable"):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE workflow_evaluation_results SET metrics_json = metrics_json WHERE workflow_version_id = :id"),
                    {"id": version["id"]},
                )
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM workflow_evaluation_results WHERE workflow_version_id = :id"),
                {"id": version["id"]},
            ).scalar_one() == 2
            assert connection.execute(
                text("SELECT definition_hash FROM workflow_evaluation_results WHERE workflow_version_id = :id ORDER BY evaluated_at LIMIT 1"),
                {"id": version["id"]},
            ).scalar_one() == version["definition_hash"]
    finally:
        engine.dispose()

    async def cross_workspace() -> None:
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            other = await _login(client, f"other-{uuid4().hex[:8]}")
            hidden = await client.get(f"/api/workflows/{workflow['id']}", headers=_headers(other))
            assert hidden.status_code == 404, hidden.text

    asyncio.run(cross_workspace())
