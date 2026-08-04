from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

_WORKSPACE_SCOPE_SQL = text("SELECT set_config('app.workspace_id', :workspace_id, true)")


@event.listens_for(Session, "after_begin")
def _apply_workspace_scope(session: Session, transaction: object, connection: object) -> None:
    """Reapply the transaction-local RLS context after every transaction begins."""

    workspace_id = session.info.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id:
        connection.execute(_WORKSPACE_SCOPE_SQL, {"workspace_id": workspace_id})


def set_workspace_scope(db: Session, workspace_id: str) -> None:
    """Set the transaction-local PostgreSQL RLS context for this request."""

    db.info["workspace_id"] = workspace_id
    db.execute(_WORKSPACE_SCOPE_SQL, {"workspace_id": workspace_id})


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
