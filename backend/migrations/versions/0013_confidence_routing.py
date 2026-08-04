"""Add deterministic confidence routing, versioned thresholds, and sampled audits."""

from alembic import op
import sqlalchemy as sa


revision = "0013_confidence_routing"
down_revision = "0012_compliance_catalog_chase"
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
    op.create_table(
        "confidence_threshold_sets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=True),
        sa.Column("scope_key", sa.String(length=180), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("auto_threshold", sa.Float(), nullable=False),
        sa.Column("review_threshold", sa.Float(), nullable=False),
        sa.Column("halt_threshold", sa.Float(), nullable=False),
        sa.Column("value_at_risk_limit", sa.Float(), nullable=False),
        sa.Column("sample_rate", sa.Float(), nullable=False, server_default="0.02"),
        sa.Column("cost_auto_usd", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("cost_review_usd", sa.Float(), nullable=False, server_default="4.0"),
        sa.Column("cost_halt_usd", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("previous_threshold_set_id", sa.String(length=36), sa.ForeignKey("confidence_threshold_sets.id"), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'superseded', 'rolled_back')",
            name="ck_confidence_threshold_sets_status",
        ),
        sa.CheckConstraint(
            "halt_threshold >= 0 AND review_threshold >= halt_threshold AND auto_threshold >= review_threshold AND auto_threshold <= 1",
            name="ck_confidence_threshold_sets_order",
        ),
        sa.CheckConstraint("value_at_risk_limit >= 0", name="ck_confidence_threshold_sets_risk_limit"),
        sa.CheckConstraint("sample_rate >= 0.02 AND sample_rate <= 1", name="ck_confidence_threshold_sets_sample_rate"),
        sa.UniqueConstraint("workspace_id", "scope_key", "version", name="uq_confidence_threshold_scope_version"),
    )
    for column in ("workspace_id", "workflow_id", "workflow_version_id", "status", "previous_threshold_set_id", "created_by"):
        op.create_index(f"ix_confidence_threshold_sets_{column}", "confidence_threshold_sets", [column])

    op.create_table(
        "confidence_assessments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("assessment_key", sa.String(length=200), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=True),
        sa.Column("threshold_set_id", sa.String(length=36), sa.ForeignKey("confidence_threshold_sets.id"), nullable=False),
        sa.Column("extraction_consistency", sa.Float(), nullable=False),
        sa.Column("validation_severity", sa.Float(), nullable=False),
        sa.Column("matching_score", sa.Float(), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("sender_history_score", sa.Float(), nullable=False),
        sa.Column("value_at_risk", sa.Float(), nullable=False),
        sa.Column("value_at_risk_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("route", sa.String(length=20), nullable=False),
        sa.Column("route_band", sa.String(length=32), nullable=False),
        sa.Column("required_halt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signals_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "extraction_consistency >= 0 AND extraction_consistency <= 1 AND validation_severity >= 0 AND validation_severity <= 1 AND matching_score >= 0 AND matching_score <= 1 AND novelty_score >= 0 AND novelty_score <= 1 AND sender_history_score >= 0 AND sender_history_score <= 1",
            name="ck_confidence_assessment_signal_ranges",
        ),
        sa.CheckConstraint("value_at_risk >= 0 AND value_at_risk_score >= 0 AND value_at_risk_score <= 1", name="ck_confidence_assessment_risk_range"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_confidence_assessment_confidence_range"),
        sa.CheckConstraint("route IN ('auto', 'review', 'halt')", name="ck_confidence_assessment_route"),
        sa.UniqueConstraint("workspace_id", "assessment_key", name="uq_confidence_assessments_workspace_key"),
    )
    for column in ("workspace_id", "workflow_id", "workflow_version_id", "threshold_set_id", "route", "created_at"):
        op.create_index(f"ix_confidence_assessments_{column}", "confidence_assessments", [column])

    op.create_table(
        "confidence_audits",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("assessment_id", sa.String(length=36), sa.ForeignKey("confidence_assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("threshold_set_id", sa.String(length=36), sa.ForeignKey("confidence_threshold_sets.id"), nullable=False),
        sa.Column("sample_rate", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("actual_correct", sa.Boolean(), nullable=True),
        sa.Column("false_auto", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("alert_code", sa.String(length=80), nullable=True),
        sa.Column("alert_message", sa.Text(), nullable=True),
        sa.Column("rollback_threshold_set_id", sa.String(length=36), sa.ForeignKey("confidence_threshold_sets.id"), nullable=True),
        sa.Column("audited_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("outcome_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'completed', 'alerted')", name="ck_confidence_audits_status"),
        sa.CheckConstraint("sample_rate >= 0.02 AND sample_rate <= 1", name="ck_confidence_audits_sample_rate"),
        sa.UniqueConstraint("workspace_id", "assessment_id", name="uq_confidence_audits_assessment"),
    )
    for column in ("workspace_id", "assessment_id", "threshold_set_id", "status", "audited_by", "created_at"):
        op.create_index(f"ix_confidence_audits_{column}", "confidence_audits", [column])

    for table in ("confidence_threshold_sets", "confidence_assessments", "confidence_audits"):
        _enable_workspace_rls(op.get_bind(), table)


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("confidence_audits", "confidence_assessments", "confidence_threshold_sets"):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
        op.drop_table(table)
