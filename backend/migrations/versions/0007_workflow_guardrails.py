"""Harden published-child and evaluation-result immutability."""

from alembic import op
import sqlalchemy as sa


revision = "0007_workflow_guardrails"
down_revision = "0006_workflow_hash_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_published_workflow_child_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM workflow_versions
                    WHERE id = OLD.workflow_version_id AND status = 'published'
                ) OR (
                    TG_OP = 'UPDATE' AND EXISTS (
                        SELECT 1 FROM workflow_versions
                        WHERE id = NEW.workflow_version_id AND status = 'published'
                    )
                ) THEN
                    RAISE EXCEPTION 'children of published workflow versions are immutable';
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
            CREATE OR REPLACE FUNCTION prevent_workflow_evaluation_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'workflow evaluation results are immutable';
            END;
            $$
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TRIGGER workflow_evaluation_results_immutable
            BEFORE UPDATE OR DELETE ON workflow_evaluation_results
            FOR EACH ROW EXECUTE FUNCTION prevent_workflow_evaluation_mutation()
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DROP TRIGGER IF EXISTS workflow_evaluation_results_immutable ON workflow_evaluation_results"))
    connection.execute(sa.text("DROP FUNCTION IF EXISTS prevent_workflow_evaluation_mutation()"))
