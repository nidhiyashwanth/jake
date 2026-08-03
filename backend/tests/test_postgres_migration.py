import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


REQUIRED_TABLES = {
    "vendors",
    "compliance_documents",
    "compliance_checks",
    "review_tasks",
    "compliance_status",
    "audit_events",
}


@pytest.mark.integration
def test_alembic_creates_required_postgres_schema() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("Set DATABASE_URL to a reachable PostgreSQL 16 database for integration tests")
    if "sqlite" in database_url.lower() or not database_url.lower().startswith("postgresql"):
        pytest.fail("Integration tests require PostgreSQL; SQLite is not an accepted substitute")

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            assert REQUIRED_TABLES <= set(inspect(connection).get_table_names())
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
