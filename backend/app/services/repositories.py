from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ComplianceDocument, ComplianceStatus, ReviewTask, Vendor
from app.services.audit import append_audit_log


def _workspace_id(db: Session) -> str:
    workspace_id = db.info.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise DomainError("REQUEST_CONTEXT_MISSING", "A workspace-scoped database session is required", 500)
    return workspace_id


def _record_not_found_access(db: Session, target_type: str, target_id: str) -> None:
    context = db.info.get("request_context")
    if context is None:
        return
    append_audit_log(
        db,
        action="data.access_denied",
        target_type=target_type,
        target_id=target_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"reason": "not_visible_in_active_workspace"},
    )
    db.commit()


def get_vendor_or_404(db: Session, vendor_id: str) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id,
            Vendor.workspace_id == _workspace_id(db),
        )
    )
    if vendor is None:
        _record_not_found_access(db, "vendor", vendor_id)
        raise DomainError("VENDOR_NOT_FOUND", f"Vendor {vendor_id} was not found", 404)
    return vendor


def get_document_or_404(db: Session, document_id: str) -> ComplianceDocument:
    document = db.scalar(
        select(ComplianceDocument).where(
            ComplianceDocument.id == document_id,
            ComplianceDocument.workspace_id == _workspace_id(db),
        )
    )
    if document is None:
        _record_not_found_access(db, "compliance_document", document_id)
        raise DomainError("DOCUMENT_NOT_FOUND", f"Document {document_id} was not found", 404)
    return document


def get_review_or_404(db: Session, review_id: str) -> ReviewTask:
    review = db.scalar(
        select(ReviewTask).where(
            ReviewTask.id == review_id,
            ReviewTask.workspace_id == _workspace_id(db),
        )
    )
    if review is None:
        _record_not_found_access(db, "review_task", review_id)
        raise DomainError("REVIEW_NOT_FOUND", f"Review task {review_id} was not found", 404)
    return review


def latest_status(db: Session, vendor_id: str) -> ComplianceStatus | None:
    return db.scalar(
        select(ComplianceStatus)
        .where(
            ComplianceStatus.vendor_id == vendor_id,
            ComplianceStatus.workspace_id == _workspace_id(db),
        )
        .order_by(ComplianceStatus.as_of.desc(), ComplianceStatus.id.desc())
        .limit(1)
    )
