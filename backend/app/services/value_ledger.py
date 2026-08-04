"""Append-only value realization events and CFO-facing rollups."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import math
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import DomainError
from app.models import (
    Baseline,
    BaselineMetric,
    Execution,
    ExecutionEvent,
    ExecutionStep,
    ReviewTask,
    ValueEvent,
    WorkflowVersion,
    new_id,
    utc_now,
)
from app.services.observability import redact_untrusted


VALUE_FORMULA_VERSION = "value.v1"
VALUE_KINDS = frozenset(
    {
        "unit_processed",
        "touch_avoided",
        "time_saved",
        "error_prevented",
        "cycle_time_reduced",
        "human_touch_cost",
        "model_cost",
        "infra_cost",
        "rework",
    }
)
VALUE_METHODS = frozenset({"baseline_rate", "measured_ab", "customer_asserted", "sampled_audit"})
VALUE_CONFIDENCE = frozenset({"high", "medium", "low"})
TERMINAL_EXECUTION_STATES = frozenset({"completed", "dead_letter", "failed", "halted"})


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise DomainError("INVALID_VALUE_EVENT", f"{field} must be numeric", 422)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_VALUE_EVENT", f"{field} must be numeric", 422) from exc
    if not math.isfinite(number) or abs(number) >= 1_000_000_000_000:
        raise DomainError("INVALID_VALUE_EVENT", f"{field} must be finite and bounded", 422)
    return number


def append_value_event(
    db: Session,
    *,
    workspace_id: str,
    event_key: str,
    source_artifact_type: str,
    source_artifact_id: str,
    kind: str,
    quantity: float,
    unit: str,
    dollar_value: float,
    method: str,
    confidence: str,
    formula_version: str = VALUE_FORMULA_VERSION,
    execution_id: str | None = None,
    workflow_version_id: str | None = None,
    workflow_version_hash: str | None = None,
    baseline_id: str | None = None,
    baseline_hash: str | None = None,
    review_task_id: str | None = None,
    audit_event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    computed_at: datetime | None = None,
) -> ValueEvent:
    """Append one event, returning the existing row for a repeated idempotency key."""

    if not event_key.strip() or len(event_key) > 240:
        raise DomainError("INVALID_VALUE_EVENT", "event_key must be non-empty and bounded", 422)
    if kind not in VALUE_KINDS:
        raise DomainError("INVALID_VALUE_EVENT", f"Unsupported value event kind: {kind}", 422)
    if method not in VALUE_METHODS:
        raise DomainError("INVALID_VALUE_EVENT", f"Unsupported value event method: {method}", 422)
    if confidence not in VALUE_CONFIDENCE:
        raise DomainError("INVALID_VALUE_EVENT", f"Unsupported value event confidence: {confidence}", 422)
    quantity = _number(quantity, field="quantity")
    dollar_value = _number(dollar_value, field="dollar_value")
    existing = db.scalar(
        select(ValueEvent).where(
            ValueEvent.workspace_id == workspace_id,
            ValueEvent.event_key == event_key,
        )
    )
    if existing is not None:
        return existing
    event = ValueEvent(
        id=new_id(),
        workspace_id=workspace_id,
        event_key=event_key,
        execution_id=execution_id,
        workflow_version_id=workflow_version_id,
        workflow_version_hash=workflow_version_hash,
        baseline_id=baseline_id,
        baseline_hash=baseline_hash,
        review_task_id=review_task_id,
        source_artifact_type=source_artifact_type,
        source_artifact_id=source_artifact_id,
        audit_event_id=audit_event_id,
        kind=kind,
        quantity=quantity,
        unit=unit.strip()[:80] or "unit",
        dollar_value=dollar_value,
        method=method,
        confidence=confidence,
        formula_version=formula_version,
        metadata_json=redact_untrusted(metadata or {}),
        computed_at=computed_at or utc_now(),
    )
    db.add(event)
    db.flush()
    return event


def _metrics(db: Session, baseline: Baseline | None) -> dict[str, float]:
    if baseline is None or baseline.status != "signed":
        return {}
    rows = db.scalars(
        select(BaselineMetric).where(
            BaselineMetric.workspace_id == baseline.workspace_id,
            BaselineMetric.baseline_id == baseline.id,
        )
    ).all()
    return {row.key: float(row.value) for row in rows}


def _percent_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 100 if value > 1 else value


def _baseline_context(db: Session, execution: Execution) -> tuple[WorkflowVersion | None, Baseline | None, dict[str, float]]:
    version = db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.id == execution.workflow_version_id,
            WorkflowVersion.workspace_id == execution.workspace_id,
        )
    )
    baseline = None
    if version and version.baseline_id:
        baseline = db.scalar(
            select(Baseline).where(
                Baseline.id == version.baseline_id,
                Baseline.workspace_id == execution.workspace_id,
            )
        )
    return version, baseline, _metrics(db, baseline)


def _execution_outcome(db: Session, execution: Execution) -> str:
    human_decision = db.scalar(
        select(ExecutionEvent.id).where(
            ExecutionEvent.workspace_id == execution.workspace_id,
            ExecutionEvent.execution_id == execution.id,
            ExecutionEvent.event_type == "human.decision_recorded",
        ).limit(1)
    )
    if human_decision:
        return "reviewed"
    if execution.status in {"halted", "failed", "dead_letter"}:
        return "halted"
    return "auto"


def _elapsed_hours(execution: Execution) -> float | None:
    if execution.started_at is None or execution.completed_at is None:
        return None
    seconds = (execution.completed_at - execution.started_at).total_seconds()
    if seconds <= 0:
        return None
    return seconds / 3600


def ensure_execution_value_events(db: Session, execution: Execution) -> list[ValueEvent]:
    """Materialize deterministic value evidence once a real execution is terminal."""

    if execution.dry_run or execution.replay_of_id or execution.status not in TERMINAL_EXECUTION_STATES:
        return []
    version, baseline, metrics = _baseline_context(db, execution)
    outcome = _execution_outcome(db, execution)
    baseline_id = baseline.id if baseline else None
    baseline_hash = baseline.canonical_hash if baseline else None
    version_id = version.id if version else execution.workflow_version_id
    version_hash = version.immutable_hash or version.definition_hash if version else execution.workflow_version_hash
    actor_id = execution.created_by
    base_metadata = {
        "outcome": outcome,
        "execution_status": execution.status,
        "actor_id": actor_id,
        "department": (execution.input_json or {}).get("department") if isinstance(execution.input_json, dict) else None,
        "baseline_signed": bool(baseline),
    }
    events: list[ValueEvent] = []

    def add(
        *,
        key_suffix: str,
        kind: str,
        quantity: float,
        unit: str,
        dollar_value: float,
        method: str,
        confidence: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        events.append(
            append_value_event(
                db,
                workspace_id=execution.workspace_id,
                event_key=f"execution:{execution.id}:{key_suffix}",
                source_artifact_type="execution",
                source_artifact_id=execution.id,
                execution_id=execution.id,
                workflow_version_id=version_id,
                workflow_version_hash=version_hash,
                baseline_id=baseline_id,
                baseline_hash=baseline_hash,
                kind=kind,
                quantity=quantity,
                unit=unit,
                dollar_value=dollar_value,
                method=method,
                confidence=confidence,
                metadata={**base_metadata, **(metadata or {})},
            )
        )

    add(
        key_suffix="unit-processed",
        kind="unit_processed",
        quantity=1,
        unit="execution",
        dollar_value=0,
        method="measured_ab",
        confidence="high",
    )

    if outcome == "auto":
        minutes = metrics.get("minutes_p50")
        rate = metrics.get("fully_loaded_cost_per_hour")
        if minutes and rate:
            hours = minutes / 60
            add(
                key_suffix="time-saved",
                kind="time_saved",
                quantity=hours,
                unit="hours",
                dollar_value=hours * rate,
                method="baseline_rate",
                confidence="medium",
                metadata={"baseline_minutes_p50": minutes, "hourly_rate": rate},
            )
        add(
            key_suffix="touch-avoided",
            kind="touch_avoided",
            quantity=max(1, metrics.get("headcount_touching", 1)),
            unit="human_touch",
            dollar_value=0,
            method="baseline_rate" if baseline else "measured_ab",
            confidence="medium" if baseline else "low",
            metadata={"valuation_status": "count_only"},
        )

    elapsed = _elapsed_hours(execution)
    baseline_cycle = metrics.get("cycle_time_hours")
    if elapsed is not None and baseline_cycle and baseline_cycle > elapsed:
        add(
            key_suffix="cycle-time-reduced",
            kind="cycle_time_reduced",
            quantity=baseline_cycle - elapsed,
            unit="hours",
            dollar_value=0,
            method="measured_ab",
            confidence="high",
            metadata={"baseline_cycle_time_hours": baseline_cycle, "measured_cycle_time_hours": elapsed},
        )

    model_cost = round(sum(max(0, float(step.cost_usd or 0)) for step in execution.steps), 8)
    if model_cost > 0:
        add(
            key_suffix="model-cost",
            kind="model_cost",
            quantity=model_cost,
            unit="USD",
            dollar_value=-model_cost,
            method="measured_ab",
            confidence="high",
            metadata={"step_count": len(execution.steps)},
        )

    if outcome == "reviewed":
        review_minutes = metrics.get("review_minutes")
        rate = metrics.get("fully_loaded_cost_per_hour")
        if review_minutes and rate:
            review_hours = review_minutes / 60
            add(
                key_suffix="human-touch-cost",
                kind="human_touch_cost",
                quantity=review_hours,
                unit="hours",
                dollar_value=-(review_hours * rate),
                method="baseline_rate",
                confidence="medium",
                metadata={"review_minutes": review_minutes, "hourly_rate": rate},
            )
        else:
            add(
                key_suffix="human-touch-cost",
                kind="human_touch_cost",
                quantity=1,
                unit="review",
                dollar_value=0,
                method="measured_ab",
                confidence="low",
                metadata={"valuation_status": "unpriced_review_touch"},
            )

    infra_cost = float(get_settings().value_infra_cost_per_run_usd or 0)
    if infra_cost > 0:
        add(
            key_suffix="infra-cost",
            kind="infra_cost",
            quantity=infra_cost,
            unit="USD",
            dollar_value=-infra_cost,
            method="measured_ab",
            confidence="medium",
            metadata={"meter": "VALUE_INFRA_COST_PER_RUN_USD"},
        )

    if execution.retry_count > 0:
        minutes = metrics.get("minutes_p50")
        rate = metrics.get("fully_loaded_cost_per_hour")
        rework_value = -(execution.retry_count * minutes / 60 * rate) if minutes and rate else 0
        add(
            key_suffix="rework",
            kind="rework",
            quantity=execution.retry_count,
            unit="retry",
            dollar_value=rework_value,
            method="baseline_rate" if minutes and rate else "measured_ab",
            confidence="medium" if minutes and rate else "low",
            metadata={"retry_count": execution.retry_count, "valuation_status": "priced" if minutes and rate else "count_only"},
        )
    return events


def event_projection(event: ValueEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, ValueEvent):
        item = {
            "id": event.id,
            "event_key": event.event_key,
            "workspace_id": event.workspace_id,
            "execution_id": event.execution_id,
            "workflow_version_id": event.workflow_version_id,
            "workflow_version_hash": event.workflow_version_hash,
            "baseline_id": event.baseline_id,
            "baseline_hash": event.baseline_hash,
            "review_task_id": event.review_task_id,
            "source_artifact_type": event.source_artifact_type,
            "source_artifact_id": event.source_artifact_id,
            "audit_event_id": event.audit_event_id,
            "kind": event.kind,
            "quantity": event.quantity,
            "unit": event.unit,
            "dollar_value": event.dollar_value,
            "method": event.method,
            "confidence": event.confidence,
            "formula_version": event.formula_version,
            "metadata": event.metadata_json or {},
            "computed_at": event.computed_at.isoformat(),
            "created_at": event.created_at.isoformat(),
        }
    else:
        item = dict(event)
        item["metadata"] = item.get("metadata") or item.get("metadata_json") or {}
    links: dict[str, str] = {"event": f"/api/value/events/{item['id']}"}
    if item.get("execution_id"):
        links["execution"] = f"/api/runtime/executions/{item['execution_id']}"
    if item.get("review_task_id"):
        links["review"] = f"/api/reviews/{item['review_task_id']}"
    if item.get("audit_event_id"):
        links["audit"] = f"/api/value/events/{item['id']}#audit-{item['audit_event_id']}"
    item["metadata"] = redact_untrusted(item["metadata"])
    item["links"] = links
    return item


def calculate_value_rollup(
    events: Iterable[dict[str, Any]],
    *,
    baseline_metrics: dict[str, float] | None = None,
    baseline_id: str | None = None,
    baseline_hash: str | None = None,
    implementation_cost_usd: float = 0,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, Any]:
    """Calculate dashboard numbers from event rows; kept pure for reconciliation tests."""

    rows = [dict(row) for row in events]
    metrics = baseline_metrics or {}
    unit_rows = [row for row in rows if row.get("kind") == "unit_processed"]
    ingested = sum(float(row.get("quantity") or 0) for row in unit_rows)
    outcome_counts = {"auto": 0.0, "reviewed": 0.0, "halted": 0.0}
    adoption: dict[tuple[str, str], float] = {}
    for row in unit_rows:
        outcome = (row.get("metadata") or {}).get("outcome")
        if outcome in outcome_counts:
            outcome_counts[outcome] += float(row.get("quantity") or 0)
        metadata = row.get("metadata") or {}
        actor = str(metadata.get("actor_id") or "unknown")
        department = str(metadata.get("department") or "unassigned")
        adoption[(actor, department)] = adoption.get((actor, department), 0) + float(row.get("quantity") or 0)
    auto = outcome_counts["auto"]
    reviewed = outcome_counts["reviewed"]
    halted = outcome_counts["halted"]
    delta = ingested - auto - reviewed - halted
    benefits = sum(max(0, float(row.get("dollar_value") or 0)) for row in rows)
    costs = sum(abs(min(0, float(row.get("dollar_value") or 0))) for row in rows)
    net = sum(float(row.get("dollar_value") or 0) for row in rows)
    completed_units = auto + reviewed
    hours_saved = sum(float(row.get("quantity") or 0) for row in rows if row.get("kind") == "time_saved")
    cycle_rows = [row for row in rows if row.get("kind") == "cycle_time_reduced"]
    measured_cycles = [
        float((row.get("metadata") or {}).get("measured_cycle_time_hours"))
        for row in cycle_rows
        if (row.get("metadata") or {}).get("measured_cycle_time_hours") is not None
    ]
    baseline_cycle = [
        float((row.get("metadata") or {}).get("baseline_cycle_time_hours"))
        for row in cycle_rows
        if (row.get("metadata") or {}).get("baseline_cycle_time_hours") is not None
    ] or ([float(metrics["cycle_time_hours"])] if metrics.get("cycle_time_hours") else [])
    measured_error_count = sum(float(row.get("quantity") or 0) for row in rows if row.get("kind") == "error_prevented")
    implementation_cost = max(0, float(implementation_cost_usd or 0))
    roi = ((net / costs) * 100) if costs > 0 else None
    payback_days = (implementation_cost / net) * max(1, (period_end - period_start).days if period_start and period_end else 30) if implementation_cost > 0 and net > 0 else None
    payback_date = (datetime.now(timezone.utc) + timedelta(days=payback_days)).date().isoformat() if payback_days is not None else None
    orphan_event_count = sum(1 for row in rows if row.get("orphan") is True)
    return {
        "formula_version": VALUE_FORMULA_VERSION,
        "period": {"start": period_start.isoformat() if period_start else None, "end": period_end.isoformat() if period_end else None},
        "baseline": {"id": baseline_id, "hash": baseline_hash, "metrics": metrics},
        "volume": {
            "ingested": round(ingested, 6),
            "auto": round(auto, 6),
            "reviewed": round(reviewed, 6),
            "halted": round(halted, 6),
            "straight_through_rate_pct": round(auto / ingested * 100, 4) if ingested else 0,
            "review_rate_pct": round(reviewed / ingested * 100, 4) if ingested else 0,
            "measured_error_rate_pct": round(measured_error_count / ingested * 100, 4) if ingested and measured_error_count else None,
        },
        "reconciliation": {
            "ingested": round(ingested, 6),
            "auto": round(auto, 6),
            "reviewed": round(reviewed, 6),
            "halted": round(halted, 6),
            "delta": round(delta, 6),
            "reconciles": abs(delta) < 0.000001,
            "orphan_events": orphan_event_count,
        },
        "value": {
            "hours_saved": round(hours_saved, 6),
            "gross_benefits_usd": round(benefits, 6),
            "costs_usd": round(costs, 6),
            "net_dollars_usd": round(net, 6),
            "cost_per_completed_unit_usd": round(costs / completed_units, 6) if completed_units else None,
            "implementation_cost_usd": round(implementation_cost, 6),
            "roi_pct": round(roi, 4) if roi is not None else None,
            "payback_days": round(payback_days, 4) if payback_days is not None else None,
            "payback_date": payback_date,
        },
        "cycle_time": {
            "average_measured_hours": round(sum(measured_cycles) / len(measured_cycles), 6) if measured_cycles else None,
            "baseline_hours": round(sum(baseline_cycle) / len(baseline_cycle), 6) if baseline_cycle else None,
            "reduction_hours": round(sum(float(row.get("quantity") or 0) for row in cycle_rows), 6),
        },
        "adoption": [
            {"actor_id": actor, "department": department, "units": round(units, 6)}
            for (actor, department), units in sorted(adoption.items())
        ],
        "event_count": len(rows),
        "drilldown": {
            "volume": "/api/value/drilldown?metric=volume",
            "hours_saved": "/api/value/drilldown?metric=hours_saved",
            "net_dollars": "/api/value/drilldown?metric=net_dollars",
            "costs": "/api/value/drilldown?metric=costs",
        },
    }


def rollup_value_events(
    db: Session,
    *,
    workspace_id: str,
    period_start: date | None = None,
    period_end: date | None = None,
    workflow_version_id: str | None = None,
    baseline_id: str | None = None,
    implementation_cost_usd: float = 0,
) -> tuple[dict[str, Any], list[ValueEvent]]:
    query = select(ValueEvent).where(ValueEvent.workspace_id == workspace_id)
    if period_start:
        query = query.where(ValueEvent.computed_at >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc))
    if period_end:
        query = query.where(ValueEvent.computed_at < datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    if workflow_version_id:
        query = query.where(ValueEvent.workflow_version_id == workflow_version_id)
    if baseline_id:
        query = query.where(ValueEvent.baseline_id == baseline_id)
    events = db.scalars(query.order_by(ValueEvent.computed_at.asc(), ValueEvent.id.asc())).all()
    execution_ids = {event.execution_id for event in events if event.execution_id}
    review_ids = {event.review_task_id for event in events if event.review_task_id}
    visible_execution_ids = set(
        db.scalars(select(Execution.id).where(Execution.workspace_id == workspace_id, Execution.id.in_(execution_ids))).all()
    ) if execution_ids else set()
    visible_review_ids = set(
        db.scalars(select(ReviewTask.id).where(ReviewTask.workspace_id == workspace_id, ReviewTask.id.in_(review_ids))).all()
    ) if review_ids else set()
    rows = []
    for event in events:
        row = event_projection(event)
        row["orphan"] = bool(
            (event.execution_id and event.execution_id not in visible_execution_ids)
            or (event.review_task_id and event.review_task_id not in visible_review_ids)
        )
        rows.append(row)
    baseline = None
    if baseline_id:
        baseline = db.scalar(select(Baseline).where(Baseline.id == baseline_id, Baseline.workspace_id == workspace_id))
    elif events and events[0].baseline_id:
        baseline = db.scalar(select(Baseline).where(Baseline.id == events[0].baseline_id, Baseline.workspace_id == workspace_id))
    metrics = _metrics(db, baseline)
    rollup = calculate_value_rollup(
        rows,
        baseline_metrics=metrics,
        baseline_id=baseline.id if baseline else (events[0].baseline_id if events else None),
        baseline_hash=baseline.canonical_hash if baseline else (events[0].baseline_hash if events else None),
        implementation_cost_usd=implementation_cost_usd,
        period_start=period_start,
        period_end=period_end,
    )
    return rollup, events


def csv_value_export(rollup: dict[str, Any], events: Iterable[ValueEvent]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["value_ledger", VALUE_FORMULA_VERSION])
    writer.writerow(["baseline_id", rollup["baseline"].get("id")])
    writer.writerow(["baseline_hash", rollup["baseline"].get("hash")])
    writer.writerow(["reconciles", rollup["reconciliation"]["reconciles"]])
    writer.writerow(["ingested", rollup["reconciliation"]["ingested"]])
    writer.writerow(["auto", rollup["reconciliation"]["auto"]])
    writer.writerow(["reviewed", rollup["reconciliation"]["reviewed"]])
    writer.writerow(["halted", rollup["reconciliation"]["halted"]])
    writer.writerow([])
    writer.writerow(["event_id", "event_key", "kind", "quantity", "unit", "dollar_value", "method", "confidence", "execution_id", "workflow_version_id", "baseline_id", "source_artifact_type", "source_artifact_id", "computed_at"])
    for event in events:
        writer.writerow([
            event.id,
            event.event_key,
            event.kind,
            event.quantity,
            event.unit,
            event.dollar_value,
            event.method,
            event.confidence,
            event.execution_id,
            event.workflow_version_id,
            event.baseline_id,
            event.source_artifact_type,
            event.source_artifact_id,
            event.computed_at.isoformat(),
        ])
    return output.getvalue()


def pdf_value_export(rollup: dict[str, Any], events: Iterable[ValueEvent]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise DomainError("VALUE_EXPORT_UNAVAILABLE", "PDF export dependencies are not installed", 503) from exc
    buffer = StringIO()
    # SimpleDocTemplate needs a binary file; BytesIO is imported lazily to keep the service lightweight.
    from io import BytesIO

    pdf_buffer = BytesIO()
    document = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=0.5 * inch, leftMargin=0.5 * inch, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    story: list[Any] = [Paragraph("AI Operations Value Realization Pack", styles["Title"]), Spacer(1, 8)]
    story.append(Paragraph(f"Formula {VALUE_FORMULA_VERSION} · Baseline hash: {rollup['baseline'].get('hash') or 'not signed'}", styles["BodyText"]))
    story.append(Spacer(1, 10))
    summary = rollup["reconciliation"]
    value = rollup["value"]
    story.append(
        Table(
            [
                ["Reconciles", str(summary["reconciles"]), "Ingested", str(summary["ingested"])],
                ["Auto", str(summary["auto"]), "Reviewed", str(summary["reviewed"])],
                ["Halted", str(summary["halted"]), "Net USD", f"{value['net_dollars_usd']:.2f}"],
                ["Hours saved", f"{value['hours_saved']:.2f}", "ROI", str(value["roi_pct"] if value["roi_pct"] is not None else "not priced")],
            ],
            colWidths=[1.2 * inch, 1.4 * inch, 1.2 * inch, 1.6 * inch],
            style=TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd8c7")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf4e8")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]),
        )
    )
    story.append(Spacer(1, 12))
    story.append(Paragraph("Immutable event evidence", styles["Heading2"]))
    rows = [["ID", "Kind", "Qty", "USD", "Method", "Confidence"]]
    for event in list(events)[:200]:
        rows.append([event.id[:12], event.kind, f"{event.quantity:.4f}", f"{event.dollar_value:.4f}", event.method, event.confidence])
    story.append(Table(rows, repeatRows=1, colWidths=[0.9 * inch, 1.35 * inch, 0.65 * inch, 0.8 * inch, 1.05 * inch, 0.8 * inch], style=TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d8e1d5")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#285d4e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("PADDING", (0, 0), (-1, -1), 4),
    ])))
    document.build(story)
    return pdf_buffer.getvalue()
