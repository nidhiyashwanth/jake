from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def set_workspace_scope(db: Session, workspace_id: str) -> None:
    """Set the transaction-local PostgreSQL RLS context for this request."""

    db.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"), {"workspace_id": workspace_id})
    db.info["workspace_id"] = workspace_id


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
