"""API boundary for the P-01 compliance catalog and chase sandbox."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ComplianceRequirementSet, ReasonCodeTaxonomy, VendorEntity, VendorRequirement, new_id
from app.schemas import ChaseCreate, ChaseReplyRequest, ChaseTouchRequest, RequirementSetCreate, VendorEntityCreate, VendorRequirementBind
from app.services.audit import append_audit_log
from app.services.authorization import authorize
from app.services.chase import chase_payload, create_chase_thread, get_chase_or_404, record_chase_reply, send_chase_touch
from app.services.compliance import (
    binding_payload,
    create_requirement_set,
    reason_code_rows_payload,
    requirement_set_payload,
    seed_reason_codes,
    vendor_entity_payload,
)
from app.services.compliance_catalog import document_type_payload, reason_code_payload, rule_library_payload
from app.services.repositories import get_vendor_or_404
from app.services.tenancy import current_context, get_scoped_db


router = APIRouter(prefix="/api", tags=["compliance"])
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


@router.get("/compliance/document-types")
def list_document_types(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "compliance.read", target_type="document_taxonomy", target_id=context.workspace_id)
    return {"items": document_type_payload(), "count": len(document_type_payload())}


@router.get("/compliance/rule-library")
def list_rule_library(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "compliance.read", target_type="rule_library", target_id=context.workspace_id)
    return {"items": rule_library_payload(), "count": len(rule_library_payload())}


@router.get("/compliance/reason-codes")
def list_reason_codes(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "compliance.read", target_type="reason_code_taxonomy", target_id=context.workspace_id)
    rows = db.scalars(
        select(ReasonCodeTaxonomy)
        .where(ReasonCodeTaxonomy.workspace_id == context.workspace_id, ReasonCodeTaxonomy.active.is_(True))
        .order_by(ReasonCodeTaxonomy.code.asc())
    ).all()
    items = reason_code_rows_payload(rows) if rows else reason_code_payload()
    return {"items": items, "count": len(items), "taxonomy_version": rows[0].taxonomy_version if rows else "wedge-v1"}


@router.get("/compliance/requirement-sets")
def list_requirement_sets(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "requirement.read", target_type="requirement_set_index", target_id=context.workspace_id)
    rows = db.scalars(
        select(ComplianceRequirementSet)
        .where(ComplianceRequirementSet.workspace_id == context.workspace_id)
        .order_by(ComplianceRequirementSet.name.asc(), ComplianceRequirementSet.version.desc())
    ).all()
    return {"items": [requirement_set_payload(db, row) for row in rows], "count": len(rows)}


@router.post("/compliance/requirement-sets", status_code=201)
def create_requirement_set_route(payload: RequirementSetCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "requirement.manage", target_type="requirement_set", target_id=payload.name)
    row = create_requirement_set(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        name=payload.name,
        version=payload.version,
        status=payload.status,
        project_id=payload.project_id,
        custom_rules=payload.custom_rules,
    )
    append_audit_log(
        db,
        action="compliance.requirement_set.created",
        target_type="requirement_set",
        target_id=row.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"name": row.name, "version": row.version, "status": row.status, "requirement_count": len(row.requirements)},
    )
    db.commit()
    db.refresh(row)
    return {"requirement_set": requirement_set_payload(db, row)}


@router.get("/compliance/requirement-sets/{requirement_set_id}")
def get_requirement_set(requirement_set_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "requirement.read", target_type="requirement_set", target_id=requirement_set_id)
    row = db.scalar(
        select(ComplianceRequirementSet).where(
            ComplianceRequirementSet.id == requirement_set_id,
            ComplianceRequirementSet.workspace_id == context.workspace_id,
        )
    )
    if row is None:
        raise DomainError("REQUIREMENT_SET_NOT_FOUND", "The requirement-set version was not found", 404)
    return {"requirement_set": requirement_set_payload(db, row)}


@router.get("/vendors/{vendor_id}/entities")
def list_vendor_entities(vendor_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "compliance.read", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    rows = db.scalars(
        select(VendorEntity)
        .where(VendorEntity.workspace_id == context.workspace_id, VendorEntity.vendor_id == vendor.id, VendorEntity.active.is_(True))
        .order_by(VendorEntity.name.asc())
    ).all()
    return {"items": [vendor_entity_payload(row) for row in rows], "count": len(rows)}


@router.post("/vendors/{vendor_id}/entities", status_code=201)
def create_vendor_entity(vendor_id: str, payload: VendorEntityCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "vendor.entity.manage", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    row = VendorEntity(
        id=new_id(),
        workspace_id=context.workspace_id,
        vendor_id=vendor.id,
        name=" ".join(payload.name.split()),
        entity_relationship=payload.relationship,
    )
    db.add(row)
    vendor.dba_names_json = [*(vendor.dba_names_json or []), row.name] if payload.relationship == "dba" else (vendor.dba_names_json or [])
    append_audit_log(db, action="vendor.entity.created", target_type="vendor_entity", target_id=row.id, workspace_id=context.workspace_id, actor_id=context.user_id, after={"name": row.name, "relationship": row.entity_relationship})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("VENDOR_ENTITY_ALREADY_EXISTS", "That vendor entity already exists", 409) from exc
    db.refresh(row)
    return {"entity": vendor_entity_payload(row)}


@router.get("/vendors/{vendor_id}/requirement-bindings")
def list_vendor_requirement_bindings(vendor_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "requirement.read", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    rows = db.scalars(
        select(VendorRequirement)
        .where(VendorRequirement.workspace_id == context.workspace_id, VendorRequirement.vendor_id == vendor.id)
        .order_by(VendorRequirement.created_at.desc())
    ).all()
    return {"items": [binding_payload(row) for row in rows], "count": len(rows)}


@router.post("/vendors/{vendor_id}/requirement-bindings", status_code=201)
def bind_vendor_requirement_set(vendor_id: str, payload: VendorRequirementBind, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "requirement.manage", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    requirement_set = db.scalar(
        select(ComplianceRequirementSet).where(
            ComplianceRequirementSet.id == payload.requirement_set_id,
            ComplianceRequirementSet.workspace_id == context.workspace_id,
        )
    )
    if requirement_set is None:
        raise DomainError("REQUIREMENT_SET_NOT_FOUND", "The requirement-set version was not found", 404)
    if requirement_set.status != "active":
        raise DomainError("REQUIREMENT_SET_NOT_ACTIVE", "Only an active requirement-set version can be bound", 422)
    row = VendorRequirement(
        id=new_id(),
        workspace_id=context.workspace_id,
        vendor_id=vendor.id,
        requirement_set_id=requirement_set.id,
        project_id=payload.project_id,
        overrides_json=payload.overrides,
        created_by=context.user_id,
    )
    db.add(row)
    append_audit_log(db, action="vendor.requirement_set.bound", target_type="vendor_requirement", target_id=row.id, workspace_id=context.workspace_id, actor_id=context.user_id, after={"requirement_set_id": requirement_set.id, "project_id": payload.project_id})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("VENDOR_REQUIREMENT_ALREADY_BOUND", "That vendor and requirement-set scope is already bound", 409) from exc
    db.refresh(row)
    return {"binding": binding_payload(row)}


@router.get("/vendors/{vendor_id}/chases")
def list_chases(vendor_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "chase.read", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    from app.models import ChaseThread

    rows = db.scalars(
        select(ChaseThread)
        .where(ChaseThread.workspace_id == context.workspace_id, ChaseThread.vendor_id == vendor.id)
        .order_by(ChaseThread.created_at.desc())
    ).all()
    return {"items": [chase_payload(db, row) for row in rows], "count": len(rows)}


@router.post("/vendors/{vendor_id}/chases", status_code=201)
def create_chase(vendor_id: str, payload: ChaseCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "chase.manage", target_type="vendor", target_id=vendor_id)
    vendor = get_vendor_or_404(db, vendor_id)
    thread = create_chase_thread(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        vendor=vendor,
        requirement_id=payload.requirement_id,
        customer_sender_connector_id=payload.customer_sender_connector_id,
        internal_owner_user_id=payload.internal_owner_user_id,
        expected_doc_type=payload.expected_doc_type,
        project_id=payload.project_id,
        channel=payload.channel,
        max_attempts=payload.max_attempts,
        max_messages_per_week=payload.max_messages_per_week,
        touch_schedule_days=payload.touch_schedule_days,
    )
    append_audit_log(db, action="chase.created", target_type="chase_thread", target_id=thread.id, workspace_id=context.workspace_id, actor_id=context.user_id, after={"expected_doc_type": thread.expected_doc_type, "customer_owned_sender": True})
    db.commit()
    return {"chase": chase_payload(db, thread)}


@router.get("/chases/{chase_id}")
def get_chase(chase_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "chase.read", target_type="chase_thread", target_id=chase_id)
    return {"chase": chase_payload(db, get_chase_or_404(db, chase_id))}


@router.post("/chases/{chase_id}/touch")
def send_chase(chase_id: str, payload: ChaseTouchRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "chase.send", target_type="chase_thread", target_id=chase_id)
    thread = get_chase_or_404(db, chase_id)
    send_chase_touch(db, thread=thread, body=payload.body, approved=payload.approved)
    append_audit_log(db, action="chase.touch.sent", target_type="chase_thread", target_id=thread.id, workspace_id=context.workspace_id, actor_id=context.user_id, after={"attempt": thread.attempts, "customer_owned_sender": True})
    db.commit()
    return {"chase": chase_payload(db, thread)}


@router.post("/chases/{chase_id}/reply")
def receive_chase_reply(chase_id: str, payload: ChaseReplyRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "chase.manage", target_type="chase_thread", target_id=chase_id)
    thread = get_chase_or_404(db, chase_id)
    record_chase_reply(db, thread=thread, body=payload.body, attachment_document_id=payload.attachment_document_id)
    append_audit_log(db, action="chase.reply.received", target_type="chase_thread", target_id=thread.id, workspace_id=context.workspace_id, actor_id=context.user_id, after={"attachment_document_id": payload.attachment_document_id, "status": thread.status})
    db.commit()
    return {"chase": chase_payload(db, thread)}
