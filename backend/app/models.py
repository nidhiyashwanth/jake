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
    dba_names_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tax_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    risk_tier: Mapped[str] = mapped_column(String(24), nullable=False, default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    documents: Mapped[list["ComplianceDocument"]] = relationship(back_populates="vendor")
    statuses: Mapped[list["ComplianceStatus"]] = relationship(back_populates="vendor")
    entities: Mapped[list["VendorEntity"]] = relationship(back_populates="vendor", cascade="all, delete-orphan")
    requirement_bindings: Mapped[list["VendorRequirement"]] = relationship(back_populates="vendor", cascade="all, delete-orphan")
    chase_threads: Mapped[list["ChaseThread"]] = relationship(back_populates="vendor", cascade="all, delete-orphan")


class ComplianceDocument(WorkspaceScopedMixin, Base):
    __tablename__ = "compliance_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extracted_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="received")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(240), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("compliance_documents.id"), nullable=True, index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    vendor: Mapped[Vendor] = relationship(back_populates="documents")


class ComplianceCheck(WorkspaceScopedMixin, Base):
    __tablename__ = "compliance_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requirement_key: Mapped[str] = mapped_column(String(80), nullable=False)
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_requirements.id"), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    priority_band: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    priority_factors_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    assigned_to_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_minutes: Mapped[int] = mapped_column(nullable=False, default=60)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    escalation_level: Mapped[int] = mapped_column(nullable=False, default=0)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    after_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_touched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["ReviewTaskEvent"]] = relationship(back_populates="review_task", cascade="all, delete-orphan")


class ReviewTaskEvent(WorkspaceScopedMixin, Base):
    """Append-only operator history for assignment, correction, and escalation."""

    __tablename__ = "review_task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_task_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id"), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    review_task: Mapped[ReviewTask] = relationship(back_populates="events")


class Connector(WorkspaceScopedMixin, Base):
    """A workspace-scoped integration configuration without raw credentials."""

    __tablename__ = "connectors"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_connectors_workspace_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unconfigured")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    egress_hosts_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    credentials: Mapped[list["Credential"]] = relationship(back_populates="connector", cascade="all, delete-orphan")


