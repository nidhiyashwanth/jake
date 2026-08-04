"""Persist a redacted MCP request fingerprint for safe idempotency reuse."""

from alembic import op
import sqlalchemy as sa


revision = "0019_mcp_request_hash"
down_revision = "0018_vendor_scope_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connector_calls", sa.Column("request_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_connector_calls_request_hash", "connector_calls", ["request_hash"])


def downgrade() -> None:
    op.drop_index("ix_connector_calls_request_hash", table_name="connector_calls")
    op.drop_column("connector_calls", "request_hash")
