"""Add runtime worker heartbeat evidence for inspection and degraded mode."""

from alembic import op
import sqlalchemy as sa


revision = "0015_runtime_inspection"
down_revision = "0014_evaluation_golden_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_worker_heartbeats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('healthy', 'degraded', 'stopped')", name="ck_runtime_worker_heartbeats_status"),
        sa.UniqueConstraint("workspace_id", "worker_id", name="uq_runtime_worker_heartbeats_scope_worker"),
    )
    op.create_index("ix_runtime_worker_heartbeats_workspace_id", "runtime_worker_heartbeats", ["workspace_id"])
    op.create_index("ix_runtime_worker_heartbeats_status", "runtime_worker_heartbeats", ["status"])
    op.create_index("ix_runtime_worker_heartbeats_last_seen_at", "runtime_worker_heartbeats", ["last_seen_at"])
    op.create_index("ix_runtime_worker_heartbeats_trace_id", "runtime_worker_heartbeats", ["trace_id"])
    connection = op.get_bind()
    connection.execute(sa.text('ALTER TABLE "runtime_worker_heartbeats" ENABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text('ALTER TABLE "runtime_worker_heartbeats" FORCE ROW LEVEL SECURITY'))
    connection.execute(
        sa.text(
            '''CREATE POLICY "runtime_worker_heartbeats_workspace_isolation" ON "runtime_worker_heartbeats"
               USING (workspace_id = current_setting('app.workspace_id', true))
               WITH CHECK (workspace_id = current_setting('app.workspace_id', true))'''
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text('ALTER TABLE "runtime_worker_heartbeats" DISABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text('DROP POLICY IF EXISTS "runtime_worker_heartbeats_workspace_isolation" ON "runtime_worker_heartbeats"'))
    op.drop_table("runtime_worker_heartbeats")
