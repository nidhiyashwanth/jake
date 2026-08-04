from datetime import datetime, timezone
import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import DomainError
from app.models import (
    AuditEvent,
    AuditLog,
    AuthSession,
    Baseline,
    OpportunityScore,
    ComplianceDocument,
    ComplianceStatus,
    Membership,
    Organization,
    Process,
    ProcessInterview,
    ReviewTask,
    User,
    Vendor,
    Workspace,
    new_id,
)
from app.schemas import (
    DevelopmentLogin,
    DiscoveryDraftPatch,
    DiscoveryExceptionCreate,
    DiscoveryQuestionAnswer,
    BaselineCreate,
    BaselineSign,
    BaselineUpdate,
    InterviewCreate,
    InterviewUpdate,
    MemberInvite,
    MemberPatch,
    OpportunityScoreRequest,
    ProcessCreate,
    ProcessUpdate,
    ReviewUpdate,
    VendorCreate,
    WorkspaceModeUpdate,
    WorkspaceContextSwitch,
)
from app.services.audit import append_audit_log, append_data_access_log
from app.services.authorization import authorize, normalize_role, require_workspace
from app.services.compliance_catalog import DOCUMENT_TYPE_BY_ALIAS, normalize_document_type
from app.services.documents import as_date, coerce_correction, extract_document_fields
from app.services.discovery import (
    baseline_payload,
    calculate_score,
    create_baseline,
    create_interview,
    create_process,
    export_baseline,
    get_baseline_or_404,
    get_interview_or_404,
    get_process_or_404,
    get_score_or_404,
    interview_payload,
    process_payload,
    score_payload,
    sign_baseline,
    update_baseline,
    update_interview,
    update_process,
)
from app.services.repositories import get_document_or_404, get_review_or_404, get_vendor_or_404, latest_status
from app.services.review_desk import append_review_event
from app.services.tenancy import (
    RequestContext,
    create_development_session,
    current_context,
    get_scoped_db,
    switch_session_workspace,
)
from app.services.verification import history_payload, review_payload, run_verification, status_payload
from app.services.value_ledger import append_value_event
from app.services.governance import redact_governance_payload, register_artifact


router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_db)]
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _vendor_payload(vendor: Vendor, status: ComplianceStatus | None = None) -> dict[str, Any]:
    return {
        "id": vendor.id,
        "legal_name": vendor.legal_name,
        "dba_names": vendor.dba_names_json,
        "status": vendor.status,
        "risk_tier": vendor.risk_tier,
        "created_at": vendor.created_at.isoformat(),
        "latest_status": status_payload(status) if status else None,
    }


def _document_payload(document: ComplianceDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "vendor_id": document.vendor_id,
        "doc_type": document.doc_type,
        "filename": document.filename,
        "media_type": document.media_type,
        "extracted_fields": document.extracted_fields,
        "status": document.status,
        "issued_at": document.issued_at.isoformat() if document.issued_at else None,
        "expires_at": document.expires_at.isoformat() if document.expires_at else None,
        "issuer": document.issuer,
        "sha256": document.sha256,
        "superseded_by": document.superseded_by,
        "created_at": document.created_at.isoformat(),
    }


