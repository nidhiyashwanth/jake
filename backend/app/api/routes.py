from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import DomainError
from app.models import AuditEvent, ComplianceDocument, ComplianceStatus, ReviewTask, Vendor
from app.schemas import ReviewUpdate, VendorCreate
from app.services.documents import coerce_correction, extract_document_fields
from app.services.repositories import get_document_or_404, get_review_or_404, get_vendor_or_404, latest_status
from app.services.verification import history_payload, review_payload, run_verification, status_payload


router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_db)]


def _vendor_payload(vendor: Vendor, status: ComplianceStatus | None = None) -> dict[str, Any]:
    return {
        "id": vendor.id,
        "legal_name": vendor.legal_name,
        "created_at": vendor.created_at.isoformat(),
        "latest_status": status_payload(status) if status else None,
    }


def _document_payload(document: ComplianceDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "vendor_id": document.vendor_id,
        "doc_type": document.doc_type,
        "filename": document.filename,
        "media_type": document.media_type,
        "extracted_fields": document.extracted_fields,
        "created_at": document.created_at.isoformat(),
    }


def _event_payload(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "payload": event.payload,
        "occurred_at": event.occurred_at.isoformat(),
    }


@router.get("/health")
def health(db: Db) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise DomainError("DATABASE_NOT_READY", "PostgreSQL is not ready", 503) from exc
    return {"status": "ok", "service": "compliance-api", "database": "up"}


@router.post("/vendors", status_code=201)
def create_vendor(payload: VendorCreate, db: Db) -> dict[str, Any]:
    vendor = Vendor(legal_name=payload.legal_name)
    db.add(vendor)
    try:
        db.commit()
        db.refresh(vendor)
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("VENDOR_ALREADY_EXISTS", "A vendor with this legal name already exists", 409) from exc
    return _vendor_payload(vendor)


@router.get("/vendors")
def list_vendors(db: Db) -> dict[str, Any]:
    vendors = db.scalars(select(Vendor).order_by(Vendor.legal_name.asc())).all()
    return {"items": [_vendor_payload(vendor, latest_status(db, vendor.id)) for vendor in vendors]}


@router.get("/vendors/{vendor_id}")
def get_vendor(vendor_id: str, db: Db) -> dict[str, Any]:
    vendor = get_vendor_or_404(db, vendor_id)
    documents = db.scalars(
        select(ComplianceDocument).where(ComplianceDocument.vendor_id == vendor.id).order_by(desc(ComplianceDocument.created_at))
    ).all()
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.vendor_id == vendor.id).order_by(desc(AuditEvent.occurred_at)).limit(50)
    ).all()
    return {
        **_vendor_payload(vendor, latest_status(db, vendor.id)),
        "documents": [_document_payload(document) for document in documents],
        "recent_events": [_event_payload(event) for event in events],
    }


@router.post("/vendors/{vendor_id}/documents", status_code=201)
async def upload_document(
    vendor_id: str,
    db: Db,
    file: Annotated[UploadFile, File(...)],
    doc_type: Annotated[str, Form()] = "COI",
) -> dict[str, Any]:
    vendor = get_vendor_or_404(db, vendor_id)
    if doc_type.upper() != "COI":
        raise DomainError("DOCUMENT_TYPE_UNSUPPORTED", "The MVP upload path accepts doc_type=COI", 422)
    content = await file.read()
    from app.config import get_settings

    if len(content) > get_settings().max_upload_bytes:
        raise DomainError("DOCUMENT_TOO_LARGE", "The uploaded document exceeds the 10 MB MVP limit", 413)
    filename = file.filename or "uploaded-coi.txt"
    media_type = file.content_type or "application/octet-stream"
    fields = extract_document_fields(content, filename, media_type)
    document = ComplianceDocument(
        vendor_id=vendor.id,
        doc_type="COI",
        filename=filename,
        media_type=media_type,
        content=content,
        extracted_fields=fields,
    )
    db.add(document)
    db.flush()
    db.add(
        AuditEvent(
            vendor_id=vendor.id,
            event_type="document_uploaded",
            actor_type="operator",
            entity_type="compliance_document",
            entity_id=document.id,
            payload={"filename": filename, "doc_type": "COI", "extracted_fields": fields},
        )
    )
    db.commit()
    db.refresh(document)
    return _document_payload(document)


@router.post("/documents/{document_id}/verify")
def verify_document(document_id: str, db: Db) -> dict[str, Any]:
    document = get_document_or_404(db, document_id)
    vendor = get_vendor_or_404(db, document.vendor_id)
    return run_verification(db, vendor, document)


@router.get("/vendors/{vendor_id}/status")
def get_status(vendor_id: str, db: Db) -> dict[str, Any]:
    get_vendor_or_404(db, vendor_id)
    current = latest_status(db, vendor_id)
    if current is None:
        raise DomainError("STATUS_NOT_FOUND", "Verify a COI before requesting compliance status", 404)
    return {"current": status_payload(current), "history": history_payload(db, vendor_id)}


@router.get("/vendors/{vendor_id}/ledger")
def get_ledger(vendor_id: str, db: Db) -> dict[str, Any]:
    get_vendor_or_404(db, vendor_id)
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.vendor_id == vendor_id).order_by(desc(AuditEvent.occurred_at), desc(AuditEvent.id))
    ).all()
    return {"items": [_event_payload(event) for event in events]}


@router.get("/reviews")
def list_reviews(db: Db) -> dict[str, Any]:
    rows = db.execute(
        select(ReviewTask, Vendor.legal_name)
        .join(Vendor, Vendor.id == ReviewTask.vendor_id)
        .where(ReviewTask.status == "open")
        .order_by(ReviewTask.created_at.asc())
    ).all()
    items = []
    for review, legal_name in rows:
        item = review_payload(review)
        item["vendor_legal_name"] = legal_name
        items.append(item)
    return {"items": items}


@router.patch("/reviews/{review_id}")
def update_review(review_id: str, payload: ReviewUpdate, db: Db) -> dict[str, Any]:
    review = get_review_or_404(db, review_id)
    if review.status != "open":
        raise DomainError("REVIEW_NOT_OPEN", "This review task has already been resolved or superseded", 409)
    if payload.field and payload.field != review.correction_field:
        raise DomainError("CORRECTION_FIELD_MISMATCH", f"This task expects {review.correction_field}", 422)
    document = get_document_or_404(db, review.document_id)
    vendor = get_vendor_or_404(db, review.vendor_id)
    corrected = coerce_correction(review.correction_field, payload.value)
    fields = dict(document.extracted_fields)
    fields[review.correction_field] = corrected
    document.extracted_fields = fields
    review.status = "resolved"
    review.resolved_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            vendor_id=vendor.id,
            event_type="review_correction_applied",
            actor_type="human_operator",
            entity_type="review_task",
            entity_id=review.id,
            payload={"field": review.correction_field, "value": corrected, "document_id": document.id},
        )
    )
    db.flush()
    return run_verification(db, vendor, document, actor_type="human_operator")
