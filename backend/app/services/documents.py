from datetime import date, datetime
from io import BytesIO
import re
from typing import Any

from app.errors import DomainError


FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "named_insured": (r"named\s+insured", r"insured\s+name"),
    "certificate_holder": (r"certificate\s+holder", r"holder"),
    "gl_occurrence_limit": (r"gl\s+occurrence\s+limit", r"general\s+liability\s+occurrence", r"occurrence\s+limit"),
    "policy_expiry": (r"policy\s+expiry", r"policy\s+expiration", r"expiration\s+date", r"expiry"),
    "additional_insured": (r"additional\s+insured",),
    "waiver_of_subrogation": (r"waiver\s+of\s+subrogation", r"waiver\s+subrogation"),
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
            "This PDF has no readable text. Image-only OCR is outside the MVP; upload a text-readable COI.",
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


def extract_document_fields(content: bytes, filename: str, media_type: str) -> dict[str, Any]:
    return normalize_fields(extract_text(content, filename, media_type))


def coerce_correction(field: str, value: Any) -> Any:
    if field in {"named_insured", "certificate_holder"}:
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
    if field in {"additional_insured", "waiver_of_subrogation"}:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            parsed = _parse_bool(value)
            if parsed is not None:
                return parsed
        raise DomainError("CORRECTION_INVALID", f"{field} must be true/false or yes/no", 422)
    if field == "policy_expiry":
        normalized = _parse_date(str(value))
        if normalized is None:
            raise DomainError("CORRECTION_INVALID", "policy_expiry must be YYYY-MM-DD or MM/DD/YYYY", 422)
        return normalized
    raise DomainError("CORRECTION_FIELD_UNSUPPORTED", f"The field {field} cannot be corrected in the MVP", 422)


def as_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
