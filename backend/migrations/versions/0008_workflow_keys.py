"""Add stable workspace-scoped workflow keys for API and UI contracts."""

from alembic import op
import sqlalchemy as sa


revision = "0008_workflow_keys"
down_revision = "0007_workflow_guardrails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("key", sa.String(length=120), nullable=True))
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE workflows
            SET key = left(
                regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g'),
                100
            ) || '-' || left(id, 8)
            WHERE key IS NULL
            """
        )
    )
    op.alter_column("workflows", "key", nullable=False)
    op.create_unique_constraint("uq_workflows_workspace_key", "workflows", ["workspace_id", "key"])


def downgrade() -> None:
    op.drop_constraint("uq_workflows_workspace_key", "workflows", type_="unique")
    op.drop_column("workflows", "key")
