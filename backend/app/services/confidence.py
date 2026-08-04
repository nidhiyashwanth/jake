"""Deterministic confidence calibration, routing, simulation, and sampled audit.

The service intentionally treats model-reported confidence as untrusted input.  A
bounded weighted rule over observable signals owns the decision, and every
threshold or routed assessment is persisted with the evidence needed to replay
the decision later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any, Iterable

from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    ConfidenceAssessment,
    ConfidenceAudit,
    ConfidenceThresholdSet,
    WorkflowVersion,
    new_id,
    utc_now,
)
from app.services.audit import append_audit_log


FORMULA_VERSION = "confidence.v1"
MIN_SAMPLE_RATE = 0.02
WEIGHTS: dict[str, float] = {
    "extraction_consistency": 0.22,
    "validation_quality": 0.20,
    "matching_score": 0.20,
    "novelty_quality": 0.15,
    "sender_history_score": 0.13,
    "value_at_risk_score": 0.10,
}


@dataclass(frozen=True)
class ThresholdValues:
    auto_threshold: float
    review_threshold: float
    halt_threshold: float
    value_at_risk_limit: float
    sample_rate: float = MIN_SAMPLE_RATE
    cost_auto_usd: float = 0.05
    cost_review_usd: float = 4.0
    cost_halt_usd: float = 1.0

    def validate(self) -> None:
        if not 0 <= self.halt_threshold <= self.review_threshold <= self.auto_threshold <= 1:
            raise ValueError("halt_threshold must be <= review_threshold <= auto_threshold")
        if self.value_at_risk_limit < 0:
            raise ValueError("value_at_risk_limit cannot be negative")
        if not MIN_SAMPLE_RATE <= self.sample_rate <= 1:
            raise ValueError("sample_rate must be between 0.02 and 1")


@dataclass(frozen=True)
class ConfidenceSignals:
    extraction_consistency: float
    validation_severity: float
    matching_score: float
    novelty_score: float
    sender_history_score: float
    value_at_risk: float
    required_halt: bool = False
    evidence: dict[str, Any] | None = None

    def validate(self) -> None:
        for name in (
            "extraction_consistency",
            "validation_severity",
            "matching_score",
            "novelty_score",
            "sender_history_score",
        ):
            value = float(getattr(self, name))
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.value_at_risk < 0:
            raise ValueError("value_at_risk cannot be negative")


@dataclass(frozen=True)
class ConfidenceDecision:
    confidence: float
    route: str
    route_band: str
    value_at_risk_score: float
    components: dict[str, float]
    evidence: dict[str, Any]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _risk_score(value_at_risk: float, limit: float) -> float:
    if value_at_risk < 0:
        raise ValueError("value_at_risk cannot be negative")
    if limit <= 0:
        return 0.0 if value_at_risk > 0 else 1.0
    return _clamp(1.0 - (value_at_risk / limit))


def compute_confidence(signals: ConfidenceSignals, thresholds: ThresholdValues) -> ConfidenceDecision:
    """Compute and route confidence from observable signals only.

    ``validation_severity`` and ``novelty_score`` are risk scores where higher
    means less confidence.  ``value_at_risk`` is converted to a bounded quality
    component using the configured auto-risk limit.  No model confidence value
    is accepted by this function.
    """

    signals.validate()
    thresholds.validate()
    value_at_risk_score = _risk_score(signals.value_at_risk, thresholds.value_at_risk_limit)
    components = {
        "extraction_consistency": _clamp(signals.extraction_consistency),
        "validation_quality": _clamp(1.0 - signals.validation_severity),
        "matching_score": _clamp(signals.matching_score),
        "novelty_quality": _clamp(1.0 - signals.novelty_score),
        "sender_history_score": _clamp(signals.sender_history_score),
        "value_at_risk_score": value_at_risk_score,
    }
    confidence = _clamp(sum(WEIGHTS[name] * components[name] for name in WEIGHTS))

    if signals.required_halt:
        route = "halt"
        route_band = "forced_halt"
        reason = "required_halt_signal"
    elif confidence < thresholds.halt_threshold:
        route = "halt"
        route_band = "below_halt_threshold"
        reason = "confidence_below_halt_threshold"
    elif confidence < thresholds.review_threshold:
        route = "review"
        route_band = "low_confidence_review"
        reason = "confidence_below_review_threshold"
    elif confidence < thresholds.auto_threshold:
        route = "review"
        route_band = "standard_review"
        reason = "confidence_below_auto_threshold"
    elif signals.value_at_risk > thresholds.value_at_risk_limit:
        route = "review"
        route_band = "value_at_risk_review"
        reason = "value_at_risk_above_auto_limit"
    else:
        route = "auto"
        route_band = "high_confidence_auto"
        reason = "confidence_above_auto_threshold"

    return ConfidenceDecision(
        confidence=confidence,
        route=route,
        route_band=route_band,
        value_at_risk_score=value_at_risk_score,
        components=components,
        evidence={
            "formula_version": FORMULA_VERSION,
            "weights": WEIGHTS,
            "reason": reason,
            "value_at_risk_limit": thresholds.value_at_risk_limit,
            "value_at_risk_cap_applied": signals.value_at_risk > thresholds.value_at_risk_limit,
            "model_confidence_used": False,
            **(signals.evidence or {}),
        },
    )


def _stable_sample(key: str, sample_rate: float) -> bool:
    """Select a stable sample so retries cannot evade the audit boundary."""

    if not MIN_SAMPLE_RATE <= sample_rate <= 1:
        raise ValueError("sample_rate must be between 0.02 and 1")
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    bucket = int.from_bytes(digest, "big") / float(2**256)
    return bucket < sample_rate


def scope_key(workflow_version_id: str | None) -> str:
    return f"workflow-version:{workflow_version_id}" if workflow_version_id else "workspace-default"


def threshold_values(threshold: ConfidenceThresholdSet) -> ThresholdValues:
    return ThresholdValues(
        auto_threshold=threshold.auto_threshold,
        review_threshold=threshold.review_threshold,
        halt_threshold=threshold.halt_threshold,
        value_at_risk_limit=threshold.value_at_risk_limit,
        sample_rate=threshold.sample_rate,
        cost_auto_usd=threshold.cost_auto_usd,
        cost_review_usd=threshold.cost_review_usd,
        cost_halt_usd=threshold.cost_halt_usd,
    )


def threshold_payload(threshold: ConfidenceThresholdSet) -> dict[str, Any]:
    return {
        "id": threshold.id,
        "workflow_id": threshold.workflow_id,
        "workflow_version_id": threshold.workflow_version_id,
        "scope_key": threshold.scope_key,
        "version": threshold.version,
        "status": threshold.status,
        "auto_threshold": threshold.auto_threshold,
        "review_threshold": threshold.review_threshold,
        "halt_threshold": threshold.halt_threshold,
        "value_at_risk_limit": threshold.value_at_risk_limit,
        "sample_rate": threshold.sample_rate,
        "cost_auto_usd": threshold.cost_auto_usd,
        "cost_review_usd": threshold.cost_review_usd,
        "cost_halt_usd": threshold.cost_halt_usd,
        "previous_threshold_set_id": threshold.previous_threshold_set_id,
        "created_by": threshold.created_by,
        "created_at": threshold.created_at.isoformat(),
        "activated_at": threshold.activated_at.isoformat() if threshold.activated_at else None,
        "superseded_at": threshold.superseded_at.isoformat() if threshold.superseded_at else None,
        "rolled_back_at": threshold.rolled_back_at.isoformat() if threshold.rolled_back_at else None,
        "rollback_reason": threshold.rollback_reason,
    }


def assessment_payload(assessment: ConfidenceAssessment) -> dict[str, Any]:
    return {
        "id": assessment.id,
        "assessment_key": assessment.assessment_key,
        "workflow_id": assessment.workflow_id,
        "workflow_version_id": assessment.workflow_version_id,
        "threshold_set_id": assessment.threshold_set_id,
        "signals": {
            "extraction_consistency": assessment.extraction_consistency,
            "validation_severity": assessment.validation_severity,
            "matching_score": assessment.matching_score,
            "novelty_score": assessment.novelty_score,
            "sender_history_score": assessment.sender_history_score,
            "value_at_risk": assessment.value_at_risk,
            "value_at_risk_score": assessment.value_at_risk_score,
            "required_halt": assessment.required_halt,
        },
        "confidence": assessment.confidence,
        "route": assessment.route,
        "route_band": assessment.route_band,
        "evidence": assessment.evidence_json,
        "sampled_for_audit": assessment.route == "auto" and bool(assessment.evidence_json.get("sampled_for_audit")),
        "created_at": assessment.created_at.isoformat(),
    }


def audit_payload(audit: ConfidenceAudit) -> dict[str, Any]:
    return {
        "id": audit.id,
        "assessment_id": audit.assessment_id,
        "threshold_set_id": audit.threshold_set_id,
        "sample_rate": audit.sample_rate,
        "status": audit.status,
        "actual_correct": audit.actual_correct,
        "false_auto": audit.false_auto,
        "alert_code": audit.alert_code,
        "alert_message": audit.alert_message,
        "rollback_threshold_set_id": audit.rollback_threshold_set_id,
        "audited_by": audit.audited_by,
        "outcome_summary": audit.outcome_summary,
        "created_at": audit.created_at.isoformat(),
        "resolved_at": audit.resolved_at.isoformat() if audit.resolved_at else None,
    }


def get_threshold_or_404(db: Session, threshold_id: str, workspace_id: str) -> ConfidenceThresholdSet:
    threshold = db.scalar(
        select(ConfidenceThresholdSet).where(
            ConfidenceThresholdSet.id == threshold_id,
            ConfidenceThresholdSet.workspace_id == workspace_id,
        )
    )
    if threshold is None:
        raise DomainError("CONFIDENCE_THRESHOLD_NOT_FOUND", f"Threshold set {threshold_id} was not found", 404)
    return threshold


def active_threshold_set(
    db: Session,
    *,
    workspace_id: str,
    workflow_version_id: str | None,
) -> ConfidenceThresholdSet:
    if workflow_version_id:
        exact = db.scalar(
            select(ConfidenceThresholdSet)
            .where(
                ConfidenceThresholdSet.workspace_id == workspace_id,
                ConfidenceThresholdSet.workflow_version_id == workflow_version_id,
                ConfidenceThresholdSet.status == "active",
            )
            .order_by(desc(ConfidenceThresholdSet.version))
        )
        if exact is not None:
            return exact
    fallback = db.scalar(
        select(ConfidenceThresholdSet)
        .where(
            ConfidenceThresholdSet.workspace_id == workspace_id,
            ConfidenceThresholdSet.workflow_version_id.is_(None),
            ConfidenceThresholdSet.status == "active",
        )
        .order_by(desc(ConfidenceThresholdSet.version))
    )
    if fallback is None:
        raise DomainError(
            "CONFIDENCE_THRESHOLDS_NOT_CONFIGURED",
            "Publish a confidence threshold set before assessing a run",
            409,
        )
    return fallback


def create_threshold_set(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    workflow_version: WorkflowVersion | None,
    version: int | None,
    status: str,
    values: ThresholdValues,
    reason: str | None,
) -> ConfidenceThresholdSet:
    values.validate()
    key = scope_key(workflow_version.id if workflow_version else None)
    latest_version = db.scalar(
        select(func.max(ConfidenceThresholdSet.version)).where(
            ConfidenceThresholdSet.workspace_id == workspace_id,
            ConfidenceThresholdSet.scope_key == key,
        )
    ) or 0
    chosen_version = version or latest_version + 1
    if chosen_version <= latest_version:
        raise DomainError(
            "CONFIDENCE_THRESHOLD_VERSION_CONFLICT",
            f"Threshold scope {key} already has version {latest_version}; use a higher version",
            409,
        )

    previous = db.scalar(
        select(ConfidenceThresholdSet)
        .where(
            ConfidenceThresholdSet.workspace_id == workspace_id,
            ConfidenceThresholdSet.scope_key == key,
            ConfidenceThresholdSet.status == "active",
        )
        .order_by(desc(ConfidenceThresholdSet.version))
    )
    now = utc_now()
    if status == "active" and previous is not None:
        previous.status = "superseded"
        previous.superseded_at = now
    threshold = ConfidenceThresholdSet(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_id=workflow_version.workflow_id if workflow_version else None,
        workflow_version_id=workflow_version.id if workflow_version else None,
        scope_key=key,
        version=chosen_version,
        status=status,
        auto_threshold=values.auto_threshold,
        review_threshold=values.review_threshold,
        halt_threshold=values.halt_threshold,
        value_at_risk_limit=values.value_at_risk_limit,
        sample_rate=values.sample_rate,
        cost_auto_usd=values.cost_auto_usd,
        cost_review_usd=values.cost_review_usd,
        cost_halt_usd=values.cost_halt_usd,
        previous_threshold_set_id=previous.id if status == "active" and previous else None,
        created_by=actor_id,
        created_at=now,
        activated_at=now if status == "active" else None,
        rollback_reason=reason,
    )
    db.add(threshold)
    db.flush()
    return threshold


def assess(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    assessment_key: str,
    workflow_version_id: str | None,
    signals: ConfidenceSignals,
) -> tuple[ConfidenceAssessment, ConfidenceAudit | None, bool]:
    existing = db.scalar(
        select(ConfidenceAssessment).where(
            ConfidenceAssessment.workspace_id == workspace_id,
            ConfidenceAssessment.assessment_key == assessment_key,
        )
    )
    if existing is not None:
        audit = db.scalar(
            select(ConfidenceAudit).where(
                ConfidenceAudit.workspace_id == workspace_id,
                ConfidenceAudit.assessment_id == existing.id,
            )
        )
        return existing, audit, False

    threshold = active_threshold_set(
        db,
        workspace_id=workspace_id,
        workflow_version_id=workflow_version_id,
    )
    decision = compute_confidence(signals, threshold_values(threshold))
    sampled = decision.route == "auto" and _stable_sample(assessment_key, threshold.sample_rate)
    evidence = {**decision.evidence, "threshold_set_version": threshold.version, "sampled_for_audit": sampled}
    workflow_id = threshold.workflow_id if threshold.workflow_version_id == workflow_version_id else None
    if workflow_version_id and workflow_id is None:
        workflow_id = db.scalar(select(WorkflowVersion.workflow_id).where(WorkflowVersion.id == workflow_version_id))
    assessment = ConfidenceAssessment(
        id=new_id(),
        workspace_id=workspace_id,
        assessment_key=assessment_key,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        threshold_set_id=threshold.id,
        extraction_consistency=signals.extraction_consistency,
        validation_severity=signals.validation_severity,
        matching_score=signals.matching_score,
        novelty_score=signals.novelty_score,
        sender_history_score=signals.sender_history_score,
        value_at_risk=signals.value_at_risk,
        value_at_risk_score=decision.value_at_risk_score,
        confidence=decision.confidence,
        route=decision.route,
        route_band=decision.route_band,
        required_halt=signals.required_halt,
        signals_json={
            "extraction_consistency": signals.extraction_consistency,
            "validation_severity": signals.validation_severity,
            "matching_score": signals.matching_score,
            "novelty_score": signals.novelty_score,
            "sender_history_score": signals.sender_history_score,
            "value_at_risk": signals.value_at_risk,
        },
        evidence_json=evidence,
    )
    db.add(assessment)
    db.flush()
    audit: ConfidenceAudit | None = None
    if sampled:
        audit = ConfidenceAudit(
            id=new_id(),
            workspace_id=workspace_id,
            assessment_id=assessment.id,
            threshold_set_id=threshold.id,
            sample_rate=threshold.sample_rate,
            status="pending",
            created_at=utc_now(),
        )
        db.add(audit)
        db.flush()
    return assessment, audit, True


def _route_for_simulation(decision: ConfidenceDecision, signals: ConfidenceSignals, thresholds: ThresholdValues) -> str:
    return decision.route


def simulate(
    cases: Iterable[ConfidenceSignals],
    known_correct: Iterable[bool | None],
    threshold_specs: Iterable[tuple[str, ThresholdValues]],
) -> list[dict[str, Any]]:
    case_list = list(cases)
    outcome_list = list(known_correct)
    if len(case_list) != len(outcome_list):
        raise ValueError("cases and known_correct must have the same length")
    if not case_list:
        raise ValueError("at least one simulator case is required")
    results: list[dict[str, Any]] = []
    total = len(case_list)
    for label, thresholds in threshold_specs:
        auto = review = halt = 0
        known_auto = false_auto = 0
        for case, outcome in zip(case_list, outcome_list):
            decision = compute_confidence(case, thresholds)
            if decision.route == "auto":
                auto += 1
                if outcome is not None:
                    known_auto += 1
                    false_auto += int(not outcome)
            elif decision.route == "review":
                review += 1
            else:
                halt += 1
        estimated_error = (false_auto / known_auto) if known_auto else None
        cost = auto * thresholds.cost_auto_usd + review * thresholds.cost_review_usd + halt * thresholds.cost_halt_usd
        results.append(
            {
                "label": label,
                "total": total,
                "auto_count": auto,
                "review_count": review,
                "halt_count": halt,
                "auto_rate": auto / total,
                "review_rate": review / total,
                "halt_rate": halt / total,
                "known_auto_count": known_auto,
                "false_auto_count": false_auto,
                "estimated_error": estimated_error,
                "estimated_cost_usd": round(cost, 6),
                "reconciles": auto + review + halt == total,
                "thresholds": {
                    "auto_threshold": thresholds.auto_threshold,
                    "review_threshold": thresholds.review_threshold,
                    "halt_threshold": thresholds.halt_threshold,
                    "value_at_risk_limit": thresholds.value_at_risk_limit,
                },
            }
        )
    return results


def get_audit_or_404(db: Session, audit_id: str, workspace_id: str) -> ConfidenceAudit:
    audit = db.scalar(
        select(ConfidenceAudit).where(
            ConfidenceAudit.id == audit_id,
            ConfidenceAudit.workspace_id == workspace_id,
        )
    )
    if audit is None:
        raise DomainError("CONFIDENCE_AUDIT_NOT_FOUND", f"Confidence audit {audit_id} was not found", 404)
    return audit


def complete_audit(
    db: Session,
    *,
    audit: ConfidenceAudit,
    workspace_id: str,
    actor_id: str,
    actual_correct: bool,
    outcome_summary: str | None,
) -> ConfidenceAudit:
    if audit.status != "pending":
        raise DomainError("CONFIDENCE_AUDIT_ALREADY_RESOLVED", "This sampled audit already has an outcome", 409)
    assessment = db.scalar(
        select(ConfidenceAssessment).where(
            ConfidenceAssessment.id == audit.assessment_id,
            ConfidenceAssessment.workspace_id == workspace_id,
        )
    )
    if assessment is None:
        raise DomainError("CONFIDENCE_ASSESSMENT_NOT_FOUND", "The sampled assessment is no longer visible", 404)
    if assessment.route != "auto":
        raise DomainError("CONFIDENCE_AUDIT_NOT_AUTO", "Only sampled high-confidence auto-runs can be audited", 422)

    now = utc_now()
    audit.actual_correct = actual_correct
    audit.audited_by = actor_id
    audit.outcome_summary = outcome_summary
    audit.resolved_at = now
    if actual_correct:
        audit.status = "completed"
        db.flush()
        return audit

    audit.status = "alerted"
    audit.false_auto = True
    audit.alert_code = "FALSE_AUTO"
    audit.alert_message = "A sampled high-confidence auto-run was corrected by an operator; the active threshold was rolled back."
    current = db.scalar(
        select(ConfidenceThresholdSet).where(
            ConfidenceThresholdSet.id == audit.threshold_set_id,
            ConfidenceThresholdSet.workspace_id == workspace_id,
        )
    )
    rollback_target: ConfidenceThresholdSet | None = None
    if current is not None and current.status == "active":
        if current.previous_threshold_set_id:
            rollback_target = db.scalar(
                select(ConfidenceThresholdSet).where(
                    ConfidenceThresholdSet.id == current.previous_threshold_set_id,
                    ConfidenceThresholdSet.workspace_id == workspace_id,
                )
            )
        current.status = "rolled_back"
        current.rolled_back_at = now
        current.rollback_reason = audit.alert_message
        current.superseded_at = now
        if rollback_target is not None:
            rollback_target.status = "active"
            rollback_target.activated_at = now
            audit.rollback_threshold_set_id = rollback_target.id
    db.flush()
    append_audit_log(
        db,
        action="confidence.false_auto_alert",
        target_type="confidence_audit",
        target_id=audit.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={
            "assessment_id": assessment.id,
            "threshold_set_id": audit.threshold_set_id,
            "rollback_threshold_set_id": audit.rollback_threshold_set_id,
            "false_auto": True,
        },
    )
    append_audit_log(
        db,
        action="confidence.threshold.rollback",
        target_type="confidence_threshold_set",
        target_id=current.id if current else audit.threshold_set_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"rollback_threshold_set_id": audit.rollback_threshold_set_id, "reason": "false_auto"},
    )
    db.flush()
    return audit


def list_thresholds(db: Session, workspace_id: str) -> list[ConfidenceThresholdSet]:
    return db.scalars(
        select(ConfidenceThresholdSet)
        .where(ConfidenceThresholdSet.workspace_id == workspace_id)
        .order_by(desc(ConfidenceThresholdSet.created_at), desc(ConfidenceThresholdSet.version))
    ).all()


def list_audits(db: Session, workspace_id: str) -> list[ConfidenceAudit]:
    return db.scalars(
        select(ConfidenceAudit)
        .where(ConfidenceAudit.workspace_id == workspace_id)
        .order_by(desc(ConfidenceAudit.created_at), desc(ConfidenceAudit.id))
    ).all()
