"""Add the durable Postgres execution runtime and transactional outbox."""

from alembic import op
import sqlalchemy as sa


revision = "0009_runtime"
down_revision = "0008_workflow_keys"
branch_labels = None
depends_on = None


RUNTIME_TABLES = (
    "executions",
    "execution_steps",
    "outbox_events",
    "external_write_receipts",
    "execution_events",
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
        "executions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("workflow_version_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("replay_of_id", sa.String(length=36), sa.ForeignKey("executions.id"), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_human', 'completed', 'failed', 'dead_letter', 'halted', 'replayed')",
            name="ck_executions_status",
        ),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_executions_workspace_idempotency"),
    )
    op.create_index("ix_executions_workspace_id", "executions", ["workspace_id"])
    op.create_index("ix_executions_workflow_id", "executions", ["workflow_id"])
    op.create_index("ix_executions_workflow_version_id", "executions", ["workflow_version_id"])
    op.create_index("ix_executions_correlation_id", "executions", ["correlation_id"])
    op.create_index("ix_executions_status", "executions", ["status"])
    op.create_index("ix_executions_created_by", "executions", ["created_by"])
    op.create_index("ix_executions_next_attempt_at", "executions", ["next_attempt_at"])

    op.create_table(
        "execution_steps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model_ref", sa.String(length=160), nullable=True),
        sa.Column("prompt_ref", sa.String(length=160), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=240), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("claimed_by", sa.String(length=120), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wait_reason", sa.Text(), nullable=True),
        sa.Column("compensation_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'running', 'waiting_human', 'completed', 'failed', 'dead_letter', 'skipped')",
            name="ck_execution_steps_status",
        ),
        sa.UniqueConstraint("execution_id", "node_key", name="uq_execution_steps_execution_node"),
    )
    op.create_index("ix_execution_steps_workspace_id", "execution_steps", ["workspace_id"])
    op.create_index("ix_execution_steps_execution_id", "execution_steps", ["execution_id"])
    op.create_index("ix_execution_steps_workflow_version_id", "execution_steps", ["workflow_version_id"])
    op.create_index("ix_execution_steps_status", "execution_steps", ["status"])
    op.create_index("ix_execution_steps_available_at", "execution_steps", ["available_at"])
    op.create_index("ix_execution_steps_claimed_by", "execution_steps", ["claimed_by"])
    op.create_index("ix_execution_steps_correlation_id", "execution_steps", ["correlation_id"])
    op.create_index("ix_execution_steps_idempotency_key", "execution_steps", ["idempotency_key"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("executions.id"), nullable=True),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("execution_steps.id"), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("dedupe_key", sa.String(length=240), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=120), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'claimed', 'delivered', 'dead_letter')", name="ck_outbox_status"),
        sa.UniqueConstraint("workspace_id", "dedupe_key", name="uq_outbox_workspace_dedupe"),
    )
    op.create_index("ix_outbox_events_workspace_id", "outbox_events", ["workspace_id"])
    op.create_index("ix_outbox_events_execution_id", "outbox_events", ["execution_id"])
    op.create_index("ix_outbox_events_step_id", "outbox_events", ["step_id"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_events_available_at", "outbox_events", ["available_at"])
    op.create_index("ix_outbox_events_correlation_id", "outbox_events", ["correlation_id"])

    op.create_table(
        "external_write_receipts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("execution_steps.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("connector_key", sa.String(length=120), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_external_writes_workspace_idempotency"),
    )
    op.create_index("ix_external_write_receipts_workspace_id", "external_write_receipts", ["workspace_id"])
    op.create_index("ix_external_write_receipts_execution_id", "external_write_receipts", ["execution_id"])
    op.create_index("ix_external_write_receipts_step_id", "external_write_receipts", ["step_id"])
    op.create_index("ix_external_write_receipts_idempotency_key", "external_write_receipts", ["idempotency_key"])

    op.create_table(
        "execution_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("execution_steps.id"), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_events_workspace_id", "execution_events", ["workspace_id"])
    op.create_index("ix_execution_events_execution_id", "execution_events", ["execution_id"])
    op.create_index("ix_execution_events_step_id", "execution_events", ["step_id"])
    op.create_index("ix_execution_events_correlation_id", "execution_events", ["correlation_id"])
    op.create_index("ix_execution_events_occurred_at", "execution_events", ["occurred_at"])

    connection = op.get_bind()
    for table in RUNTIME_TABLES:
        _enable_workspace_rls(connection, table)


def downgrade() -> None:
    connection = op.get_bind()
    for table in reversed(RUNTIME_TABLES):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
        op.drop_table(table)
