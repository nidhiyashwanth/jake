from datetime import date, datetime
from io import BytesIO
import re
from typing import Any

from app.errors import DomainError
from app.services.compliance_catalog import normalize_document_type


FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "named_insured": (r"named\s+insured", r"insured\s+name"),
    "certificate_holder": (r"certificate\s+holder", r"holder"),
    "gl_occurrence_limit": (r"gl\s+occurrence\s+limit", r"general\s+liability\s+occurrence", r"occurrence\s+limit"),
    "policy_expiry": (r"policy\s+expiry", r"policy\s+expiration", r"expiration\s+date", r"expiry"),
    "additional_insured": (r"additional\s+insured",),
    "waiver_of_subrogation": (r"waiver\s+of\s+subrogation", r"waiver\s+subrogation"),
}

EXTENDED_FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "gl_aggregate_limit": (r"gl\s+aggregate\s+limit", r"general\s+liability\s+aggregate", r"aggregate\s+limit"),
    "per_project_aggregate": (r"per\s+project\s+aggregate", r"aggregate\s+per\s+project"),
    "auto_csl_limit": (r"auto\s+csl\s+limit", r"auto\s+liability\s+combined", r"combined\s+single\s+limit"),
    "hired_non_owned_auto": (r"hired\s+and\s+non[- ]owned\s+auto", r"hired/non[- ]owned\s+auto"),
    "umbrella_limit": (r"umbrella\s+limit", r"excess\s+limit"),
    "umbrella_underlying_aligned": (r"umbrella\s+underlying\s+aligned", r"underlying\s+policies\s+aligned"),
    "workers_comp_present": (r"workers[ -]comp\s+present", r"workers[ -]comp\s+coverage"),
    "workers_comp_exemption_valid": (r"workers[ -]comp\s+exemption\s+valid", r"exemption\s+valid"),
    "ai_form_edition": (r"additional\s+insured\s+form\s+edition", r"ai\s+form\s+edition", r"form\s+edition"),
    "ongoing_operations": (r"ongoing\s+operations",),
    "completed_operations": (r"completed\s+operations",),
    "primary_non_contributory": (r"primary\s+and\s+non[- ]contributory", r"primary/non[- ]contributory"),
    "policy_effective": (r"policy\s+effective", r"effective\s+date", r"policy\s+start"),
    "carrier": (r"carrier", r"insurer"),
    "am_best_rating": (r"am\s+best\s+rating", r"am\s+best"),
    "carrier_admitted": (r"carrier\s+admitted", r"admitted\s+carrier"),
    "cancellation_notice_days": (r"cancellation\s+notice\s+days", r"cancellation\s+notice", r"notice\s+days"),
    "scan_quality": (r"scan\s+quality", r"document\s+quality"),
    "manual_alteration_suspected": (r"manual\s+alteration", r"alteration\s+suspected"),
    "contract_start": (r"contract\s+start", r"work\s+start"),
    "contract_end": (r"contract\s+end", r"work\s+end"),
    "w9_name": (r"w[- ]?9\s+name", r"taxpayer\s+name"),
    "w9_current": (r"w[- ]?9\s+current", r"w[- ]?9\s+signed", r"w[- ]?9\s+certified"),
    "license_expiry": (r"contractor\s+licen[cs]e\s+expiry", r"license\s+expiry", r"licence\s+expiry"),
    "business_license_expiry": (r"business\s+licen[cs]e\s+expiry", r"business\s+expiry"),
    "msa_executed": (r"msa\s+executed", r"agreement\s+executed", r"subcontract\s+executed"),
    "lien_waiver_type": (r"lien\s+waiver\s+type",),
    "osha_expiry": (r"osha\s+(?:10|30)\s+expiry", r"safety\s+certification\s+expiry", r"osha\s+expiry"),
}


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # pypdf exposes several parser-specific exceptions.
        raise DomainError("DOCUMENT_PARSE_FAILED", f"The PDF could not be read: {exc}", 422) from exc
    if not text.strip():
        raise DomainError(
            "OCR_REQUIRED",
            "This PDF has no readable text. Image-only OCR is outside the MVP; upload a text-readable compliance document.",
            422,
        )
    return text


