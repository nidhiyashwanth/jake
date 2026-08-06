"""Add immutable, workspace-scoped value realization events."""

from alembic import op
import sqlalchemy as sa


revision = "0016_value_ledger"
down_revision = "0015_runtime_inspection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "value_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("event_key", sa.String(length=240), nullable=False),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("executions.id"), nullable=True),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=True),
        sa.Column("workflow_version_hash", sa.String(length=64), nullable=True),
        sa.Column("baseline_id", sa.String(length=36), sa.ForeignKey("baselines.id"), nullable=True),
        sa.Column("baseline_hash", sa.String(length=64), nullable=True),
        sa.Column("review_task_id", sa.String(length=36), sa.ForeignKey("review_tasks.id"), nullable=True),
        sa.Column("source_artifact_type", sa.String(length=80), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=120), nullable=False),
        sa.Column("audit_event_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=80), nullable=False),
        sa.Column("dollar_value", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("formula_version", sa.String(length=40), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "kind IN ('unit_processed', 'touch_avoided', 'time_saved', 'error_prevented', 'cycle_time_reduced', 'human_touch_cost', 'model_cost', 'infra_cost', 'rework')",
            name="ck_value_events_kind",
        ),
        sa.CheckConstraint(
            "method IN ('baseline_rate', 'measured_ab', 'customer_asserted', 'sampled_audit')",
            name="ck_value_events_method",
        ),
        sa.CheckConstraint("confidence IN ('high', 'medium', 'low')", name="ck_value_events_confidence"),
        sa.CheckConstraint("quantity = quantity AND abs(quantity) < 1000000000000", name="ck_value_events_quantity_finite"),
        sa.CheckConstraint("dollar_value = dollar_value AND abs(dollar_value) < 1000000000000", name="ck_value_events_dollar_finite"),
        sa.UniqueConstraint("workspace_id", "event_key", name="uq_value_events_workspace_event_key"),
    )
    for column in ("workspace_id", "execution_id", "workflow_version_id", "baseline_id", "review_task_id", "source_artifact_id", "audit_event_id", "kind", "computed_at"):
        op.create_index(f"ix_value_events_{column}", "value_events", [column])
    connection = op.get_bind()
    connection.execute(sa.text('ALTER TABLE "value_events" ENABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text('ALTER TABLE "value_events" FORCE ROW LEVEL SECURITY'))
    connection.execute(
        sa.text(
            '''CREATE POLICY "value_events_workspace_isolation" ON "value_events"
               USING (workspace_id = current_setting('app.workspace_id', true))
               WITH CHECK (workspace_id = current_setting('app.workspace_id', true))'''
        )
    )
    connection.execute(
        sa.text(
            '''CREATE OR REPLACE FUNCTION prevent_value_event_mutation() RETURNS trigger AS $$
               BEGIN
                 RAISE EXCEPTION 'value_events are append-only';
               END;
               $$ LANGUAGE plpgsql'''
        )
    )
    connection.execute(
        sa.text(
            '''CREATE TRIGGER value_events_immutable
               BEFORE UPDATE OR DELETE ON "value_events"
               FOR EACH ROW EXECUTE FUNCTION prevent_value_event_mutation()'''
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text('DROP TRIGGER IF EXISTS value_events_immutable ON "value_events"'))
    connection.execute(sa.text('DROP FUNCTION IF EXISTS prevent_value_event_mutation()'))
    connection.execute(sa.text('ALTER TABLE "value_events" DISABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text('DROP POLICY IF EXISTS "value_events_workspace_isolation" ON "value_events"'))
    op.drop_table("value_events")
