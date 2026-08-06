"""Canonical wedge taxonomy, reason codes, and deterministic rule templates."""

from __future__ import annotations

from typing import Any


DOCUMENT_TYPES: tuple[dict[str, Any], ...] = (
    {"key": "COI", "label": "ACORD 25 certificate of insurance", "family": "insurance", "aliases": ["ACORD25", "ACORD 25", "CERTIFICATE_OF_INSURANCE"]},
    {"key": "ACORD_855", "label": "ACORD 855 / additional-insured endorsement", "family": "insurance", "aliases": ["ACORD855", "ADDITIONAL_INSURED", "AI_ENDORSEMENT"]},
    {"key": "W9", "label": "IRS W-9", "family": "tax", "aliases": ["W-9", "IRS_W9"]},
    {"key": "STATE_CONTRACTOR_LICENSE", "label": "State contractor licence", "family": "license", "aliases": ["STATE_LICENSE", "CONTRACTOR_LICENSE"]},
    {"key": "BUSINESS_LICENSE", "label": "Business licence", "family": "license", "aliases": ["BUSINESS_LICENCE"]},
    {"key": "WORKERS_COMP_EXEMPTION", "label": "Workers-comp exemption", "family": "insurance", "aliases": ["WC_EXEMPTION", "WORKERS_COMP_EXEMPTION_FORM"]},
    {"key": "OSHA_10_30", "label": "OSHA 10/30 safety certification", "family": "safety", "aliases": ["OSHA10", "OSHA30", "SAFETY_CERTIFICATION"]},
    {"key": "MSA", "label": "Master services agreement / subcontract", "family": "contract", "aliases": ["SUBCONTRACT", "SUBCONTRACT_AGREEMENT", "MSA_SUBCONTRACT"]},
    {"key": "LIEN_WAIVER_CONDITIONAL", "label": "Conditional lien waiver", "family": "lien", "aliases": ["CONDITIONAL_LIEN_WAIVER"]},
    {"key": "LIEN_WAIVER_UNCONDITIONAL", "label": "Unconditional lien waiver", "family": "lien", "aliases": ["UNCONDITIONAL_LIEN_WAIVER"]},
    {"key": "LIEN_WAIVER_PROGRESS", "label": "Progress lien waiver", "family": "lien", "aliases": ["PROGRESS_LIEN_WAIVER"]},
    {"key": "LIEN_WAIVER_FINAL", "label": "Final lien waiver", "family": "lien", "aliases": ["FINAL_LIEN_WAIVER"]},
)

DOCUMENT_TYPE_BY_ALIAS = {
    alias.casefold().replace("-", "_").replace(" ", "_"): item["key"]
    for item in DOCUMENT_TYPES
    for alias in [item["key"], *item["aliases"]]
}


