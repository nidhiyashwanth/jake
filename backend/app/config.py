from functools import lru_cache

import base64

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SUPPORTED_ENVIRONMENTS = {"development", "dev", "test", "staging", "production"}


def normalize_database_url(value: str) -> str:
    if value.lower().startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


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
    vault_kek_base64: str | None = None
    vault_key_version: str = "local-kms-v1"
    connector_egress_allowlist: str = "localhost,sandbox.local,mcp.local,rest.local"
    otel_exporter_otlp_endpoint: str | None = None
    langfuse_host: str | None = None
    langfuse_otel_endpoint: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    sentry_dsn: str | None = None
    value_infra_cost_per_run_usd: float = Field(default=0, ge=0, le=100000)

    dev_default_organization_id: str = "00000000-0000-0000-0000-000000000001"
    dev_default_workspace_id: str = "00000000-0000-0000-0000-000000000002"
    dev_default_user_id: str = "00000000-0000-0000-0000-000000000003"

    @field_validator("database_url")
    @classmethod
    def require_postgres(cls, value: str) -> str:
        normalized = value.lower()
        if "sqlite" in normalized or not normalized.startswith("postgresql"):
            raise ValueError("DATABASE_URL must use PostgreSQL; SQLite is not supported")
        return normalize_database_url(value)

    @model_validator(mode="after")
    def validate_auth_boundary(self) -> "Settings":
        environment = self.environment.casefold().strip()
        if environment not in SUPPORTED_ENVIRONMENTS:
            raise ValueError("ENVIRONMENT must be development, staging, or production")
        if environment not in {"development", "dev", "test"}:
            if self.auth_provider == "development" or self.allow_development_identity:
                raise ValueError("production-like environments require a non-development auth provider")
        if self.auth_provider not in {"development", "oidc_jwt"}:
            raise ValueError("AUTH_PROVIDER must be development or oidc_jwt")
        if environment not in {"development", "dev", "test"} and not self.vault_kek_base64:
            raise ValueError("production-like environments require VAULT_KEK_BASE64 from the deployment secret manager")
        if environment not in {"development", "dev", "test"} and (not self.allowed_origins_list or "*" in self.allowed_origins_list):
            raise ValueError("production-like environments require an explicit non-wildcard ALLOWED_ORIGINS value")
        if self.vault_kek_base64:
            try:
                decoded = base64.b64decode(self.vault_kek_base64, validate=True)
            except Exception as exc:
                raise ValueError("VAULT_KEK_BASE64 must be valid base64") from exc
            if len(decoded) != 32:
                raise ValueError("VAULT_KEK_BASE64 must decode to exactly 32 bytes")
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def connector_egress_allowlist_list(self) -> list[str]:
        return [host.strip().casefold() for host in self.connector_egress_allowlist.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