class WorkspaceKeyEnvelope(WorkspaceScopedMixin, Base):
    """Encrypted per-workspace DEK; the KEK is owned by the deployment boundary."""

    __tablename__ = "workspace_key_envelopes"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_workspace_key_envelopes_workspace"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dek_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    encrypted_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Credential(WorkspaceScopedMixin, Base):
    """Ciphertext-only credential record; plaintext exists only inside the vault call."""

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    secret_type: Mapped[str] = mapped_column(String(40), nullable=False, default="token")
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    key_version: Mapped[str] = mapped_column(String(80), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    connector: Mapped[Connector] = relationship(back_populates="credentials")


class McpServer(WorkspaceScopedMixin, Base):
    """Pinned MCP metadata and allow-lists; descriptions are retained as untrusted data."""

    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_mcp_servers_workspace_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="none")
    server_version: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    allowed_tools_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    workflow_version_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    egress_hosts_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ConnectorCall(WorkspaceScopedMixin, Base):
    """Redacted connector/MCP call evidence; raw arguments and results never persist."""

    __tablename__ = "connector_calls"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_connector_calls_workspace_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connector_id: Mapped[str | None] = mapped_column(ForeignKey("connectors.id"), nullable=True, index=True)
    mcp_server_id: Mapped[str | None] = mapped_column(ForeignKey("mcp_servers.id"), nullable=True, index=True)
    workflow_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    call_type: Mapped[str] = mapped_column(String(40), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_untrusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    egress_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(240), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class CredentialAccessLog(WorkspaceScopedMixin, Base):
    """Auditor-readable credential access metadata without any secret material."""

    __tablename__ = "credential_access_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    purpose: Mapped[str] = mapped_column(String(180), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class VendorEntity(WorkspaceScopedMixin, Base):
    """A legal entity, DBA, subsidiary, or JV that can satisfy a named-insured rule."""

    __tablename__ = "vendor_entities"
    __table_args__ = (UniqueConstraint("workspace_id", "vendor_id", "name", name="uq_vendor_entities_workspace_vendor_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_relationship: Mapped[str] = mapped_column("relationship", String(40), nullable=False, default="dba")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    vendor: Mapped[Vendor] = relationship(back_populates="entities")


class ComplianceRequirementSet(WorkspaceScopedMixin, Base):
    """A customer-editable, versioned set of document requirements."""

    __tablename__ = "compliance_requirement_sets"
    __table_args__ = (UniqueConstraint("workspace_id", "name", "version", name="uq_requirement_sets_workspace_name_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    project_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    requirements: Mapped[list["ComplianceRequirement"]] = relationship(back_populates="requirement_set", cascade="all, delete-orphan")
    vendor_bindings: Mapped[list["VendorRequirement"]] = relationship(back_populates="requirement_set", cascade="all, delete-orphan")


class ComplianceRequirement(WorkspaceScopedMixin, Base):
    """One versioned, explainable rule in a requirement set."""

    __tablename__ = "compliance_requirements"
    __table_args__ = (UniqueConstraint("requirement_set_id", "key", name="uq_compliance_requirements_set_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    requirement_set_id: Mapped[str] = mapped_column(ForeignKey("compliance_requirement_sets.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="review")
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    human_statement: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    requirement_set: Mapped[ComplianceRequirementSet] = relationship(back_populates="requirements")


class VendorRequirement(WorkspaceScopedMixin, Base):
    """Optional vendor/project binding and deterministic rule overrides."""

    __tablename__ = "vendor_requirements"
    __table_args__ = (UniqueConstraint("workspace_id", "vendor_id", "requirement_set_id", "project_id", name="uq_vendor_requirements_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    requirement_set_id: Mapped[str] = mapped_column(ForeignKey("compliance_requirement_sets.id"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    overrides_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    vendor: Mapped[Vendor] = relationship(back_populates="requirement_bindings")
    requirement_set: Mapped[ComplianceRequirementSet] = relationship(back_populates="vendor_bindings")


class CoverageLine(WorkspaceScopedMixin, Base):
    """Normalized insurance or licence coverage line retained beside the source document."""

    __tablename__ = "coverage_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    compliance_document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    line_type: Mapped[str] = mapped_column(String(60), nullable=False)
    occurrence_limit: Mapped[int | None] = mapped_column(nullable=True)
    aggregate_limit: Mapped[int | None] = mapped_column(nullable=True)
    deductible: Mapped[int | None] = mapped_column(nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(240), nullable=True)
    am_best_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    admitted_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    endorsements_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ReasonCodeTaxonomy(WorkspaceScopedMixin, Base):
    """Versioned reason-code vocabulary used verbatim in review and exports."""

    __tablename__ = "reason_code_taxonomy"
    __table_args__ = (UniqueConstraint("workspace_id", "taxonomy_version", "code", name="uq_reason_code_taxonomy_workspace_version_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    taxonomy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ChaseThread(WorkspaceScopedMixin, Base):
    """A bounded, customer-owned document chase; it never decides vendor approval."""

    __tablename__ = "chase_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_requirements.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="email")
    customer_sender_connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id"), nullable=False, index=True)
    internal_owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expected_doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=4)
    max_messages_per_week: Mapped[int] = mapped_column(nullable=False, default=3)
    touch_schedule_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=lambda: [0, 3, 7, 14])
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    success_document_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_documents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    vendor: Mapped[Vendor] = relationship(back_populates="chase_threads")
    events: Mapped[list["ChaseEvent"]] = relationship(back_populates="thread", cascade="all, delete-orphan")


class ChaseEvent(WorkspaceScopedMixin, Base):
    """Append-only chase evidence with body hashes and attachment linkage."""

    __tablename__ = "chase_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chase_thread_id: Mapped[str] = mapped_column(ForeignKey("chase_threads.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False, default=0)
    body_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_document_id: Mapped[str | None] = mapped_column(ForeignKey("compliance_documents.id"), nullable=True, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    thread: Mapped[ChaseThread] = relationship(back_populates="events")


class ComplianceStatus(WorkspaceScopedMixin, Base):
    __tablename__ = "compliance_status"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
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


class Workflow(WorkspaceScopedMixin, Base):
    """A named workflow whose executable definitions are versioned separately."""

    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workflows_workspace_key"),
        UniqueConstraint("workspace_id", "name", name="uq_workflows_workspace_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    process_id: Mapped[str | None] = mapped_column(ForeignKey("processes.id"), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    versions: Mapped[list["WorkflowVersion"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowVersion.version"
    )


class WorkflowVersion(WorkspaceScopedMixin, Base):
    """A draft is editable; a published version is database-enforced immutable."""

    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="workflow.v1")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    immutable_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    baseline_id: Mapped[str | None] = mapped_column(ForeignKey("baselines.id"), nullable=True, index=True)
    eval_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    workflow: Mapped[Workflow] = relationship(back_populates="versions", foreign_keys=[workflow_id])
    nodes: Mapped[list["WorkflowNode"]] = relationship(
        back_populates="workflow_version", cascade="all, delete-orphan", order_by="WorkflowNode.node_key"
    )
    edges: Mapped[list["WorkflowEdge"]] = relationship(
        back_populates="workflow_version", cascade="all, delete-orphan", order_by="WorkflowEdge.from_node"
    )
    thresholds: Mapped[list["WorkflowThreshold"]] = relationship(
        back_populates="workflow_version", cascade="all, delete-orphan", order_by="WorkflowThreshold.key"
    )
    evaluations: Mapped[list["WorkflowEvaluationResult"]] = relationship(
        back_populates="workflow_version", cascade="all, delete-orphan", order_by="WorkflowEvaluationResult.evaluated_at"
    )


class WorkflowNode(WorkspaceScopedMixin, Base):
    __tablename__ = "workflow_nodes"
    __table_args__ = (UniqueConstraint("workflow_version_id", "node_key", name="uq_workflow_nodes_version_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column("type", String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    position_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    workflow_version: Mapped[WorkflowVersion] = relationship(back_populates="nodes")


class WorkflowEdge(WorkspaceScopedMixin, Base):
    __tablename__ = "workflow_edges"
    __table_args__ = (
        UniqueConstraint(
            "workflow_version_id", "from_node", "to_node", name="uq_workflow_edges_version_from_to"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    from_node: Mapped[str] = mapped_column(String(64), nullable=False)
    to_node: Mapped[str] = mapped_column(String(64), nullable=False)
    condition_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    workflow_version: Mapped[WorkflowVersion] = relationship(back_populates="edges")


class WorkflowThreshold(WorkspaceScopedMixin, Base):
    __tablename__ = "workflow_thresholds"
    __table_args__ = (UniqueConstraint("workflow_version_id", "key", name="uq_workflow_thresholds_version_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    workflow_version: Mapped[WorkflowVersion] = relationship(back_populates="thresholds")


class Prompt(WorkspaceScopedMixin, Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_prompts_workspace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    versions: Mapped[list["PromptVersion"]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan", order_by="PromptVersion.version"
    )


class PromptVersion(WorkspaceScopedMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompts.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    output_schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    prompt: Mapped[Prompt] = relationship(back_populates="versions")


class ModelConfig(WorkspaceScopedMixin, Base):
    __tablename__ = "model_configs"
    __table_args__ = (UniqueConstraint("workspace_id", "key", "version", name="uq_model_configs_workspace_key_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkflowEvaluationResult(WorkspaceScopedMixin, Base):
    """The narrow E-01 seam: results are immutable and bound to an exact definition hash."""

    __tablename__ = "workflow_evaluation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    failure_reasons_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    evaluator: Mapped[str] = mapped_column(String(120), nullable=False)
    evaluation_type: Mapped[str] = mapped_column(String(40), nullable=False, default="workflow")
    golden_set_id: Mapped[str | None] = mapped_column(ForeignKey("golden_sets.id"), nullable=True, index=True)
    baseline_evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_evaluation_results.id"), nullable=True, index=True
    )
    metric_deltas_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    failing_cases_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    workflow_version: Mapped[WorkflowVersion] = relationship(back_populates="evaluations")


class GoldenSet(WorkspaceScopedMixin, Base):
    """Immutable, rights-labelled evaluation cases for one workflow family."""

    __tablename__ = "golden_sets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "workflow_version_id", "name", "version", name="uq_golden_sets_scope_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    source_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    gate_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    cases: Mapped[list["GoldenCase"]] = relationship(
        back_populates="golden_set", cascade="all, delete-orphan", order_by="GoldenCase.case_key"
    )


class GoldenCase(WorkspaceScopedMixin, Base):
    """One corrected, manually curated, or injection-canary case with rights evidence."""

    __tablename__ = "golden_cases"
    __table_args__ = (UniqueConstraint("golden_set_id", "case_key", name="uq_golden_cases_set_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    golden_set_id: Mapped[str] = mapped_column(ForeignKey("golden_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    case_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rights_status: Mapped[str] = mapped_column(String(40), nullable=False)
    rights_basis: Mapped[str] = mapped_column(Text, nullable=False)
    sender: Mapped[str] = mapped_column(String(240), nullable=False, default="unknown")
    document_type: Mapped[str] = mapped_column(String(80), nullable=False, default="unknown")
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expected_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    prediction_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    canary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    golden_set: Mapped[GoldenSet] = relationship(back_populates="cases")


class DriftSnapshot(WorkspaceScopedMixin, Base):
    """Append-only rolling correction-rate snapshot and operator alert."""

    __tablename__ = "drift_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    window_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ok", index=True)
    baseline_correction_rate: Mapped[float] = mapped_column(Float, nullable=False)
    max_delta: Mapped[float] = mapped_column(Float, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    alerts_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class ConfidenceThresholdSet(WorkspaceScopedMixin, Base):
    """Versioned, customer-owned routing policy for one workflow scope."""

    __tablename__ = "confidence_threshold_sets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "scope_key", "version", name="uq_confidence_threshold_scope_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflows.id"), nullable=True, index=True)
    workflow_version_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True, index=True)
    scope_key: Mapped[str] = mapped_column(String(180), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    auto_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    review_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    halt_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    value_at_risk_limit: Mapped[float] = mapped_column(Float, nullable=False)
    sample_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.02)
    cost_auto_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    cost_review_usd: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    cost_halt_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    previous_threshold_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("confidence_threshold_sets.id"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfidenceAssessment(WorkspaceScopedMixin, Base):
    """Append-only deterministic confidence decision; model self-confidence is never a signal."""

    __tablename__ = "confidence_assessments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "assessment_key", name="uq_confidence_assessments_workspace_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflows.id"), nullable=True, index=True)
    workflow_version_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True, index=True)
    threshold_set_id: Mapped[str] = mapped_column(ForeignKey("confidence_threshold_sets.id"), nullable=False, index=True)
    extraction_consistency: Mapped[float] = mapped_column(Float, nullable=False)
    validation_severity: Mapped[float] = mapped_column(Float, nullable=False)
    matching_score: Mapped[float] = mapped_column(Float, nullable=False)
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False)
    sender_history_score: Mapped[float] = mapped_column(Float, nullable=False)
    value_at_risk: Mapped[float] = mapped_column(Float, nullable=False)
    value_at_risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    route: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    route_band: Mapped[str] = mapped_column(String(32), nullable=False)
    required_halt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    signals_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class ConfidenceAudit(WorkspaceScopedMixin, Base):
    """Sampled high-confidence run review and any resulting safety rollback."""

    __tablename__ = "confidence_audits"
    __table_args__ = (UniqueConstraint("workspace_id", "assessment_id", name="uq_confidence_audits_assessment"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("confidence_assessments.id"), nullable=False, index=True)
    threshold_set_id: Mapped[str] = mapped_column(ForeignKey("confidence_threshold_sets.id"), nullable=False, index=True)
    sample_rate: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    actual_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    false_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    alert_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_threshold_set_id: Mapped[str | None] = mapped_column(ForeignKey("confidence_threshold_sets.id"), nullable=True)
    audited_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Execution(WorkspaceScopedMixin, Base):
    """Durable run state pinned to one immutable workflow version."""

    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_executions_workspace_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    workflow_version_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(nullable=False, default=3)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replay_of_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id"), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    steps: Mapped[list["ExecutionStep"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="ExecutionStep.sequence"
    )
    outbox_events: Mapped[list["OutboxEvent"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="OutboxEvent.created_at"
    )


class ExecutionStep(WorkspaceScopedMixin, Base):
    """One durable node attempt; only pending rows are claimable by a worker."""

    __tablename__ = "execution_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "node_key", name="uq_execution_steps_execution_node"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), nullable=False, index=True)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    attempt: Mapped[int] = mapped_column(nullable=False, default=0)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(nullable=True)
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    wait_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    execution: Mapped[Execution] = relationship(back_populates="steps")


class OutboxEvent(WorkspaceScopedMixin, Base):
    """Transactional event delivery record; delivery is at-least-once and dedupe-keyed."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "dedupe_key", name="uq_outbox_workspace_dedupe"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id"), nullable=True, index=True)
    step_id: Mapped[str | None] = mapped_column(ForeignKey("execution_steps.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    execution: Mapped[Execution | None] = relationship(back_populates="outbox_events")


class ExternalWriteReceipt(WorkspaceScopedMixin, Base):
    """The durable idempotency fence for an external connector write."""

    __tablename__ = "external_write_receipts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_external_writes_workspace_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), nullable=False, index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("execution_steps.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExecutionEvent(WorkspaceScopedMixin, Base):
    """Append-only run timeline used by the inspector and operational support."""

    __tablename__ = "execution_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), nullable=False, index=True)
    step_id: Mapped[str | None] = mapped_column(ForeignKey("execution_steps.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class RuntimeWorkerHeartbeat(WorkspaceScopedMixin, Base):
    """Last durable signal from a runtime worker for operator degraded-mode checks."""

    __tablename__ = "runtime_worker_heartbeats"
    __table_args__ = (UniqueConstraint("workspace_id", "worker_id", name="uq_runtime_worker_heartbeats_scope_worker"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="healthy", index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    processed_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ValueEvent(WorkspaceScopedMixin, Base):
    """Immutable, explainable unit of measured value or cost."""

    __tablename__ = "value_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "event_key", name="uq_value_events_workspace_event_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_key: Mapped[str] = mapped_column(String(240), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id"), nullable=True, index=True)
    workflow_version_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True, index=True)
    workflow_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    baseline_id: Mapped[str | None] = mapped_column(ForeignKey("baselines.id"), nullable=True, index=True)
    baseline_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_task_id: Mapped[str | None] = mapped_column(ForeignKey("review_tasks.id"), nullable=True, index=True)
    source_artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    audit_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    dollar_value: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
