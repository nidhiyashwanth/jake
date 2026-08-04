"""Bounded document-chase state machine with customer-owned sender guardrails."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    ChaseEvent,
    ChaseThread,
    ComplianceDocument,
    ComplianceRequirement,
    ComplianceStatus,
    Connector,
    Membership,
    User,
    Vendor,
    new_id,
    utc_now,
)
from app.services.compliance_catalog import normalize_document_type


UNSAFE_NEGOTIATION = re.compile(
    r"(?i)\b(?:approve|approved|negotiate|negotiation|reduce\s+(?:the\s+)?limit|waive\s+(?:the\s+)?requirement|you\s+may\s+work|cleared\s+to\s+work)\b"
)


def _workspace_id(db: Session) -> str:
    workspace_id = db.info.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise DomainError("REQUEST_CONTEXT_MISSING", "A workspace-scoped database session is required", 500)
    return workspace_id


def get_chase_or_404(db: Session, chase_id: str) -> ChaseThread:
    thread = db.scalar(select(ChaseThread).where(ChaseThread.id == chase_id, ChaseThread.workspace_id == _workspace_id(db)))
    if thread is None:
        raise DomainError("CHASE_NOT_FOUND", f"Chase thread {chase_id} was not found", 404)
    return thread


def _event(thread: ChaseThread, *, event_type: str, summary: str, attempt: int = 0, body: str | None = None, attachment_document_id: str | None = None, payload: dict[str, Any] | None = None) -> ChaseEvent:
    event = ChaseEvent(
        id=new_id(),
        workspace_id=thread.workspace_id,
        chase_thread_id=thread.id,
        event_type=event_type,
        channel=thread.channel,
        attempt=attempt,
        body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest() if body is not None else None,
        summary=summary,
        attachment_document_id=attachment_document_id,
        payload_json=payload or {},
    )
    return event


def create_chase_thread(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    vendor: Vendor,
    requirement_id: str | None,
    customer_sender_connector_id: str,
    internal_owner_user_id: str | None,
    expected_doc_type: str,
    project_id: str | None,
    channel: str,
    max_attempts: int,
    max_messages_per_week: int,
    touch_schedule_days: list[int],
) -> ChaseThread:
    if _workspace_id(db) != workspace_id or vendor.workspace_id != workspace_id:
        raise DomainError("WORKSPACE_CONTEXT_MISMATCH", "Chase thread workspace does not match the active workspace", 403)
    if channel != "email":
        raise DomainError("CHASE_CHANNEL_UNSUPPORTED", "The v1 chase sandbox only sends through customer-owned email", 422)
    if touch_schedule_days != sorted(set(touch_schedule_days)) or any(day < 0 or day > 90 for day in touch_schedule_days):
        raise DomainError("CHASE_SCHEDULE_INVALID", "Touch schedule must be sorted, unique, and within 90 days", 422)
    connector = db.scalar(
        select(Connector).where(
            Connector.id == customer_sender_connector_id,
            Connector.workspace_id == workspace_id,
        )
    )
    if connector is None:
        raise DomainError("CHASE_SENDER_NOT_FOUND", "The customer-owned sender connector was not found", 404)
    if connector.kind != "email":
        raise DomainError("CHASE_SENDER_KIND_INVALID", "Chase threads must use an email connector owned by the customer", 422)
    owner_id = internal_owner_user_id or actor_id
    owner = db.scalar(
        select(User).where(
            User.id == owner_id,
            User.memberships.any((Membership.workspace_id == workspace_id) & (Membership.status == "active")),
        )
    )
    if owner is None:
        raise DomainError("CHASE_OWNER_NOT_IN_WORKSPACE", "The internal chase owner is not an active workspace member", 422)
    normalized_doc_type = normalize_document_type(expected_doc_type)
    requirement = None
    if requirement_id:
        requirement = db.scalar(
            select(ComplianceRequirement).where(
                ComplianceRequirement.id == requirement_id,
                ComplianceRequirement.workspace_id == workspace_id,
            )
        )
        if requirement is None:
            raise DomainError("CHASE_REQUIREMENT_NOT_FOUND", "The chase requirement was not found", 404)
        if requirement.doc_type != normalized_doc_type:
            raise DomainError("CHASE_DOCUMENT_TYPE_MISMATCH", "The chase document type does not match its requirement", 422)
    thread = ChaseThread(
        id=new_id(),
        workspace_id=workspace_id,
        vendor_id=vendor.id,
        requirement_id=requirement_id,
        channel=channel,
        customer_sender_connector_id=connector.id,
        internal_owner_user_id=owner.id,
        expected_doc_type=normalized_doc_type,
        project_id=project_id,
        status="open",
        attempts=0,
        max_attempts=max_attempts,
        max_messages_per_week=max_messages_per_week,
        touch_schedule_json=touch_schedule_days,
        next_action_at=utc_now(),
    )
    db.add(thread)
    db.flush()
    db.add(
        _event(
            thread,
            event_type="chase.created",
            summary=f"Opened a bounded request for {normalized_doc_type}; sender is customer-owned.",
            payload={"customer_owned_sender": True, "cc_internal_owner_on_escalation": True, "max_attempts": max_attempts, "weekly_cap": max_messages_per_week},
        )
    )
    return thread


def _weekly_sent_count(db: Session, thread: ChaseThread) -> int:
    since = utc_now() - timedelta(days=7)
    return int(
        db.scalar(
            select(func.count(ChaseEvent.id))
            .join(ChaseThread, ChaseThread.id == ChaseEvent.chase_thread_id)
            .where(
                ChaseEvent.workspace_id == thread.workspace_id,
                ChaseThread.vendor_id == thread.vendor_id,
                ChaseEvent.event_type == "chase.touch.sent",
                ChaseEvent.occurred_at >= since,
            )
        )
        or 0
    )


def send_chase_touch(db: Session, *, thread: ChaseThread, body: str, approved: bool) -> ChaseThread:
    if UNSAFE_NEGOTIATION.search(body):
        raise DomainError(
            "CHASE_UNSAFE_NEGOTIATION",
            "Chase messages may request missing evidence but may not negotiate coverage or state approval to work",
            422,
        )
    if not approved:
        raise DomainError("CHASE_APPROVAL_REQUIRED", "An explicit operator approval is required before the sandbox sends a chase", 409)
    if thread.status in {"compliant_and_verified", "closed"}:
        raise DomainError("CHASE_ALREADY_COMPLETE", "The chase already has a compliant-and-verified success event", 409)
    if thread.attempts >= thread.max_attempts:
        raise DomainError("CHASE_ATTEMPTS_EXHAUSTED", "The chase has reached its maximum touch count and must be handled by the internal owner", 409)
    if _weekly_sent_count(db, thread) >= thread.max_messages_per_week:
        raise DomainError("CHASE_WEEKLY_CAP_EXCEEDED", "The vendor weekly chase-message cap has been reached", 409)
    connector = db.scalar(select(Connector).where(Connector.id == thread.customer_sender_connector_id, Connector.workspace_id == thread.workspace_id))
    if connector is None or connector.kind != "email":
        raise DomainError("CHASE_SENDER_NOT_FOUND", "The customer-owned email sender is not available", 409)
    if connector.status != "healthy":
        raise DomainError("CHASE_SENDER_NOT_HEALTHY", "Test the customer-owned email connector before sending a chase", 409)
    now = utc_now()
    thread.attempts += 1
    thread.last_sent_at = now
    schedule = list(thread.touch_schedule_json or [])
    next_delay = schedule[thread.attempts] if thread.attempts < len(schedule) else None
    thread.next_action_at = now + timedelta(days=next_delay) if next_delay is not None else None
    event = _event(
        thread,
        event_type="chase.touch.sent",
        summary=f"Sent touch {thread.attempts} requesting {thread.expected_doc_type}; no approval or coverage decision was stated.",
        attempt=thread.attempts,
        body=body,
        payload={"customer_owned_sender": True, "approval_recorded": True, "cc_internal_owner": False},
    )
    db.add(event)
    if thread.attempts >= thread.max_attempts:
        thread.status = "escalated"
        thread.escalated_at = now
        db.add(
            _event(
                thread,
                event_type="chase.escalated",
                summary="Maximum chase attempts reached; escalated to the internal owner with CC guardrail.",
                attempt=thread.attempts,
                payload={"cc_internal_owner": True, "internal_owner_user_id": thread.internal_owner_user_id},
            )
        )
    else:
        thread.status = "awaiting_reply"
    db.flush()
    return thread


def record_chase_reply(db: Session, *, thread: ChaseThread, body: str, attachment_document_id: str | None) -> ChaseThread:
    attachment = None
    if attachment_document_id:
        attachment = db.scalar(
            select(ComplianceDocument).where(
                ComplianceDocument.id == attachment_document_id,
                ComplianceDocument.workspace_id == thread.workspace_id,
                ComplianceDocument.vendor_id == thread.vendor_id,
            )
        )
        if attachment is None:
            raise DomainError("CHASE_ATTACHMENT_NOT_FOUND", "The reply attachment is not visible in the chase workspace", 404)
    if attachment is None or attachment.doc_type != thread.expected_doc_type:
        db.add(
            _event(
                thread,
                event_type="chase.reply.unmatched",
                summary=f"Reply received but no matching {thread.expected_doc_type} attachment was linked.",
                body=body,
                attachment_document_id=attachment.id if attachment else None,
                payload={"expected_doc_type": thread.expected_doc_type, "matched": False},
            )
        )
        thread.status = "awaiting_reply"
        db.flush()
        return thread
    verified = db.scalar(
        select(ComplianceStatus)
        .where(
            ComplianceStatus.workspace_id == thread.workspace_id,
            ComplianceStatus.vendor_id == thread.vendor_id,
            ComplianceStatus.document_id == attachment.id,
            ComplianceStatus.status == "compliant",
        )
        .order_by(ComplianceStatus.as_of.desc())
    )
    if verified is None:
        db.add(
            _event(
                thread,
                event_type="chase.reply.document_received",
                summary=f"Matching {thread.expected_doc_type} attachment received; verification is still required.",
                body=body,
                attachment_document_id=attachment.id,
                payload={"expected_doc_type": thread.expected_doc_type, "matched": True, "verified": False},
            )
        )
        thread.status = "awaiting_verification"
        db.flush()
        return thread
    thread.status = "compliant_and_verified"
    thread.success_document_id = attachment.id
    thread.next_action_at = None
    db.add(
        _event(
            thread,
            event_type="chase.compliant_and_verified",
            summary=f"Success: {thread.expected_doc_type} received and verified; chase closed without an approval decision.",
            body=body,
            attachment_document_id=attachment.id,
            payload={"expected_doc_type": thread.expected_doc_type, "matched": True, "verified": True},
        )
    )
    db.flush()
    return thread


def chase_payload(db: Session, thread: ChaseThread, *, include_events: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": thread.id,
        "vendor_id": thread.vendor_id,
        "requirement_id": thread.requirement_id,
        "channel": thread.channel,
        "customer_sender_connector_id": thread.customer_sender_connector_id,
        "internal_owner_user_id": thread.internal_owner_user_id,
        "expected_doc_type": thread.expected_doc_type,
        "project_id": thread.project_id,
        "status": thread.status,
        "attempts": thread.attempts,
        "max_attempts": thread.max_attempts,
        "max_messages_per_week": thread.max_messages_per_week,
        "touch_schedule_days": thread.touch_schedule_json,
        "last_sent_at": thread.last_sent_at.isoformat() if thread.last_sent_at else None,
        "next_action_at": thread.next_action_at.isoformat() if thread.next_action_at else None,
        "escalated_at": thread.escalated_at.isoformat() if thread.escalated_at else None,
        "success_document_id": thread.success_document_id,
        "created_at": thread.created_at.isoformat(),
        "updated_at": thread.updated_at.isoformat(),
    }
    if include_events:
        events = db.scalars(
            select(ChaseEvent)
            .where(ChaseEvent.workspace_id == thread.workspace_id, ChaseEvent.chase_thread_id == thread.id)
            .order_by(ChaseEvent.occurred_at.asc(), ChaseEvent.id.asc())
        ).all()
        payload["events"] = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "channel": event.channel,
                "attempt": event.attempt,
                "body_sha256": event.body_sha256,
                "summary": event.summary,
                "attachment_document_id": event.attachment_document_id,
                "payload": event.payload_json,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ]
    return payload
