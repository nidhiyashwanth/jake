from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="organization")


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_workspaces_organization_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="development")
    delivery_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="delivery")
    handoff_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="operator")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="workspaces")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id", name="uq_memberships_user_workspace"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
    workspace: Mapped[Workspace] = relationship()


class WorkspaceContext(Base):
    __tablename__ = "workspace_contexts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("auth_sessions.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceScopedMixin:
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)


class Process(WorkspaceScopedMixin, Base):
    __tablename__ = "processes"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_processes_workspace_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    department: Mapped[str | None] = mapped_column(String(160), nullable=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    system_of_record: Mapped[str | None] = mapped_column(String(160), nullable=True)
    trigger_json: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    inputs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    decisions_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    exceptions_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    approvals_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    outputs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    failure_modes_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    steps: Mapped[list["ProcessStep"]] = relationship(back_populates="process", cascade="all, delete-orphan")
    interviews: Mapped[list["ProcessInterview"]] = relationship(
        back_populates="process", cascade="all, delete-orphan"
    )
    baselines: Mapped[list["Baseline"]] = relationship(back_populates="process", cascade="all, delete-orphan")
    opportunity_scores: Mapped[list["OpportunityScore"]] = relationship(
        back_populates="process", cascade="all, delete-orphan"
    )


class ProcessStep(WorkspaceScopedMixin, Base):
    __tablename__ = "process_steps"
    __table_args__ = (UniqueConstraint("process_id", "seq", name="uq_process_steps_process_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    process_id: Mapped[str] = mapped_column(ForeignKey("processes.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    system: Mapped[str | None] = mapped_column(String(160), nullable=True)
    minutes_p50: Mapped[float | None] = mapped_column(Float, nullable=True)
    minutes_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_decision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    process: Mapped[Process] = relationship(back_populates="steps")


class ProcessInterview(WorkspaceScopedMixin, Base):
    __tablename__ = "process_interviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    process_id: Mapped[str] = mapped_column(ForeignKey("processes.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    transcript_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    draft_graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    exception_list: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    baseline_questions: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    captured_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    process: Mapped[Process] = relationship(back_populates="interviews")


class Baseline(WorkspaceScopedMixin, Base):
    __tablename__ = "baselines"
    __table_args__ = (UniqueConstraint("process_id", "version", name="uq_baselines_process_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    process_id: Mapped[str] = mapped_column(ForeignKey("processes.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    signed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canonical_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    supersedes_baseline_id: Mapped[str | None] = mapped_column(
        ForeignKey("baselines.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    process: Mapped[Process] = relationship(back_populates="baselines", foreign_keys=[process_id])
    supersedes: Mapped["Baseline | None"] = relationship(
        remote_side=[id], foreign_keys=[supersedes_baseline_id], uselist=False
    )
    metrics: Mapped[list["BaselineMetric"]] = relationship(
        back_populates="baseline", cascade="all, delete-orphan", order_by="BaselineMetric.key"
    )


class BaselineMetric(WorkspaceScopedMixin, Base):
    __tablename__ = "baseline_metrics"
    __table_args__ = (UniqueConstraint("baseline_id", "key", name="uq_baseline_metrics_baseline_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    baseline_id: Mapped[str] = mapped_column(ForeignKey("baselines.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="customer_asserted")
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    baseline: Mapped[Baseline] = relationship(back_populates="metrics")


class OpportunityScore(WorkspaceScopedMixin, Base):
    __tablename__ = "opportunity_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    process_id: Mapped[str] = mapped_column(ForeignKey("processes.id"), nullable=False, index=True)
    baseline_id: Mapped[str] = mapped_column(ForeignKey("baselines.id"), nullable=False, index=True)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    annual_cost: Mapped[float] = mapped_column(Float, nullable=False)
    projected_savings: Mapped[float] = mapped_column(Float, nullable=False)
    automatable_pct: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    effort_weeks: Mapped[float] = mapped_column(Float, nullable=False)
    risk_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    component_breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    input_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    process: Mapped[Process] = relationship(back_populates="opportunity_scores")


class Vendor(WorkspaceScopedMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("workspace_id", "legal_name", name="uq_vendors_workspace_legal_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    documents: Mapped[list["ComplianceDocument"]] = relationship(back_populates="vendor")
    statuses: Mapped[list["ComplianceStatus"]] = relationship(back_populates="vendor")


class ComplianceDocument(WorkspaceScopedMixin, Base):
    __tablename__ = "compliance_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extracted_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    vendor: Mapped[Vendor] = relationship(back_populates="documents")


class ComplianceCheck(WorkspaceScopedMixin, Base):
    __tablename__ = "compliance_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requirement_key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    required_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ReviewTask(WorkspaceScopedMixin, Base):
    __tablename__ = "review_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    check_id: Mapped[str] = mapped_column(ForeignKey("compliance_checks.id"), nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(80), nullable=False)
    correction_field: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceStatus(WorkspaceScopedMixin, Base):
    __tablename__ = "compliance_status"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    failing_requirements: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    computed_by_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    vendor: Mapped[Vendor] = relationship(back_populates="statuses")


class AuditEvent(WorkspaceScopedMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class DataAccessLog(Base):
    __tablename__ = "data_access_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    purpose: Mapped[str] = mapped_column(String(160), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