REASON_CODES: tuple[dict[str, str], ...] = (
    {"code": "PASS", "label": "Passed", "explanation": "The observed evidence satisfies the versioned requirement."},
    {"code": "FIELD_MISSING", "label": "Required field missing", "explanation": "The source did not provide a value that can be verified deterministically."},
    {"code": "NAMED_INSURED_MISMATCH", "label": "Named insured mismatch", "explanation": "The named insured is not the vendor legal name or an active registered DBA/entity."},
    {"code": "DBA_VARIANT", "label": "Registered DBA variant", "explanation": "The named insured matches an active DBA or related vendor entity rather than the legal name."},
    {"code": "HOLDER_WRONG_ENTITY", "label": "Wrong certificate-holder entity", "explanation": "The certificate holder does not match the contracting entity configured for this workspace."},
    {"code": "LIMIT_BELOW_REQUIRED", "label": "Limit below required", "explanation": "The observed coverage limit is lower than the active requirement-set limit."},
    {"code": "AGGREGATE_SHARED_NOT_PER_PROJECT", "label": "Shared aggregate", "explanation": "The contract requires a per-project aggregate but the source only shows a shared aggregate."},
    {"code": "AUTO_COVERAGE_MISSING", "label": "Auto coverage missing", "explanation": "The required auto-liability evidence or combined single limit was not found."},
    {"code": "HIRED_NONOWNED_MISSING", "label": "Hired/non-owned auto missing", "explanation": "The requirement calls for hired and non-owned auto coverage and the source does not confirm it."},
    {"code": "UMBRELLA_UNDERLYING_MISMATCH", "label": "Umbrella underlying mismatch", "explanation": "The umbrella/excess evidence does not identify the required underlying policies."},
    {"code": "WC_EXEMPTION_INVALID_STATE", "label": "Workers-comp exemption invalid", "explanation": "The exemption is absent, expired, or not valid for the state of work."},
    {"code": "AI_ENDORSEMENT_MISSING", "label": "Additional insured missing", "explanation": "The required additional-insured endorsement was not confirmed."},
    {"code": "AI_FORM_EDITION_WRONG", "label": "Additional-insured form edition wrong", "explanation": "The endorsement form edition does not match the active requirement."},
    {"code": "COMPLETED_OPS_NOT_INCLUDED", "label": "Completed operations absent", "explanation": "The additional-insured evidence does not include completed operations when required."},
    {"code": "WAIVER_SUBRO_MISSING", "label": "Waiver of subrogation missing", "explanation": "The source does not confirm the required waiver of subrogation."},
    {"code": "PRIMARY_NONCONTRIB_MISSING", "label": "Primary/non-contributory missing", "explanation": "The source does not confirm primary and non-contributory wording."},
    {"code": "POLICY_EXPIRES_MID_CONTRACT", "label": "Policy expires during work", "explanation": "The policy period does not cover the entire configured contract/work period."},
    {"code": "CARRIER_RATING_LOW", "label": "Carrier rating below threshold", "explanation": "The carrier rating is below the minimum configured threshold."},
    {"code": "CARRIER_NOT_ADMITTED", "label": "Carrier not admitted", "explanation": "The carrier is not confirmed as admitted in the state of work."},
    {"code": "CANCELLATION_NOTICE_SHORT", "label": "Cancellation notice too short", "explanation": "The cancellation notice period is shorter than the contract requirement."},
    {"code": "EXPIRY_BUFFER_TOO_SHORT", "label": "Expiry buffer too short", "explanation": "The document expires sooner than the configured renewal buffer."},
    {"code": "DUPLICATE_SUPERSEDED", "label": "Duplicate or superseded document", "explanation": "This source is not the current effective document for the vendor requirement."},
    {"code": "ILLEGIBLE_SCAN", "label": "Illegible scan", "explanation": "The source quality is insufficient for a deterministic verification."},
    {"code": "WRONG_DOC_TYPE_SENT", "label": "Wrong document type", "explanation": "The submitted document does not match the open requirement's document type."},
    {"code": "MULTI_POLICY_SPLIT_ACROSS_PAGES", "label": "Evidence split across pages", "explanation": "Required coverage appears split or incomplete across the source pages."},
    {"code": "MANUAL_ALTERATION_SUSPECTED", "label": "Suspected manual alteration", "explanation": "The source contains a marker requiring human inspection before acceptance."},
    {"code": "EXPIRED_ON_ARRIVAL", "label": "Expired on arrival", "explanation": "The received document was already expired on the verification date."},
    {"code": "W9_NAME_MISMATCH", "label": "W-9 name mismatch", "explanation": "The W-9 legal name does not match the vendor legal name or registered DBA."},
    {"code": "W9_NOT_CURRENT", "label": "W-9 not current", "explanation": "The W-9 is missing a current signature or certification."},
    {"code": "LICENSE_EXPIRED", "label": "Licence expired", "explanation": "The licence expiration date is before the verification date or work period."},
    {"code": "MSA_NOT_EXECUTED", "label": "Agreement not executed", "explanation": "The MSA or subcontract does not show execution by the required parties."},
    {"code": "LIEN_WAIVER_TYPE_MISMATCH", "label": "Lien waiver type mismatch", "explanation": "The lien waiver variant does not match the requirement for this payment stage."},
    {"code": "OSHA_TRAINING_EXPIRED", "label": "Safety certification expired", "explanation": "The OSHA certification is not current for the work period."},
)


