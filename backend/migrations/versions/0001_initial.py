"""Create the F01 compliance verification schema."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("legal_name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "compliance_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("doc_type", sa.String(length=30), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_compliance_documents_vendor_id", "compliance_documents", ["vendor_id"])
    op.create_table(
        "compliance_checks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("compliance_documents.id"), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_key", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_value", sa.JSON(), nullable=True),
        sa.Column("required_value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_compliance_checks_vendor_id", "compliance_checks", ["vendor_id"])
    op.create_index("ix_compliance_checks_document_id", "compliance_checks", ["document_id"])
    op.create_index("ix_compliance_checks_run_id", "compliance_checks", ["run_id"])
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("compliance_documents.id"), nullable=False),
        sa.Column("check_id", sa.String(length=36), sa.ForeignKey("compliance_checks.id"), nullable=False),
        sa.Column("requirement_key", sa.String(length=80), nullable=False),
        sa.Column("correction_field", sa.String(length=80), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_review_tasks_vendor_id", "review_tasks", ["vendor_id"])
    op.create_index("ix_review_tasks_document_id", "review_tasks", ["document_id"])
    op.create_table(
        "compliance_status",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("compliance_documents.id"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("failing_requirements", sa.JSON(), nullable=False),
        sa.Column("computed_by_version", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
    )
    op.create_index("ix_compliance_status_vendor_id", "compliance_status", ["vendor_id"])
    op.create_index("ix_compliance_status_document_id", "compliance_status", ["document_id"])
    op.create_index("ix_compliance_status_as_of", "compliance_status", ["as_of"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vendor_id", sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_vendor_id", "audit_events", ["vendor_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("compliance_status")
    op.drop_table("review_tasks")
    op.drop_table("compliance_checks")
    op.drop_table("compliance_documents")
    op.drop_table("vendors")
