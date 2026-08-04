"""Pure, deterministic evaluation for the versioned wedge rule library."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from app.config import get_settings
from app.models import ComplianceDocument, ComplianceRequirement, Vendor


@dataclass(frozen=True)
class RuleResult:
    key: str
    label: str
    field: str
    result: str
    reason_code: str
    message: str
    observed_value: Any
    required_value: Any
    requirement_id: str | None = None
    confidence: float = 1.0
    explanation: str | None = None


def same_name(left: Any, right: Any) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    normalized_left = " ".join(left.casefold().replace(",", "").split())
    normalized_right = " ".join(right.casefold().replace(",", "").split())
    return normalized_left == normalized_right


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        normalized = value.replace(",", "").replace("$", "").strip()
        try:
            return float(normalized) if "." in normalized else int(normalized)
        except ValueError:
            return None
    return None


def _rating_score(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper().replace(" ", "")
    # The deterministic wedge library only needs the common AM Best bands.
    ordered = {"A++": 10, "A+": 9, "A": 8, "A-": 7, "B++": 6, "B+": 5, "B": 4, "B-": 3, "C++": 2, "C+": 1, "C": 0}
    return ordered.get(normalized)


def _display(value: Any) -> str:
    if value is None or value == "":
        return "no value"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _vendor_names(vendor: Vendor, entity_names: Iterable[str] = ()) -> list[str]:
    names = [vendor.legal_name, *(vendor.dba_names_json or []), *entity_names]
    return [name for name in names if isinstance(name, str) and name.strip()]


def evaluate_requirement(
    requirement: ComplianceRequirement,
    *,
    vendor: Vendor,
    document: ComplianceDocument,
    fields: dict[str, Any],
    entity_names: Iterable[str] = (),
    overrides: dict[str, Any] | None = None,
    today: date | None = None,
) -> RuleResult:
    today = today or date.today()
    definition = dict(requirement.rule_json or {})
    field = str(definition.get("field") or requirement.key)
    kind = str(definition.get("kind") or "equals")
    required = (overrides or {}).get(requirement.key, definition.get("required"))
    observed = fields.get(field)
    if field == "document_status":
        observed = document.status
    if field == "document_type":
        observed = document.doc_type
    statement = requirement.human_statement
    result = False
    reason_code = requirement.reason_code
    confidence = 1.0

    if kind == "vendor_name":
        names = _vendor_names(vendor, entity_names)
        result = any(same_name(observed, name) for name in names)
        if result and not same_name(observed, vendor.legal_name):
            reason_code = "DBA_VARIANT"
        elif not observed:
            reason_code = "FIELD_MISSING"
        else:
            reason_code = "PASS" if result else requirement.reason_code
        confidence = 0.98 if result else 0.92
    elif kind == "certificate_holder":
        expected = required or get_settings().required_certificate_holder
        result = same_name(observed, expected)
        reason_code = "PASS" if result else ("FIELD_MISSING" if not observed else requirement.reason_code)
        required = expected
    elif kind == "minimum":
        observed_number = _number(observed)
        required_number = _number(required)
        result = observed_number is not None and required_number is not None and observed_number >= required_number
        reason_code = "PASS" if result else ("FIELD_MISSING" if observed_number is None else requirement.reason_code)
        observed = observed_number
        required = required_number
    elif kind == "boolean":
        result = observed is True
        reason_code = "PASS" if result else ("FIELD_MISSING" if observed is None else requirement.reason_code)
    elif kind == "boolean_false":
        result = observed is False
        reason_code = "PASS" if result else ("FIELD_MISSING" if observed is None else requirement.reason_code)
    elif kind == "equals":
        result = isinstance(observed, str) and isinstance(required, str) and observed.casefold().strip() == required.casefold().strip()
        reason_code = "PASS" if result else ("FIELD_MISSING" if observed in (None, "") else requirement.reason_code)
    elif kind == "date_future":
        parsed = _as_date(observed)
        result = parsed is not None and parsed >= today
        reason_code = "PASS" if result else ("FIELD_MISSING" if parsed is None else requirement.reason_code)
        observed = parsed.isoformat() if parsed else observed
    elif kind == "date_covers":
        parsed = _as_date(observed)
        contract_end = _as_date(fields.get(str(required))) if isinstance(required, str) else _as_date(required)
        result = parsed is not None and contract_end is not None and parsed >= contract_end
        reason_code = "PASS" if result else ("FIELD_MISSING" if parsed is None else requirement.reason_code)
        required = contract_end.isoformat() if contract_end else required
        observed = parsed.isoformat() if parsed else observed
    elif kind == "date_not_after":
        parsed = _as_date(observed)
        contract_start = _as_date(fields.get(str(required))) if isinstance(required, str) else _as_date(required)
        result = parsed is not None and contract_start is not None and parsed <= contract_start
        reason_code = "PASS" if result else ("FIELD_MISSING" if parsed is None else requirement.reason_code)
        required = contract_start.isoformat() if contract_start else required
        observed = parsed.isoformat() if parsed else observed
    elif kind == "date_buffer":
        parsed = _as_date(observed)
        buffer_days = int(required or 0)
        result = parsed is not None and parsed >= today + timedelta(days=buffer_days)
        reason_code = "PASS" if result else ("FIELD_MISSING" if parsed is None else requirement.reason_code)
        required = f">={today.isoformat()}+{buffer_days}d"
        observed = parsed.isoformat() if parsed else observed
    elif kind == "rating":
        observed_score = _rating_score(observed)
        required_score = _rating_score(required)
        result = observed_score is not None and required_score is not None and observed_score >= required_score
        reason_code = "PASS" if result else ("FIELD_MISSING" if observed_score is None else requirement.reason_code)
    elif kind == "current_document":
        result = observed == "received" and document.superseded_by is None
        reason_code = "PASS" if result else requirement.reason_code
    elif kind == "document_type":
        result = observed == required
        reason_code = "PASS" if result else requirement.reason_code
    else:
        reason_code = "FIELD_MISSING" if observed in (None, "") else requirement.reason_code

    if result:
        message = statement
    else:
        message = f"{statement} Observed {_display(observed)}; required {_display(required)}."
    return RuleResult(
        key=requirement.key,
        label=statement,
        field=field,
        result="pass" if result else "fail",
        reason_code=reason_code,
        message=message,
        observed_value=observed,
        required_value=required,
        requirement_id=requirement.id,
        confidence=confidence,
        explanation=statement,
    )
