"""Queue, provenance, SLA, and operator-history rules for the review desk."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ComplianceDocument, ReviewTask, ReviewTaskEvent, User, Vendor, new_id, utc_now


REASON_PRIORITY: dict[str, tuple[float, str, int]] = {
    "FIELD_MISSING": (0.95, "urgent", 30),
    "NAME_MISMATCH": (0.90, "urgent", 30),
    "HOLDER_MISMATCH": (0.90, "urgent", 30),
    "LIMIT_BELOW_MINIMUM": (0.85, "high", 60),
    "POLICY_EXPIRED": (0.85, "high", 60),
    "ENDORSEMENT_MISSING": (0.75, "high", 60),
}
DEFAULT_PRIORITY = (0.60, "normal", 120)
MAX_BULK_TASKS = 25


def _priority(reason_code: str) -> tuple[float, str, int]:
    return REASON_PRIORITY.get(reason_code, DEFAULT_PRIORITY)


def source_provenance(document: ComplianceDocument, field: str, value: Any) -> dict[str, Any]:
    """Return a deterministic, reviewable locator without claiming OCR certainty."""

    text = document.content.decode("utf-8", errors="replace")
    candidates = []
    if value not in (None, ""):
        candidates.append(str(value))
    candidates.append(field.replace("_", " "))
    start = -1
    matched = field.replace("_", " ")
    for candidate in candidates:
        position = text.casefold().find(candidate.casefold())
        if position >= 0:
            start = position
            matched = candidate
            break
    if start < 0:
        start = 0
        matched = text[:120] or "No source text available"
    end = min(len(text), start + max(len(matched), 1))
    line = text.count("\n", 0, start) + 1
    excerpt_start = max(0, start - 80)
    excerpt_end = min(len(text), max(end, start + 1) + 160)
    return {
        "document_id": document.id,
        "filename": document.filename,
        "page": 1,
        "line": line,
        "char_start": start,
        "char_end": end,
        "bbox": None,
        "matched_text": matched[:240],
        "excerpt": text[excerpt_start:excerpt_end],
        "locator_kind": "text_character_range",
        "source_quality": "deterministic_text_locator",
    }


def prepare_review_task(task: ReviewTask, document: ComplianceDocument, *, now=None) -> ReviewTask:
    now = now or utc_now()
    score, band, sla_minutes = _priority(task.reason_code)
    task.priority_score = score
    task.priority_band = band
    task.priority_factors_json = {
        "formula_version": "review.priority.v1",
        "reason_code": task.reason_code,
        "risk_weight": score,
        "value_at_risk": None,
    }
    task.sla_minutes = sla_minutes
    task.due_at = now + timedelta(minutes=sla_minutes)
    task.provenance_json = source_provenance(document, task.correction_field, (document.extracted_fields or {}).get(task.correction_field))
    task.last_touched_at = now
    task.updated_at = now
    return task


def append_review_event(
    db: Session,
    task: ReviewTask,
    *,
    actor_id: str | None,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ReviewTaskEvent:
    event = ReviewTaskEvent(
        id=new_id(),
        workspace_id=task.workspace_id,
        review_task_id=task.id,
        actor_id=actor_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        payload_json=payload or {},
        occurred_at=utc_now(),
    )
    db.add(event)
    return event


def _assigned_name(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.scalar(select(User).where(User.id == user_id))
    return user.name if user else None


def review_payload(
    db: Session,
    task: ReviewTask,
    *,
    vendor_name: str | None = None,
    document_name: str | None = None,
    include_events: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": task.id,
        "vendor_id": task.vendor_id,
        "vendor_legal_name": vendor_name,
        "document_id": task.document_id,
        "document_filename": document_name,
        "check_id": task.check_id,
        "requirement_key": task.requirement_key,
        "correction_field": task.correction_field,
        "reason_code": task.reason_code,
        "status": task.status,
        "priority_score": task.priority_score,
        "priority_band": task.priority_band,
        "priority_factors": task.priority_factors_json,
        "assigned_to_user_id": task.assigned_to_user_id,
        "assigned_to_name": _assigned_name(db, task.assigned_to_user_id),
        "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
        "sla_minutes": task.sla_minutes,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "escalation_level": task.escalation_level,
        "escalated_at": task.escalated_at.isoformat() if task.escalated_at else None,
        "escalation_reason": task.escalation_reason,
        "correction_reason_code": task.correction_reason_code,
        "correction_note": task.correction_note,
        "before_value": task.before_value_json,
        "after_value": task.after_value_json,
        "provenance": task.provenance_json,
        "created_at": task.created_at.isoformat(),
        "last_touched_at": task.last_touched_at.isoformat() if task.last_touched_at else None,
        "updated_at": task.updated_at.isoformat(),
        "resolved_at": task.resolved_at.isoformat() if task.resolved_at else None,
    }
    if include_events:
        events = db.scalars(
            select(ReviewTaskEvent)
            .where(ReviewTaskEvent.review_task_id == task.id, ReviewTaskEvent.workspace_id == task.workspace_id)
            .order_by(ReviewTaskEvent.occurred_at, ReviewTaskEvent.id)
        ).all()
        payload["events"] = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "actor_id": event.actor_id,
                "payload": event.payload_json,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ]
    return payload


def queue_rows(db: Session, *, workspace_id: str, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    query = (
        select(ReviewTask, Vendor.legal_name, ComplianceDocument.filename)
        .join(Vendor, Vendor.id == ReviewTask.vendor_id)
        .join(ComplianceDocument, ComplianceDocument.id == ReviewTask.document_id)
        .where(
            ReviewTask.workspace_id == workspace_id,
            Vendor.workspace_id == workspace_id,
            ComplianceDocument.workspace_id == workspace_id,
        )
        .order_by(ReviewTask.priority_score.desc(), ReviewTask.due_at.asc().nullslast(), ReviewTask.created_at.asc())
        .limit(limit)
    )
    if status != "all":
        query = query.where(ReviewTask.status == status)
    rows = db.execute(query).all()
    items: list[dict[str, Any]] = []
    now = utc_now()
    for task, vendor_name, document_name in rows:
        if task.status == "open" and task.due_at is None:
            document = db.scalar(select(ComplianceDocument).where(ComplianceDocument.id == task.document_id))
            if document is not None:
                prepare_review_task(task, document, now=now)
        item = review_payload(db, task, vendor_name=vendor_name, document_name=document_name)
        item["sla_state"] = "overdue" if task.due_at and task.due_at < now else "within_sla"
        items.append(item)
    return items


def assign_task(db: Session, task: ReviewTask, *, actor_id: str, assignee_user_id: str | None) -> ReviewTask:
    if assignee_user_id is not None:
        user = db.scalar(
            select(User).join(User.memberships).where(
                User.id == assignee_user_id,
                User.memberships.any(workspace_id=task.workspace_id, status="active"),
            )
        )
        if user is None:
            raise DomainError("REVIEW_ASSIGNEE_NOT_IN_WORKSPACE", "The assignee is not an active workspace member", 422)
    previous = task.assigned_to_user_id
    task.assigned_to_user_id = assignee_user_id
    task.assigned_at = utc_now() if assignee_user_id else None
    task.last_touched_at = utc_now()
    append_review_event(
        db,
        task,
        actor_id=actor_id,
        event_type="review.assigned" if assignee_user_id else "review.unassigned",
        payload={"previous_assignee_user_id": previous, "assignee_user_id": assignee_user_id},
    )
    return task


def escalate_task(db: Session, task: ReviewTask, *, actor_id: str, reason: str, level: int | None = None) -> ReviewTask:
    reason = " ".join(reason.split())[:500]
    if not reason:
        raise DomainError("ESCALATION_REASON_REQUIRED", "An escalation reason is required", 422)
    previous_level = task.escalation_level
    task.escalation_level = max(previous_level + 1, level or 0)
    task.escalated_at = utc_now()
    task.escalation_reason = reason
    task.last_touched_at = task.escalated_at
    append_review_event(
        db,
        task,
        actor_id=actor_id,
        event_type="review.escalated",
        payload={"from_level": previous_level, "to_level": task.escalation_level, "reason": reason},
    )
    return task


def require_bulk_cap(review_ids: list[str]) -> None:
    if not review_ids:
        raise DomainError("REVIEW_IDS_REQUIRED", "Select at least one review task", 422)
    if len(review_ids) > MAX_BULK_TASKS:
        raise DomainError("REVIEW_BULK_CAP_EXCEEDED", f"Bulk actions are capped at {MAX_BULK_TASKS} tasks", 422)
