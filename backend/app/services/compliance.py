"""Persistence boundary for versioned compliance policy and vendor bindings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    ComplianceRequirement,
    ComplianceRequirementSet,
    ReasonCodeTaxonomy,
    Vendor,
    VendorEntity,
    VendorRequirement,
    new_id,
    utc_now,
)
from app.services.compliance_catalog import REASON_CODES, RULE_LIBRARY, normalize_document_type


def _workspace_id(db: Session) -> str:
    workspace_id = db.info.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise DomainError("REQUEST_CONTEXT_MISSING", "A workspace-scoped database session is required", 500)
    return workspace_id


def _active_now(row: ComplianceRequirementSet, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return (
        row.status == "active"
        and (row.effective_from is None or row.effective_from <= now)
        and (row.effective_to is None or row.effective_to >= now)
    )


def seed_reason_codes(db: Session, *, workspace_id: str, actor_id: str) -> list[ReasonCodeTaxonomy]:
    existing = {
        row.code: row
        for row in db.scalars(
            select(ReasonCodeTaxonomy).where(
                ReasonCodeTaxonomy.workspace_id == workspace_id,
                ReasonCodeTaxonomy.taxonomy_version == "wedge-v1",
            )
        ).all()
    }
    rows: list[ReasonCodeTaxonomy] = []
    for item in REASON_CODES:
        row = existing.get(item["code"])
        if row is None:
            row = ReasonCodeTaxonomy(
                id=new_id(),
                workspace_id=workspace_id,
                taxonomy_version="wedge-v1",
                code=item["code"],
                label=item["label"],
                explanation=item["explanation"],
                created_by=actor_id,
            )
            db.add(row)
        rows.append(row)
    db.flush()
    return rows


def create_requirement_set(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    name: str,
    version: int,
    status: str = "active",
    project_id: str | None = None,
    custom_rules: list[dict[str, Any]] | None = None,
) -> ComplianceRequirementSet:
    if status not in {"draft", "active"}:
        raise DomainError("REQUIREMENT_SET_STATUS_INVALID", "Requirement set status must be draft or active", 422)
    if version < 1:
        raise DomainError("REQUIREMENT_SET_VERSION_INVALID", "Requirement set version must be positive", 422)
    workspace = _workspace_id(db)
    if workspace != workspace_id:
        raise DomainError("WORKSPACE_CONTEXT_MISMATCH", "Requirement set workspace does not match the active workspace", 403)
    existing = db.scalar(
        select(ComplianceRequirementSet).where(
            ComplianceRequirementSet.workspace_id == workspace_id,
            ComplianceRequirementSet.name == name,
            ComplianceRequirementSet.version == version,
        )
    )
    if existing is not None:
        raise DomainError("REQUIREMENT_SET_ALREADY_EXISTS", "That requirement-set version already exists", 409)
    if status == "active":
        active_sets = db.scalars(
            select(ComplianceRequirementSet).where(
                ComplianceRequirementSet.workspace_id == workspace_id,
                ComplianceRequirementSet.name == name,
                ComplianceRequirementSet.status == "active",
            )
        ).all()
        for active in active_sets:
            active.status = "superseded"
            active.effective_to = utc_now()
    row = ComplianceRequirementSet(
        id=new_id(),
        workspace_id=workspace_id,
        name=" ".join(name.split()),
        version=version,
        status=status,
        project_id=project_id,
        effective_from=utc_now() if status == "active" else None,
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    definitions = custom_rules if custom_rules is not None else [dict(item) for item in RULE_LIBRARY]
    keys = set()
    for definition in definitions:
        key = str(definition.get("key") or "").strip()
        if not key or key in keys:
            raise DomainError("REQUIREMENT_RULE_INVALID", "Every requirement must have a unique rule key", 422)
        keys.add(key)
        doc_type = normalize_document_type(str(definition.get("doc_type") or "COI"))
        statement = str(definition.get("statement") or "").strip()
        if not statement:
            raise DomainError("REQUIREMENT_EXPLANATION_REQUIRED", f"Rule {key} needs a human-readable statement", 422)
        rule_json = {
            "field": definition.get("field", key),
            "kind": definition.get("kind", "equals"),
            "required": definition.get("required"),
        }
        db.add(
            ComplianceRequirement(
                id=new_id(),
                workspace_id=workspace_id,
                requirement_set_id=row.id,
                key=key,
                doc_type=doc_type,
                rule_json=rule_json,
                severity=str(definition.get("severity") or "review"),
                reason_code=str(definition.get("reason_code") or "FIELD_MISSING"),
                human_statement=statement,
                active=True,
            )
        )
    seed_reason_codes(db, workspace_id=workspace_id, actor_id=actor_id)
    db.flush()
    return row


def active_requirement_context(
    db: Session,
    *,
    vendor: Vendor,
    project_id: str | None = None,
) -> tuple[ComplianceRequirementSet | None, dict[str, Any]]:
    workspace_id = _workspace_id(db)
    binding_query = (
        select(VendorRequirement, ComplianceRequirementSet)
        .join(ComplianceRequirementSet, ComplianceRequirementSet.id == VendorRequirement.requirement_set_id)
        .where(
            VendorRequirement.workspace_id == workspace_id,
            VendorRequirement.vendor_id == vendor.id,
            VendorRequirement.active.is_(True),
            ComplianceRequirementSet.status == "active",
        )
        .order_by(VendorRequirement.project_id.desc().nullslast(), ComplianceRequirementSet.version.desc())
    )
    bindings = db.execute(binding_query).all()
    for binding, requirement_set in bindings:
        if binding.project_id is None or binding.project_id == project_id:
            return requirement_set, dict(binding.overrides_json or {})
    global_set = db.scalar(
        select(ComplianceRequirementSet)
        .where(
            ComplianceRequirementSet.workspace_id == workspace_id,
            ComplianceRequirementSet.status == "active",
            ComplianceRequirementSet.project_id == project_id,
        )
        .order_by(ComplianceRequirementSet.version.desc(), ComplianceRequirementSet.created_at.desc())
    )
    if global_set is None and project_id is not None:
        global_set = db.scalar(
            select(ComplianceRequirementSet)
            .where(
                ComplianceRequirementSet.workspace_id == workspace_id,
                ComplianceRequirementSet.status == "active",
                ComplianceRequirementSet.project_id.is_(None),
            )
            .order_by(ComplianceRequirementSet.version.desc(), ComplianceRequirementSet.created_at.desc())
        )
    return global_set, {}


def applicable_requirements(
    db: Session,
    *,
    vendor: Vendor,
    doc_type: str,
    project_id: str | None = None,
) -> tuple[ComplianceRequirementSet | None, list[ComplianceRequirement], dict[str, Any]]:
    requirement_set, overrides = active_requirement_context(db, vendor=vendor, project_id=project_id)
    if requirement_set is None:
        return None, [], overrides
    normalized_doc_type = normalize_document_type(doc_type)
    rows = db.scalars(
        select(ComplianceRequirement)
        .where(
            ComplianceRequirement.workspace_id == _workspace_id(db),
            ComplianceRequirement.requirement_set_id == requirement_set.id,
            ComplianceRequirement.doc_type == normalized_doc_type,
            ComplianceRequirement.active.is_(True),
        )
        .order_by(ComplianceRequirement.key.asc())
    ).all()
    return requirement_set, rows, overrides


def requirement_set_payload(db: Session, row: ComplianceRequirementSet) -> dict[str, Any]:
    requirements = db.scalars(
        select(ComplianceRequirement)
        .where(
            ComplianceRequirement.requirement_set_id == row.id,
            ComplianceRequirement.workspace_id == row.workspace_id,
        )
        .order_by(ComplianceRequirement.key.asc())
    ).all()
    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "status": row.status,
        "project_id": row.project_id,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "created_at": row.created_at.isoformat(),
        "requirements": [
            {
                "id": requirement.id,
                "key": requirement.key,
                "doc_type": requirement.doc_type,
                "rule": requirement.rule_json,
                "severity": requirement.severity,
                "reason_code": requirement.reason_code,
                "human_statement": requirement.human_statement,
                "active": requirement.active,
            }
            for requirement in requirements
        ],
    }


def reason_code_rows_payload(rows: list[ReasonCodeTaxonomy]) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "taxonomy_version": row.taxonomy_version,
            "code": row.code,
            "label": row.label,
            "explanation": row.explanation,
            "active": row.active,
        }
        for row in rows
    ]


def vendor_entity_payload(row: VendorEntity) -> dict[str, Any]:
    return {"id": row.id, "vendor_id": row.vendor_id, "name": row.name, "relationship": row.entity_relationship, "active": row.active, "created_at": row.created_at.isoformat()}


def binding_payload(row: VendorRequirement) -> dict[str, Any]:
    return {
        "id": row.id,
        "vendor_id": row.vendor_id,
        "requirement_set_id": row.requirement_set_id,
        "project_id": row.project_id,
        "overrides": row.overrides_json,
        "active": row.active,
        "created_at": row.created_at.isoformat(),
    }
