"""Add rights-labelled golden sets, evaluation provenance, and drift snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0014_evaluation_golden_drift"
down_revision = "0013_confidence_routing"
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
        "golden_sets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("source_policy_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("gate_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_golden_sets_status"),
        sa.UniqueConstraint("workspace_id", "workflow_version_id", "name", "version", name="uq_golden_sets_scope_version"),
    )
    for column in ("workspace_id", "workflow_id", "workflow_version_id", "status", "created_by"):
        op.create_index(f"ix_golden_sets_{column}", "golden_sets", [column])

    op.create_table(
        "golden_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("golden_set_id", sa.String(length=36), sa.ForeignKey("golden_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_key", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("rights_status", sa.String(length=40), nullable=False),
        sa.Column("rights_basis", sa.Text(), nullable=False),
        sa.Column("sender", sa.String(length=240), nullable=False, server_default="unknown"),
        sa.Column("document_type", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("input_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("expected_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("prediction_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("canary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("source_type IN ('corrected', 'manual', 'canary', 'synthetic')", name="ck_golden_cases_source_type"),
        sa.CheckConstraint("rights_status IN ('contractual_rights', 'manual_review', 'synthetic')", name="ck_golden_cases_rights_status"),
        sa.UniqueConstraint("golden_set_id", "case_key", name="uq_golden_cases_set_key"),
    )
    for column in ("workspace_id", "golden_set_id"):
        op.create_index(f"ix_golden_cases_{column}", "golden_cases", [column])

    op.create_table(
        "drift_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("window_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ok"),
        sa.Column("baseline_correction_rate", sa.Float(), nullable=False),
        sa.Column("max_delta", sa.Float(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("alerts_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('ok', 'alert')", name="ck_drift_snapshots_status"),
        sa.CheckConstraint("baseline_correction_rate >= 0 AND baseline_correction_rate <= 1", name="ck_drift_snapshots_baseline_rate"),
        sa.CheckConstraint("max_delta >= 0 AND max_delta <= 1", name="ck_drift_snapshots_max_delta"),
    )
    for column in ("workspace_id", "workflow_version_id", "status", "created_by", "created_at"):
        op.create_index(f"ix_drift_snapshots_{column}", "drift_snapshots", [column])

    op.add_column("workflow_evaluation_results", sa.Column("evaluation_type", sa.String(length=40), nullable=False, server_default="workflow"))
    op.add_column("workflow_evaluation_results", sa.Column("golden_set_id", sa.String(length=36), nullable=True))
    op.add_column("workflow_evaluation_results", sa.Column("baseline_evaluation_id", sa.String(length=36), nullable=True))
    op.add_column("workflow_evaluation_results", sa.Column("metric_deltas_json", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("workflow_evaluation_results", sa.Column("failing_cases_json", sa.JSON(), nullable=False, server_default="[]"))
    op.create_foreign_key(
        "fk_workflow_evaluation_results_golden_set_id",
        "workflow_evaluation_results",
        "golden_sets",
        ["golden_set_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_workflow_evaluation_results_baseline_evaluation_id",
        "workflow_evaluation_results",
        "workflow_evaluation_results",
        ["baseline_evaluation_id"],
        ["id"],
    )
    op.create_index("ix_workflow_evaluation_results_golden_set_id", "workflow_evaluation_results", ["golden_set_id"])
    op.create_index("ix_workflow_evaluation_results_baseline_evaluation_id", "workflow_evaluation_results", ["baseline_evaluation_id"])

    for table in ("golden_sets", "golden_cases", "drift_snapshots"):
        _enable_workspace_rls(op.get_bind(), table)


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("drift_snapshots", "golden_cases", "golden_sets"):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
        op.drop_table(table)

    op.drop_index("ix_workflow_evaluation_results_baseline_evaluation_id", table_name="workflow_evaluation_results")
    op.drop_index("ix_workflow_evaluation_results_golden_set_id", table_name="workflow_evaluation_results")
    op.drop_constraint("fk_workflow_evaluation_results_baseline_evaluation_id", "workflow_evaluation_results", type_="foreignkey")
    op.drop_constraint("fk_workflow_evaluation_results_golden_set_id", "workflow_evaluation_results", type_="foreignkey")
    for column in ("failing_cases_json", "metric_deltas_json", "baseline_evaluation_id", "golden_set_id", "evaluation_type"):
        op.drop_column("workflow_evaluation_results", column)
