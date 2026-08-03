from datetime import datetime, timezone
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
)
from app.schemas import (
    DevelopmentLogin,
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
from app.services.documents import coerce_correction, extract_document_fields
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
from app.services.tenancy import (
    RequestContext,
    create_development_session,
    current_context,
    get_scoped_db,
    switch_session_workspace,
)
from app.services.verification import history_payload, review_payload, run_verification, status_payload


router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_db)]
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _vendor_payload(vendor: Vendor, status: ComplianceStatus | None = None) -> dict[str, Any]:
    return {
        "id": vendor.id,
        "legal_name": vendor.legal_name,
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


@router.post("/vendors", status_code=201)
def create_vendor(payload: VendorCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "vendor.create", target_type="vendor", target_id=payload.legal_name)
    vendor = Vendor(workspace_id=context.workspace_id, legal_name=payload.legal_name)
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
    if doc_type.upper() != "COI":
        raise DomainError("DOCUMENT_TYPE_UNSUPPORTED", "The MVP upload path accepts doc_type=COI", 422)
    content = await file.read()
    from app.config import get_settings

    if len(content) > get_settings().max_upload_bytes:
        raise DomainError("DOCUMENT_TOO_LARGE", "The uploaded document exceeds the 10 MB MVP limit", 413)
    filename = file.filename or "uploaded-coi.txt"
    media_type = file.content_type or "application/octet-stream"
    fields = extract_document_fields(content, filename, media_type)
    document = ComplianceDocument(
        workspace_id=context.workspace_id,
        vendor_id=vendor.id,
        doc_type="COI",
        filename=filename,
        media_type=media_type,
        content=content,
        extracted_fields=fields,
    )
    db.add(document)
    db.flush()
    db.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            vendor_id=vendor.id,
            event_type="document_uploaded",
            actor_type="operator",
            entity_type="compliance_document",
            entity_id=document.id,
            payload={"filename": filename, "doc_type": "COI", "extracted_fields": fields},
        )
    )
    append_audit_log(
        db,
        action="document.uploaded",
        target_type="compliance_document",
        target_id=document.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"filename": filename, "doc_type": "COI", "fields": fields},
    )
    db.commit()
    db.refresh(document)
    return _document_payload(document)


@router.post("/documents/{document_id}/verify")
def verify_document(document_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "document.verify", target_type="compliance_document", target_id=document_id)
    document = get_document_or_404(db, document_id)
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
    if payload.field and payload.field != review.correction_field:
        raise DomainError("CORRECTION_FIELD_MISMATCH", f"This task expects {review.correction_field}", 422)
    document = get_document_or_404(db, review.document_id)
    vendor = get_vendor_or_404(db, review.vendor_id)
    corrected = coerce_correction(review.correction_field, payload.value)
    fields = dict(document.extracted_fields)
    fields[review.correction_field] = corrected
    document.extracted_fields = fields
    review.status = "resolved"
    review.resolved_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            vendor_id=vendor.id,
            event_type="review_correction_applied",
            actor_type="human_operator",
            entity_type="review_task",
            entity_id=review.id,
            payload={"field": review.correction_field, "value": corrected, "document_id": document.id},
        )
    )
    append_audit_log(
        db,
        action="review.correction_applied",
        target_type="review_task",
        target_id=review.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"field": review.correction_field, "value": corrected, "document_id": document.id},
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
