from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ComplianceDocument, ComplianceStatus, ReviewTask, Vendor


def get_vendor_or_404(db: Session, vendor_id: str) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise DomainError("VENDOR_NOT_FOUND", f"Vendor {vendor_id} was not found", 404)
    return vendor


def get_document_or_404(db: Session, document_id: str) -> ComplianceDocument:
    document = db.get(ComplianceDocument, document_id)
    if document is None:
        raise DomainError("DOCUMENT_NOT_FOUND", f"Document {document_id} was not found", 404)
    return document


def get_review_or_404(db: Session, review_id: str) -> ReviewTask:
    review = db.get(ReviewTask, review_id)
    if review is None:
        raise DomainError("REVIEW_NOT_FOUND", f"Review task {review_id} was not found", 404)
    return review


def latest_status(db: Session, vendor_id: str) -> ComplianceStatus | None:
    return db.scalar(
        select(ComplianceStatus)
        .where(ComplianceStatus.vendor_id == vendor_id)
        .order_by(ComplianceStatus.as_of.desc())
        .limit(1)
    )
