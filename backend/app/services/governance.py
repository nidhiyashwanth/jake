"""Governance, privacy, retention, incident, and audit-pack services."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Iterable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    AuditEvent,
    AuditLog,
    AuditPack,
    ComplianceDocument,
    Connector,
    CredentialAccessLog,
    DataAccessLog,
    GovernanceArtifact,
    GovernanceIncident,
    LegalHold,
    ModelChangeHistory,
    ModelConfig,
    Prompt,
    PromptVersion,
    RetentionPolicy,
    RetentionRun,
    ReviewTask,
    Workflow,
    WorkflowVersion,
    new_id,
    utc_now,
)
from app.services.audit import append_audit_log
from app.services.observability import redact_untrusted
from app.services.value_ledger import rollup_value_events


PII_CLASSIFICATION_VERSION = "pii.v1"
AUDIT_PACK_SCHEMA_VERSION = "audit-pack.v1"
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d .()\-]{7,}\d)(?!\d)")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PII_KEY = re.compile(r"(?i)(^|[_\-.])(email|phone|mobile|ssn|tax[_\-.]?id|address|date[_\-.]?of[_\-.]?birth|dob|passport|driver[_\-.]?license)($|[_\-.])")
_SECRET_KEY = re.compile(r"(?i)(password|secret|token|api[_-]?key|authorization|private[_-]?key|client[_-]?secret|credential)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_MATERIAL = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _redact_text(value: str) -> str:
    if _BEARER.search(value) or _PRIVATE_MATERIAL.search(value):
        return "[REDACTED]"
    value = _EMAIL.sub("[PII EMAIL REDACTED]", value)
    value = _SSN.sub("[PII SSN REDACTED]", value)
    return _PHONE.sub("[PII PHONE REDACTED]", value)


def redact_governance_payload(value: Any, *, key: str | None = None) -> Any:
    """Redact secrets and PII values even when a caller used a generic field name."""

    if key and key.casefold() not in {"secrets_hidden"} and _SECRET_KEY.search(key):
        return "[REDACTED]"
    if key and _PII_KEY.search(key):
        return "[PII REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact_governance_payload(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_governance_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value[:20_000])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value)[:20_000])


def classify_pii_payload(value: Any) -> dict[str, Any]:
    """Return field paths only; raw PII is never persisted in the classification result."""

    flags: list[str] = []

    def walk(item: Any, path: str = "payload") -> None:
        if isinstance(item, dict):
            for item_key, child in item.items():
                child_path = f"{path}.{item_key}"
                if _PII_KEY.search(str(item_key)):
                    flags.append(child_path)
                walk(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
        elif isinstance(item, str):
            if _EMAIL.search(item) or _PHONE.search(item) or _SSN.search(item):
                flags.append(path)

    walk(value)
    unique_flags = list(dict.fromkeys(flags))
    return {
        "status": "detected" if unique_flags else "clear",
        "flags": unique_flags,
        "classification": "restricted" if unique_flags else "confidential",
        "policy_version": PII_CLASSIFICATION_VERSION,
    }


def _active_policy(db: Session, workspace_id: str, artifact_type: str) -> RetentionPolicy | None:
    exact = db.scalars(
        select(RetentionPolicy)
        .where(
            RetentionPolicy.workspace_id == workspace_id,
            RetentionPolicy.artifact_type == artifact_type,
            RetentionPolicy.active.is_(True),
        )
        .order_by(RetentionPolicy.version.desc(), RetentionPolicy.created_at.desc())
    ).first()
    if exact is not None:
        return exact
    return db.scalars(
        select(RetentionPolicy)
        .where(
            RetentionPolicy.workspace_id == workspace_id,
            RetentionPolicy.artifact_type == "*",
            RetentionPolicy.active.is_(True),
        )
        .order_by(RetentionPolicy.version.desc(), RetentionPolicy.created_at.desc())
    ).first()


def register_artifact(
    db: Session,
    *,
    workspace_id: str,
    artifact_type: str,
    artifact_id: str,
    storage_ref: str | None,
    sha256: str | None,
    mime_type: str | None,
    payload_for_classification: Any,
    created_at: datetime | None = None,
) -> GovernanceArtifact:
    classification = classify_pii_payload(payload_for_classification)
    artifact = db.scalar(
        select(GovernanceArtifact).where(
            GovernanceArtifact.workspace_id == workspace_id,
            GovernanceArtifact.artifact_type == artifact_type,
            GovernanceArtifact.artifact_id == artifact_id,
        )
    )
    if artifact is None:
        artifact = GovernanceArtifact(
            id=new_id(),
            workspace_id=workspace_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            storage_ref=storage_ref,
            sha256=sha256,
            mime_type=mime_type,
            pii_status=classification["status"],
            pii_flags_json=classification["flags"],
            classification=classification["classification"],
            created_at=created_at or utc_now(),
        )
        db.add(artifact)
        db.flush()
    policy = _active_policy(db, workspace_id, artifact_type)
    if policy and artifact.retention_until is None:
        artifact.retention_until = _as_utc(artifact.created_at) + timedelta(days=policy.retention_days)
    return artifact


def artifact_payload(artifact: GovernanceArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "artifact_id": artifact.artifact_id,
        "storage_ref": artifact.storage_ref,
        "sha256": artifact.sha256,
        "mime_type": artifact.mime_type,
        "pii_status": artifact.pii_status,
        "pii_flags": list(artifact.pii_flags_json or []),
        "classification": artifact.classification,
        "retention_until": _iso(artifact.retention_until),
        "source_deleted_at": _iso(artifact.source_deleted_at),
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
    }


def retention_policy_payload(policy: RetentionPolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "artifact_type": policy.artifact_type,
        "retention_days": policy.retention_days,
        "action": policy.action,
        "version": policy.version,
        "active": policy.active,
        "created_by": policy.created_by,
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


def legal_hold_payload(hold: LegalHold) -> dict[str, Any]:
    return {
        "id": hold.id,
        "artifact_type": hold.artifact_type,
        "artifact_id": hold.artifact_id,
        "reason": redact_governance_payload(hold.reason),
        "status": hold.status,
        "placed_by": hold.placed_by,
        "placed_at": hold.placed_at.isoformat(),
        "released_by": hold.released_by,
        "released_at": _iso(hold.released_at),
    }


def incident_payload(incident: GovernanceIncident) -> dict[str, Any]:
    return {
        "id": incident.id,
        "workflow_id": incident.workflow_id,
        "execution_id": incident.execution_id,
        "severity": incident.severity,
        "status": incident.status,
        "summary": redact_governance_payload(incident.summary),
        "root_cause": redact_governance_payload(incident.root_cause),
        "customer_notification_status": incident.customer_notification_status,
        "detected_at": incident.detected_at.isoformat(),
        "resolved_at": _iso(incident.resolved_at),
        "postmortem_link": incident.postmortem_link,
        "timeline": redact_governance_payload(incident.timeline_json or []),
        "created_by": incident.created_by,
        "updated_by": incident.updated_by,
        "created_at": incident.created_at.isoformat(),
        "updated_at": incident.updated_at.isoformat(),
    }


def create_incident(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    severity: str,
    summary: str,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    customer_notification_status: str = "not_started",
    detected_at: datetime | None = None,
    root_cause: str | None = None,
    postmortem_link: str | None = None,
) -> GovernanceIncident:
    now = utc_now()
    incident = GovernanceIncident(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        severity=severity,
        status="open",
        summary=summary.strip(),
        root_cause=root_cause.strip() if root_cause else None,
        customer_notification_status=customer_notification_status,
        detected_at=detected_at or now,
        postmortem_link=postmortem_link,
        timeline_json=[{"at": now.isoformat(), "actor_id": actor_id, "event": "incident_created"}],
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(incident)
    db.flush()
    return incident


def update_incident(
    db: Session,
    *,
    incident: GovernanceIncident,
    actor_id: str,
    status: str | None = None,
    severity: str | None = None,
    summary: str | None = None,
    root_cause: str | None = None,
    customer_notification_status: str | None = None,
    postmortem_link: str | None = None,
) -> GovernanceIncident:
    before_status = incident.status
    if status is not None:
        incident.status = status
        if status == "resolved" and incident.resolved_at is None:
            incident.resolved_at = utc_now()
        if status != "resolved":
            incident.resolved_at = None
    if severity is not None:
        incident.severity = severity
    if summary is not None:
        incident.summary = summary.strip()
    if root_cause is not None:
        incident.root_cause = root_cause.strip() or None
    if customer_notification_status is not None:
        incident.customer_notification_status = customer_notification_status
    if postmortem_link is not None:
        incident.postmortem_link = postmortem_link.strip() or None
    incident.updated_by = actor_id
    incident.updated_at = utc_now()
    if status is not None and status != before_status:
        append_incident_timeline(db, incident=incident, actor_id=actor_id, event="status_changed", details={"from": before_status, "to": status})
    db.flush()
    return incident


def append_incident_timeline(
    db: Session,
    *,
    incident: GovernanceIncident,
    actor_id: str,
    event: str,
    details: dict[str, Any] | None = None,
) -> GovernanceIncident:
    timeline = list(incident.timeline_json or [])
    timeline.append({"at": utc_now().isoformat(), "actor_id": actor_id, "event": event, "details": redact_governance_payload(details or {})})
    incident.timeline_json = timeline[-200:]
    incident.updated_by = actor_id
    incident.updated_at = utc_now()
    db.flush()
    return incident


def retention_run(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    as_of: datetime | None = None,
    dry_run: bool = True,
) -> RetentionRun:
    now = _as_utc(as_of)
    artifacts = db.scalars(
        select(GovernanceArtifact)
        .where(GovernanceArtifact.workspace_id == workspace_id, GovernanceArtifact.source_deleted_at.is_(None))
        .order_by(GovernanceArtifact.created_at.asc(), GovernanceArtifact.id.asc())
    ).all()
    active_holds = db.scalars(
        select(LegalHold).where(LegalHold.workspace_id == workspace_id, LegalHold.status == "active")
    ).all()
    held_refs = {(hold.artifact_type, hold.artifact_id) for hold in active_holds}
    decisions: list[dict[str, Any]] = []
    eligible = 0
    held = 0
    deleted = 0
    for artifact in artifacts:
        policy = _active_policy(db, workspace_id, artifact.artifact_type)
        if policy is None or policy.action == "retain":
            decisions.append({"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type, "decision": "retain", "reason": "no_delete_policy"})
            continue
        due_at = artifact.retention_until or (_as_utc(artifact.created_at) + timedelta(days=policy.retention_days))
        if due_at > now:
            decisions.append({"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type, "decision": "retain", "reason": "not_due", "due_at": due_at.isoformat()})
            continue
        if (artifact.artifact_type, artifact.artifact_id) in held_refs:
            held += 1
            decisions.append({"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type, "decision": "hold", "reason": "active_legal_hold", "due_at": due_at.isoformat()})
            continue
        eligible += 1
        decision = {"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type, "decision": "eligible", "action": policy.action, "due_at": due_at.isoformat()}
        if not dry_run:
            if artifact.artifact_type == "compliance_document":
                document = db.scalar(select(ComplianceDocument).where(ComplianceDocument.id == artifact.artifact_id, ComplianceDocument.workspace_id == workspace_id))
                if document is not None:
                    document.content = b""
                    document.status = "source_deleted"
            artifact.source_deleted_at = now
            artifact.storage_ref = None
            deleted += 1
            decision["decision"] = "source_deleted"
            append_audit_log(
                db,
                action="governance.retention.source_deleted",
                target_type=artifact.artifact_type,
                target_id=artifact.artifact_id,
                workspace_id=workspace_id,
                actor_id=actor_id,
                after={"retention_policy": policy.id, "derived_evidence_kept": True},
            )
        decisions.append(decision)
    run = RetentionRun(
        id=new_id(),
        workspace_id=workspace_id,
        as_of=now,
        dry_run=dry_run,
        scanned_count=len(artifacts),
        eligible_count=eligible,
        held_count=held,
        deleted_count=deleted,
        report_json={"policy_version": "retention.v1", "decisions": decisions},
        actor_id=actor_id,
    )
    db.add(run)
    db.flush()
    return run


def retention_run_payload(run: RetentionRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "as_of": run.as_of.isoformat(),
        "dry_run": run.dry_run,
        "scanned_count": run.scanned_count,
        "eligible_count": run.eligible_count,
        "held_count": run.held_count,
        "deleted_count": run.deleted_count,
        "report": redact_governance_payload(run.report_json or {}),
        "actor_id": run.actor_id,
        "created_at": run.created_at.isoformat(),
    }


def model_change_payload(change: ModelChangeHistory) -> dict[str, Any]:
    return {
        "id": change.id,
        "model_config_id": change.model_config_id,
        "key": change.key,
        "version": change.version,
        "provider": change.provider,
        "model_id": change.model_id,
        "prompt_key": change.prompt_key,
        "prompt_version": change.prompt_version,
        "change_type": change.change_type,
        "change_summary": redact_governance_payload(change.change_summary),
        "training_policy": change.training_policy,
        "opt_in_reference": change.opt_in_reference,
        "created_by": change.created_by,
        "created_at": change.created_at.isoformat(),
    }


def register_model_change(db: Session, *, config: ModelConfig, actor_id: str, change_summary: str | None = None) -> ModelChangeHistory:
    change = ModelChangeHistory(
        id=new_id(),
        workspace_id=config.workspace_id,
        model_config_id=config.id,
        key=config.key,
        version=config.version,
        provider=config.provider,
        model_id=config.model_id,
        change_type="registered",
        change_summary=change_summary,
        training_policy=config.training_policy,
        opt_in_reference=config.opt_in_reference,
        created_by=actor_id,
    )
    db.add(change)
    db.flush()
    return change


def _audit_row_payload(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "before": redact_governance_payload(row.before_json),
        "after": redact_governance_payload(row.after_json),
        "occurred_at": row.occurred_at.isoformat(),
    }


def _data_access_payload(row: DataAccessLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "artifact_id": row.artifact_id,
        "resource_type": row.resource_type,
        "purpose": row.purpose,
        "occurred_at": row.occurred_at.isoformat(),
    }


def _credential_access_payload(row: CredentialAccessLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "credential_id": row.credential_id,
        "action": row.action,
        "purpose": row.purpose,
        "outcome": row.outcome,
        "created_at": row.created_at.isoformat(),
    }


def _domain_audit_payload(row: AuditEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "vendor_id": row.vendor_id,
        "event_type": row.event_type,
        "actor_type": row.actor_type,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "payload": redact_governance_payload(row.payload),
        "occurred_at": row.occurred_at.isoformat(),
    }


def build_audit_pack(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    period_start: date | None = None,
    period_end: date | None = None,
) -> AuditPack:
    now = utc_now()
    period_start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc) if period_start else None
    period_end_dt = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) if period_end else None

    published = db.execute(
        select(Workflow, WorkflowVersion)
        .join(WorkflowVersion, WorkflowVersion.workflow_id == Workflow.id)
        .where(Workflow.workspace_id == workspace_id, WorkflowVersion.workspace_id == workspace_id, WorkflowVersion.status == "published")
        .order_by(Workflow.name.asc(), WorkflowVersion.version.desc())
    ).all()
    workflow_payloads = [
        {
            "workflow_id": workflow.id,
            "key": workflow.key,
            "name": workflow.name,
            "status": workflow.status,
            "version_id": version.id,
            "version": version.version,
            "definition_hash": version.definition_hash,
            "immutable_hash": version.immutable_hash,
            "baseline_id": version.baseline_id,
            "published_at": _iso(version.published_at),
            "published_by": version.published_by,
        }
        for workflow, version in published
    ]

    configs = db.scalars(select(ModelConfig).where(ModelConfig.workspace_id == workspace_id).order_by(ModelConfig.key, ModelConfig.version.desc())).all()
    changes = db.scalars(select(ModelChangeHistory).where(ModelChangeHistory.workspace_id == workspace_id).order_by(desc(ModelChangeHistory.created_at))).all()
    models_payload = [
        {
            "id": config.id,
            "key": config.key,
            "version": config.version,
            "provider": config.provider,
            "model_id": config.model_id,
            "training_policy": config.training_policy,
            "opt_in_reference": config.opt_in_reference,
            "params": redact_governance_payload(config.params_json),
            "created_at": config.created_at.isoformat(),
        }
        for config in configs
    ]
    prompts = db.scalars(select(Prompt).where(Prompt.workspace_id == workspace_id).order_by(Prompt.key)).all()
    prompt_versions = db.scalars(select(PromptVersion).where(PromptVersion.workspace_id == workspace_id).order_by(PromptVersion.prompt_id, PromptVersion.version.desc())).all()
    prompt_key_by_id = {prompt.id: prompt.key for prompt in prompts}
    prompt_payloads = [
        {
            "prompt_id": version.prompt_id,
            "key": prompt_key_by_id.get(version.prompt_id),
            "version": version.version,
            "canonical_hash": version.canonical_hash,
            "variables": list(version.variables_json or []),
            "body_included": False,
            "created_at": version.created_at.isoformat(),
        }
        for version in prompt_versions
    ]

    node_type_counts: Counter[str] = Counter()
    threshold_count = 0
    for _, version in published:
        spec = version.spec_json if isinstance(version.spec_json, dict) else {}
        nodes = spec.get("nodes", []) if isinstance(spec.get("nodes", []), list) else []
        node_type_counts.update(str(node.get("type")) for node in nodes if isinstance(node, dict) and node.get("type"))
        thresholds = spec.get("thresholds", []) if isinstance(spec.get("thresholds", []), list) else []
        threshold_count += len(thresholds)
    review_open = int(db.scalar(select(func.count(ReviewTask.id)).where(ReviewTask.workspace_id == workspace_id, ReviewTask.status == "open")) or 0)
    rollup, _ = rollup_value_events(db, workspace_id=workspace_id)

    incidents = db.scalars(select(GovernanceIncident).where(GovernanceIncident.workspace_id == workspace_id).order_by(desc(GovernanceIncident.detected_at))).all()
    policies = db.scalars(select(RetentionPolicy).where(RetentionPolicy.workspace_id == workspace_id).order_by(RetentionPolicy.artifact_type, RetentionPolicy.version.desc())).all()
    holds = db.scalars(select(LegalHold).where(LegalHold.workspace_id == workspace_id).order_by(desc(LegalHold.placed_at))).all()
    artifacts = db.scalars(select(GovernanceArtifact).where(GovernanceArtifact.workspace_id == workspace_id).order_by(GovernanceArtifact.created_at)).all()
    retention_runs = db.scalars(select(RetentionRun).where(RetentionRun.workspace_id == workspace_id).order_by(desc(RetentionRun.created_at)).limit(50)).all()
    connectors = db.scalars(select(Connector).where(Connector.workspace_id == workspace_id).order_by(Connector.name)).all()

    audit_query = select(AuditLog).where(AuditLog.workspace_id == workspace_id).order_by(desc(AuditLog.occurred_at), desc(AuditLog.id)).limit(5000)
    data_query = select(DataAccessLog).where(DataAccessLog.workspace_id == workspace_id).order_by(desc(DataAccessLog.occurred_at), desc(DataAccessLog.id)).limit(5000)
    credential_query = select(CredentialAccessLog).where(CredentialAccessLog.workspace_id == workspace_id).order_by(desc(CredentialAccessLog.created_at), desc(CredentialAccessLog.id)).limit(5000)
    domain_query = select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).order_by(desc(AuditEvent.occurred_at), desc(AuditEvent.id)).limit(5000)
    if period_start_dt:
        audit_query = audit_query.where(AuditLog.occurred_at >= period_start_dt)
        data_query = data_query.where(DataAccessLog.occurred_at >= period_start_dt)
        credential_query = credential_query.where(CredentialAccessLog.created_at >= period_start_dt)
        domain_query = domain_query.where(AuditEvent.occurred_at >= period_start_dt)
    if period_end_dt:
        audit_query = audit_query.where(AuditLog.occurred_at < period_end_dt)
        data_query = data_query.where(DataAccessLog.occurred_at < period_end_dt)
        credential_query = credential_query.where(CredentialAccessLog.created_at < period_end_dt)
        domain_query = domain_query.where(AuditEvent.occurred_at < period_end_dt)
    audit_rows = db.scalars(audit_query).all()
    data_rows = db.scalars(data_query).all()
    credential_rows = db.scalars(credential_query).all()
    domain_rows = db.scalars(domain_query).all()
    pii_counts = Counter(artifact.pii_status for artifact in artifacts)
    artifact_type_counts = Counter(artifact.artifact_type for artifact in artifacts)
    payload: dict[str, Any] = {
        "schema_version": AUDIT_PACK_SCHEMA_VERSION,
        "redaction": {"policy_version": PII_CLASSIFICATION_VERSION, "secrets_hidden": True, "pii_values_hidden": True, "prompt_bodies_excluded": True},
        "generated_at": now.isoformat(),
        "period": {"start": period_start.isoformat() if period_start else None, "end": period_end.isoformat() if period_end else None},
        "production_workflows": workflow_payloads,
        "models": models_payload,
        "model_change_history": [model_change_payload(change) for change in changes[:5000]],
        "prompts": prompt_payloads,
        "human_oversight": {
            "review_queue_open": review_open,
            "published_node_types": dict(sorted(node_type_counts.items())),
            "published_threshold_count": threshold_count,
            "operator_roles": ["owner", "admin", "operator", "auditor"],
            "approval_boundary": "top_level_orchestration_remains_deterministic; model_calls_are_bounded",
        },
        "data_flows": {
            "connectors": [{"name": connector.name, "kind": connector.kind, "status": connector.status, "egress_hosts": list(connector.egress_hosts_json or [])} for connector in connectors],
            "artifact_types": dict(sorted(artifact_type_counts.items())),
            "redact_before_model_policy": "redaction.v1",
            "training_policy_default": "no_training",
        },
        "value_realization": {"formula_version": "value.v1", "rollup": redact_governance_payload(rollup)},
        "incidents": [incident_payload(incident) for incident in incidents[:5000]],
        "retention": {
            "policies": [retention_policy_payload(policy) for policy in policies[:5000]],
            "legal_holds": [legal_hold_payload(hold) for hold in holds[:5000]],
            "runs": [retention_run_payload(run) for run in retention_runs],
            "artifact_summary": {"total": len(artifacts), "source_deleted": sum(1 for item in artifacts if item.source_deleted_at), "pii_status": dict(sorted(pii_counts.items()))},
        },
        "audit": {
            "audit_logs": [_audit_row_payload(row) for row in audit_rows],
            "data_access_logs": [_data_access_payload(row) for row in data_rows],
            "credential_access_logs": [_credential_access_payload(row) for row in credential_rows],
            "domain_events": [_domain_audit_payload(row) for row in domain_rows],
            "truncated": {"audit_logs": len(audit_rows) >= 5000, "data_access_logs": len(data_rows) >= 5000, "credential_access_logs": len(credential_rows) >= 5000, "domain_events": len(domain_rows) >= 5000},
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    pack = AuditPack(
        id=new_id(),
        workspace_id=workspace_id,
        schema_version=AUDIT_PACK_SCHEMA_VERSION,
        redaction_policy_version=PII_CLASSIFICATION_VERSION,
        payload_json=payload,
        sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        generated_by=actor_id,
        generated_at=now,
    )
    db.add(pack)
    db.flush()
    return pack


def audit_pack_payload(pack: AuditPack) -> dict[str, Any]:
    return {
        "id": pack.id,
        "schema_version": pack.schema_version,
        "redaction_policy_version": pack.redaction_policy_version,
        "sha256": pack.sha256,
        "generated_by": pack.generated_by,
        "generated_at": pack.generated_at.isoformat(),
        "payload": redact_governance_payload(pack.payload_json),
    }


def governance_summary(db: Session, *, workspace_id: str) -> dict[str, Any]:
    artifacts = db.scalars(select(GovernanceArtifact).where(GovernanceArtifact.workspace_id == workspace_id)).all()
    incidents = db.scalars(select(GovernanceIncident).where(GovernanceIncident.workspace_id == workspace_id)).all()
    holds = db.scalars(select(LegalHold).where(LegalHold.workspace_id == workspace_id, LegalHold.status == "active")).all()
    policies = db.scalars(select(RetentionPolicy).where(RetentionPolicy.workspace_id == workspace_id, RetentionPolicy.active.is_(True))).all()
    models = db.scalars(select(ModelConfig).where(ModelConfig.workspace_id == workspace_id)).all()
    latest_run = db.scalars(select(RetentionRun).where(RetentionRun.workspace_id == workspace_id).order_by(desc(RetentionRun.created_at)).limit(1)).first()
    audit_count = int(db.scalar(select(func.count(AuditLog.id)).where(AuditLog.workspace_id == workspace_id)) or 0)
    access_count = int(db.scalar(select(func.count(DataAccessLog.id)).where(DataAccessLog.workspace_id == workspace_id)) or 0)
    credential_count = int(db.scalar(select(func.count(CredentialAccessLog.id)).where(CredentialAccessLog.workspace_id == workspace_id)) or 0)
    return {
        "policy_version": PII_CLASSIFICATION_VERSION,
        "artifact_count": len(artifacts),
        "pii_detected_count": sum(1 for item in artifacts if item.pii_status == "detected"),
        "source_deleted_count": sum(1 for item in artifacts if item.source_deleted_at),
        "active_legal_hold_count": len(holds),
        "active_retention_policy_count": len(policies),
        "open_incident_count": sum(1 for incident in incidents if incident.status != "resolved"),
        "model_count": len(models),
        "audit_log_count": audit_count,
        "data_access_log_count": access_count,
        "credential_access_log_count": credential_count,
        "last_retention_run": retention_run_payload(latest_run) if latest_run else None,
        "controls": {
            "audit_logs_append_only": True,
            "data_access_logs_append_only": True,
            "credential_access_logs_append_only": True,
            "prompt_bodies_excluded_from_audit_pack": True,
            "no_training_default": all(model.training_policy == "no_training" for model in models),
        },
    }
