from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ApiError(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ApiError


JsonValue = Any
