"""HTTP boundary for confidence policy, routing decisions, and sampled audit."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ConfidenceAssessment, ConfidenceAudit, WorkflowVersion
from app.schemas import (
    ConfidenceAssessmentRequest,
    ConfidenceAuditOutcomeRequest,
    ConfidenceSimulationRequest,
    ConfidenceThresholdSetCreate,
)
from app.services.audit import append_audit_log
from app.services.authorization import authorize
from app.services.confidence import (
    ConfidenceSignals,
    ThresholdValues,
    assess,
    assessment_payload,
    audit_payload,
    complete_audit,
    create_threshold_set,
    get_audit_or_404,
    get_threshold_or_404,
    list_audits,
    list_thresholds,
    simulate,
    threshold_payload,
)
from app.services.tenancy import current_context, get_scoped_db


router = APIRouter(prefix="/api")
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _workflow_version_or_404(db: Session, version_id: str, workspace_id: str) -> WorkflowVersion:
    version = db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.id == version_id,
            WorkflowVersion.workspace_id == workspace_id,
        )
    )
    if version is None:
        raise DomainError("WORKFLOW_VERSION_NOT_FOUND", f"Workflow version {version_id} was not found", 404)
    return version


def _threshold_values(payload: ConfidenceThresholdSetCreate) -> ThresholdValues:
    return ThresholdValues(
        auto_threshold=payload.auto_threshold,
        review_threshold=payload.review_threshold,
        halt_threshold=payload.halt_threshold,
        value_at_risk_limit=payload.value_at_risk_limit,
        sample_rate=payload.sample_rate,
        cost_auto_usd=payload.cost_auto_usd,
        cost_review_usd=payload.cost_review_usd,
        cost_halt_usd=payload.cost_halt_usd,
    )


@router.get("/confidence/threshold-sets")
def list_confidence_threshold_sets(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.read", target_type="confidence_threshold_set")
    return {"items": [threshold_payload(item) for item in list_thresholds(db, context.workspace_id)]}


@router.post("/confidence/threshold-sets", status_code=201)
def create_confidence_threshold_set(payload: ConfidenceThresholdSetCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.manage", target_type="confidence_threshold_set")
    workflow_version = _workflow_version_or_404(db, payload.workflow_version_id, context.workspace_id) if payload.workflow_version_id else None
    threshold = create_threshold_set(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        workflow_version=workflow_version,
        version=payload.version,
        status=payload.status,
        values=_threshold_values(payload),
        reason=payload.reason,
    )
    append_audit_log(
        db,
        action="confidence.threshold.created",
        target_type="confidence_threshold_set",
        target_id=threshold.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={
            "scope_key": threshold.scope_key,
            "version": threshold.version,
            "status": threshold.status,
            "previous_threshold_set_id": threshold.previous_threshold_set_id,
            "sample_rate": threshold.sample_rate,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(threshold)
    return {"threshold_set": threshold_payload(threshold)}


@router.get("/confidence/threshold-sets/{threshold_id}")
def get_confidence_threshold_set(threshold_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.read", target_type="confidence_threshold_set", target_id=threshold_id)
    threshold = get_threshold_or_404(db, threshold_id, context.workspace_id)
    return {"threshold_set": threshold_payload(threshold)}


@router.post("/confidence/assess", status_code=201)
def assess_confidence(payload: ConfidenceAssessmentRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.assess", target_type="confidence_assessment", target_id=payload.assessment_key)
    if payload.workflow_version_id:
        _workflow_version_or_404(db, payload.workflow_version_id, context.workspace_id)
    assessment, audit, created = assess(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        assessment_key=payload.assessment_key,
        workflow_version_id=payload.workflow_version_id,
        signals=ConfidenceSignals(
            extraction_consistency=payload.extraction_consistency,
            validation_severity=payload.validation_severity,
            matching_score=payload.matching_score,
            novelty_score=payload.novelty_score,
            sender_history_score=payload.sender_history_score,
            value_at_risk=payload.value_at_risk,
            required_halt=payload.required_halt,
            evidence=payload.evidence,
        ),
    )
    if created:
        append_audit_log(
            db,
            action="confidence.assessed",
            target_type="confidence_assessment",
            target_id=assessment.id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            after={"route": assessment.route, "confidence": assessment.confidence, "threshold_set_id": assessment.threshold_set_id},
        )
    db.commit()
    db.refresh(assessment)
    if audit is not None:
        db.refresh(audit)
    return {
        "assessment": assessment_payload(assessment),
        "audit": audit_payload(audit) if audit else None,
        "idempotent_replay": not created,
    }


@router.get("/confidence/assessments")
def list_confidence_assessments(db: ScopedDb, limit: int = 100) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.read", target_type="confidence_assessment")
    bounded_limit = max(1, min(int(limit), 200))
    items = db.scalars(
        select(ConfidenceAssessment)
        .where(ConfidenceAssessment.workspace_id == context.workspace_id)
        .order_by(desc(ConfidenceAssessment.created_at), desc(ConfidenceAssessment.id))
        .limit(bounded_limit)
    ).all()
    return {"items": [assessment_payload(item) for item in items]}


@router.post("/confidence/simulate")
def simulate_confidence(payload: ConfidenceSimulationRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.read", target_type="confidence_simulator")
    cases = [
        ConfidenceSignals(
            extraction_consistency=item.extraction_consistency,
            validation_severity=item.validation_severity,
            matching_score=item.matching_score,
            novelty_score=item.novelty_score,
            sender_history_score=item.sender_history_score,
            value_at_risk=item.value_at_risk,
            required_halt=item.required_halt,
            evidence={"case_key": item.case_key},
        )
        for item in payload.cases
    ]
    threshold_specs = [
        (
            item.label,
            ThresholdValues(
                auto_threshold=item.auto_threshold,
                review_threshold=item.review_threshold,
                halt_threshold=item.halt_threshold,
                value_at_risk_limit=item.value_at_risk_limit,
                cost_auto_usd=item.cost_auto_usd,
                cost_review_usd=item.cost_review_usd,
                cost_halt_usd=item.cost_halt_usd,
            ),
        )
        for item in payload.thresholds
    ]
    results = simulate(cases, [item.known_correct for item in payload.cases], threshold_specs)
    return {"formula_version": "confidence.v1", "case_count": len(cases), "results": results}


@router.get("/confidence/audits")
def list_confidence_audits(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.audit.read", target_type="confidence_audit")
    return {"items": [audit_payload(item) for item in list_audits(db, context.workspace_id)]}


@router.post("/confidence/audits/{audit_id}/outcome")
def complete_confidence_audit(
    audit_id: str,
    payload: ConfidenceAuditOutcomeRequest,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "confidence.audit", target_type="confidence_audit", target_id=audit_id)
    audit = get_audit_or_404(db, audit_id, context.workspace_id)
    complete_audit(
        db,
        audit=audit,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        actual_correct=payload.actual_correct,
        outcome_summary=payload.outcome_summary,
    )
    db.commit()
    db.refresh(audit)
    return {"audit": audit_payload(audit), "thresholds": [threshold_payload(item) for item in list_thresholds(db, context.workspace_id)]}
