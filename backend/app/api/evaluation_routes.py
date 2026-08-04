"""HTTP boundary for rights-labelled golden sets, evaluation gates, and drift."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import DriftSnapshot, GoldenSet, WorkflowEvaluationResult, WorkflowVersion
from app.schemas import DriftSnapshotRequest, GoldenEvaluationRunRequest, GoldenSetCreate
from app.services.audit import append_audit_log
from app.services.authorization import authorize
from app.services.evaluations import (
    DriftObservation,
    create_golden_set,
    drift_payload,
    get_golden_set_or_404,
    golden_set_payload,
    list_drift_snapshots,
    list_golden_sets,
    record_drift_snapshot,
    run_golden_evaluation,
)
from app.services.tenancy import current_context, get_scoped_db
from app.services.workflow import evaluation_gate_payload, evaluation_payload


router = APIRouter(prefix="/api")
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _version_or_404(db: Session, version_id: str, workspace_id: str) -> WorkflowVersion:
    version = db.scalar(select(WorkflowVersion).where(WorkflowVersion.id == version_id, WorkflowVersion.workspace_id == workspace_id))
    if version is None:
        raise DomainError("WORKFLOW_VERSION_NOT_FOUND", f"Workflow version {version_id} was not found", 404)
    return version


@router.get("/evaluations/golden-sets")
def list_evaluation_golden_sets(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.read", target_type="golden_set")
    items = list_golden_sets(db, context.workspace_id)
    return {"items": [golden_set_payload(db, item, include_cases=False) for item in items], "count": len(items)}


@router.post("/evaluations/golden-sets", status_code=201)
def create_evaluation_golden_set(payload: GoldenSetCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.write", target_type="golden_set")
    version = _version_or_404(db, payload.workflow_version_id, context.workspace_id)
    golden_set = create_golden_set(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        workflow_version=version,
        name=payload.name,
        version=payload.version,
        status=payload.status,
        source_policy=payload.source_policy,
        gate=payload.gate.model_dump(),
        cases=[item.model_dump() for item in payload.cases],
    )
    append_audit_log(
        db,
        action="evaluation.golden_set.created",
        target_type="golden_set",
        target_id=golden_set.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"workflow_version_id": version.id, "case_count": len(payload.cases), "canonical_hash": golden_set.canonical_hash, "status": golden_set.status},
    )
    db.commit()
    db.refresh(golden_set)
    return {"golden_set": golden_set_payload(db, golden_set)}


@router.get("/evaluations/golden-sets/{golden_set_id}")
def get_evaluation_golden_set(golden_set_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.read", target_type="golden_set", target_id=golden_set_id)
    golden_set = get_golden_set_or_404(db, golden_set_id, context.workspace_id)
    return {"golden_set": golden_set_payload(db, golden_set)}


@router.post("/workflow-versions/{version_id}/evaluations/golden", status_code=201)
def run_evaluation_golden_set(version_id: str, payload: GoldenEvaluationRunRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.write", target_type="workflow_version", target_id=version_id)
    version = _version_or_404(db, version_id, context.workspace_id)
    golden_set = get_golden_set_or_404(db, payload.golden_set_id, context.workspace_id)
    result = run_golden_evaluation(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        workflow_version=version,
        golden_set=golden_set,
        baseline_evaluation_id=payload.baseline_evaluation_id,
    )
    db.commit()
    db.refresh(result)
    return {
        "evaluation": evaluation_payload(result),
        "passed": result.passed,
        "failure_reasons": result.failure_reasons_json,
        "failing_cases": result.failing_cases_json,
        "evaluation_gate": evaluation_gate_payload(db, version),
    }


@router.get("/evaluations/drift")
def list_evaluation_drift(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.read", target_type="drift_snapshot")
    items = list_drift_snapshots(db, context.workspace_id)
    return {"items": [drift_payload(item) for item in items], "count": len(items)}


@router.post("/evaluations/drift", status_code=201)
def record_evaluation_drift(payload: DriftSnapshotRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.write", target_type="drift_snapshot")
    _version_or_404(db, payload.workflow_version_id, context.workspace_id)
    snapshot = record_drift_snapshot(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        workflow_version_id=payload.workflow_version_id,
        window_key=payload.window_key,
        observations=[DriftObservation(sender=item.sender, document_type=item.document_type, corrected=item.corrected) for item in payload.observations],
        baseline_correction_rate=payload.baseline_correction_rate,
        max_delta=payload.max_delta,
        min_samples=payload.min_samples,
    )
    db.commit()
    db.refresh(snapshot)
    return {"snapshot": drift_payload(snapshot), "alerted": snapshot.status == "alert"}
