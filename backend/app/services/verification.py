from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import DomainError
from app.models import AuditEvent, ComplianceCheck, ComplianceDocument, ComplianceStatus, ReviewTask, Vendor, VendorEntity, new_id, utc_now
from app.services.audit import append_audit_log
from app.services.compliance import applicable_requirements
from app.services.compliance_rules import RuleResult, evaluate_requirement
from app.services.documents import as_date
from app.services.review_desk import append_review_event, prepare_review_task


def _same_name(left: Any, right: Any) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


def evaluate_rules(vendor: Vendor, fields: dict[str, Any], today: date | None = None) -> list[RuleResult]:
    settings = get_settings()
    today = today or date.today()
    expiry = as_date(fields.get("policy_expiry"))
    occurrence = fields.get("gl_occurrence_limit")
    rules = [
        RuleResult(
            "named_insured_match",
            "Named insured matches vendor legal name",
            "named_insured",
            "pass" if _same_name(fields.get("named_insured"), vendor.legal_name) else "fail",
            "PASS" if _same_name(fields.get("named_insured"), vendor.legal_name) else ("FIELD_MISSING" if not fields.get("named_insured") else "NAME_MISMATCH"),
            "Named insured matches the vendor legal name."
            if _same_name(fields.get("named_insured"), vendor.legal_name)
            else f"Observed {fields.get('named_insured') or 'no value'}; expected {vendor.legal_name}.",
            fields.get("named_insured"),
            vendor.legal_name,
        ),
        RuleResult(
            "certificate_holder_match",
            "Certificate holder matches contracting entity",
            "certificate_holder",
            "pass" if _same_name(fields.get("certificate_holder"), settings.required_certificate_holder) else "fail",
            "PASS" if _same_name(fields.get("certificate_holder"), settings.required_certificate_holder) else ("FIELD_MISSING" if not fields.get("certificate_holder") else "HOLDER_MISMATCH"),
            "Certificate holder matches the seeded contracting entity."
            if _same_name(fields.get("certificate_holder"), settings.required_certificate_holder)
            else f"Observed {fields.get('certificate_holder') or 'no value'}; expected {settings.required_certificate_holder}.",
            fields.get("certificate_holder"),
            settings.required_certificate_holder,
        ),
        RuleResult(
            "gl_occurrence_minimum",
            "General liability occurrence limit meets minimum",
            "gl_occurrence_limit",
            "pass" if isinstance(occurrence, int) and occurrence >= settings.minimum_gl_occurrence_limit else "fail",
            "PASS" if isinstance(occurrence, int) and occurrence >= settings.minimum_gl_occurrence_limit else ("FIELD_MISSING" if occurrence is None else "LIMIT_BELOW_MINIMUM"),
            "The GL occurrence limit meets the seeded minimum."
            if isinstance(occurrence, int) and occurrence >= settings.minimum_gl_occurrence_limit
            else f"Observed {occurrence or 'no value'}; minimum is {settings.minimum_gl_occurrence_limit}.",
            occurrence,
            settings.minimum_gl_occurrence_limit,
        ),
        RuleResult(
            "policy_not_expired",
            "Policy expiry is in the future",
            "policy_expiry",
            "pass" if expiry is not None and expiry >= today else "fail",
            "PASS" if expiry is not None and expiry >= today else ("FIELD_MISSING" if expiry is None else "POLICY_EXPIRED"),
            "Policy is valid on the verification date."
            if expiry is not None and expiry >= today
            else f"Observed {fields.get('policy_expiry') or 'no value'}; verification date is {today.isoformat()}.",
            fields.get("policy_expiry"),
            f">={today.isoformat()}",
        ),
        RuleResult(
            "additional_insured_present",
            "Additional insured endorsement is present",
            "additional_insured",
            "pass" if fields.get("additional_insured") is True else "fail",
            "PASS" if fields.get("additional_insured") is True else ("FIELD_MISSING" if fields.get("additional_insured") is None else "ENDORSEMENT_MISSING"),
            "Additional insured is marked present." if fields.get("additional_insured") is True else "Additional insured is missing or not confirmed.",
            fields.get("additional_insured"),
            True,
        ),
        RuleResult(
            "waiver_of_subrogation_present",
            "Waiver of subrogation is present",
            "waiver_of_subrogation",
            "pass" if fields.get("waiver_of_subrogation") is True else "fail",
            "PASS" if fields.get("waiver_of_subrogation") is True else ("FIELD_MISSING" if fields.get("waiver_of_subrogation") is None else "ENDORSEMENT_MISSING"),
            "Waiver of subrogation is marked present." if fields.get("waiver_of_subrogation") is True else "Waiver of subrogation is missing or not confirmed.",
            fields.get("waiver_of_subrogation"),
            True,
        ),
    ]
    return rules


