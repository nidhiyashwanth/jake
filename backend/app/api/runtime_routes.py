"""HTTP boundary for durable executions, workers, replay, and outbox evidence."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import DomainError
from app.models import Execution
from app.schemas import (
    RuntimeAdvanceRequest,
    RuntimeExecutionCreate,
    RuntimeOutboxDispatchRequest,
    RuntimeReplayRequest,
    RuntimeResumeRequest,
    RuntimeRetryRequest,
)
from app.services.audit import append_audit_log, append_data_access_log
from app.services.authorization import authorize
from app.services.runtime import (
    advance_execution,
    create_execution,
    dispatch_outbox,
    execution_payload,
    recover_stale_claims,
    replay_execution,
    resume_execution,
    retry_execution,
)
from app.services.tenancy import RequestContext, current_context, get_scoped_db


router = APIRouter(prefix="/api/runtime", tags=["runtime"])
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _execution_or_404(db: Session, workspace_id: str, execution_id: str) -> Execution:
    execution = db.scalar(
        select(Execution).where(
            Execution.id == execution_id,
            Execution.workspace_id == workspace_id,
        )
    )
    if execution is None:
        raise DomainError("EXECUTION_NOT_FOUND", "The execution was not found in this workspace", 404)
    return execution


def _set_correlation(response: Response, correlation_id: str) -> None:
    response.headers["X-Correlation-ID"] = correlation_id


@router.post("/executions", status_code=201)
def create_runtime_execution(
    payload: RuntimeExecutionCreate,
    response: Response,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.create", target_type="workflow_version", target_id=payload.workflow_version_id)
    execution, created = create_execution(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        version_id=payload.workflow_version_id,
        input_json=payload.input,
        idempotency_key=payload.idempotency_key,
        correlation_id=payload.correlation_id,
        max_retries=payload.max_retries,
    )
    append_audit_log(
        db,
        action="execution.created" if created else "execution.idempotent_replay",
        target_type="execution",
        target_id=execution.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"workflow_version_id": execution.workflow_version_id, "correlation_id": execution.correlation_id, "created": created},
    )
    db.commit()
    _set_correlation(response, execution.correlation_id)
    return {"execution": execution_payload(db, execution), "created": created, "idempotent": not created}


@router.get("/executions")
def list_runtime_executions(db: ScopedDb, limit: int = 50, status: str | None = None) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.read")
    limit = max(1, min(limit, 100))
    query = (
        select(Execution)
        .where(Execution.workspace_id == context.workspace_id)
        .order_by(Execution.created_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Execution.status == status)
    items = db.scalars(query).all()
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=context.workspace_id,
        resource_type="executions",
        purpose="execution_list",
    )
    db.commit()
    return {
        "items": [
            {
                "id": item.id,
                "workflow_id": item.workflow_id,
                "workflow_version_id": item.workflow_version_id,
                "workflow_version_hash": item.workflow_version_hash,
                "status": item.status,
                "correlation_id": item.correlation_id,
                "idempotency_key": item.idempotency_key,
                "dry_run": item.dry_run,
                "created_at": item.created_at.isoformat(),
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in items
        ]
    }


@router.get("/executions/{execution_id}")
def get_runtime_execution(execution_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.read", target_type="execution", target_id=execution_id)
    execution = _execution_or_404(db, context.workspace_id, execution_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=execution.id,
        resource_type="execution",
        purpose="execution_read",
    )
    db.commit()
    return {"execution": execution_payload(db, execution)}


@router.post("/executions/{execution_id}/advance")
def advance_runtime_execution(
    execution_id: str,
    payload: RuntimeAdvanceRequest,
    response: Response,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.run", target_type="execution", target_id=execution_id)
    execution = _execution_or_404(db, context.workspace_id, execution_id)
    steps = advance_execution(
        db,
        execution,
        worker_id=payload.worker_id or f"api-worker:{context.user_id}",
        max_steps=payload.max_steps,
    )
    append_audit_log(
        db,
        action="execution.advanced",
        target_type="execution",
        target_id=execution.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"step_count": len(steps), "worker_id": payload.worker_id or context.user_id, "status": execution.status},
    )
    db.commit()
    _set_correlation(response, execution.correlation_id)
    return {"execution": execution_payload(db, execution), "advanced_steps": [step.id for step in steps]}


@router.post("/executions/{execution_id}/retry")
def retry_runtime_execution(
    execution_id: str,
    payload: RuntimeRetryRequest,
    response: Response,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.retry", target_type="execution", target_id=execution_id)
    execution = _execution_or_404(db, context.workspace_id, execution_id)
    step = retry_execution(db, execution, reason=payload.reason, step_id=payload.step_id)
    append_audit_log(
        db,
        action="execution.manual_retry",
        target_type="execution",
        target_id=execution.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"step_id": step.id, "reason": payload.reason},
    )
    db.commit()
    _set_correlation(response, execution.correlation_id)
    return {"execution": execution_payload(db, execution), "retried_step_id": step.id}


@router.post("/executions/{execution_id}/resume")
def resume_runtime_execution(
    execution_id: str,
    payload: RuntimeResumeRequest,
    response: Response,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.run", target_type="execution", target_id=execution_id)
    execution = _execution_or_404(db, context.workspace_id, execution_id)
    step = resume_execution(db, execution, decision=payload.decision, output=payload.output, note=payload.note)
    append_audit_log(
        db,
        action="execution.human_resumed",
        target_type="execution",
        target_id=execution.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"step_id": step.id, "decision": payload.decision},
    )
    db.commit()
    _set_correlation(response, execution.correlation_id)
    return {"execution": execution_payload(db, execution), "resumed_step_id": step.id}


@router.post("/executions/{execution_id}/replay")
def replay_runtime_execution(
    execution_id: str,
    payload: RuntimeReplayRequest,
    response: Response,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.replay", target_type="execution", target_id=execution_id)
    original = _execution_or_404(db, context.workspace_id, execution_id)
    replay = replay_execution(
        db,
        original,
        actor_id=context.user_id,
        idempotency_key=payload.idempotency_key,
        correlation_id=payload.correlation_id,
    )
    append_audit_log(
        db,
        action="execution.replayed",
        target_type="execution",
        target_id=replay.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"replay_of_id": original.id, "side_effects": False, "workflow_version_hash": replay.workflow_version_hash},
    )
    db.commit()
    _set_correlation(response, replay.correlation_id)
    return {"execution": execution_payload(db, replay), "side_effects": False, "replay_of_id": original.id}


@router.post("/workers/recover")
def recover_runtime_worker(db: ScopedDb, lease_seconds: int = 60) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.run", target_type="worker", target_id=context.workspace_id)
    recovered = recover_stale_claims(db, workspace_id=context.workspace_id, lease_seconds=max(1, min(3600, lease_seconds)))
    append_audit_log(
        db,
        action="worker.claims_recovered",
        target_type="worker",
        target_id=context.workspace_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"recovered": recovered, "lease_seconds": lease_seconds},
    )
    db.commit()
    return {"recovered": recovered, "lease_seconds": lease_seconds}


@router.post("/outbox/dispatch")
def dispatch_runtime_outbox(payload: RuntimeOutboxDispatchRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "execution.run", target_type="outbox", target_id=context.workspace_id)
    events = dispatch_outbox(
        db,
        workspace_id=context.workspace_id,
        worker_id=payload.worker_id or f"api-outbox:{context.user_id}",
        limit=payload.limit,
    )
    append_audit_log(
        db,
        action="outbox.dispatched",
        target_type="outbox",
        target_id=context.workspace_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"count": len(events)},
    )
    db.commit()
    return {"dispatched": len(events), "event_ids": [event.id for event in events]}
