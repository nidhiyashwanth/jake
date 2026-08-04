"""Operator review desk queue and guarded task actions."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ComplianceDocument, ReviewTask, Vendor
from app.schemas import ReviewAssignRequest, ReviewBulkActionRequest, ReviewEscalateRequest
from app.services.audit import append_audit_log, append_data_access_log
from app.services.authorization import authorize
from app.services.repositories import get_review_or_404
from app.services.review_desk import assign_task, escalate_task, queue_rows, require_bulk_cap, review_payload
from app.services.tenancy import current_context, get_scoped_db


router = APIRouter(prefix="/api", tags=["review-desk"])
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


@router.get("/reviews/queue")
def review_queue(db: ScopedDb, status: str = "open", limit: int = 50) -> dict[str, Any]:
    context = current_context(db)
    if status not in {"open", "resolved", "superseded", "all"}:
        raise DomainError("INVALID_REVIEW_STATUS", "status must be open, resolved, superseded, or all", 422)
    authorize(db, context, "review.queue.read", target_type="review_queue", target_id=context.workspace_id)
    items = queue_rows(db, workspace_id=context.workspace_id, status=status, limit=limit)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=context.workspace_id,
        resource_type="review_queue",
        purpose="review_queue_read",
    )
    db.commit()
    return {"items": items, "count": len(items), "limit": max(1, min(limit, 100)), "priority_formula": "review.priority.v1", "bulk_cap": 25}


@router.get("/reviews/{review_id}")
def review_detail(review_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "review.queue.read", target_type="review_task", target_id=review_id)
    review = get_review_or_404(db, review_id)
    vendor_name = db.scalar(select(Vendor.legal_name).where(Vendor.id == review.vendor_id, Vendor.workspace_id == context.workspace_id))
    document_name = db.scalar(select(ComplianceDocument.filename).where(ComplianceDocument.id == review.document_id, ComplianceDocument.workspace_id == context.workspace_id))
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=review.id,
        resource_type="review_task",
        purpose="review_detail_read",
    )
    db.commit()
    return {"review": review_payload(db, review, vendor_name=vendor_name, document_name=document_name, include_events=True)}


@router.post("/reviews/{review_id}/assign")
def assign_review(review_id: str, payload: ReviewAssignRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "review.assign", target_type="review_task", target_id=review_id)
    review = get_review_or_404(db, review_id)
    assign_task(db, review, actor_id=context.user_id, assignee_user_id=payload.assignee_user_id)
    append_audit_log(
        db,
        action="review.assigned" if payload.assignee_user_id else "review.unassigned",
        target_type="review_task",
        target_id=review.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"assignee_user_id": payload.assignee_user_id},
    )
    db.commit()
    return {"review": review_payload(db, review)}


@router.post("/reviews/{review_id}/escalate")
def escalate_review(review_id: str, payload: ReviewEscalateRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "review.escalate", target_type="review_task", target_id=review_id)
    review = get_review_or_404(db, review_id)
    if review.status != "open":
        raise DomainError("REVIEW_NOT_OPEN", "Only open review tasks can be escalated", 409)
    escalate_task(db, review, actor_id=context.user_id, reason=payload.reason, level=payload.level)
    append_audit_log(
        db,
        action="review.escalated",
        target_type="review_task",
        target_id=review.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"level": review.escalation_level, "reason": payload.reason},
    )
    db.commit()
    return {"review": review_payload(db, review)}


@router.post("/reviews/bulk")
def bulk_review_action(payload: ReviewBulkActionRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "review.bulk", target_type="review_queue", target_id=context.workspace_id)
    require_bulk_cap(payload.review_ids)
    reviews = []
    for review_id in payload.review_ids:
        review = get_review_or_404(db, review_id)
        if review.status != "open":
            raise DomainError("REVIEW_NOT_OPEN", "Bulk actions can target open review tasks only", 409)
        reviews.append(review)
    if payload.action in {"assign", "unassign"}:
        assignee = payload.assignee_user_id if payload.action == "assign" else None
        for review in reviews:
            assign_task(db, review, actor_id=context.user_id, assignee_user_id=assignee)
    else:
        if not payload.reason:
            raise DomainError("ESCALATION_REASON_REQUIRED", "An escalation reason is required", 422)
        for review in reviews:
            escalate_task(db, review, actor_id=context.user_id, reason=payload.reason)
    append_audit_log(
        db,
        action="review.bulk_action",
        target_type="review_queue",
        target_id=context.workspace_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"action": payload.action, "review_count": len(reviews), "review_ids": payload.review_ids},
    )
    db.commit()
    return {"action": payload.action, "updated": len(reviews), "review_ids": payload.review_ids}
