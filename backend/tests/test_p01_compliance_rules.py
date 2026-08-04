import json
from datetime import date
from pathlib import Path

from app.models import ComplianceDocument, ComplianceRequirement, Vendor
from app.services.compliance_catalog import RULE_LIBRARY
from app.services.compliance_rules import evaluate_requirement
from app.services.documents import extract_document_fields


GOLDEN_PATH = Path(__file__).resolve().parents[2] / "tests" / "golden" / "wedge_cases.json"


def _scenario(definition: dict, passing: bool) -> tuple[Vendor, ComplianceDocument, ComplianceRequirement, dict]:
    vendor = Vendor(id="golden-vendor", workspace_id="golden-workspace", legal_name="Acme Mechanical LLC", dba_names_json=["Acme Mechanical Services"])
    doc_type = definition["doc_type"]
    fields = {
        "named_insured": "Acme Mechanical LLC",
        "certificate_holder": "Northwind Construction LLC",
        "gl_occurrence_limit": 2_000_000,
        "gl_aggregate_limit": 4_000_000,
        "per_project_aggregate": True,
        "auto_csl_limit": 1_000_000,
        "hired_non_owned_auto": True,
        "umbrella_limit": 5_000_000,
        "umbrella_underlying_aligned": True,
        "workers_comp_present": True,
        "workers_comp_exemption_valid": True,
        "additional_insured": True,
        "ai_form_edition": "current",
        "ongoing_operations": True,
        "completed_operations": True,
        "waiver_of_subrogation": True,
        "primary_non_contributory": True,
        "policy_effective": "2026-01-01",
        "policy_expiry": "2099-12-31",
        "contract_start": "2026-02-01",
        "contract_end": "2026-12-31",
        "am_best_rating": "A-",
        "carrier_admitted": True,
        "cancellation_notice_days": 30,
        "document_status": "received",
        "scan_quality": "good",
        "document_type": doc_type,
        "w9_name": "Acme Mechanical LLC",
        "w9_current": True,
        "license_expiry": "2099-12-31",
        "business_license_expiry": "2099-12-31",
        "msa_executed": True,
        "lien_waiver_type": "LIEN_WAIVER_CONDITIONAL",
        "osha_expiry": "2099-12-31",
        "manual_alteration_suspected": False,
    }
    key = definition["key"]
    field = definition.get("field", key)
    kind = definition.get("kind")
    if passing is False:
        if kind == "vendor_name":
            fields[field] = "Different Vendor LLC"
        elif kind == "certificate_holder":
            fields[field] = "Wrong Contracting Entity"
        elif kind == "minimum":
            fields[field] = max(0, int(definition["required"]) - 1)
        elif kind in {"boolean", "boolean_false"}:
            fields[field] = False if kind == "boolean" else True
        elif kind == "equals":
            fields[field] = "legacy"
        elif kind in {"date_future", "date_buffer"}:
            fields[field] = "2020-01-01"
        elif kind == "date_covers":
            fields[field] = "2026-06-01"
        elif kind == "date_not_after":
            fields[field] = "2026-03-01"
        elif kind == "rating":
            fields[field] = "B"
        elif kind == "current_document":
            fields[field] = "superseded"
        elif kind == "document_type":
            fields[field] = "WRONG"
    if key == "dba_registered" and passing:
        fields[field] = "Acme Mechanical Services"
    document = ComplianceDocument(
        id="golden-document",
        workspace_id="golden-workspace",
        vendor_id=vendor.id,
        doc_type="WRONG" if kind == "document_type" and not passing else doc_type,
        filename="golden.txt",
        media_type="text/plain",
        content=b"golden evidence",
        extracted_fields=fields,
        status=fields["document_status"],
    )
    if kind == "current_document" and not passing:
        document.status = "superseded"
        document.superseded_by = "newer-document"
    requirement = ComplianceRequirement(
        id=f"requirement-{key}",
        workspace_id="golden-workspace",
        requirement_set_id="golden-set",
        key=key,
        doc_type=doc_type,
        rule_json={"field": field, "kind": kind, "required": definition.get("required")},
        reason_code=definition["reason_code"],
        human_statement=definition["statement"],
    )
    return vendor, document, requirement, fields


def test_wedge_library_has_exactly_35_explainable_rules() -> None:
    assert len(RULE_LIBRARY) == 35
    assert len({item["key"] for item in RULE_LIBRARY}) == 35
    assert all(item["statement"].strip() for item in RULE_LIBRARY)
    assert all(item["reason_code"].strip() for item in RULE_LIBRARY)


def test_100_case_wedge_golden_set_is_deterministic() -> None:
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(cases) >= 100
    assert len({case["id"] for case in cases}) == len(cases)
    by_key = {item["key"]: item for item in RULE_LIBRARY}
    assert {case["rule"] for case in cases} <= set(by_key)
    for case in cases:
        vendor, document, requirement, fields = _scenario(by_key[case["rule"]], case["expected"] == "pass")
        result = evaluate_requirement(requirement, vendor=vendor, document=document, fields=fields, today=date(2026, 8, 4))
        assert result.result == case["expected"], f"{case['id']} returned {result.result}: {result.message}"
        assert result.explanation == requirement.human_statement


def test_v1_document_fixtures_are_readable_and_typed() -> None:
    fixture_dir = GOLDEN_PATH.parents[1] / "fixtures" / "p01"
    fixture_types = {
        "coi-complete.txt": "COI",
        "acord-855-complete.txt": "ACORD_855",
        "w9-complete.txt": "W9",
        "state-contractor-license.txt": "STATE_CONTRACTOR_LICENSE",
        "business-license.txt": "BUSINESS_LICENSE",
        "workers-comp-exemption.txt": "WORKERS_COMP_EXEMPTION",
        "osha-10-30.txt": "OSHA_10_30",
        "msa-executed.txt": "MSA",
        "lien-conditional.txt": "LIEN_WAIVER_CONDITIONAL",
        "lien-unconditional.txt": "LIEN_WAIVER_UNCONDITIONAL",
        "lien-progress.txt": "LIEN_WAIVER_PROGRESS",
        "lien-final.txt": "LIEN_WAIVER_FINAL",
    }
    for filename, doc_type in fixture_types.items():
        fields = extract_document_fields((fixture_dir / filename).read_bytes(), filename, "text/plain", doc_type)
        assert fields["document_type"] == doc_type
