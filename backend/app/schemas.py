from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
