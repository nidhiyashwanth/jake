from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class VendorCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=200)

    @field_validator("legal_name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("legal_name cannot be blank")
        return value


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | int | bool | None
    field: str | None = None
    reason_code: str | None = Field(default=None, min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=1000)


class ReviewAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: str | None = Field(default=None, max_length=36)


class ReviewEscalateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    level: int | None = Field(default=None, ge=1, le=5)


class ReviewBulkActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_ids: list[str] = Field(min_length=1, max_length=25)
    action: Literal["assign", "unassign", "escalate"]
    assignee_user_id: str | None = Field(default=None, max_length=36)
    reason: str | None = Field(default=None, max_length=500)


ConnectorKind = Literal["email", "object_storage", "notify", "rest", "webhook", "sftp", "database", "csv_excel", "rpa"]


class ConnectorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    kind: ConnectorKind
    config: dict[str, Any] = Field(default_factory=dict)
    egress_hosts: list[str] = Field(default_factory=list, max_length=20)


class ConnectorTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str | None = Field(default=None, max_length=500)


class WebhookVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=100_000)
    timestamp: int = Field(ge=0)
    signature: str = Field(min_length=1, max_length=200)


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=160)
    secret: SecretStr
    secret_type: str = Field(default="token", min_length=1, max_length=40)
    expires_at: datetime | None = None


class CredentialRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr
    expires_at: datetime | None = None


class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=500)
    auth_mode: str = Field(default="none", min_length=1, max_length=40)
    server_version: str = Field(min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    workflow_version_ids: list[str] = Field(default_factory=list, max_length=100)
    egress_hosts: list[str] = Field(default_factory=list, max_length=20)


class McpToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)
    workflow_version_id: str | None = Field(default=None, max_length=36)
    value_at_risk: float = Field(default=0, ge=0)
    approved: bool = False
    approval_note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=240)


class ProcessStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=2000)
    seq: int | None = Field(default=None, ge=1)
    system: str | None = Field(default=None, max_length=160)
    minutes_p50: float | None = Field(default=None, ge=0)
    minutes_p90: float | None = Field(default=None, ge=0)
    is_decision: bool = False

    @field_validator("description", "system")
    @classmethod
    def trim_step_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("text cannot be blank")
        return value

    @model_validator(mode="after")
    def p90_not_below_p50(self) -> "ProcessStepInput":
        if self.minutes_p50 is not None and self.minutes_p90 is not None and self.minutes_p90 < self.minutes_p50:
            raise ValueError("minutes_p90 cannot be below minutes_p50")
        return self


class ProcessCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    department: str | None = Field(default=None, max_length=160)
    owner_user_id: str | None = Field(default=None, max_length=36)
    system_of_record: str | None = Field(default=None, max_length=160)
    trigger: Any = None
    inputs: list[Any] = Field(default_factory=list)
    steps: list[ProcessStepInput] = Field(default_factory=list, max_length=200)
    decisions: list[Any] = Field(default_factory=list)
    exceptions: list[Any] = Field(default_factory=list)
    approvals: list[Any] = Field(default_factory=list)
    outputs: list[Any] = Field(default_factory=list)
    failure_modes: list[Any] = Field(default_factory=list)
    baseline_metrics: dict[str, Any] | list[Any] | None = None
    captured_by: str | None = Field(default=None, max_length=120)
    client_reference: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def require_structured_intake(self) -> "ProcessCreate":
        required = ("trigger", "inputs", "steps", "decisions", "exceptions", "approvals", "outputs", "failure_modes")
        missing = [field for field in required if field not in self.model_fields_set or not getattr(self, field)]
        if missing:
            raise ValueError("structured discovery intake is missing: " + ", ".join(missing))
        return self

    @field_validator("name", "department", "system_of_record")
    @classmethod
    def trim_process_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("text cannot be blank")
        return value


class ProcessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=240)
    department: str | None = Field(default=None, max_length=160)
    owner_user_id: str | None = Field(default=None, max_length=36)
    system_of_record: str | None = Field(default=None, max_length=160)
    trigger: Any = None
    inputs: list[Any] | None = None
    steps: list[ProcessStepInput] | None = Field(default=None, max_length=200)
    decisions: list[Any] | None = None
    exceptions: list[Any] | None = None
    approvals: list[Any] | None = None
    outputs: list[Any] | None = None
    failure_modes: list[Any] | None = None

    @field_validator("name", "department", "system_of_record")
    @classmethod
    def trim_optional_process_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("text cannot be blank")
        return value


class InterviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["sop", "transcript", "screen_recording_narration"] = "transcript"
    content: str | None = Field(default=None, min_length=1, max_length=500_000)
    transcript: str | None = Field(default=None, min_length=1, max_length=500_000)
    sop_text: str | None = Field(default=None, min_length=1, max_length=500_000)
    transcript_ref: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_content(self) -> "InterviewCreate":
        if not any(value for value in (self.content, self.transcript, self.sop_text)):
            raise ValueError("content, transcript, or sop_text is required")
        return self

    @property
    def source_content(self) -> str:
        return self.content or self.transcript or self.sop_text or ""


class InterviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text: str | None = Field(default=None, min_length=1, max_length=500_000)
    draft_graph: dict[str, Any] | None = None
    exception_list: list[Any] | None = None
    baseline_questions: list[Any] | None = None

    @model_validator(mode="after")
    def require_edit(self) -> "InterviewUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one draft field is required")
        return self


class BaselineMetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    value: float
    unit: str | None = Field(default=None, max_length=40)
    source: str = Field(default="customer_asserted", min_length=1, max_length=80)
    provenance: dict[str, Any] = Field(default_factory=dict)


class BaselineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: dict[str, Any] | list[BaselineMetricInput] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=5000)
    supersedes_baseline_id: str | None = Field(default=None, max_length=36)
    source: str | None = Field(default=None, max_length=120)
    period_start: str | None = Field(default=None, max_length=40)
    period_end: str | None = Field(default=None, max_length=40)


class BaselineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: dict[str, Any] | list[BaselineMetricInput] | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_draft_edit(self) -> "BaselineUpdate":
        if not self.model_fields_set:
            raise ValueError("metrics or notes is required")
        return self


class BaselineSign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature_note: str | None = Field(default=None, max_length=2000)
    signer_name: str | None = Field(default=None, max_length=200)
    signer_email: str | None = Field(default=None, max_length=320)
    attestation: str | None = Field(default=None, max_length=4000)
    signer: dict[str, Any] | None = None
    confirm_immutable: bool | None = None


class OpportunityScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure_score: float | None = Field(default=None, ge=0, le=1)
    rule_clarity_score: float | None = Field(default=None, ge=0, le=1)
    data_availability_score: float | None = Field(default=None, ge=0, le=1)
    exception_rate: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    effort_weeks: float | None = Field(default=None, gt=0)
    risk_multiplier: float | None = Field(default=None, gt=0)
    review_rate: float | None = Field(default=None, ge=0, le=1)
    review_minutes: float | None = Field(default=None, ge=0)
    model_cost_annual: float | None = Field(default=None, ge=0)
    infra_cost_annual: float | None = Field(default=None, ge=0)
    model_cost: float | None = Field(default=None, ge=0)
    infra_cost: float | None = Field(default=None, ge=0)
    automatable_pct: float | None = Field(default=None, ge=0, le=1)
    formula_version: str | None = Field(default=None, max_length=40)
    inputs: dict[str, Any] | None = None
    input_provenance: dict[str, Any] = Field(default_factory=dict)


WorkflowNodeType = Literal[
    "trigger",
    "fetch",
    "parse",
    "classify",
    "extract",
    "rule",
    "score",
    "llm",
    "tool",
    "approve",
    "notify",
    "halt",
]


class WorkflowNodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    type: WorkflowNodeType
    label: str = Field(min_length=1, max_length=240)
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] | None = None

    @field_validator("key", "label")
    @classmethod
    def trim_workflow_node_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("workflow node text cannot be blank")
        return value


class _WorkflowNodeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")


class TriggerNodeConfig(_WorkflowNodeConfig):
    event: str | None = None
    input_schema: dict[str, Any] | None = None


class FetchNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    source: str | None = None
    connector_key: str | None = None
    resource: str | None = None


class ParseNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class ClassifyNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    labels: list[str] | None = None


class ExtractNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    fields: dict[str, Any] | None = None


class RuleNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    expression: str | None = None


class ScoreNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    score_key: str | None = None


class LlmNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    prompt_key: str | None = None
    prompt_version: int | None = None
    model_config_key: str | None = None
    model_config_version: int | None = None
    output_schema: dict[str, Any] | None = None


class ToolNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    connector_key: str | None = None
    tool_key: str | None = None
    tool_name: str | None = None
    write: bool = False
    requires_approval: bool = False


class ApproveNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    reason: str | None = None


class NotifyNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    channel: str | None = None
    recipient: str | None = None
    template: str | None = None


class HaltNodeConfig(_WorkflowNodeConfig):
    input: str | None = None
    reason: str | None = None


class WorkflowEdgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=120)
    from_node: str | None = Field(default=None, min_length=1, max_length=64)
    to_node: str | None = Field(default=None, min_length=1, max_length=64)
    source: str | None = Field(default=None, min_length=1, max_length=64)
    target: str | None = Field(default=None, min_length=1, max_length=64)
    condition: dict[str, Any] | str | None = None

    @field_validator("from_node", "to_node", "source", "target")
    @classmethod
    def trim_workflow_edge_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("workflow edge node keys cannot be blank")
        return value

    @model_validator(mode="after")
    def resolve_edge_aliases(self) -> "WorkflowEdgeInput":
        self.from_node = self.from_node or self.source
        self.to_node = self.to_node or self.target
        if not self.from_node or not self.to_node:
            raise ValueError("workflow edges require from_node/to_node or source/target")
        return self


class WorkflowThresholdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    value: float | None = Field(default=None, allow_inf_nan=False)
    description: str | None = Field(default=None, max_length=240)
    operator: str | None = Field(default=None, max_length=20)
    action: str | None = Field(default=None, max_length=80)

    @field_validator("key", "description")
    @classmethod
    def trim_threshold_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("threshold text cannot be blank")
        return value


class WorkflowSpecInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="workflow.v1", max_length=40)
    nodes: list[WorkflowNodeInput] = Field(default_factory=list, max_length=200)
    edges: list[WorkflowEdgeInput] = Field(default_factory=list, max_length=400)
    thresholds: list[WorkflowThresholdInput] = Field(default_factory=list, max_length=100)
    prompts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    model_configs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    baseline_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(default=None, min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    process_id: str | None = Field(default=None, max_length=36)
    baseline_id: str | None = Field(default=None, max_length=36)
    nodes: list[WorkflowNodeInput] = Field(default_factory=list, max_length=200)
    edges: list[WorkflowEdgeInput] = Field(default_factory=list, max_length=400)
    thresholds: list[WorkflowThresholdInput] = Field(default_factory=list, max_length=100)
    prompts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    model_configs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    @field_validator("key", "name", "description")
    @classmethod
    def trim_workflow_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("workflow text cannot be blank")
        return value


class WorkflowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_workflow_edit(self) -> "WorkflowUpdate":
        if not self.model_fields_set:
            raise ValueError("key, name, or description is required")
        return self

    @field_validator("key", "name", "description")
    @classmethod
    def trim_optional_workflow_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("workflow text cannot be blank")
        return value


class WorkflowVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version: int | None = Field(default=None, ge=1)
    source_version_id: str | None = Field(default=None, max_length=36)
    baseline_id: str | None = Field(default=None, max_length=36)
    nodes: list[WorkflowNodeInput] | None = Field(default=None, max_length=200)
    edges: list[WorkflowEdgeInput] | None = Field(default=None, max_length=400)
    thresholds: list[WorkflowThresholdInput] | None = Field(default=None, max_length=100)
    prompts: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    model_configs: list[dict[str, Any]] | None = Field(default=None, max_length=100)


class WorkflowVersionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str | None = Field(default=None, max_length=40)
    baseline_id: str | None = Field(default=None, max_length=36)
    nodes: list[WorkflowNodeInput] | None = Field(default=None, max_length=200)
    edges: list[WorkflowEdgeInput] | None = Field(default=None, max_length=400)
    thresholds: list[WorkflowThresholdInput] | None = Field(default=None, max_length=100)
    prompts: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    model_configs: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_version_edit(self) -> "WorkflowVersionPatch":
        if not self.model_fields_set:
            raise ValueError("a workflow version field is required")
        return self


class WorkflowEvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_hash: str = Field(min_length=64, max_length=64)
    passed: bool
    metrics: dict[str, Any] = Field(default_factory=dict)
    failure_reasons: list[str] = Field(default_factory=list, max_length=100)
    evaluator: str = Field(min_length=1, max_length=120)

    @field_validator("definition_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("definition_hash must be a SHA-256 hexadecimal hash")
        return value

    @field_validator("evaluator")
    @classmethod
    def trim_evaluator(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("evaluator cannot be blank")
        return value

    @model_validator(mode="after")
    def require_failure_reasons_when_failed(self) -> "WorkflowEvaluationCreate":
        if not self.passed and not self.failure_reasons:
            raise ValueError("failure_reasons are required when passed is false")
        return self


class WorkflowEvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_key: str = Field(min_length=1, max_length=160)

    @field_validator("suite_key")
    @classmethod
    def trim_suite_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("suite_key cannot be blank")
        return value


class PromptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    body: str = Field(min_length=1, max_length=100_000)
    variables: list[str] = Field(default_factory=list, max_length=100)
    output_schema: dict[str, Any] | None = None

    @field_validator("key", "body", "description")
    @classmethod
    def trim_prompt_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("prompt text cannot be blank")
        return value.strip() if value == value.strip() else value


class PromptVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=100_000)
    variables: list[str] = Field(default_factory=list, max_length=100)
    output_schema: dict[str, Any] | None = None


class ModelConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    version: int | None = Field(default=None, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("key", "provider", "model_id")
    @classmethod
    def trim_model_config_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("model config text cannot be blank")
        return value


class DiscoveryDraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_graph: dict[str, Any] | list[Any] | None = None
    exceptions: list[Any] | None = None
    baseline_questions: list[Any] | None = None
    edited_by: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_draft_change(self) -> "DiscoveryDraftPatch":
        if not self.model_fields_set.intersection({"draft_graph", "exceptions", "baseline_questions"}):
            raise ValueError("draft_graph, exceptions, or baseline_questions is required")
        return self


class DiscoveryQuestionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=4000)
    answered_by: str | None = Field(default=None, max_length=120)


class DiscoveryExceptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1, max_length=4000)
    frequency_per_month: float | None = Field(default=None, ge=0)
    severity: str | None = Field(default=None, max_length=40)
    origin: str = Field(default="human", max_length=40)
    captured_by: str | None = Field(default=None, max_length=120)


RoleValue = Literal["owner", "admin", "builder", "operator", "reviewer", "viewer", "auditor"]


class DevelopmentLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)

    @field_validator("email", "name", "organization_name", "workspace_name")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value cannot be blank")
        return value


class WorkspaceContextSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=36)


class WorkspaceModeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["delivery", "handoff"]


class MemberInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    role: RoleValue = "viewer"

    @field_validator("email", "name")
    @classmethod
    def trim_member_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value cannot be blank")
        return value


class MemberPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RoleValue | None = None
    disabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "MemberPatch":
        if self.role is None and self.disabled is None:
            raise ValueError("role or disabled is required")
        return self


class ApiError(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ApiError


JsonValue = Any


class RuntimeExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_version_id: str = Field(min_length=1, max_length=36)
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=200)
    correlation_id: str | None = Field(default=None, max_length=120)
    max_retries: int = Field(default=3, ge=0, le=12)

    @field_validator("workflow_version_id", "idempotency_key", "correlation_id")
    @classmethod
    def trim_runtime_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("runtime identifiers cannot be blank")
        return value


class RuntimeAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str | None = Field(default=None, max_length=120)
    max_steps: int = Field(default=1, ge=1, le=50)


class RuntimeRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=2000)
    step_id: str | None = Field(default=None, max_length=36)


class RuntimeResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=100)
    output: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=2000)


class RuntimeReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)
    correlation_id: str | None = Field(default=None, max_length=120)


class RuntimeOutboxDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=20, ge=1, le=100)
