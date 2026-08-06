"""CFO-facing value ledger, drill-down, and audit-pack exports."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.services.audit import append_audit_log, append_data_access_log
from app.services.authorization import authorize
from app.services.tenancy import current_context, get_scoped_db
from app.services.value_ledger import (
    csv_value_export,
    event_projection,
    pdf_value_export,
    rollup_value_events,
)


router = APIRouter(prefix="/api/value", tags=["value-ledger"])
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _validate_cost(value: float) -> float:
    if value < 0 or value > 100_000_000:
        raise DomainError("INVALID_IMPLEMENTATION_COST", "implementation_cost_usd must be between 0 and 100000000", 422)
    return value


def _rollup(
    db: Session,
    *,
    period_start: date | None,
    period_end: date | None,
    workflow_version_id: str | None,
    baseline_id: str | None,
    implementation_cost_usd: float,
) -> tuple[Any, Any]:
    if period_start and period_end and period_start > period_end:
        raise DomainError("INVALID_VALUE_PERIOD", "period_start cannot be after period_end", 422)
    return rollup_value_events(
        db,
        workspace_id=current_context(db).workspace_id,
        period_start=period_start,
        period_end=period_end,
        workflow_version_id=workflow_version_id,
        baseline_id=baseline_id,
        implementation_cost_usd=_validate_cost(implementation_cost_usd),
    )


def _record_read(db: Session, *, artifact_id: str, resource_type: str, purpose: str) -> None:
    context = current_context(db)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=artifact_id,
        resource_type=resource_type,
        purpose=purpose,
    )


@router.get("/rollup")
def value_rollup(
    db: ScopedDb,
    period_start: date | None = None,
    period_end: date | None = None,
    workflow_version_id: str | None = None,
    baseline_id: str | None = None,
    implementation_cost_usd: float = 0,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "value.read", target_type="value_rollup", target_id=context.workspace_id)
    rollup, _ = _rollup(
        db,
        period_start=period_start,
        period_end=period_end,
        workflow_version_id=workflow_version_id,
        baseline_id=baseline_id,
        implementation_cost_usd=implementation_cost_usd,
    )
    _record_read(db, artifact_id=context.workspace_id, resource_type="value_rollup", purpose="value_dashboard_read")
    db.commit()
    return rollup


@router.get("/events")
def value_events(
    db: ScopedDb,
    kind: str | None = None,
    execution_id: str | None = None,
    workflow_version_id: str | None = None,
    baseline_id: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "value.read", target_type="value_events", target_id=context.workspace_id)
    _, events = _rollup(
        db,
        period_start=period_start,
        period_end=period_end,
        workflow_version_id=workflow_version_id,
        baseline_id=baseline_id,
        implementation_cost_usd=0,
    )
    if kind:
        events = [event for event in events if event.kind == kind]
    if execution_id:
        events = [event for event in events if event.execution_id == execution_id]
    bounded_limit = max(1, min(limit, 200))
    _record_read(db, artifact_id=context.workspace_id, resource_type="value_events", purpose="value_event_list_read")
    db.commit()
    return {"items": [event_projection(event) for event in events[-bounded_limit:][::-1]], "count": len(events), "limit": bounded_limit}


@router.get("/events/{event_id}")
def value_event_detail(event_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "value.read", target_type="value_event", target_id=event_id)
    _, events = _rollup(db, period_start=None, period_end=None, workflow_version_id=None, baseline_id=None, implementation_cost_usd=0)
    event = next((item for item in events if item.id == event_id), None)
    if event is None:
        raise DomainError("VALUE_EVENT_NOT_FOUND", "The value event was not found in this workspace", 404)
    _record_read(db, artifact_id=event.id, resource_type="value_event", purpose="value_event_detail_read")
    db.commit()
    return {"event": event_projection(event)}


@router.get("/drilldown")
def value_drilldown(
    db: ScopedDb,
    metric: str = "net_dollars",
    period_start: date | None = None,
    period_end: date | None = None,
    workflow_version_id: str | None = None,
    baseline_id: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "value.read", target_type="value_drilldown", target_id=metric)
    if metric not in {"volume", "hours_saved", "net_dollars", "costs", "benefits", "cycle_time"}:
        raise DomainError("INVALID_VALUE_METRIC", "metric must be volume, hours_saved, net_dollars, costs, benefits, or cycle_time", 422)
    _, events = _rollup(
        db,
        period_start=period_start,
        period_end=period_end,
        workflow_version_id=workflow_version_id,
        baseline_id=baseline_id,
        implementation_cost_usd=0,
    )
    selected = []
    for event in events:
        if metric == "volume" and event.kind == "unit_processed":
            selected.append(event)
        elif metric == "hours_saved" and event.kind == "time_saved":
            selected.append(event)
        elif metric == "cycle_time" and event.kind == "cycle_time_reduced":
            selected.append(event)
        elif metric == "costs" and event.dollar_value < 0:
            selected.append(event)
        elif metric == "benefits" and event.dollar_value > 0:
            selected.append(event)
        elif metric == "net_dollars":
            selected.append(event)
    bounded_limit = max(1, min(limit, 500))
    _record_read(db, artifact_id=context.workspace_id, resource_type="value_drilldown", purpose=f"value_{metric}_drilldown")
    db.commit()
    return {"metric": metric, "items": [event_projection(event) for event in selected[-bounded_limit:][::-1]], "count": len(selected)}


@router.get("/exports/value.csv")
def export_value_csv(
    db: ScopedDb,
    period_start: date | None = None,
    period_end: date | None = None,
    workflow_version_id: str | None = None,
    baseline_id: str | None = None,
    implementation_cost_usd: float = 0,
) -> Response:
    context = current_context(db)
    authorize(db, context, "value.export", target_type="value_export", target_id="csv")
    rollup, events = _rollup(
        db,
        period_start=period_start,
        period_end=period_end,
        workflow_version_id=workflow_version_id,
        baseline_id=baseline_id,
        implementation_cost_usd=implementation_cost_usd,
    )
    content = csv_value_export(rollup, events)
    append_audit_log(
        db,
        action="value.exported",
        target_type="value_export",
        target_id=context.workspace_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"format": "csv", "event_count": len(events), "reconciles": rollup["reconciliation"]["reconciles"]},
    )
    _record_read(db, artifact_id=context.workspace_id, resource_type="value_export", purpose="value_csv_export")
    db.commit()
    return Response(content=content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=value-realization.csv"})


@router.get("/exports/value.pdf")
def export_value_pdf(
    db: ScopedDb,
    period_start: date | None = None,
    period_end: date | None = None,
    workflow_version_id: str | None = None,
    baseline_id: str | None = None,
    implementation_cost_usd: float = 0,
) -> Response:
    context = current_context(db)
    authorize(db, context, "value.export", target_type="value_export", target_id="pdf")
    rollup, events = _rollup(
        db,
        period_start=period_start,
        period_end=period_end,
        workflow_version_id=workflow_version_id,
        baseline_id=baseline_id,
        implementation_cost_usd=implementation_cost_usd,
    )
    content = pdf_value_export(rollup, events)
    append_audit_log(
        db,
        action="value.exported",
        target_type="value_export",
        target_id=context.workspace_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"format": "pdf", "event_count": len(events), "reconciles": rollup["reconciliation"]["reconciles"]},
    )
    _record_read(db, artifact_id=context.workspace_id, resource_type="value_export", purpose="value_pdf_export")
    db.commit()
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=value-realization.pdf"})
