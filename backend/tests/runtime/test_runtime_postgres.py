"""PostgreSQL integration coverage for the durable execution runtime."""

from __future__ import annotations

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
        pytest.skip("Set DATABASE_URL to a reachable PostgreSQL 16 database for runtime integration tests")
    if "sqlite" in value.lower() or not value.lower().startswith("postgresql"):
        pytest.fail("Runtime integration tests require PostgreSQL; SQLite is not an accepted substitute")
    return value


def _migrate(database_url: str) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _headers(login: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {login['access_token']}",
        "X-Workspace-ID": login["workspace"]["id"],
    }


@pytest.mark.integration
def test_runtime_is_graph_ordered_idempotent_and_replay_safe() -> None:
    database_url = _database_url()
    _migrate(database_url)
    from app.main import app

    suffix = uuid4().hex[:10]

    async def exercise() -> tuple[str, str, str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            login = await client.post(
                "/api/auth/dev-login",
                json={
                    "email": f"runtime-{suffix}@example.invalid",
                    "name": "Runtime owner",
                    "organization_name": f"Runtime org {suffix}",
                    "workspace_name": f"Runtime workspace {suffix}",
                },
            )
            assert login.status_code == 200, login.text
            headers = _headers(login.json())
            workflow = await client.post(
                "/api/workflows",
                headers=headers,
                json={
                    "name": f"Runtime graph {suffix}",
                    "nodes": [
                        {"key": "trigger", "type": "trigger", "label": "Trigger", "config": {"event": "run"}},
                        {
                            "key": "tool",
                            "type": "tool",
                            "label": "Write after approval",
                            "config": {
                                "connector_key": "synthetic.receipts",
                                "tool_key": "synthetic.receipts.write",
                                "write": True,
                                "writes_external": True,
                                "requires_approval": True,
                                "idempotency_key": "runtime-write",
                            },
                        },
                        {"key": "halt", "type": "halt", "label": "Halt", "config": {"reason": "done"}},
                    ],
                    "edges": [
                        {"from_node": "trigger", "to_node": "tool"},
                        {"from_node": "tool", "to_node": "halt"},
                    ],
                },
            )
            assert workflow.status_code == 201, workflow.text
            version = workflow.json()["version"]
            evaluation = await client.post(
                f"/api/workflow-versions/{version['id']}/evaluation-runs",
                headers=headers,
                json={"suite_key": "w01.synthetic.baseline"},
            )
            assert evaluation.status_code == 201, evaluation.text
            published = await client.post(
                f"/api/workflow-versions/{version['id']}/publish",
                headers=headers,
            )
            assert published.status_code == 200, published.text
            assert len(published.json()["version"]["immutable_hash"]) == 64

            request = {
                "workflow_version_id": version["id"],
                "input": {"document_id": f"doc-{suffix}"},
                "idempotency_key": f"run-{suffix}",
            }
            created = await client.post("/api/runtime/executions", headers=headers, json=request)
            assert created.status_code == 201, created.text
            execution = created.json()["execution"]
            execution_id = execution["id"]
            assert [step["node_key"] for step in execution["steps"]] == ["trigger", "tool", "halt"]

            duplicate = await client.post("/api/runtime/executions", headers=headers, json=request)
            assert duplicate.status_code in {200, 201}, duplicate.text
            assert duplicate.json()["idempotent"] is True
            assert duplicate.json()["execution"]["id"] == execution_id

            advanced = await client.post(
                f"/api/runtime/executions/{execution_id}/advance",
                headers=headers,
                json={"max_steps": 50, "worker_id": "pytest-runtime"},
            )
            assert advanced.status_code == 200, advanced.text
            assert advanced.json()["execution"]["status"] == "waiting_human"
            assert [step["status"] for step in advanced.json()["execution"]["steps"]] == [
                "completed",
                "waiting_human",
                "pending",
            ]

            resumed = await client.post(
                f"/api/runtime/executions/{execution_id}/resume",
                headers=headers,
                json={"decision": "approve", "output": {"approved": True}, "note": "pytest"},
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["execution"]["external_write_count"] == 1

            finished = await client.post(
                f"/api/runtime/executions/{execution_id}/advance",
                headers=headers,
                json={"max_steps": 50, "worker_id": "pytest-runtime"},
            )
            assert finished.status_code == 200, finished.text
            assert finished.json()["execution"]["status"] == "halted"
            assert finished.json()["execution"]["external_write_count"] == 1

            replay = await client.post(
                f"/api/runtime/executions/{execution_id}/replay",
                headers=headers,
                json={"idempotency_key": f"replay-{suffix}"},
            )
            assert replay.status_code == 200, replay.text
            assert replay.json()["side_effects"] is False
            assert replay.json()["execution"]["dry_run"] is True
            assert replay.json()["execution"]["external_write_count"] == 0
            return execution_id, login.json()["workspace"]["id"], version["id"]

    execution_id, workspace_id, version_id = asyncio.run(exercise())
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM external_write_receipts WHERE execution_id = :id"),
                {"id": execution_id},
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM outbox_events WHERE execution_id = :id"),
                {"id": execution_id},
            ).scalar_one() >= 1
            assert connection.execute(
                text("SELECT workflow_version_hash FROM executions WHERE id = :id AND workspace_id = :workspace_id"),
                {"id": execution_id, "workspace_id": workspace_id},
            ).scalar_one()
            assert connection.execute(
                text("SELECT count(*) FROM execution_events WHERE execution_id = :id"),
                {"id": execution_id},
            ).scalar_one() >= 5
            assert connection.execute(
                text("SELECT status FROM workflow_versions WHERE id = :id"),
                {"id": version_id},
            ).scalar_one() == "published"
    finally:
        engine.dispose()
