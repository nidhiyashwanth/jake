"""Pure contract tests for the I-01 inspection boundary."""

from app.services.observability import redact_untrusted, trace_context


def test_redaction_hides_secrets_pii_and_bearer_material_without_hiding_workflow_evidence() -> None:
    payload = {
        "node_key": "verify_certificate",
        "status": "completed",
        "api_token": "do-not-leak",
        "customer": {"email": "person@example.invalid", "phone": "+91-0000000000"},
        "headers": {"Authorization": "Bearer do-not-leak"},
        "nested": [{"client_secret": "also-private"}],
    }

    safe = redact_untrusted(payload)

    assert safe["node_key"] == "verify_certificate"
    assert safe["status"] == "completed"
    assert safe["api_token"] == "[REDACTED]"
    assert safe["customer"]["email"] == "[PII REDACTED]"
    assert safe["customer"]["phone"] == "[PII REDACTED]"
    assert safe["headers"]["Authorization"] == "[REDACTED]"
    assert safe["nested"][0]["client_secret"] == "[REDACTED]"
    assert "do-not-leak" not in str(safe)


def test_trace_context_is_stable_for_correlation_and_distinct_per_span() -> None:
    first = trace_context("corr-123", "execution-1")
    repeat = trace_context("corr-123", "execution-1")
    other_span = trace_context("corr-123", "event-2")

    assert first == repeat
    assert first["correlation_id"] == "corr-123"
    assert len(first["trace_id"]) == 32
    assert len(first["span_id"]) == 16
    assert first["trace_id"] == other_span["trace_id"]
    assert first["span_id"] != other_span["span_id"]


def test_redaction_truncates_untrusted_text() -> None:
    safe = redact_untrusted({"message": "x" * 25_000})

    assert len(safe["message"]) == 20_000