# Exactly 35 templates are shipped in the v1 library. Rule JSON is intentionally
# data-shaped so customers can version and test the policy without code edits.
RULE_LIBRARY: tuple[dict[str, Any], ...] = (
    {"key": "named_insured_match", "doc_type": "COI", "field": "named_insured", "kind": "vendor_name", "reason_code": "NAMED_INSURED_MISMATCH", "statement": "Named insured matches the vendor legal name or an active registered DBA/entity.", "required": True},
    {"key": "dba_registered", "doc_type": "COI", "field": "named_insured", "kind": "vendor_name", "reason_code": "NAMED_INSURED_MISMATCH", "statement": "A DBA or related entity used as named insured is registered on the vendor record.", "required": True},
    {"key": "certificate_holder_match", "doc_type": "COI", "field": "certificate_holder", "kind": "certificate_holder", "reason_code": "HOLDER_WRONG_ENTITY", "statement": "Certificate holder matches the contracting entity configured for this workspace.", "required": None},
    {"key": "gl_occurrence_minimum", "doc_type": "COI", "field": "gl_occurrence_limit", "kind": "minimum", "reason_code": "LIMIT_BELOW_REQUIRED", "statement": "GL occurrence limit meets the active contract minimum.", "required": 2_000_000},
    {"key": "gl_aggregate_minimum", "doc_type": "COI", "field": "gl_aggregate_limit", "kind": "minimum", "reason_code": "LIMIT_BELOW_REQUIRED", "statement": "GL aggregate limit meets the active contract minimum.", "required": 4_000_000},
    {"key": "gl_per_project_aggregate", "doc_type": "COI", "field": "per_project_aggregate", "kind": "boolean", "reason_code": "AGGREGATE_SHARED_NOT_PER_PROJECT", "statement": "GL aggregate is designated per project when the contract requires it.", "required": True},
    {"key": "auto_csl_minimum", "doc_type": "COI", "field": "auto_csl_limit", "kind": "minimum", "reason_code": "AUTO_COVERAGE_MISSING", "statement": "Auto liability combined single limit meets the active contract minimum.", "required": 1_000_000},
    {"key": "hired_non_owned_auto", "doc_type": "COI", "field": "hired_non_owned_auto", "kind": "boolean", "reason_code": "HIRED_NONOWNED_MISSING", "statement": "Hired and non-owned auto coverage is confirmed when required.", "required": True},
    {"key": "umbrella_minimum", "doc_type": "COI", "field": "umbrella_limit", "kind": "minimum", "reason_code": "LIMIT_BELOW_REQUIRED", "statement": "Umbrella/excess limit meets the active contract minimum.", "required": 5_000_000},
    {"key": "umbrella_underlying_alignment", "doc_type": "COI", "field": "umbrella_underlying_aligned", "kind": "boolean", "reason_code": "UMBRELLA_UNDERLYING_MISMATCH", "statement": "Umbrella/excess sits over the required underlying policies.", "required": True},
    {"key": "workers_comp_present", "doc_type": "COI", "field": "workers_comp_present", "kind": "boolean", "reason_code": "FIELD_MISSING", "statement": "Workers-comp coverage is present or a valid exemption is supplied.", "required": True},
    {"key": "workers_comp_exemption_valid", "doc_type": "WORKERS_COMP_EXEMPTION", "field": "workers_comp_exemption_valid", "kind": "boolean", "reason_code": "WC_EXEMPTION_INVALID_STATE", "statement": "Workers-comp exemption is valid for the state of work and current work period.", "required": True},
    {"key": "additional_insured_present", "doc_type": "ACORD_855", "field": "additional_insured", "kind": "boolean", "reason_code": "AI_ENDORSEMENT_MISSING", "statement": "Additional-insured endorsement is present for the contracting entity.", "required": True},
    {"key": "additional_insured_form_edition", "doc_type": "ACORD_855", "field": "ai_form_edition", "kind": "equals", "reason_code": "AI_FORM_EDITION_WRONG", "statement": "Additional-insured endorsement uses the required form edition.", "required": "current"},
    {"key": "ongoing_operations", "doc_type": "ACORD_855", "field": "ongoing_operations", "kind": "boolean", "reason_code": "AI_ENDORSEMENT_MISSING", "statement": "Additional-insured endorsement includes ongoing operations.", "required": True},
    {"key": "completed_operations", "doc_type": "ACORD_855", "field": "completed_operations", "kind": "boolean", "reason_code": "COMPLETED_OPS_NOT_INCLUDED", "statement": "Additional-insured endorsement includes completed operations.", "required": True},
    {"key": "waiver_of_subrogation", "doc_type": "ACORD_855", "field": "waiver_of_subrogation", "kind": "boolean", "reason_code": "WAIVER_SUBRO_MISSING", "statement": "Waiver of subrogation is present for the required lines.", "required": True},
    {"key": "primary_non_contributory", "doc_type": "ACORD_855", "field": "primary_non_contributory", "kind": "boolean", "reason_code": "PRIMARY_NONCONTRIB_MISSING", "statement": "Primary and non-contributory wording is present.", "required": True},
    {"key": "policy_period_start", "doc_type": "COI", "field": "policy_effective", "kind": "date_not_after", "reason_code": "POLICY_EXPIRES_MID_CONTRACT", "statement": "Policy effective date starts no later than the configured work period.", "required": "contract_start"},
    {"key": "policy_period_covers_work", "doc_type": "COI", "field": "policy_expiry", "kind": "date_covers", "reason_code": "POLICY_EXPIRES_MID_CONTRACT", "statement": "Policy period covers the entire configured contract/work period.", "required": "contract_end"},
    {"key": "carrier_rating_minimum", "doc_type": "COI", "field": "am_best_rating", "kind": "rating", "reason_code": "CARRIER_RATING_LOW", "statement": "Carrier AM Best rating meets the active minimum.", "required": "A-"},
    {"key": "carrier_admitted", "doc_type": "COI", "field": "carrier_admitted", "kind": "boolean", "reason_code": "CARRIER_NOT_ADMITTED", "statement": "Carrier is admitted in the state of work.", "required": True},
    {"key": "cancellation_notice", "doc_type": "COI", "field": "cancellation_notice_days", "kind": "minimum", "reason_code": "CANCELLATION_NOTICE_SHORT", "statement": "Cancellation notice provision meets the contract terms.", "required": 30},
    {"key": "expiry_buffer", "doc_type": "COI", "field": "policy_expiry", "kind": "date_buffer", "reason_code": "EXPIRY_BUFFER_TOO_SHORT", "statement": "Policy expiry is at least the configured renewal buffer away.", "required": 45},
    {"key": "duplicate_superseded", "doc_type": "COI", "field": "document_status", "kind": "current_document", "reason_code": "DUPLICATE_SUPERSEDED", "statement": "The document is the current non-superseded source for this requirement.", "required": "received"},
    {"key": "scan_quality", "doc_type": "COI", "field": "scan_quality", "kind": "equals", "reason_code": "ILLEGIBLE_SCAN", "statement": "Source scan quality is sufficient for deterministic verification.", "required": "good"},
    {"key": "document_type_match", "doc_type": "COI", "field": "document_type", "kind": "document_type", "reason_code": "WRONG_DOC_TYPE_SENT", "statement": "The submitted document type matches the active requirement.", "required": "COI"},
    {"key": "w9_legal_name_match", "doc_type": "W9", "field": "w9_name", "kind": "vendor_name", "reason_code": "W9_NAME_MISMATCH", "statement": "W-9 legal name matches the vendor legal name or an active registered DBA/entity.", "required": True},
    {"key": "w9_current", "doc_type": "W9", "field": "w9_current", "kind": "boolean", "reason_code": "W9_NOT_CURRENT", "statement": "W-9 is currently signed and certified.", "required": True},
    {"key": "state_license_valid", "doc_type": "STATE_CONTRACTOR_LICENSE", "field": "license_expiry", "kind": "date_future", "reason_code": "LICENSE_EXPIRED", "statement": "State contractor licence remains valid for the verification date.", "required": True},
    {"key": "business_license_valid", "doc_type": "BUSINESS_LICENSE", "field": "business_license_expiry", "kind": "date_future", "reason_code": "LICENSE_EXPIRED", "statement": "Business licence remains valid for the verification date.", "required": True},
    {"key": "msa_executed", "doc_type": "MSA", "field": "msa_executed", "kind": "boolean", "reason_code": "MSA_NOT_EXECUTED", "statement": "MSA or subcontract is executed by the required parties.", "required": True},
    {"key": "lien_waiver_type", "doc_type": "LIEN_WAIVER_CONDITIONAL", "field": "lien_waiver_type", "kind": "document_type", "reason_code": "LIEN_WAIVER_TYPE_MISMATCH", "statement": "Lien waiver variant matches the required payment stage.", "required": "LIEN_WAIVER_CONDITIONAL"},
    {"key": "osha_training_current", "doc_type": "OSHA_10_30", "field": "osha_expiry", "kind": "date_future", "reason_code": "OSHA_TRAINING_EXPIRED", "statement": "OSHA 10/30 safety certification remains current for the work period.", "required": True},
    {"key": "manual_alteration_clear", "doc_type": "COI", "field": "manual_alteration_suspected", "kind": "boolean_false", "reason_code": "MANUAL_ALTERATION_SUSPECTED", "statement": "No manual-alteration marker requires human inspection.", "required": False},
)


def normalize_document_type(value: str | None) -> str:
    if not value:
        return "COI"
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    short_variants = {
        "conditional": "LIEN_WAIVER_CONDITIONAL",
        "unconditional": "LIEN_WAIVER_UNCONDITIONAL",
        "progress": "LIEN_WAIVER_PROGRESS",
        "final": "LIEN_WAIVER_FINAL",
    }
    if normalized in short_variants:
        return short_variants[normalized]
    return DOCUMENT_TYPE_BY_ALIAS.get(normalized, value.strip().upper().replace("-", "_"))


def document_type_payload() -> list[dict[str, Any]]:
    return [dict(item) for item in DOCUMENT_TYPES]


def rule_library_payload() -> list[dict[str, Any]]:
    return [dict(item) for item in RULE_LIBRARY]


def reason_code_payload() -> list[dict[str, str]]:
    return [dict(item) for item in REASON_CODES]
