"""Make global and project-scoped vendor bindings unique under PostgreSQL NULL semantics."""

from alembic import op
import sqlalchemy as sa


revision = "0018_vendor_scope_unique"
down_revision = "0017_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            """
            SELECT workspace_id, vendor_id, requirement_set_id
            FROM vendor_requirements
            WHERE project_id IS NULL
            GROUP BY workspace_id, vendor_id, requirement_set_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce global vendor requirement uniqueness until duplicate bindings are resolved"
        )

    op.drop_constraint("uq_vendor_requirements_scope", "vendor_requirements", type_="unique")
    op.create_index(
        "uq_vendor_requirements_global_scope",
        "vendor_requirements",
        ["workspace_id", "vendor_id", "requirement_set_id"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "uq_vendor_requirements_project_scope",
        "vendor_requirements",
        ["workspace_id", "vendor_id", "requirement_set_id", "project_id"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_vendor_requirements_project_scope", table_name="vendor_requirements")
    op.drop_index("uq_vendor_requirements_global_scope", table_name="vendor_requirements")
    op.create_unique_constraint(
        "uq_vendor_requirements_scope",
        "vendor_requirements",
        ["workspace_id", "vendor_id", "requirement_set_id", "project_id"],
    )
