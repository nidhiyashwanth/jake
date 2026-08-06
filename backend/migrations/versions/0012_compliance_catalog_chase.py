"""Add the versioned compliance catalog, document taxonomy, and chase boundary."""

from alembic import op
import sqlalchemy as sa


revision = "0012_compliance_catalog_chase"
down_revision = "0011_connectors_vault"
branch_labels = None
depends_on = None


def _enable_workspace_rls(connection: sa.Connection, table: str) -> None:
    connection.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    connection.execute(
        sa.text(
            f'''CREATE POLICY "{table}_workspace_isolation" ON "{table}"
                USING (workspace_id = current_setting('app.workspace_id', true))
                WITH CHECK (workspace_id = current_setting('app.workspace_id', true))'''
        )
    )


def upgrade() -> None:
    op.add_column("vendors", sa.Column("dba_names_json", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("vendors", sa.Column("tax_id_hash", sa.String(length=64), nullable=True))
    op.add_column("vendors", sa.Column("status", sa.String(length=24), nullable=False, server_default="active"))
    op.add_column("vendors", sa.Column("risk_tier", sa.String(length=24), nullable=False, server_default="standard"))

    op.add_column("compliance_documents", sa.Column("status", sa.String(length=24), nullable=False, server_default="received"))
    op.add_column("compliance_documents", sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("compliance_documents", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("compliance_documents", sa.Column("issuer", sa.String(length=240), nullable=True))
    op.add_column("compliance_documents", sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("compliance_documents", sa.Column("superseded_by", sa.String(length=36), nullable=True))
    op.add_column("compliance_documents", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_compliance_documents_superseded_by",
        "compliance_documents",
        "compliance_documents",
        ["superseded_by"],
        ["id"],
    )
    op.create_index("ix_compliance_documents_superseded_by", "compliance_documents", ["superseded_by"])

    op.add_column("compliance_checks", sa.Column("requirement_id", sa.String(length=36), nullable=True))
    op.add_column("compliance_checks", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("compliance_checks", sa.Column("confidence", sa.Float(), nullable=True))

    op.add_column("compliance_status", sa.Column("project_id", sa.String(length=120), nullable=True))
    op.create_index("ix_compliance_status_project_id", "compliance_status", ["project_id"])

    op.create_table(
        "vendor_entities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("relationship", sa.String(length=40), nullable=False, server_default="dba"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "vendor_id", "name", name="uq_vendor_entities_workspace_vendor_name"),
    )
    op.create_index("ix_vendor_entities_workspace_id", "vendor_entities", ["workspace_id"])
    op.create_index("ix_vendor_entities_vendor_id", "vendor_entities", ["vendor_id"])

    op.create_table(
        "compliance_requirement_sets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("project_id", sa.String(length=120), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "name", "version", name="uq_requirement_sets_workspace_name_version"),
    )
    op.create_index("ix_compliance_requirement_sets_workspace_id", "compliance_requirement_sets", ["workspace_id"])
    op.create_index("ix_compliance_requirement_sets_project_id", "compliance_requirement_sets", ["project_id"])
    op.create_index("ix_compliance_requirement_sets_created_by", "compliance_requirement_sets", ["created_by"])

    op.create_table(
        "compliance_requirements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("requirement_set_id", sa.String(length=36), sa.ForeignKey("compliance_requirement_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("rule_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="review"),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("human_statement", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("requirement_set_id", "key", name="uq_compliance_requirements_set_key"),
    )
    op.create_index("ix_compliance_requirements_workspace_id", "compliance_requirements", ["workspace_id"])
    op.create_index("ix_compliance_requirements_requirement_set_id", "compliance_requirements", ["requirement_set_id"])
    op.create_foreign_key(
        "fk_compliance_checks_requirement_id",
        "compliance_checks",
        "compliance_requirements",
        ["requirement_id"],
        ["id"],
    )
    op.create_index("ix_compliance_checks_requirement_id", "compliance_checks", ["requirement_id"])

    op.create_table(
        "vendor_requirements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_set_id", sa.String(length=36), sa.ForeignKey("compliance_requirement_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(length=120), nullable=True),
        sa.Column("overrides_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "vendor_id", "requirement_set_id", "project_id", name="uq_vendor_requirements_scope"),
    )
    op.create_index("ix_vendor_requirements_workspace_id", "vendor_requirements", ["workspace_id"])
    op.create_index("ix_vendor_requirements_vendor_id", "vendor_requirements", ["vendor_id"])
    op.create_index("ix_vendor_requirements_requirement_set_id", "vendor_requirements", ["requirement_set_id"])
    op.create_index("ix_vendor_requirements_project_id", "vendor_requirements", ["project_id"])
    op.create_index("ix_vendor_requirements_created_by", "vendor_requirements", ["created_by"])

    op.create_table(
        "coverage_lines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("compliance_document_id", sa.String(length=36), sa.ForeignKey("compliance_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_type", sa.String(length=60), nullable=False),
        sa.Column("occurrence_limit", sa.Integer(), nullable=True),
        sa.Column("aggregate_limit", sa.Integer(), nullable=True),
        sa.Column("deductible", sa.Integer(), nullable=True),
        sa.Column("carrier", sa.String(length=240), nullable=True),
        sa.Column("am_best_rating", sa.String(length=20), nullable=True),
        sa.Column("admitted_state", sa.String(length=20), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("endorsements_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_coverage_lines_workspace_id", "coverage_lines", ["workspace_id"])
    op.create_index("ix_coverage_lines_compliance_document_id", "coverage_lines", ["compliance_document_id"])

    op.create_table(
        "reason_code_taxonomy",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "taxonomy_version", "code", name="uq_reason_code_taxonomy_workspace_version_code"),
    )
    op.create_index("ix_reason_code_taxonomy_workspace_id", "reason_code_taxonomy", ["workspace_id"])
    op.create_index("ix_reason_code_taxonomy_created_by", "reason_code_taxonomy", ["created_by"])

    op.create_table(
        "chase_threads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), sa.ForeignKey("compliance_requirements.id"), nullable=True),
        sa.Column("channel", sa.String(length=24), nullable=False, server_default="email"),
        sa.Column("customer_sender_connector_id", sa.String(length=36), sa.ForeignKey("connectors.id"), nullable=False),
        sa.Column("internal_owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expected_doc_type", sa.String(length=50), nullable=False),
        sa.Column("project_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("max_messages_per_week", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("touch_schedule_json", sa.JSON(), nullable=False, server_default="[0,3,7,14]"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_document_id", sa.String(length=36), sa.ForeignKey("compliance_documents.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_chase_threads_workspace_id", "chase_threads", ["workspace_id"])
    op.create_index("ix_chase_threads_vendor_id", "chase_threads", ["vendor_id"])
    op.create_index("ix_chase_threads_requirement_id", "chase_threads", ["requirement_id"])
    op.create_index("ix_chase_threads_customer_sender_connector_id", "chase_threads", ["customer_sender_connector_id"])
    op.create_index("ix_chase_threads_internal_owner_user_id", "chase_threads", ["internal_owner_user_id"])
    op.create_index("ix_chase_threads_project_id", "chase_threads", ["project_id"])
    op.create_index("ix_chase_threads_next_action_at", "chase_threads", ["next_action_at"])

    op.create_table(
        "chase_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("chase_thread_id", sa.String(length=36), sa.ForeignKey("chase_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("body_sha256", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("attachment_document_id", sa.String(length=36), sa.ForeignKey("compliance_documents.id"), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_chase_events_workspace_id", "chase_events", ["workspace_id"])
    op.create_index("ix_chase_events_chase_thread_id", "chase_events", ["chase_thread_id"])
    op.create_index("ix_chase_events_attachment_document_id", "chase_events", ["attachment_document_id"])
    op.create_index("ix_chase_events_occurred_at", "chase_events", ["occurred_at"])

    for table in (
        "vendor_entities",
        "compliance_requirement_sets",
        "compliance_requirements",
        "vendor_requirements",
        "coverage_lines",
        "reason_code_taxonomy",
        "chase_threads",
        "chase_events",
    ):
        _enable_workspace_rls(op.get_bind(), table)


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "chase_events",
        "chase_threads",
        "reason_code_taxonomy",
        "coverage_lines",
        "vendor_requirements",
        "compliance_requirements",
        "compliance_requirement_sets",
        "vendor_entities",
    ):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
    for table in ("chase_events", "chase_threads", "reason_code_taxonomy", "coverage_lines", "vendor_requirements", "compliance_requirements", "compliance_requirement_sets", "vendor_entities"):
        op.drop_table(table)

    op.drop_index("ix_compliance_status_project_id", table_name="compliance_status")
    op.drop_column("compliance_status", "project_id")
    op.drop_index("ix_compliance_checks_requirement_id", table_name="compliance_checks")
    op.drop_constraint("fk_compliance_checks_requirement_id", "compliance_checks", type_="foreignkey")
    for column in ("confidence", "explanation", "requirement_id"):
        op.drop_column("compliance_checks", column)
    op.drop_index("ix_compliance_documents_superseded_by", table_name="compliance_documents")
    op.drop_constraint("fk_compliance_documents_superseded_by", "compliance_documents", type_="foreignkey")
    for column in ("superseded_at", "superseded_by", "sha256", "issuer", "expires_at", "issued_at", "status"):
        op.drop_column("compliance_documents", column)
    for column in ("risk_tier", "status", "tax_id_hash", "dba_names_json"):
        op.drop_column("vendors", column)
