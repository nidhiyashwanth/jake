from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "AI Operations Compliance API"
    environment: str = "development"
    database_url: str
    allowed_origins: str = "http://localhost:3000"
    required_certificate_holder: str = "Northwind Construction LLC"
    minimum_gl_occurrence_limit: int = 2_000_000
    rules_version: str = "rules.v1"
    max_upload_bytes: int = 10 * 1024 * 1024

    @field_validator("database_url")
    @classmethod
    def require_postgres(cls, value: str) -> str:
        normalized = value.lower()
        if "sqlite" in normalized or not normalized.startswith("postgresql"):
            raise ValueError("DATABASE_URL must use PostgreSQL; SQLite is not supported")
        return value

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
