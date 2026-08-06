"""Keep prompt content hashes deterministic without making them tenant-global keys."""

from alembic import op
import sqlalchemy as sa


revision = "0005_prompt_hash_scope"
down_revision = "0004_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            'ALTER TABLE "prompt_versions" '
            'DROP CONSTRAINT IF EXISTS "prompt_versions_canonical_hash_key"'
        )
    )


def downgrade() -> None:
    # A content hash is evidence, not a cross-workspace identity.  Keep the
    # downgrade deliberately non-destructive rather than reintroducing a
    # tenant-crossing uniqueness constraint.
    pass