def extract_text(content: bytes, filename: str, media_type: str) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if media_type == "application/pdf" or suffix == "pdf":
        return _extract_pdf_text(content)
    if media_type.startswith("text/") or suffix in {"txt", "text", "csv"}:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DomainError("DOCUMENT_ENCODING_UNSUPPORTED", "Text documents must be UTF-8 encoded", 422) from exc
        if not text.strip():
            raise DomainError("DOCUMENT_EMPTY", "The uploaded document contains no text", 422)
        return text
    raise DomainError("DOCUMENT_TYPE_UNSUPPORTED", "Upload a text-readable .txt or .pdf COI", 415)


def _first_label_value(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        # Keep label matching on one physical line. Using ``\s`` here would
        # let an empty label consume the next field through a newline.
        match = re.search(rf"(?im)^[ \t]*(?:{label})[ \t]*[:\-][ \t]*(.+?)[ \t]*$", text)
        if match:
            value = " ".join(match.group(1).strip().split())
            return value or None
    return None


def _parse_limit(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.upper().replace(",", "").replace("$", "").replace("USD", "").strip()
    million_match = re.search(r"(\d+(?:\.\d+)?)\s*M(?:ILLION)?", normalized)
    if million_match:
        return int(float(million_match.group(1)) * 1_000_000)
    number_match = re.search(r"\d+", normalized)
    return int(number_match.group(0)) if number_match else None


def _parse_bool(value: str | None) -> bool | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    if normalized in {"yes", "true", "present", "included", "y"}:
        return True
    if normalized in {"no", "false", "absent", "not included", "n"}:
        return False
    return None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value.replace(",", ""))
    return int(match.group(0)) if match else None


def _parse_quality(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    if normalized in {"good", "clear", "readable", "pass"}:
        return "good"
    if normalized in {"poor", "illegible", "bad", "fail"}:
        return "poor"
    return normalized[:40]


def normalize_fields(text: str) -> dict[str, Any]:
    raw = {key: _first_label_value(text, labels) for key, labels in FIELD_PATTERNS.items()}
    return {
        "named_insured": raw["named_insured"],
        "certificate_holder": raw["certificate_holder"],
        "gl_occurrence_limit": _parse_limit(raw["gl_occurrence_limit"]),
        "policy_expiry": _parse_date(raw["policy_expiry"]),
        "additional_insured": _parse_bool(raw["additional_insured"]),
        "waiver_of_subrogation": _parse_bool(raw["waiver_of_subrogation"]),
    }


def normalize_extended_fields(text: str, doc_type: str = "COI") -> dict[str, Any]:
    """Parse the bounded text fixture contract for every v1 document type."""

    fields = normalize_fields(text)
    raw = {key: _first_label_value(text, labels) for key, labels in EXTENDED_FIELD_PATTERNS.items()}
    fields.update(
        {
            "gl_aggregate_limit": _parse_limit(raw["gl_aggregate_limit"]),
            "per_project_aggregate": _parse_bool(raw["per_project_aggregate"]),
            "auto_csl_limit": _parse_limit(raw["auto_csl_limit"]),
            "hired_non_owned_auto": _parse_bool(raw["hired_non_owned_auto"]),
            "umbrella_limit": _parse_limit(raw["umbrella_limit"]),
            "umbrella_underlying_aligned": _parse_bool(raw["umbrella_underlying_aligned"]),
            "workers_comp_present": _parse_bool(raw["workers_comp_present"]),
            "workers_comp_exemption_valid": _parse_bool(raw["workers_comp_exemption_valid"]),
            "ai_form_edition": raw["ai_form_edition"],
            "ongoing_operations": _parse_bool(raw["ongoing_operations"]),
            "completed_operations": _parse_bool(raw["completed_operations"]),
            "primary_non_contributory": _parse_bool(raw["primary_non_contributory"]),
            "policy_effective": _parse_date(raw["policy_effective"]),
            "carrier": raw["carrier"],
            "am_best_rating": raw["am_best_rating"],
            "carrier_admitted": _parse_bool(raw["carrier_admitted"]),
            "cancellation_notice_days": _parse_int(raw["cancellation_notice_days"]),
            "scan_quality": _parse_quality(raw["scan_quality"]),
            "manual_alteration_suspected": _parse_bool(raw["manual_alteration_suspected"]),
            "contract_start": _parse_date(raw["contract_start"]),
            "contract_end": _parse_date(raw["contract_end"]),
            "w9_name": raw["w9_name"],
            "w9_current": _parse_bool(raw["w9_current"]),
            "license_expiry": _parse_date(raw["license_expiry"]),
            "business_license_expiry": _parse_date(raw["business_license_expiry"]),
            "msa_executed": _parse_bool(raw["msa_executed"]),
            "lien_waiver_type": normalize_document_type(raw["lien_waiver_type"]) if raw["lien_waiver_type"] else None,
            "osha_expiry": _parse_date(raw["osha_expiry"]),
            "document_type": normalize_document_type(doc_type),
        }
    )
    # A labelled quality marker is preferred. If none exists, the source is
    # still readable but remains explicitly reviewable rather than inferred as
    # a positive quality assertion.
    return fields


def extract_document_fields(content: bytes, filename: str, media_type: str, doc_type: str = "COI") -> dict[str, Any]:
    return normalize_extended_fields(extract_text(content, filename, media_type), doc_type=doc_type)


def coerce_correction(field: str, value: Any) -> Any:
    if field in {"named_insured", "certificate_holder", "w9_name", "carrier", "ai_form_edition", "lien_waiver_type", "scan_quality"}:
        if not isinstance(value, str) or not value.strip():
            raise DomainError("CORRECTION_INVALID", f"{field} must be a non-empty string", 422)
        return " ".join(value.split())
    if field == "gl_occurrence_limit":
        if isinstance(value, bool):
            raise DomainError("CORRECTION_INVALID", "gl_occurrence_limit must be an integer", 422)
        try:
            normalized = str(value).replace(",", "").replace("$", "").strip()
            number = int(normalized)
        except (TypeError, ValueError) as exc:
            raise DomainError("CORRECTION_INVALID", "gl_occurrence_limit must be an integer", 422) from exc
        if number < 0:
            raise DomainError("CORRECTION_INVALID", "gl_occurrence_limit cannot be negative", 422)
        return number
    if field in {
        "additional_insured",
        "waiver_of_subrogation",
        "per_project_aggregate",
        "hired_non_owned_auto",
        "umbrella_underlying_aligned",
        "workers_comp_present",
        "workers_comp_exemption_valid",
        "ongoing_operations",
        "completed_operations",
        "primary_non_contributory",
        "carrier_admitted",
        "w9_current",
        "msa_executed",
        "manual_alteration_suspected",
    }:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            parsed = _parse_bool(value)
            if parsed is not None:
                return parsed
        raise DomainError("CORRECTION_INVALID", f"{field} must be true/false or yes/no", 422)
    if field in {"policy_expiry", "policy_effective", "contract_start", "contract_end", "license_expiry", "business_license_expiry", "osha_expiry"}:
        normalized = _parse_date(str(value))
        if normalized is None:
            raise DomainError("CORRECTION_INVALID", f"{field} must be YYYY-MM-DD or MM/DD/YYYY", 422)
        return normalized
    if field in {"gl_aggregate_limit", "auto_csl_limit", "umbrella_limit", "cancellation_notice_days"}:
        if isinstance(value, bool):
            raise DomainError("CORRECTION_INVALID", f"{field} must be numeric", 422)
        try:
            return int(str(value).replace(",", "").replace("$", "").strip())
        except (TypeError, ValueError) as exc:
            raise DomainError("CORRECTION_INVALID", f"{field} must be numeric", 422) from exc
    raise DomainError("CORRECTION_FIELD_UNSUPPORTED", f"The field {field} cannot be corrected in the MVP", 422)


def as_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
