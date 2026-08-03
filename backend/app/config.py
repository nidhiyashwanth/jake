from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "AI Operations Compliance API"
    environment: str = "development"
    database_url: str
    auth_provider: str = "development"
    session_ttl_minutes: int = Field(default=480, gt=0, le=30 * 24 * 60)
    allow_development_identity: bool = True
    allowed_origins: str = "http://localhost:3000"
    required_certificate_holder: str = "Northwind Construction LLC"
    minimum_gl_occurrence_limit: int = 2_000_000
    rules_version: str = "rules.v1"
    max_upload_bytes: int = 10 * 1024 * 1024

    dev_default_organization_id: str = "00000000-0000-0000-0000-000000000001"
    dev_default_workspace_id: str = "00000000-0000-0000-0000-000000000002"
    dev_default_user_id: str = "00000000-0000-0000-0000-000000000003"

    @field_validator("database_url")
    @classmethod
    def require_postgres(cls, value: str) -> str:
        normalized = value.lower()
        if "sqlite" in normalized or not normalized.startswith("postgresql"):
            raise ValueError("DATABASE_URL must use PostgreSQL; SQLite is not supported")
        return value

    @model_validator(mode="after")
    def validate_auth_boundary(self) -> "Settings":
        if self.environment.casefold() not in {"development", "dev", "test"}:
            if self.auth_provider == "development" or self.allow_development_identity:
                raise ValueError("production-like environments require a non-development auth provider")
        if self.auth_provider not in {"development", "oidc_jwt"}:
            raise ValueError("AUTH_PROVIDER must be development or oidc_jwt")
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
