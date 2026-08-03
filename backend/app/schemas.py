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
