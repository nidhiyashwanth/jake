import asyncio
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


COI_WITH_REPAIRABLE_FAILURE = b"""Named Insured: Acme Mechanical LLC
Certificate Holder:
GL Occurrence Limit: $2,000,000
Policy Expiry: 2099-12-31
Additional Insured: Yes
Waiver of Subrogation: Yes
"""


def _require_postgres() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("Set DATABASE_URL to a reachable PostgreSQL 16 database for integration tests")
    if "sqlite" in database_url.lower() or not database_url.lower().startswith("postgresql"):
        pytest.fail("API integration tests require PostgreSQL; SQLite is not an accepted substitute")
    return database_url


def _migrate(database_url: str) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.mark.integration
def test_api_flow_persists_review_correction_status_history_and_ledger() -> None:
    database_url = _require_postgres()
    _migrate(database_url)

    from app.main import app

    engine = create_engine(database_url, pool_pre_ping=True)
    vendor_id: str | None = None
    try:
        async def exercise() -> None:
            nonlocal vendor_id
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                vendor_response = await client.post(
                    "/api/vendors",
                    json={"legal_name": f"Acme Mechanical Integration {uuid4().hex[:8]}"},
                )
                assert vendor_response.status_code == 201, vendor_response.text
                vendor = vendor_response.json()
                vendor_id = vendor["id"]

                # Match the vendor name in the fixture to the created vendor so only
                # the certificate-holder rule remains open for human correction.
                vendor_name = vendor["legal_name"]
                content = COI_WITH_REPAIRABLE_FAILURE.replace(b"Acme Mechanical LLC", vendor_name.encode())
                upload = await client.post(
                    f"/api/vendors/{vendor_id}/documents",
                    files={"file": ("integration-coi.txt", content, "text/plain")},
                    data={"doc_type": "COI"},
                )
                assert upload.status_code == 201, upload.text
                document_id = upload.json()["id"]

                first = await client.post(f"/api/documents/{document_id}/verify")
                assert first.status_code == 200, first.text
                assert first.json()["status"]["status"] == "needs_review"
                assert first.json()["status"]["failing_requirements"] == ["certificate_holder_match"]

                reviews = await client.get("/api/reviews")
                assert reviews.status_code == 200, reviews.text
                review = next(item for item in reviews.json()["items"] if item["vendor_id"] == vendor_id)
                corrected = await client.patch(
                    f"/api/reviews/{review['id']}",
                    json={"field": "certificate_holder", "value": "Northwind Construction LLC", "reason_code": "SOURCE_TEXT_CORRECTION", "note": "Confirmed against the source certificate."},
                )
                assert corrected.status_code == 200, corrected.text
                assert corrected.json()["status"]["status"] == "compliant"

                status = await client.get(f"/api/vendors/{vendor_id}/status")
                ledger = await client.get(f"/api/vendors/{vendor_id}/ledger")
                assert status.status_code == 200
                assert len(status.json()["history"]) >= 2
                assert ledger.status_code == 200
                event_types = [item["event_type"] for item in ledger.json()["items"]]
                assert {"document_uploaded", "verification_completed", "review_correction_applied"} <= set(event_types)

        asyncio.run(exercise())
    finally:
        if vendor_id:
            with engine.begin() as connection:
                for table in ("audit_events", "compliance_status", "review_tasks", "compliance_checks", "compliance_documents"):
                    connection.execute(text(f"DELETE FROM {table} WHERE vendor_id = :vendor_id"), {"vendor_id": vendor_id})
                connection.execute(text("DELETE FROM vendors WHERE id = :vendor_id"), {"vendor_id": vendor_id})
        engine.dispose()