def check_payload(check: ComplianceCheck) -> dict[str, Any]:
    return {
        "id": check.id,
        "requirement_key": check.requirement_key,
        "label": check.label,
        "result": check.result,
        "reason_code": check.reason_code,
        "message": check.message,
        "explanation": check.explanation or check.message,
        "confidence": check.confidence,
        "requirement_id": check.requirement_id,
        "observed_value": check.observed_value,
        "required_value": check.required_value,
        "created_at": check.created_at.isoformat(),
    }


def status_payload(status: ComplianceStatus) -> dict[str, Any]:
    return {
        "id": status.id,
        "vendor_id": status.vendor_id,
        "document_id": status.document_id,
        "project_id": status.project_id,
        "as_of": status.as_of.isoformat(),
        "status": status.status,
        "failing_requirements": status.failing_requirements,
        "computed_by_version": status.computed_by_version,
        "evidence": status.evidence,
    }


def run_verification(db: Session, vendor: Vendor, document: ComplianceDocument, actor_type: str = "system") -> dict[str, Any]:
    settings = get_settings()
    workspace_id = db.info.get("workspace_id")
    if not isinstance(workspace_id, str) or workspace_id != vendor.workspace_id or workspace_id != document.workspace_id:
        raise DomainError("REQUEST_CONTEXT_MISSING", "Verification requires a matching workspace context", 500)
    request_context = db.info.get("request_context")
    actor_id = getattr(request_context, "user_id", None)
    run_id = str(uuid4())
    now = utc_now()
    project_id = document.extracted_fields.get("project_id") if isinstance(document.extracted_fields, dict) else None
    requirement_set, requirements, overrides = applicable_requirements(
        db,
        vendor=vendor,
        doc_type=document.doc_type,
        project_id=project_id if isinstance(project_id, str) else None,
    )
    if requirements:
        entity_names = db.scalars(
            select(VendorEntity.name).where(
                VendorEntity.workspace_id == workspace_id,
                VendorEntity.vendor_id == vendor.id,
                VendorEntity.active.is_(True),
            )
        ).all()
        results = [
            evaluate_requirement(
                requirement,
                vendor=vendor,
                document=document,
                fields=document.extracted_fields,
                entity_names=entity_names,
                overrides=overrides,
            )
            for requirement in requirements
        ]
    else:
        # F01 workspaces without an explicitly published P-01 requirement set
        # retain the original six-rule contract. The expanded engine is opt-in
        # through a versioned set and never silently changes old evidence.
        requirement_set = None
        results = evaluate_rules(vendor, document.extracted_fields)

    old_open_tasks = db.scalars(
        select(ReviewTask).where(
            ReviewTask.document_id == document.id,
            ReviewTask.workspace_id == workspace_id,
            ReviewTask.status == "open",
        )
    ).all()
    for task in old_open_tasks:
        task.status = "superseded"
        task.resolved_at = now
        task.last_touched_at = now

    checks: list[ComplianceCheck] = []
    reviews: list[ReviewTask] = []
    for result in results:
        check = ComplianceCheck(
            id=new_id(),
            workspace_id=workspace_id,
            vendor_id=vendor.id,
            document_id=document.id,
            run_id=run_id,
            requirement_key=result.key,
            requirement_id=result.requirement_id,
            label=result.label,
            result=result.result,
            reason_code=result.reason_code,
            message=result.message,
            explanation=result.explanation or result.message,
            confidence=result.confidence,
            observed_value=result.observed_value,
            required_value=result.required_value,
        )
        db.add(check)
        checks.append(check)
        if result.result != "pass":
            review = ReviewTask(
                workspace_id=workspace_id,
                vendor_id=vendor.id,
                document_id=document.id,
                check_id=check.id,
                requirement_key=result.key,
                correction_field=result.field,
                reason_code=result.reason_code,
                status="open",
                created_at=now,
                updated_at=now,
                last_touched_at=now,
            )
            prepare_review_task(review, document, now=now)
            db.add(review)
            reviews.append(review)
    db.flush()

    for task in old_open_tasks:
        append_review_event(
            db,
            task,
            actor_id=actor_id,
            event_type="review.superseded",
            from_status="open",
            to_status="superseded",
            payload={"reason": "new_verification_run", "document_id": document.id},
        )
    for review in reviews:
        append_review_event(
            db,
            review,
            actor_id=actor_id,
            event_type="review.created",
            to_status="open",
            payload={"reason_code": review.reason_code, "priority_band": review.priority_band},
        )

    failing = [result.key for result in results if result.result != "pass"]
    status = "compliant" if not failing else "needs_review"
    evidence = {
        "document_filename": document.filename,
        "normalized_fields": document.extracted_fields,
        "requirement_set": {
            "id": requirement_set.id,
            "name": requirement_set.name,
            "version": requirement_set.version,
        } if requirement_set else None,
        "checks": [check_payload(check) for check in checks],
        "review_task_ids": [review.id for review in reviews],
    }
    snapshot = ComplianceStatus(
        workspace_id=workspace_id,
        vendor_id=vendor.id,
        document_id=document.id,
        project_id=project_id if isinstance(project_id, str) else None,
        as_of=now,
        status=status,
        failing_requirements=failing,
        computed_by_version=settings.rules_version,
        evidence=evidence,
    )
    db.add(snapshot)
    db.flush()
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            vendor_id=vendor.id,
            event_type="verification_completed",
            actor_type=actor_type,
            entity_type="compliance_status",
            entity_id=snapshot.id,
            payload={"status": status, "failing_requirements": failing, "document_id": document.id},
        )
    )
    append_audit_log(
        db,
        action="verification.completed",
        target_type="compliance_status",
        target_id=snapshot.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"status": status, "failing_requirements": failing, "document_id": document.id},
    )
    db.commit()

    return {
        "run_id": run_id,
        "status": status_payload(snapshot),
        "checks": [check_payload(check) for check in checks],
        "review_tasks": [review_payload(review) for review in reviews],
    }