def _event_payload(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "payload": event.payload,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _context_payload(context: RequestContext) -> dict[str, Any]:
    return {
        "user": {"id": context.user_id, "email": context.user_email, "name": context.user_name},
        "organization": {"id": context.organization_id},
        "workspace": {
            "id": context.workspace_id,
            "name": context.workspace_name,
            "environment": context.workspace_environment,
            "delivery_mode": context.delivery_mode,
            "handoff_mode": context.handoff_mode,
        },
        "membership": {"id": context.membership_id, "role": context.role},
        "session_id": context.session_id,
        "development_fallback": context.development_fallback,
    }


def _workspace_context_payload(db: Session, context: RequestContext) -> dict[str, Any]:
    organization = db.get(Organization, context.organization_id)
    return {
        "id": context.workspace_id,
        "name": context.workspace_name,
        "environment": context.workspace_environment,
        "organization": {
            "id": context.organization_id,
            "name": organization.name if organization else "Workspace organization",
            "kind": organization.kind if organization else "customer",
        },
        "role": normalize_role(context.role),
        "membership_status": "active",
        "mode": context.delivery_mode,
    }


def _session_payload(db: Session, context: RequestContext) -> dict[str, Any]:
    user = db.get(User, context.user_id)
    active_session = db.get(AuthSession, context.session_id) if context.session_id else None
    memberships = db.execute(
        select(Membership, Workspace, Organization)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .join(Organization, Organization.id == Workspace.organization_id)
        .where(Membership.user_id == context.user_id, Membership.status == "active")
        .order_by(Organization.name.asc(), Workspace.name.asc())
    ).all()
    workspaces = [
        {
            "id": workspace.id,
            "name": workspace.name,
            "environment": workspace.environment,
            "organization": {"id": organization.id, "name": organization.name, "kind": organization.kind},
            "role": normalize_role(membership.role),
            "membership_status": membership.status,
            "mode": workspace.delivery_mode,
        }
        for membership, workspace, organization in memberships
    ]
    organization = db.get(Organization, context.organization_id)
    return {
        "user": {
            "id": context.user_id,
            "email": context.user_email,
            "display_name": context.user_name,
            "name": context.user_name,
            "initials": "".join(part[:1] for part in context.user_name.split()[:2]).upper() or "OP",
            "status": "active",
        },
        "organization": {
            "id": context.organization_id,
            "name": organization.name if organization else "Workspace organization",
            "kind": organization.kind if organization else "customer",
        },
        "workspaces": workspaces,
        "active_workspace_id": context.workspace_id,
        "auth_mode": "development" if get_settings().auth_provider == "development" else "provider",
        "expires_at": active_session.expires_at.isoformat() if active_session else None,
    }


def _membership_payload(membership: Membership, user: User) -> dict[str, Any]:
    return {
        "id": membership.id,
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "workspace_id": membership.workspace_id,
        "role": membership.role,
        "status": membership.status,
        "invited_at": membership.invited_at.isoformat(),
        "disabled_at": membership.disabled_at.isoformat() if membership.disabled_at else None,
    }


@router.get("/health")
def health(db: Db) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise DomainError("DATABASE_NOT_READY", "PostgreSQL is not ready", 503) from exc
    return {"status": "ok", "service": "compliance-api", "database": "up"}


@router.post("/auth/dev-login")
def development_login(payload: DevelopmentLogin, request: Request, db: Db) -> dict[str, Any]:
    result = create_development_session(
        db,
        request,
        email=payload.email,
        name=payload.name,
        organization_name=payload.organization_name,
        workspace_name=payload.workspace_name,
    )
    user = result["user"]
    workspace = result["workspace"]
    membership = result["membership"]
    session = result["session"]
    assert isinstance(user, User)
    assert isinstance(membership, Membership)
    return {
        "access_token": result["token"],
        "token_type": "bearer",
        "mode": "development_only",
        "session": {"id": session.id, "expires_at": session.expires_at.isoformat()},
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "workspace": {"id": workspace.id, "name": workspace.name},
        "role": membership.role,
    }


@router.get("/auth/me")
def get_me(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workspace.read")
    return _context_payload(context)


@router.get("/auth/session")
def get_session(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workspace.read")
    return _session_payload(db, context)


@router.post("/auth/context")
def change_context(payload: WorkspaceContextSwitch, request: Request, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    next_context = switch_session_workspace(db, request, context, payload.workspace_id)
    db.info["request_context"] = next_context
    return _context_payload(next_context)


@router.get("/workspaces")
def list_workspaces(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workspace.read")
    session_payload = _session_payload(db, context)
    return {"items": session_payload["workspaces"]}


@router.post("/workspaces/{workspace_id}/activate")
def activate_workspace(workspace_id: str, request: Request, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    next_context = switch_session_workspace(db, request, context, workspace_id)
    db.info["request_context"] = next_context
    return {"workspace": _workspace_context_payload(db, next_context), "active_workspace_id": workspace_id}


@router.patch("/workspaces/{workspace_id}/mode")
def update_workspace_mode(workspace_id: str, payload: WorkspaceModeUpdate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    require_workspace(context, workspace_id, db)
    authorize(db, context, "workspace.manage", target_type="workspace", target_id=workspace_id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise DomainError("WORKSPACE_NOT_FOUND", "The workspace was not found", 404)
    before = workspace.delivery_mode
    workspace.delivery_mode = payload.mode
    append_audit_log(
        db,
        action="workspace.mode_changed",
        target_type="workspace",
        target_id=workspace.id,
        workspace_id=workspace.id,
        actor_id=context.user_id,
        before={"mode": before},
        after={"mode": workspace.delivery_mode},
    )
    db.commit()
    refreshed_context = RequestContext(
        user_id=context.user_id,
        user_email=context.user_email,
        user_name=context.user_name,
        organization_id=context.organization_id,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        workspace_environment=workspace.environment,
        delivery_mode=workspace.delivery_mode,
        handoff_mode=workspace.handoff_mode,
        membership_id=context.membership_id,
        role=context.role,
        session_id=context.session_id,
        development_fallback=context.development_fallback,
    )
    db.info["request_context"] = refreshed_context
    return {"workspace": _workspace_context_payload(db, refreshed_context), "active_workspace_id": workspace.id}


@router.post("/auth/logout")
def logout(request: Request, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    if context.session_id is None:
        return {"revoked": False, "development_fallback": True}
    from app.models import AuthSession

    session = db.get(AuthSession, context.session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        append_audit_log(
            db,
            action="auth.logout",
            target_type="session",
            target_id=session.id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
        )
        db.commit()
    return {"revoked": True, "session_id": context.session_id}


@router.post("/processes", status_code=201)
def create_discovery_process(payload: ProcessCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.create", target_type="process", target_id=payload.name)
    process = create_process(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        payload=payload,
    )
    db.commit()
    db.refresh(process)
    return process_payload(db, process, workspace_id=context.workspace_id)


@router.get("/processes")
def list_discovery_processes(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.read")
    processes = db.scalars(
        select(Process)
        .where(Process.workspace_id == context.workspace_id)
        .order_by(Process.name.asc())
    ).all()
    items = [process_payload(db, process, workspace_id=context.workspace_id, actor_id=context.user_id) for process in processes]
    db.commit()
    return {"items": items}


@router.get("/processes/{process_id}")
def get_discovery_process(process_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.read", target_type="process", target_id=process_id)
    process = get_process_or_404(db, process_id, context.workspace_id)
    payload = process_payload(db, process, workspace_id=context.workspace_id, actor_id=context.user_id)
    db.commit()
    return payload


@router.patch("/processes/{process_id}")
def patch_discovery_process(process_id: str, payload: ProcessUpdate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.update", target_type="process", target_id=process_id)
    process = get_process_or_404(db, process_id, context.workspace_id)
    update_process(db, process, workspace_id=context.workspace_id, actor_id=context.user_id, payload=payload)
    db.commit()
    db.refresh(process)
    return process_payload(db, process, workspace_id=context.workspace_id)


@router.post("/processes/{process_id}/interviews", status_code=201)
def ingest_process_interview(process_id: str, payload: InterviewCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.interview.ingest", target_type="process", target_id=process_id)
    process = get_process_or_404(db, process_id, context.workspace_id)
    interview = create_interview(
        db,
        process,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        source_type=payload.source_type,
        source_text=payload.source_content,
        transcript_ref=payload.transcript_ref,
    )
    db.commit()
    db.refresh(interview)
    return interview_payload(interview)


@router.get("/processes/{process_id}/interviews")
def list_process_interviews(process_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.read", target_type="process", target_id=process_id)
    get_process_or_404(db, process_id, context.workspace_id)
    interviews = db.scalars(
        select(ProcessInterview)
        .where(
            ProcessInterview.process_id == process_id,
            ProcessInterview.workspace_id == context.workspace_id,
        )
        .order_by(ProcessInterview.captured_at.desc())
    ).all()
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=process_id,
        resource_type="process_interviews",
        purpose="interview_list",
    )
    db.commit()
    return {"items": [interview_payload(item) for item in interviews]}


@router.patch("/process-interviews/{interview_id}")
def patch_process_interview(interview_id: str, payload: InterviewUpdate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.update", target_type="process_interview", target_id=interview_id)
    interview = get_interview_or_404(db, interview_id, context.workspace_id)
    update_interview(
        db,
        interview,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        payload=payload,
    )
    db.commit()
    db.refresh(interview)
    return interview_payload(interview)


@router.post("/processes/{process_id}/baselines", status_code=201)
def create_discovery_baseline(process_id: str, payload: BaselineCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.create", target_type="process", target_id=process_id)
    process = get_process_or_404(db, process_id, context.workspace_id)
    baseline = create_baseline(
        db,
        process,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        raw_metrics=payload.metrics,
        notes=payload.notes,
        supersedes_baseline_id=payload.supersedes_baseline_id,
    )
    db.commit()
    db.refresh(baseline)
    return baseline_payload(db, baseline, workspace_id=context.workspace_id)


@router.get("/processes/{process_id}/baselines")
def list_discovery_baselines(process_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.read", target_type="process", target_id=process_id)
    get_process_or_404(db, process_id, context.workspace_id)
    baselines = db.scalars(
        select(Baseline)
        .where(Baseline.process_id == process_id, Baseline.workspace_id == context.workspace_id)
        .order_by(Baseline.version.desc())
    ).all()
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=process_id,
        resource_type="baselines",
        purpose="baseline_list",
    )
    db.commit()
    return {"items": [baseline_payload(db, item, workspace_id=context.workspace_id) for item in baselines]}


@router.get("/baselines/{baseline_id}")
def get_discovery_baseline(baseline_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.read", target_type="baseline", target_id=baseline_id)
    baseline = get_baseline_or_404(db, baseline_id, context.workspace_id)
    payload = baseline_payload(db, baseline, workspace_id=context.workspace_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=baseline.id,
        resource_type="baseline",
        purpose="baseline_read",
    )
    db.commit()
    return payload


@router.patch("/baselines/{baseline_id}")
def patch_discovery_baseline(baseline_id: str, payload: BaselineUpdate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.update", target_type="baseline", target_id=baseline_id)
    baseline = get_baseline_or_404(db, baseline_id, context.workspace_id)
    update_baseline(
        db,
        baseline,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        raw_metrics=payload.metrics,
        notes=payload.notes,
        fields_set=payload.model_fields_set,
    )
    db.commit()
    db.refresh(baseline)
    return baseline_payload(db, baseline, workspace_id=context.workspace_id)


@router.post("/baselines/{baseline_id}/sign")
def sign_discovery_baseline(
    baseline_id: str,
    db: ScopedDb,
    payload: BaselineSign | None = None,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.sign", target_type="baseline", target_id=baseline_id)
    baseline = get_baseline_or_404(db, baseline_id, context.workspace_id)
    sign_baseline(
        db,
        baseline,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        signature_note=payload.signature_note if payload else None,
    )
    db.commit()
    db.refresh(baseline)
    return baseline_payload(db, baseline, workspace_id=context.workspace_id)


@router.get("/baselines/{baseline_id}/export")
def export_discovery_baseline(baseline_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.read", target_type="baseline", target_id=baseline_id)
    baseline = get_baseline_or_404(db, baseline_id, context.workspace_id)
    if baseline.status != "signed":
        raise DomainError("BASELINE_NOT_SIGNED", "Only a signed baseline can be exported", 409)
    payload = export_baseline(db, baseline, workspace_id=context.workspace_id)
    append_audit_log(
        db,
        action="discovery.baseline.exported",
        target_type="baseline",
        target_id=baseline.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"canonical_hash": baseline.canonical_hash, "version": baseline.version},
    )
    db.commit()
    return payload


@router.post("/baselines/{baseline_id}/score", status_code=201)
def score_discovery_baseline(
    baseline_id: str,
    payload: OpportunityScoreRequest,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "score.compute", target_type="baseline", target_id=baseline_id)
    baseline = get_baseline_or_404(db, baseline_id, context.workspace_id)
    score = calculate_score(
        db,
        baseline,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        request_inputs=payload,
    )
    db.commit()
    db.refresh(score)
    return score_payload(score)


@router.get("/processes/{process_id}/opportunity-scores")
def list_opportunity_scores(process_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "score.read", target_type="process", target_id=process_id)
    get_process_or_404(db, process_id, context.workspace_id)
    scores = db.scalars(
        select(OpportunityScore)
        .where(OpportunityScore.process_id == process_id, OpportunityScore.workspace_id == context.workspace_id)
        .order_by(OpportunityScore.computed_at.desc())
    ).all()
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=process_id,
        resource_type="opportunity_scores",
        purpose="score_list",
    )
    db.commit()
    return {"items": [score_payload(item) for item in scores]}


@router.get("/opportunity-scores/{score_id}")
def get_opportunity_score(score_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "score.read", target_type="opportunity_score", target_id=score_id)
    score = get_score_or_404(db, score_id, context.workspace_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=score.id,
        resource_type="opportunity_score",
        purpose="score_read",
    )
    db.commit()
    return score_payload(score)


def _latest_interview(db: Session, process_id: str, workspace_id: str) -> ProcessInterview:
    interview = db.scalar(
        select(ProcessInterview)
        .where(
            ProcessInterview.process_id == process_id,
            ProcessInterview.workspace_id == workspace_id,
        )
        .order_by(ProcessInterview.captured_at.desc())
    )
    if interview is None:
        raise DomainError("DRAFT_NOT_FOUND", "Ingest an SOP or transcript before editing the discovery draft", 404)
    return interview


def _nested_baseline(db: Session, process_id: str, baseline_id: str, workspace_id: str) -> Baseline:
    baseline = get_baseline_or_404(db, baseline_id, workspace_id)
    if baseline.process_id != process_id:
        raise DomainError("BASELINE_NOT_FOUND", "The baseline does not belong to this discovery", 404)
    return baseline


@router.post("/discoveries", status_code=201)
def create_discovery_alias(payload: ProcessCreate, db: ScopedDb) -> dict[str, Any]:
    return create_discovery_process(payload, db)


@router.get("/discoveries")
def list_discoveries_alias(db: ScopedDb) -> dict[str, Any]:
    return list_discovery_processes(db)


@router.get("/discoveries/{discovery_id}")
def get_discovery_alias(discovery_id: str, db: ScopedDb) -> dict[str, Any]:
    payload = get_discovery_process(discovery_id, db)
    return {
        **payload,
        "process": payload,
        "discovery": payload,
        "ingestions": payload.get("interviews", []),
        "baseline_questions": (
            payload.get("interviews", [])[0].get("baseline_questions", [])
            if payload.get("interviews")
            else []
        ),
    }


@router.patch("/discoveries/{discovery_id}")
def patch_discovery_alias(discovery_id: str, payload: ProcessUpdate, db: ScopedDb) -> dict[str, Any]:
    return patch_discovery_process(discovery_id, payload, db)


@router.post("/discoveries/{discovery_id}/ingestions", status_code=201)
async def ingest_discovery_alias(
    discovery_id: str,
    db: ScopedDb,
    file: UploadFile | None = File(default=None),
    source_type: str = Form(default="transcript"),
    source_name: str | None = Form(default=None),
    content: str | None = Form(default=None),
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.interview.ingest", target_type="discovery", target_id=discovery_id)
    process = get_process_or_404(db, discovery_id, context.workspace_id)
    if source_type not in {"sop", "transcript", "screen_recording_narration"}:
        raise DomainError("INVALID_SOURCE_TYPE", "source_type must be sop, transcript, or screen_recording_narration", 422)
    source_text = content or ""
    if file is not None:
        source_bytes = await file.read(500_001)
        if len(source_bytes) > 500_000:
            raise DomainError("SOURCE_TOO_LARGE", "Discovery source must be at most 500000 bytes", 413)
        source_text = source_bytes.decode("utf-8", errors="replace")
        await file.close()
    if not source_text.strip():
        raise DomainError("SOURCE_REQUIRED", "An SOP or transcript file/content is required", 422)
    interview = create_interview(
        db,
        process,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        source_type=source_type,
        source_text=source_text,
        transcript_ref=source_name,
    )
    db.commit()
    db.refresh(interview)
    payload = interview_payload(interview)
    payload["ingestion_id"] = interview.id
    return payload


@router.get("/discoveries/{discovery_id}/draft")
def get_discovery_draft_alias(discovery_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.read", target_type="discovery", target_id=discovery_id)
    draft = interview_payload(_latest_interview(db, discovery_id, context.workspace_id))
    db.commit()
    return {"process_id": discovery_id, "draft": draft["draft"], **draft}


@router.patch("/discoveries/{discovery_id}/draft")
def patch_discovery_draft_alias(
    discovery_id: str,
    payload: DiscoveryDraftPatch,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.update", target_type="discovery", target_id=discovery_id)
    interview = _latest_interview(db, discovery_id, context.workspace_id)
    if "draft_graph" in payload.model_fields_set:
        graph = payload.draft_graph
        if isinstance(graph, list):
            graph = {"version": 2, "status": "draft", "publishable": False, "nodes": graph, "edges": []}
        interview.draft_graph = graph or {"version": 2, "status": "draft", "publishable": False, "nodes": [], "edges": []}
    if "exceptions" in payload.model_fields_set:
        interview.exception_list = list(payload.exceptions or [])
    if "baseline_questions" in payload.model_fields_set:
        interview.baseline_questions = list(payload.baseline_questions or [])
    append_audit_log(
        db,
        action="discovery.draft_updated",
        target_type="discovery",
        target_id=discovery_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"edited_by": payload.edited_by or "human", "interview_id": interview.id},
    )
    db.commit()
    db.refresh(interview)
    return interview_payload(interview)


@router.post("/discoveries/{discovery_id}/questions/{question_id}/answer")
def answer_discovery_question_alias(
    discovery_id: str,
    question_id: str,
    payload: DiscoveryQuestionAnswer,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.update", target_type="discovery_question", target_id=question_id)
    interview = _latest_interview(db, discovery_id, context.workspace_id)
    questions = list(interview.baseline_questions or [])
    question = next(
        (item for item in questions if isinstance(item, dict) and item.get("id") == question_id),
        None,
    )
    if question is None:
        raise DomainError("QUESTION_NOT_FOUND", "The discovery question was not found", 404)
    question["answer"] = payload.answer
    question["status"] = "answered"
    question["answered"] = True
    interview.baseline_questions = questions
    append_audit_log(
        db,
        action="discovery.question_answered",
        target_type="discovery_question",
        target_id=question_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"process_id": discovery_id, "answered_by": payload.answered_by or "human"},
    )
    db.commit()
    return {"id": question_id, "status": "answered", "question": question, "answer": payload.answer}


@router.post("/discoveries/{discovery_id}/exceptions", status_code=201)
def add_discovery_exception_alias(
    discovery_id: str,
    payload: DiscoveryExceptionCreate,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "discovery.update", target_type="discovery_exception", target_id=discovery_id)
    interview = _latest_interview(db, discovery_id, context.workspace_id)
    if payload.origin.casefold() != "human":
        raise DomainError("HUMAN_ORIGIN_REQUIRED", "Exceptions in the review surface must be captured by a human", 422)
    exception = {
        "id": new_id(),
        "code": payload.code,
        "description": payload.description,
        "frequency_per_month": payload.frequency_per_month,
        "severity": payload.severity,
        "origin": "human",
        "captured_by": payload.captured_by or context.user_id,
        "editable": True,
    }
    interview.exception_list = [*(interview.exception_list or []), exception]
    append_audit_log(
        db,
        action="discovery.exception_created",
        target_type="discovery_exception",
        target_id=exception["id"],
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"process_id": discovery_id, "origin": "human", "code": payload.code},
    )
    db.commit()
    return exception


@router.post("/discoveries/{discovery_id}/baselines", status_code=201)
def create_discovery_baseline_alias(
    discovery_id: str,
    payload: BaselineCreate,
    db: ScopedDb,
) -> dict[str, Any]:
    return create_discovery_baseline(discovery_id, payload, db)


@router.get("/discoveries/{discovery_id}/baselines")
def list_discovery_baselines_alias(discovery_id: str, db: ScopedDb) -> dict[str, Any]:
    return list_discovery_baselines(discovery_id, db)


@router.get("/discoveries/{discovery_id}/baselines/{baseline_id}")
def get_nested_discovery_baseline(discovery_id: str, baseline_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.read", target_type="baseline", target_id=baseline_id)
    baseline = _nested_baseline(db, discovery_id, baseline_id, context.workspace_id)
    db.commit()
    return baseline_payload(db, baseline, workspace_id=context.workspace_id)


@router.post("/discoveries/{discovery_id}/baselines/{baseline_id}/sign")
def sign_nested_discovery_baseline(
    discovery_id: str,
    baseline_id: str,
    payload: BaselineSign,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.sign", target_type="baseline", target_id=baseline_id)
    baseline = _nested_baseline(db, discovery_id, baseline_id, context.workspace_id)
    sign_baseline(
        db,
        baseline,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        signature_note=payload.attestation or payload.signature_note,
    )
    db.commit()
    db.refresh(baseline)
    return baseline_payload(db, baseline, workspace_id=context.workspace_id)


@router.get("/discoveries/{discovery_id}/baselines/{baseline_id}/export")
def export_nested_discovery_baseline(discovery_id: str, baseline_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "baseline.read", target_type="baseline", target_id=baseline_id)
    baseline = _nested_baseline(db, discovery_id, baseline_id, context.workspace_id)
    if baseline.status != "signed":
        raise DomainError("BASELINE_NOT_SIGNED", "Only a signed baseline can be exported", 409)
    payload = export_baseline(db, baseline, workspace_id=context.workspace_id)
    append_audit_log(
        db,
        action="discovery.baseline.exported",
        target_type="baseline",
        target_id=baseline.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"canonical_hash": baseline.canonical_hash, "version": baseline.version},
    )
    db.commit()
    return payload


@router.post("/discoveries/{discovery_id}/baselines/{baseline_id}/scores", status_code=201)
def score_nested_discovery_baseline(
    discovery_id: str,
    baseline_id: str,
    payload: OpportunityScoreRequest,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "score.compute", target_type="baseline", target_id=baseline_id)
    _nested_baseline(db, discovery_id, baseline_id, context.workspace_id)
    score = calculate_score(
        db,
        get_baseline_or_404(db, baseline_id, context.workspace_id),
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        request_inputs=payload,
    )
    db.commit()
    db.refresh(score)
    return {"score": score_payload(score), **score_payload(score)}


@router.post("/baselines/{baseline_id}/scores", status_code=201)
def score_discovery_baseline_plural(
    baseline_id: str,
    payload: OpportunityScoreRequest,
    db: ScopedDb,
) -> dict[str, Any]:
    return score_discovery_baseline(baseline_id, payload, db)


@router.post("/vendors", status_code=201)
def create_vendor(payload: VendorCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "vendor.create", target_type="vendor", target_id=payload.legal_name)
    vendor = Vendor(
        workspace_id=context.workspace_id,
        legal_name=payload.legal_name,
        dba_names_json=payload.dba_names,
        risk_tier=payload.risk_tier,
    )
    db.add(vendor)
    try:
        db.flush()
        append_audit_log(
            db,
            action="vendor.created",
            target_type="vendor",
            target_id=vendor.id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            after={"legal_name": vendor.legal_name},
        )
        db.commit()
        db.refresh(vendor)
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("VENDOR_ALREADY_EXISTS", "A vendor with this legal name already exists", 409) from exc
    return _vendor_payload(vendor)


@router.get("/vendors")
def list_vendors(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "vendor.read")
    vendors = db.scalars(
        select(Vendor)
        .where(Vendor.workspace_id == context.workspace_id)
        .order_by(Vendor.legal_name.asc())
    ).all()
    items = [_vendor_payload(vendor, latest_status(db, vendor.id)) for vendor in vendors]
    for vendor in vendors:
        append_data_access_log(
            db,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            artifact_id=vendor.id,
            resource_type="vendor",
            purpose="vendor_list",
        )
    db.commit()
    return {"items": items}


@router.get("/vendors/{vendor_id}")
def get_vendor(vendor_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "vendor.read", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    documents = db.scalars(
        select(ComplianceDocument)
        .where(
            ComplianceDocument.vendor_id == vendor.id,
            ComplianceDocument.workspace_id == context.workspace_id,
        )
        .order_by(desc(ComplianceDocument.created_at))
    ).all()
    events = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.vendor_id == vendor.id,
            AuditEvent.workspace_id == context.workspace_id,
        )
        .order_by(desc(AuditEvent.occurred_at))
        .limit(50)
    ).all()
    vendor_status = latest_status(db, vendor.id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=vendor.id,
        resource_type="vendor",
        purpose="vendor_detail",
    )
    for document in documents:
        append_data_access_log(
            db,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            artifact_id=document.id,
            resource_type="compliance_document",
            purpose="vendor_detail",
        )
    db.commit()
    return {
        **_vendor_payload(vendor, vendor_status),
        "documents": [_document_payload(document) for document in documents],
        "recent_events": [_event_payload(event) for event in events],
    }


@router.post("/vendors/{vendor_id}/documents", status_code=201)
async def upload_document(
    vendor_id: str,
    db: ScopedDb,
    file: Annotated[UploadFile, File(...)],
    doc_type: Annotated[str, Form()] = "COI",
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "document.upload", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    normalized_doc_type = normalize_document_type(doc_type)
    if normalized_doc_type not in set(DOCUMENT_TYPE_BY_ALIAS.values()):
        raise DomainError("DOCUMENT_TYPE_UNSUPPORTED", f"The v1 document taxonomy does not include {doc_type}", 422)
    content = await file.read()
    from app.config import get_settings

    if len(content) > get_settings().max_upload_bytes:
        raise DomainError("DOCUMENT_TOO_LARGE", "The uploaded document exceeds the 10 MB MVP limit", 413)
    filename = file.filename or "uploaded-coi.txt"
    media_type = file.content_type or "application/octet-stream"
    fields = extract_document_fields(content, filename, media_type, normalized_doc_type)
    now = datetime.now(timezone.utc)
    expiry_value = next(
        (fields.get(key) for key in ("policy_expiry", "license_expiry", "business_license_expiry", "osha_expiry") if fields.get(key)),
        None,
    )
    expiry_date = as_date(expiry_value)
    issued_value = fields.get("policy_effective") or fields.get("issued_at")
    issued_date = as_date(issued_value)
    document = ComplianceDocument(
        workspace_id=context.workspace_id,
        vendor_id=vendor.id,
        doc_type=normalized_doc_type,
        filename=filename,
        media_type=media_type,
        content=content,
        extracted_fields=fields,
        status="received",
        issued_at=datetime.combine(issued_date, datetime.min.time(), tzinfo=timezone.utc) if issued_date else None,
        expires_at=datetime.combine(expiry_date, datetime.min.time(), tzinfo=timezone.utc) if expiry_date else None,
        issuer=fields.get("carrier") if isinstance(fields.get("carrier"), str) else None,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    db.add(document)
    db.flush()
    register_artifact(
        db,
        workspace_id=context.workspace_id,
        artifact_type="compliance_document",
        artifact_id=document.id,
        storage_ref=f"db://compliance_documents/{document.id}",
        sha256=document.sha256,
        mime_type=document.media_type,
        payload_for_classification=fields,
        created_at=now,
    )
    previous_documents = db.scalars(
        select(ComplianceDocument).where(
            ComplianceDocument.workspace_id == context.workspace_id,
            ComplianceDocument.vendor_id == vendor.id,
            ComplianceDocument.doc_type == normalized_doc_type,
            ComplianceDocument.id != document.id,
            ComplianceDocument.superseded_by.is_(None),
        )
    ).all()
    for previous in previous_documents:
        previous.status = "superseded"
        previous.superseded_by = document.id
        previous.superseded_at = now
        db.add(
            AuditEvent(
                workspace_id=context.workspace_id,
                vendor_id=vendor.id,
                event_type="document_superseded",
                actor_type="operator",
                entity_type="compliance_document",
                entity_id=previous.id,
                payload={"superseded_by": document.id, "doc_type": normalized_doc_type},
                occurred_at=now,
            )
        )
    db.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            vendor_id=vendor.id,
            event_type="document_uploaded",
            actor_type="operator",
            entity_type="compliance_document",
            entity_id=document.id,
            payload={"filename": filename, "doc_type": normalized_doc_type, "extracted_fields": redact_governance_payload(fields)},
        )
    )
    append_audit_log(
        db,
        action="document.uploaded",
        target_type="compliance_document",
        target_id=document.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"filename": filename, "doc_type": normalized_doc_type, "fields": redact_governance_payload(fields), "pii_policy_version": "pii.v1"},
    )
    db.commit()
    db.refresh(document)
    return _document_payload(document)


@router.post("/documents/{document_id}/verify")
def verify_document(document_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "document.verify", target_type="compliance_document", target_id=document_id)
    document = get_document_or_404(db, document_id)
    if document.status == "source_deleted":
        raise DomainError("SOURCE_CONTENT_DELETED", "Retention has deleted the source content; derived evidence remains available", 410)
    vendor = get_vendor_or_404(db, document.vendor_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=document.id,
        resource_type="compliance_document",
        purpose="verification",
    )
    return run_verification(db, vendor, document, actor_type=context.role)


@router.get("/vendors/{vendor_id}/status")
def get_status(vendor_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "vendor.read", target_type="vendor", target_id=vendor_id)
    get_vendor_or_404(db, vendor_id)
    current = latest_status(db, vendor_id)
    if current is None:
        raise DomainError("STATUS_NOT_FOUND", "Verify a COI before requesting compliance status", 404)
    history = history_payload(db, vendor_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=vendor_id,
        resource_type="compliance_status",
        purpose="status_read",
    )
    db.commit()
    return {"current": status_payload(current), "history": history}


@router.get("/vendors/{vendor_id}/ledger")
def get_ledger(vendor_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "audit.read", target_type="vendor", target_id=vendor_id)
    get_vendor_or_404(db, vendor_id)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.vendor_id == vendor_id, AuditEvent.workspace_id == context.workspace_id)
        .order_by(desc(AuditEvent.occurred_at), desc(AuditEvent.id))
    ).all()
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=vendor_id,
        resource_type="audit_ledger",
        purpose="ledger_read",
    )
    db.commit()
    return {"items": [_event_payload(event) for event in events]}


@router.get("/reviews")
def list_reviews(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "review.read")
    rows = db.execute(
        select(ReviewTask, Vendor.legal_name)
        .join(Vendor, Vendor.id == ReviewTask.vendor_id)
        .where(
            ReviewTask.status == "open",
            ReviewTask.workspace_id == context.workspace_id,
            Vendor.workspace_id == context.workspace_id,
        )
        .order_by(ReviewTask.created_at.asc())
    ).all()
    items = []
    for review, legal_name in rows:
        item = review_payload(review)
        item["vendor_legal_name"] = legal_name
        items.append(item)
    return {"items": items}


@router.patch("/reviews/{review_id}")
def update_review(review_id: str, payload: ReviewUpdate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "review.update", target_type="review_task", target_id=review_id)
    review = get_review_or_404(db, review_id)
    if review.status != "open":
        raise DomainError("REVIEW_NOT_OPEN", "This review task has already been resolved or superseded", 409)
    if not payload.reason_code:
        raise DomainError("CORRECTION_REASON_REQUIRED", "A reason code is required for every human correction", 422)
    if payload.field and payload.field != review.correction_field:
        raise DomainError("CORRECTION_FIELD_MISMATCH", f"This task expects {review.correction_field}", 422)
    document = get_document_or_404(db, review.document_id)
    vendor = get_vendor_or_404(db, review.vendor_id)
    corrected = coerce_correction(review.correction_field, payload.value)
    fields = dict(document.extracted_fields)
    before_value = fields.get(review.correction_field)
    fields[review.correction_field] = corrected
    document.extracted_fields = fields
    review.status = "resolved"
    review.resolved_at = datetime.now(timezone.utc)
    review.correction_reason_code = payload.reason_code
    review.correction_note = payload.note
    review.before_value_json = before_value
    review.after_value_json = corrected
    review.last_touched_at = review.resolved_at
    review.updated_at = review.resolved_at
    append_review_event(
        db,
        review,
        actor_id=context.user_id,
        event_type="review.correction_applied",
        from_status="open",
        to_status="resolved",
        payload={
            "field": review.correction_field,
            "reason_code": payload.reason_code,
            "note": payload.note,
            "before": before_value,
            "after": corrected,
        },
    )
    audit_event = AuditEvent(
        id=new_id(),
        workspace_id=context.workspace_id,
        vendor_id=vendor.id,
        event_type="review_correction_applied",
        actor_type="human_operator",
        entity_type="review_task",
        entity_id=review.id,
        payload={"field": review.correction_field, "value": corrected, "document_id": document.id},
    )
    db.add(audit_event)
    append_value_event(
        db,
        workspace_id=context.workspace_id,
        event_key=f"review:{review.id}:resolved",
        source_artifact_type="review_task",
        source_artifact_id=review.id,
        review_task_id=review.id,
        audit_event_id=audit_event.id,
        kind="human_touch_cost",
        quantity=1,
        unit="review",
        dollar_value=0,
        method="measured_ab",
        confidence="low",
        metadata={"outcome": "reviewed", "valuation_status": "unpriced_review_correction", "actor_id": context.user_id},
    )
    append_audit_log(
        db,
        action="review.correction_applied",
        target_type="review_task",
        target_id=review.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"field": review.correction_field, "value": corrected, "reason_code": payload.reason_code, "document_id": document.id},
    )
    db.flush()
    return run_verification(db, vendor, document, actor_type=context.role)


@router.get("/workspaces/{workspace_id}/members")
def list_members(workspace_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    require_workspace(context, workspace_id, db)
    authorize(db, context, "member.read", target_type="workspace", target_id=workspace_id)
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(User.email.asc())
    ).all()
    return {"items": [_membership_payload(membership, user) for membership, user in rows]}


@router.post("/workspaces/{workspace_id}/members", status_code=201)
def invite_member(workspace_id: str, payload: MemberInvite, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    require_workspace(context, workspace_id, db)
    authorize(db, context, "member.invite", target_type="workspace", target_id=workspace_id)
    role = normalize_role(payload.role)
    if role == "owner" and context.role != "owner":
        authorize(db, context, "member.role_change", target_type="membership", target_id=payload.email)
    normalized_email = payload.email.casefold()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(email=normalized_email, name=payload.name)
        db.add(user)
        db.flush()
    existing = db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == workspace_id)
    )
    if existing is not None:
        raise DomainError("MEMBERSHIP_ALREADY_EXISTS", "This user already has a membership in the workspace", 409)
    membership = Membership(user_id=user.id, workspace_id=workspace_id, role=role, status="active")
    db.add(membership)
    db.flush()
    append_audit_log(
        db,
        action="membership.invited",
        target_type="membership",
        target_id=membership.id,
        workspace_id=workspace_id,
        actor_id=context.user_id,
        after={"user_id": user.id, "role": role},
    )
    db.commit()
    return _membership_payload(membership, user)


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
def update_member(workspace_id: str, user_id: str, payload: MemberPatch, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    require_workspace(context, workspace_id, db)
    if payload.role is not None:
        authorize(db, context, "member.role_change", target_type="membership", target_id=user_id)
    if payload.disabled is not None:
        authorize(db, context, "member.disable", target_type="membership", target_id=user_id)

    membership = db.scalar(
        select(Membership).where(Membership.user_id == user_id, Membership.workspace_id == workspace_id)
    )
    user = db.get(User, user_id)
    if membership is None or user is None:
        raise DomainError("MEMBERSHIP_NOT_FOUND", "The workspace membership was not found", 404)
    if membership.role == "owner" and context.role != "owner" and (payload.role or payload.disabled is not None):
        append_audit_log(
            db,
            action="authorization.denied",
            target_type="membership",
            target_id=membership.id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            after={"reason": "owner_protected"},
        )
        db.commit()
        raise DomainError("OWNER_PROTECTED", "Only an owner can change another owner's membership", 403)
    if user.id == context.user_id and payload.disabled is True:
        raise DomainError("SELF_DISABLE_FORBIDDEN", "A user cannot disable their active session membership", 409)
    if payload.role == "owner" and context.role != "owner":
        raise DomainError("OWNER_ROLE_FORBIDDEN", "Only an owner can grant the owner role", 403)
    if membership.role == "owner" and payload.role is not None and normalize_role(payload.role) != "owner":
        other_owner = db.scalar(
            select(Membership.id).where(
                Membership.workspace_id == workspace_id,
                Membership.role == "owner",
                Membership.status == "active",
                Membership.id != membership.id,
            )
        )
        if other_owner is None:
            raise DomainError("LAST_OWNER_PROTECTED", "The workspace must retain an active owner", 409)
    if payload.disabled is True and membership.role == "owner" and membership.status == "active":
        owner_count = db.scalar(
            select(Membership.id).where(
                Membership.workspace_id == workspace_id,
                Membership.role == "owner",
                Membership.status == "active",
                Membership.id != membership.id,
            )
        )
        if owner_count is None:
            raise DomainError("LAST_OWNER_PROTECTED", "The workspace must retain an active owner", 409)

    before = {"role": membership.role, "status": membership.status}
    if payload.role is not None:
        membership.role = normalize_role(payload.role)
    if payload.disabled is not None:
        membership.status = "disabled" if payload.disabled else "active"
        membership.disabled_at = datetime.now(timezone.utc) if payload.disabled else None
    append_audit_log(
        db,
        action="membership.updated",
        target_type="membership",
        target_id=membership.id,
        workspace_id=workspace_id,
        actor_id=context.user_id,
        before=before,
        after={"role": membership.role, "status": membership.status},
    )
    db.commit()
    return _membership_payload(membership, user)


@router.get("/audit")
def list_audit_logs(db: ScopedDb, limit: int = 100) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "audit.read")
    bounded_limit = min(max(limit, 1), 500)
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.workspace_id == context.workspace_id)
        .order_by(desc(AuditLog.occurred_at), desc(AuditLog.id))
        .limit(bounded_limit)
    ).all()
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=context.workspace_id,
        resource_type="audit_log",
        purpose="audit_read",
    )
    db.commit()
    return {
        "items": [
            {
                "id": row.id,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "actor_id": row.actor_id,
                "before": row.before_json,
                "after": row.after_json,
                "ip_address": row.ip_address,
                "occurred_at": row.occurred_at.isoformat(),
            }
            for row in rows
        ]
    }
