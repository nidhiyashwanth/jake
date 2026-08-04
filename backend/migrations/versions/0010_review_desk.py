"""Add the operator review desk queue, provenance, SLA, and event history."""

from alembic import op
import sqlalchemy as sa


revision = "0010_review_desk"
down_revision = "0009_runtime"
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
    op.add_column("review_tasks", sa.Column("priority_score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("review_tasks", sa.Column("priority_band", sa.String(length=20), nullable=False, server_default="normal"))
    op.add_column("review_tasks", sa.Column("priority_factors_json", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("review_tasks", sa.Column("assigned_to_user_id", sa.String(length=36), nullable=True))
    op.add_column("review_tasks", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("review_tasks", sa.Column("sla_minutes", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("review_tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("review_tasks", sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("review_tasks", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("review_tasks", sa.Column("escalation_reason", sa.Text(), nullable=True))
    op.add_column("review_tasks", sa.Column("correction_reason_code", sa.String(length=80), nullable=True))
    op.add_column("review_tasks", sa.Column("correction_note", sa.Text(), nullable=True))
    op.add_column("review_tasks", sa.Column("before_value_json", sa.JSON(), nullable=True))
    op.add_column("review_tasks", sa.Column("after_value_json", sa.JSON(), nullable=True))
    op.add_column("review_tasks", sa.Column("provenance_json", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("review_tasks", sa.Column("last_touched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("review_tasks", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_foreign_key(
        "fk_review_tasks_assigned_to_user",
        "review_tasks",
        "users",
        ["assigned_to_user_id"],
        ["id"],
    )
    op.create_index("ix_review_tasks_priority_score", "review_tasks", ["priority_score"])
    op.create_index("ix_review_tasks_due_at", "review_tasks", ["due_at"])
    op.create_index("ix_review_tasks_assigned_to_user_id", "review_tasks", ["assigned_to_user_id"])
    op.create_index("ix_review_tasks_escalation_level", "review_tasks", ["escalation_level"])

    op.create_table(
        "review_task_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("review_task_id", sa.String(length=36), sa.ForeignKey("review_tasks.id"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_review_task_events_workspace_id", "review_task_events", ["workspace_id"])
    op.create_index("ix_review_task_events_review_task_id", "review_task_events", ["review_task_id"])
    op.create_index("ix_review_task_events_occurred_at", "review_task_events", ["occurred_at"])
    _enable_workspace_rls(op.get_bind(), "review_task_events")


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text('ALTER TABLE "review_task_events" DISABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text('DROP POLICY IF EXISTS "review_task_events_workspace_isolation" ON "review_task_events"'))
    op.drop_table("review_task_events")
    for index in (
        "ix_review_tasks_escalation_level",
        "ix_review_tasks_assigned_to_user_id",
        "ix_review_tasks_due_at",
        "ix_review_tasks_priority_score",
    ):
        op.drop_index(index, table_name="review_tasks")
    op.drop_constraint("fk_review_tasks_assigned_to_user", "review_tasks", type_="foreignkey")
    for column in (
        "updated_at",
        "last_touched_at",
        "provenance_json",
        "after_value_json",
        "before_value_json",
        "correction_note",
        "correction_reason_code",
        "escalation_reason",
        "escalated_at",
        "escalation_level",
        "due_at",
        "sla_minutes",
        "assigned_at",
        "assigned_to_user_id",
        "priority_factors_json",
        "priority_band",
        "priority_score",
    ):
        op.drop_column("review_tasks", column)
