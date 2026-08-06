"""Add discovery drafts, signed baselines, and opportunity scoring."""

from alembic import op
import sqlalchemy as sa


revision = "0003_discovery_baselines_scoring"
down_revision = "0002_tenancy_rbac_audit"
branch_labels = None
depends_on = None

WORKSPACE_SCOPED_TABLES = (
    "processes",
    "process_steps",
    "process_interviews",
    "baselines",
    "baseline_metrics",
    "opportunity_scores",
)


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
        "processes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("department", sa.String(length=160), nullable=True),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("system_of_record", sa.String(length=160), nullable=True),
        sa.Column("trigger_json", sa.JSON(), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("decisions_json", sa.JSON(), nullable=False),
        sa.Column("exceptions_json", sa.JSON(), nullable=False),
        sa.Column("approvals_json", sa.JSON(), nullable=False),
        sa.Column("outputs_json", sa.JSON(), nullable=False),
        sa.Column("failure_modes_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_processes_workspace_name"),
    )
    op.create_index("ix_processes_workspace_id", "processes", ["workspace_id"])
    op.create_index("ix_processes_owner_user_id", "processes", ["owner_user_id"])

    op.create_table(
        "process_steps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("process_id", sa.String(length=36), sa.ForeignKey("processes.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system", sa.String(length=160), nullable=True),
        sa.Column("minutes_p50", sa.Float(), nullable=True),
        sa.Column("minutes_p90", sa.Float(), nullable=True),
        sa.Column("is_decision", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("process_id", "seq", name="uq_process_steps_process_seq"),
    )
    op.create_index("ix_process_steps_workspace_id", "process_steps", ["workspace_id"])
    op.create_index("ix_process_steps_process_id", "process_steps", ["process_id"])

    op.create_table(
        "process_interviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("process_id", sa.String(length=36), sa.ForeignKey("processes.id"), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("transcript_ref", sa.String(length=500), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("draft_graph", sa.JSON(), nullable=False),
        sa.Column("exception_list", sa.JSON(), nullable=False),
        sa.Column("baseline_questions", sa.JSON(), nullable=False),
        sa.Column("captured_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('sop', 'transcript', 'screen_recording_narration')",
            name="ck_process_interviews_source_type",
        ),
    )
    op.create_index("ix_process_interviews_workspace_id", "process_interviews", ["workspace_id"])
    op.create_index("ix_process_interviews_process_id", "process_interviews", ["process_id"])
    op.create_index("ix_process_interviews_captured_by", "process_interviews", ["captured_by"])

    op.create_table(
        "baselines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("process_id", sa.String(length=36), sa.ForeignKey("processes.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("signed_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canonical_hash", sa.String(length=64), nullable=True),
        sa.Column("supersedes_baseline_id", sa.String(length=36), sa.ForeignKey("baselines.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'signed')", name="ck_baselines_status"),
        sa.UniqueConstraint("process_id", "version", name="uq_baselines_process_version"),
        sa.UniqueConstraint("canonical_hash", name="uq_baselines_canonical_hash"),
    )
    op.create_index("ix_baselines_workspace_id", "baselines", ["workspace_id"])
    op.create_index("ix_baselines_process_id", "baselines", ["process_id"])
    op.create_index("ix_baselines_created_by", "baselines", ["created_by"])
    op.create_index("ix_baselines_signed_by", "baselines", ["signed_by"])
    op.create_index("ix_baselines_supersedes_baseline_id", "baselines", ["supersedes_baseline_id"])

    op.create_table(
        "baseline_metrics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("baseline_id", sa.String(length=36), sa.ForeignKey("baselines.id"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("baseline_id", "key", name="uq_baseline_metrics_baseline_key"),
    )
    op.create_index("ix_baseline_metrics_workspace_id", "baseline_metrics", ["workspace_id"])
    op.create_index("ix_baseline_metrics_baseline_id", "baseline_metrics", ["baseline_id"])

    op.create_table(
        "opportunity_scores",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("process_id", sa.String(length=36), sa.ForeignKey("processes.id"), nullable=False),
        sa.Column("baseline_id", sa.String(length=36), sa.ForeignKey("baselines.id"), nullable=False),
        sa.Column("formula_version", sa.String(length=40), nullable=False),
        sa.Column("annual_cost", sa.Float(), nullable=False),
        sa.Column("projected_savings", sa.Float(), nullable=False),
        sa.Column("automatable_pct", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("effort_weeks", sa.Float(), nullable=False),
        sa.Column("risk_multiplier", sa.Float(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("component_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("input_provenance_json", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_opportunity_scores_workspace_id", "opportunity_scores", ["workspace_id"])
    op.create_index("ix_opportunity_scores_process_id", "opportunity_scores", ["process_id"])
    op.create_index("ix_opportunity_scores_baseline_id", "opportunity_scores", ["baseline_id"])
    op.create_index("ix_opportunity_scores_computed_at", "opportunity_scores", ["computed_at"])

    connection = op.get_bind()
    for table in WORKSPACE_SCOPED_TABLES:
        _enable_workspace_rls(connection, table)

    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_signed_baseline_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF OLD.status = 'signed' THEN
                    RAISE EXCEPTION 'signed baselines are immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TRIGGER baselines_signed_immutable
            BEFORE UPDATE OR DELETE ON baselines
            FOR EACH ROW EXECUTE FUNCTION prevent_signed_baseline_mutation()
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_signed_baseline_metric_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM baselines
                    WHERE id = OLD.baseline_id AND status = 'signed'
                ) THEN
                    RAISE EXCEPTION 'metrics for a signed baseline are immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TRIGGER baseline_metrics_signed_immutable
            BEFORE UPDATE OR DELETE ON baseline_metrics
            FOR EACH ROW EXECUTE FUNCTION prevent_signed_baseline_metric_mutation()
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DROP TRIGGER IF EXISTS baseline_metrics_signed_immutable ON baseline_metrics"))
    connection.execute(sa.text("DROP TRIGGER IF EXISTS baselines_signed_immutable ON baselines"))
    connection.execute(sa.text("DROP FUNCTION IF EXISTS prevent_signed_baseline_metric_mutation()"))
    connection.execute(sa.text("DROP FUNCTION IF EXISTS prevent_signed_baseline_mutation()"))
    for table in reversed(WORKSPACE_SCOPED_TABLES):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
    op.drop_table("opportunity_scores")
    op.drop_table("baseline_metrics")
    op.drop_table("baselines")
    op.drop_table("process_interviews")
    op.drop_table("process_steps")
    op.drop_table("processes")
