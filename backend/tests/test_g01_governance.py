from datetime import datetime, timezone

from app.models import AuditPack, RetentionRun
from app.services.governance import (
    PII_CLASSIFICATION_VERSION,
    audit_pack_payload,
    classify_pii_payload,
    redact_governance_payload,
    retention_run_payload,
)


def test_pii_classification_retains_field_paths_without_values() -> None:
    result = classify_pii_payload({"contact_email": "operator@example.invalid", "phone": "+1 555 010 2222", "policy_number": "COI-42"})

    assert result["status"] == "detected"
    assert result["policy_version"] == PII_CLASSIFICATION_VERSION
    assert any("contact_email" in path for path in result["flags"])
    assert "operator@example.invalid" not in str(result)
    assert "555 010 2222" not in str(result)


def test_governance_redaction_hides_generic_pii_and_secrets() -> None:
    result = redact_governance_payload(
        {
            "summary": "Contact operator@example.invalid at +1 555 010 2222",
            "api_token": "should-never-appear",
            "nested": {"ssn": "123-45-6789"},
        }
    )

    assert result["summary"] == "Contact [PII EMAIL REDACTED] at [PII PHONE REDACTED]"
    assert result["api_token"] == "[REDACTED]"
    assert result["nested"]["ssn"] == "[PII REDACTED]"


def test_retention_run_payload_is_explicit_about_dry_run_and_counts() -> None:
    run = RetentionRun(
        id="run-1",
        workspace_id="workspace-1",
        as_of=datetime(2030, 1, 1, tzinfo=timezone.utc),
        dry_run=True,
        scanned_count=3,
        eligible_count=1,
        held_count=2,
        deleted_count=0,
        report_json={"decisions": [{"artifact_id": "artifact-1", "decision": "hold"}]},
        actor_id="user-1",
        created_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    payload = retention_run_payload(run)

    assert payload["dry_run"] is True
    assert payload["scanned_count"] == 3
    assert payload["eligible_count"] == 1
    assert payload["held_count"] == 2
    assert payload["deleted_count"] == 0


def test_audit_pack_payload_exposes_hash_and_redaction_metadata() -> None:
    pack = AuditPack(
        id="pack-1",
        workspace_id="workspace-1",
        schema_version="audit-pack.v1",
        redaction_policy_version=PII_CLASSIFICATION_VERSION,
        payload_json={"redaction": {"prompt_bodies_excluded": True}, "secret": "hidden"},
        sha256="a" * 64,
        generated_by="user-1",
        generated_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    payload = audit_pack_payload(pack)

    assert payload["sha256"] == "a" * 64
    assert payload["payload"]["redaction"]["prompt_bodies_excluded"] is True
    assert payload["payload"]["secret"] == "[REDACTED]"
