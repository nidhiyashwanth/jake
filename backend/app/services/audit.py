from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, DataAccessLog, new_id


def append_audit_log(
    db: Session,
    *,
    action: str,
    target_type: str,
    target_id: str,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Stage an append-only governance event without committing the caller's transaction."""

    event = AuditLog(
        id=new_id(),
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_json=before,
        after_json=after,
        ip_address=ip_address,
    )
    db.add(event)
    return event


def append_data_access_log(
    db: Session,
    *,
    workspace_id: str,
    artifact_id: str,
    resource_type: str,
    purpose: str,
    actor_id: str | None = None,
) -> DataAccessLog:
    event = DataAccessLog(
        id=new_id(),
        workspace_id=workspace_id,
        actor_id=actor_id,
        artifact_id=artifact_id,
        resource_type=resource_type,
        purpose=purpose,
    )
    db.add(event)
    return event
