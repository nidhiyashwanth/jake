"""Governance control plane: privacy, retention, incidents, model registry, and audit packs."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    AuditPack,
    GovernanceArtifact,
    GovernanceIncident,
    LegalHold,
    ModelChangeHistory,
    ModelConfig,
    RetentionPolicy,
    RetentionRun,
    Execution,
    Workflow,
    utc_now,
)
from app.schemas import (
    AuditPackRequest,
    GovernanceArtifactCreate,
    IncidentCreate,
    IncidentPatch,
    IncidentTimelineRequest,
    LegalHoldCreate,
    RetentionPolicyCreate,
    RetentionPolicyPatch,
    RetentionRunRequest,
)
from app.services.audit import append_audit_log, append_data_access_log
from app.services.authorization import authorize
from app.services.governance import (
    artifact_payload,
    audit_pack_payload,
    build_audit_pack,
    create_incident,
    governance_summary,
    incident_payload,
    legal_hold_payload,
    model_change_payload,
    redact_governance_payload,
    register_artifact,
    retention_policy_payload,
    retention_run,
    retention_run_payload,
    update_incident,
    append_incident_timeline,
)
from app.services.tenancy import current_context, get_scoped_db


router = APIRouter(prefix="/api/governance", tags=["governance"])
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _artifact_or_404(db: Session, artifact_type: str, artifact_id: str, workspace_id: str) -> GovernanceArtifact:
    artifact = db.scalar(
        select(GovernanceArtifact).where(
            GovernanceArtifact.workspace_id == workspace_id,
            GovernanceArtifact.artifact_type == artifact_type,
            GovernanceArtifact.artifact_id == artifact_id,
        )
    )
    if artifact is None:
        raise DomainError("GOVERNANCE_ARTIFACT_NOT_FOUND", "The governance artifact was not found", 404)
    return artifact


def _policy_or_404(db: Session, policy_id: str, workspace_id: str) -> RetentionPolicy:
    policy = db.scalar(select(RetentionPolicy).where(RetentionPolicy.id == policy_id, RetentionPolicy.workspace_id == workspace_id))
    if policy is None:
        raise DomainError("RETENTION_POLICY_NOT_FOUND", "The retention policy was not found", 404)
    return policy


def _hold_or_404(db: Session, hold_id: str, workspace_id: str) -> LegalHold:
    hold = db.scalar(select(LegalHold).where(LegalHold.id == hold_id, LegalHold.workspace_id == workspace_id))
    if hold is None:
        raise DomainError("LEGAL_HOLD_NOT_FOUND", "The legal hold was not found", 404)
    return hold


def _incident_or_404(db: Session, incident_id: str, workspace_id: str) -> GovernanceIncident:
    incident = db.scalar(select(GovernanceIncident).where(GovernanceIncident.id == incident_id, GovernanceIncident.workspace_id == workspace_id))
    if incident is None:
        raise DomainError("GOVERNANCE_INCIDENT_NOT_FOUND", "The governance incident was not found", 404)
    return incident


def _pack_or_404(db: Session, pack_id: str, workspace_id: str) -> AuditPack:
    pack = db.scalar(select(AuditPack).where(AuditPack.id == pack_id, AuditPack.workspace_id == workspace_id))
    if pack is None:
        raise DomainError("AUDIT_PACK_NOT_FOUND", "The audit pack was not found", 404)
    return pack


def _record_read(db: Session, *, workspace_id: str, actor_id: str, artifact_id: str, resource_type: str, purpose: str) -> None:
    append_data_access_log(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        artifact_id=artifact_id,
        resource_type=resource_type,
        purpose=purpose,
    )


@router.get("/summary")
def get_governance_summary(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    summary = governance_summary(db, workspace_id=context.workspace_id)
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="governance_summary", purpose="governance_dashboard_read")
    db.commit()
    return summary


@router.get("/artifacts")
def list_governance_artifacts(db: ScopedDb, limit: int = 200) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    rows = db.scalars(
        select(GovernanceArtifact)
        .where(GovernanceArtifact.workspace_id == context.workspace_id)
        .order_by(desc(GovernanceArtifact.created_at), desc(GovernanceArtifact.id))
        .limit(max(1, min(limit, 500)))
    ).all()
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="governance_artifacts", purpose="governance_artifact_list")
    db.commit()
    return {"items": [artifact_payload(row) for row in rows]}


@router.post("/artifacts", status_code=201)
def create_governance_artifact(payload: GovernanceArtifactCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="governance_artifact", target_id=payload.artifact_id)
    artifact = register_artifact(
        db,
        workspace_id=context.workspace_id,
        artifact_type=payload.artifact_type,
        artifact_id=payload.artifact_id,
        storage_ref=payload.storage_ref,
        sha256=payload.sha256,
        mime_type=payload.mime_type,
        payload_for_classification=payload.metadata,
    )
    append_audit_log(
        db,
        action="governance.artifact.classified",
        target_type=artifact.artifact_type,
        target_id=artifact.artifact_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"pii_status": artifact.pii_status, "classification": artifact.classification, "pii_policy_version": "pii.v1"},
    )
    db.commit()
    db.refresh(artifact)
    return artifact_payload(artifact)


@router.get("/retention-policies")
def list_retention_policies(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    rows = db.scalars(
        select(RetentionPolicy)
        .where(RetentionPolicy.workspace_id == context.workspace_id)
        .order_by(RetentionPolicy.artifact_type, RetentionPolicy.version.desc())
    ).all()
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="retention_policy", purpose="retention_policy_read")
    db.commit()
    return {"items": [retention_policy_payload(row) for row in rows]}


@router.post("/retention-policies", status_code=201)
def create_retention_policy(payload: RetentionPolicyCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="retention_policy", target_id=payload.artifact_type)
    version = int(
        db.scalar(
            select(func.max(RetentionPolicy.version)).where(
                RetentionPolicy.workspace_id == context.workspace_id,
                RetentionPolicy.artifact_type == payload.artifact_type,
            )
        )
        or 0
    ) + 1
    if payload.active:
        db.query(RetentionPolicy).filter(
            RetentionPolicy.workspace_id == context.workspace_id,
            RetentionPolicy.artifact_type == payload.artifact_type,
            RetentionPolicy.active.is_(True),
        ).update({RetentionPolicy.active: False}, synchronize_session=False)
    policy = RetentionPolicy(
        workspace_id=context.workspace_id,
        artifact_type=payload.artifact_type,
        retention_days=payload.retention_days,
        action=payload.action,
        version=version,
        active=payload.active,
        created_by=context.user_id,
    )
    db.add(policy)
    db.flush()
    append_audit_log(
        db,
        action="governance.retention_policy.created",
        target_type="retention_policy",
        target_id=policy.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"artifact_type": policy.artifact_type, "retention_days": policy.retention_days, "action": policy.action, "version": policy.version},
    )
    db.commit()
    db.refresh(policy)
    return retention_policy_payload(policy)


@router.patch("/retention-policies/{policy_id}")
def patch_retention_policy(policy_id: str, payload: RetentionPolicyPatch, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="retention_policy", target_id=policy_id)
    policy = _policy_or_404(db, policy_id, context.workspace_id)
    policy.active = payload.active
    policy.updated_at = utc_now()
    append_audit_log(
        db,
        action="governance.retention_policy.updated",
        target_type="retention_policy",
        target_id=policy.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"active": policy.active},
    )
    db.commit()
    db.refresh(policy)
    return retention_policy_payload(policy)


@router.post("/retention/run")
def run_retention(payload: RetentionRunRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="retention_run", target_id=context.workspace_id)
    run = retention_run(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        as_of=payload.as_of,
        dry_run=payload.dry_run,
    )
    append_audit_log(
        db,
        action="governance.retention_run.completed",
        target_type="retention_run",
        target_id=run.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"dry_run": run.dry_run, "eligible_count": run.eligible_count, "held_count": run.held_count, "deleted_count": run.deleted_count},
    )
    db.commit()
    db.refresh(run)
    return retention_run_payload(run)


@router.get("/retention/runs")
def list_retention_runs(db: ScopedDb, limit: int = 50) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    rows = db.scalars(
        select(RetentionRun)
        .where(RetentionRun.workspace_id == context.workspace_id)
        .order_by(desc(RetentionRun.created_at))
        .limit(max(1, min(limit, 200)))
    ).all()
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="retention_run", purpose="retention_run_read")
    db.commit()
    return {"items": [retention_run_payload(row) for row in rows]}


@router.get("/legal-holds")
def list_legal_holds(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    rows = db.scalars(select(LegalHold).where(LegalHold.workspace_id == context.workspace_id).order_by(desc(LegalHold.placed_at))).all()
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="legal_hold", purpose="legal_hold_read")
    db.commit()
    return {"items": [legal_hold_payload(row) for row in rows]}


@router.post("/legal-holds", status_code=201)
def place_legal_hold(payload: LegalHoldCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="legal_hold", target_id=payload.artifact_id)
    _artifact_or_404(db, payload.artifact_type, payload.artifact_id, context.workspace_id)
    existing = db.scalar(
        select(LegalHold).where(
            LegalHold.workspace_id == context.workspace_id,
            LegalHold.artifact_type == payload.artifact_type,
            LegalHold.artifact_id == payload.artifact_id,
            LegalHold.status == "active",
        )
    )
    if existing is not None:
        raise DomainError("LEGAL_HOLD_ALREADY_ACTIVE", "An active legal hold already exists for this artifact", 409)
    hold = LegalHold(
        workspace_id=context.workspace_id,
        artifact_type=payload.artifact_type,
        artifact_id=payload.artifact_id,
        reason=payload.reason.strip(),
        placed_by=context.user_id,
    )
    db.add(hold)
    db.flush()
    append_audit_log(
        db,
        action="governance.legal_hold.placed",
        target_type=payload.artifact_type,
        target_id=payload.artifact_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"hold_id": hold.id, "reason": redact_governance_payload(payload.reason)},
    )
    db.commit()
    db.refresh(hold)
    return legal_hold_payload(hold)


@router.post("/legal-holds/{hold_id}/release")
def release_legal_hold(hold_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="legal_hold", target_id=hold_id)
    hold = _hold_or_404(db, hold_id, context.workspace_id)
    if hold.status == "released":
        return legal_hold_payload(hold)
    hold.status = "released"
    hold.released_by = context.user_id
    hold.released_at = utc_now()
    append_audit_log(
        db,
        action="governance.legal_hold.released",
        target_type="legal_hold",
        target_id=hold.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"artifact_type": hold.artifact_type, "artifact_id": hold.artifact_id},
    )
    db.commit()
    db.refresh(hold)
    return legal_hold_payload(hold)


@router.get("/incidents")
def list_incidents(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    rows = db.scalars(select(GovernanceIncident).where(GovernanceIncident.workspace_id == context.workspace_id).order_by(desc(GovernanceIncident.detected_at))).all()
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="governance_incident", purpose="incident_read")
    db.commit()
    return {"items": [incident_payload(row) for row in rows]}


@router.post("/incidents", status_code=201)
def create_governance_incident(payload: IncidentCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="governance_incident", target_id=payload.summary[:80])
    if payload.workflow_id and db.scalar(select(Workflow.id).where(Workflow.id == payload.workflow_id, Workflow.workspace_id == context.workspace_id)) is None:
        raise DomainError("WORKFLOW_NOT_FOUND", "The incident workflow is not in the active workspace", 404)
    if payload.execution_id and db.scalar(select(Execution.id).where(Execution.id == payload.execution_id, Execution.workspace_id == context.workspace_id)) is None:
        raise DomainError("EXECUTION_NOT_FOUND", "The incident execution is not in the active workspace", 404)
    incident = create_incident(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        severity=payload.severity,
        summary=payload.summary,
        workflow_id=payload.workflow_id,
        execution_id=payload.execution_id,
        customer_notification_status=payload.customer_notification_status,
        detected_at=payload.detected_at,
        root_cause=payload.root_cause,
        postmortem_link=payload.postmortem_link,
    )
    append_audit_log(
        db,
        action="governance.incident.created",
        target_type="governance_incident",
        target_id=incident.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"severity": incident.severity, "status": incident.status, "summary": redact_governance_payload(incident.summary)},
    )
    db.commit()
    db.refresh(incident)
    return incident_payload(incident)


@router.patch("/incidents/{incident_id}")
def patch_governance_incident(incident_id: str, payload: IncidentPatch, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="governance_incident", target_id=incident_id)
    incident = _incident_or_404(db, incident_id, context.workspace_id)
    update_incident(
        db,
        incident=incident,
        actor_id=context.user_id,
        status=payload.status,
        severity=payload.severity,
        summary=payload.summary,
        root_cause=payload.root_cause,
        customer_notification_status=payload.customer_notification_status,
        postmortem_link=payload.postmortem_link,
    )
    append_audit_log(
        db,
        action="governance.incident.updated",
        target_type="governance_incident",
        target_id=incident.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"status": incident.status, "severity": incident.severity, "summary": redact_governance_payload(incident.summary)},
    )
    db.commit()
    db.refresh(incident)
    return incident_payload(incident)


@router.post("/incidents/{incident_id}/timeline")
def add_incident_timeline(incident_id: str, payload: IncidentTimelineRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.manage", target_type="governance_incident", target_id=incident_id)
    incident = _incident_or_404(db, incident_id, context.workspace_id)
    append_incident_timeline(db, incident=incident, actor_id=context.user_id, event=payload.event, details=payload.details)
    append_audit_log(
        db,
        action="governance.incident.timeline_added",
        target_type="governance_incident",
        target_id=incident.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"event": payload.event, "details": redact_governance_payload(payload.details)},
    )
    db.commit()
    db.refresh(incident)
    return incident_payload(incident)


@router.get("/model-registry")
def list_model_registry(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    configs = db.scalars(select(ModelConfig).where(ModelConfig.workspace_id == context.workspace_id).order_by(ModelConfig.key, ModelConfig.version.desc())).all()
    changes = db.scalars(select(ModelChangeHistory).where(ModelChangeHistory.workspace_id == context.workspace_id).order_by(desc(ModelChangeHistory.created_at))).all()
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="model_registry", purpose="model_registry_read")
    db.commit()
    return {
        "items": [
            {
                "id": config.id,
                "key": config.key,
                "version": config.version,
                "provider": config.provider,
                "model_id": config.model_id,
                "params": redact_governance_payload(config.params_json),
                "training_policy": config.training_policy,
                "opt_in_reference": config.opt_in_reference,
                "created_by": config.created_by,
                "created_at": config.created_at.isoformat(),
            }
            for config in configs
        ],
        "changes": [model_change_payload(change) for change in changes],
    }


@router.post("/audit-packs", status_code=201)
def create_audit_pack(payload: AuditPackRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.export", target_type="audit_pack", target_id=context.workspace_id)
    pack = build_audit_pack(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
    )
    append_audit_log(
        db,
        action="governance.audit_pack.generated",
        target_type="audit_pack",
        target_id=pack.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"sha256": pack.sha256, "schema_version": pack.schema_version},
    )
    db.commit()
    db.refresh(pack)
    return audit_pack_payload(pack)


@router.get("/audit-packs")
def list_audit_packs(db: ScopedDb, limit: int = 25) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read")
    rows = db.scalars(select(AuditPack).where(AuditPack.workspace_id == context.workspace_id).order_by(desc(AuditPack.generated_at)).limit(max(1, min(limit, 100)))).all()
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=context.workspace_id, resource_type="audit_pack", purpose="audit_pack_list")
    db.commit()
    return {"items": [{key: value for key, value in audit_pack_payload(row).items() if key != "payload"} for row in rows]}


@router.get("/audit-packs/{pack_id}")
def get_audit_pack(pack_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "governance.read", target_type="audit_pack", target_id=pack_id)
    pack = _pack_or_404(db, pack_id, context.workspace_id)
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=pack.id, resource_type="audit_pack", purpose="audit_pack_read")
    db.commit()
    return audit_pack_payload(pack)


@router.get("/audit-packs/{pack_id}/download")
def download_audit_pack(pack_id: str, db: ScopedDb) -> Response:
    context = current_context(db)
    authorize(db, context, "governance.export", target_type="audit_pack", target_id=pack_id)
    pack = _pack_or_404(db, pack_id, context.workspace_id)
    payload = audit_pack_payload(pack)
    append_audit_log(
        db,
        action="governance.audit_pack.exported",
        target_type="audit_pack",
        target_id=pack.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"sha256": pack.sha256},
    )
    _record_read(db, workspace_id=context.workspace_id, actor_id=context.user_id, artifact_id=pack.id, resource_type="audit_pack", purpose="audit_pack_export")
    db.commit()
    return Response(
        content=json.dumps(payload, sort_keys=True, ensure_ascii=True),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="audit-pack-{pack.id}.json"'},
    )
