"""Allow identical workflow content to be published as separate explicit versions."""

from alembic import op
import sqlalchemy as sa


revision = "0006_workflow_hash_scope"
down_revision = "0005_prompt_hash_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            'ALTER TABLE "workflow_versions" '
            'DROP CONSTRAINT IF EXISTS "uq_workflow_versions_immutable_hash"'
        )
    )


def downgrade() -> None:
    # Immutable hashes remain evidence of content; duplicate content across
    # separately numbered versions is valid and must not be made impossible.
    pass
