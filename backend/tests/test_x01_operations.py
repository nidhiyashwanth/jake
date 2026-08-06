import base64

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_rejects_development_auth_and_identity() -> None:
    with pytest.raises(ValidationError, match="production-like environments"):
        Settings(
            database_url="postgresql+psycopg://user:pass@db.example.invalid/app",
            environment="production",
            auth_provider="development",
            allow_development_identity=True,
            vault_kek_base64=base64.b64encode(b"x" * 32).decode("ascii"),
            allowed_origins="https://app.example.com",
        )


def test_production_requires_a_secret_manager_vault_key() -> None:
    with pytest.raises(ValidationError, match="VAULT_KEK_BASE64"):
        Settings(
            database_url="postgresql+psycopg://user:pass@db.example.invalid/app",
            environment="production",
            auth_provider="oidc_jwt",
            allow_development_identity=False,
            allowed_origins="https://app.example.com",
        )


def test_staging_accepts_oidc_with_explicit_secret_and_origin() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@db.example.invalid/app",
        environment="staging",
        auth_provider="oidc_jwt",
        allow_development_identity=False,
        vault_kek_base64=base64.b64encode(b"x" * 32).decode("ascii"),
        allowed_origins="https://staging.example.com",
    )
    assert settings.environment == "staging"
    assert settings.auth_provider == "oidc_jwt"
