from datetime import date

import pytest

from app.config import Settings
from app.errors import DomainError
from app.models import Vendor
from app.services.documents import coerce_correction, derived_document_metadata, normalize_fields
from app.services.verification import evaluate_rules


COI_TEXT = """
Named Insured: Acme Mechanical LLC
Certificate Holder: Northwind Construction LLC
GL Occurrence Limit: $2,000,000
Policy Expiry: 2099-12-31
Additional Insured: Yes
Waiver of Subrogation: Yes
"""


def test_normalizer_returns_contract_fields() -> None:
    assert normalize_fields(COI_TEXT) == {
        "named_insured": "Acme Mechanical LLC",
        "certificate_holder": "Northwind Construction LLC",
        "gl_occurrence_limit": 2_000_000,
        "policy_expiry": "2099-12-31",
        "additional_insured": True,
        "waiver_of_subrogation": True,
    }


def test_rules_produce_one_repairable_failure() -> None:
    vendor = Vendor(id="vendor-1", legal_name="Acme Mechanical LLC")
    fields = normalize_fields(COI_TEXT.replace("Certificate Holder: Northwind Construction LLC", "Certificate Holder:"))

    results = evaluate_rules(vendor, fields, today=date(2026, 8, 3))

    assert [result.key for result in results if result.result == "fail"] == ["certificate_holder_match"]
    failure = next(result for result in results if result.result == "fail")
    assert failure.reason_code == "FIELD_MISSING"
    assert failure.field == "certificate_holder"


def test_correction_values_are_normalized_and_reject_unknown_fields() -> None:
    assert coerce_correction("gl_occurrence_limit", "$3,000,000") == 3_000_000
    assert coerce_correction("additional_insured", "yes") is True
    assert coerce_correction("policy_expiry", "12/31/2099") == "2099-12-31"

    with pytest.raises(DomainError, match="cannot be corrected"):
        coerce_correction("untrusted_field", "value")


def test_denormalized_document_metadata_uses_corrected_extracted_fields() -> None:
    issued_at, expires_at, issuer = derived_document_metadata(
        {"policy_effective": "2026-01-15", "policy_expiry": "2027-01-15", "carrier": "Acme Mutual"}
    )

    assert issued_at == date(2026, 1, 15)
    assert expires_at == date(2027, 1, 15)
    assert issuer == "Acme Mutual"


def test_sqlite_is_explicitly_rejected() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(database_url="sqlite:///not-allowed.db")


def test_bare_postgres_urls_select_the_installed_psycopg_driver() -> None:
    settings = Settings(database_url="postgresql://user:pass@db.example.invalid/app")

    assert settings.database_url == "postgresql+psycopg://user:pass@db.example.invalid/app"