def review_payload(review: ReviewTask) -> dict[str, Any]:
    return {
        "id": review.id,
        "vendor_id": review.vendor_id,
        "document_id": review.document_id,
        "check_id": review.check_id,
        "requirement_key": review.requirement_key,
        "correction_field": review.correction_field,
        "reason_code": review.reason_code,
        "status": review.status,
        "priority_score": review.priority_score,
        "priority_band": review.priority_band,
        "priority_factors": review.priority_factors_json,
        "assigned_to_user_id": review.assigned_to_user_id,
        "assigned_at": review.assigned_at.isoformat() if review.assigned_at else None,
        "sla_minutes": review.sla_minutes,
        "due_at": review.due_at.isoformat() if review.due_at else None,
        "escalation_level": review.escalation_level,
        "escalated_at": review.escalated_at.isoformat() if review.escalated_at else None,
        "escalation_reason": review.escalation_reason,
        "correction_reason_code": review.correction_reason_code,
        "correction_note": review.correction_note,
        "before_value": review.before_value_json,
        "after_value": review.after_value_json,
        "provenance": review.provenance_json,
        "created_at": review.created_at.isoformat(),
        "last_touched_at": review.last_touched_at.isoformat() if review.last_touched_at else None,
        "updated_at": review.updated_at.isoformat(),
        "resolved_at": review.resolved_at.isoformat() if review.resolved_at else None,
    }


def history_payload(db: Session, vendor_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ComplianceStatus)
        .where(
            ComplianceStatus.vendor_id == vendor_id,
            ComplianceStatus.workspace_id == db.info.get("workspace_id"),
        )
        .order_by(ComplianceStatus.as_of.desc(), ComplianceStatus.id.desc())
    ).all()
    return [status_payload(row) for row in rows]
