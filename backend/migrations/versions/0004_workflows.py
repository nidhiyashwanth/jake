"""Add workspace-scoped workflow definitions, versioned graph rows, and eval gate seam."""

from alembic import op
import sqlalchemy as sa


revision = "0004_workflows"
down_revision = "0003_discovery_baselines_scoring"
branch_labels = None
depends_on = None

WORKSPACE_SCOPED_TABLES = (
    "workflows",
    "workflow_versions",
    "workflow_nodes",
    "workflow_edges",
    "workflow_thresholds",
    "prompts",
    "prompt_versions",
    "model_configs",
    "workflow_evaluation_results",
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


def _enable_append_only_rls(connection: sa.Connection, table: str) -> None:
    connection.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    connection.execute(
        sa.text(
            f'''CREATE POLICY "{table}_workspace_read" ON "{table}" FOR SELECT
                USING (workspace_id = current_setting('app.workspace_id', true))'''
        )
    )
    connection.execute(
        sa.text(
            f'''CREATE POLICY "{table}_workspace_insert" ON "{table}" FOR INSERT
                WITH CHECK (workspace_id = current_setting('app.workspace_id', true))'''
        )
    )


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("process_id", sa.String(length=36), sa.ForeignKey("processes.id"), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_workflows_status"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_workflows_workspace_name"),
    )
    op.create_index("ix_workflows_workspace_id", "workflows", ["workspace_id"])
    op.create_index("ix_workflows_process_id", "workflows", ["process_id"])
    op.create_index("ix_workflows_created_by", "workflows", ["created_by"])

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("immutable_hash", sa.String(length=64), nullable=True),
        sa.Column("baseline_id", sa.String(length=36), sa.ForeignKey("baselines.id"), nullable=True),
        sa.Column("eval_run_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_workflow_versions_status"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )
    op.create_index("ix_workflow_versions_workspace_id", "workflow_versions", ["workspace_id"])
    op.create_index("ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"])
    op.create_index("ix_workflow_versions_baseline_id", "workflow_versions", ["baseline_id"])
    op.create_index("ix_workflow_versions_eval_run_id", "workflow_versions", ["eval_run_id"])
    op.create_index("ix_workflow_versions_published_by", "workflow_versions", ["published_by"])
    op.create_index("ix_workflow_versions_created_by", "workflow_versions", ["created_by"])

    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("position_json", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('trigger', 'fetch', 'parse', 'classify', 'extract', 'rule', 'score', 'llm', 'tool', 'approve', 'notify', 'halt')",
            name="ck_workflow_nodes_type",
        ),
        sa.UniqueConstraint("workflow_version_id", "node_key", name="uq_workflow_nodes_version_key"),
    )
    op.create_index("ix_workflow_nodes_workspace_id", "workflow_nodes", ["workspace_id"])
    op.create_index("ix_workflow_nodes_workflow_version_id", "workflow_nodes", ["workflow_version_id"])

    op.create_table(
        "workflow_edges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("from_node", sa.String(length=64), nullable=False),
        sa.Column("to_node", sa.String(length=64), nullable=False),
        sa.Column("condition_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workflow_version_id", "from_node", "to_node", name="uq_workflow_edges_version_from_to"
        ),
    )
    op.create_index("ix_workflow_edges_workspace_id", "workflow_edges", ["workspace_id"])
    op.create_index("ix_workflow_edges_workflow_version_id", "workflow_edges", ["workflow_version_id"])

    op.create_table(
        "workflow_thresholds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workflow_version_id", "key", name="uq_workflow_thresholds_version_key"),
    )
    op.create_index("ix_workflow_thresholds_workspace_id", "workflow_thresholds", ["workspace_id"])
    op.create_index("ix_workflow_thresholds_workflow_version_id", "workflow_thresholds", ["workflow_version_id"])

    op.create_table(
        "prompts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "key", name="uq_prompts_workspace_key"),
    )
    op.create_index("ix_prompts_workspace_id", "prompts", ["workspace_id"])
    op.create_index("ix_prompts_created_by", "prompts", ["created_by"])

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), sa.ForeignKey("prompts.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("variables_json", sa.JSON(), nullable=False),
        sa.Column("output_schema_json", sa.JSON(), nullable=True),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_version"),
    )
    op.create_index("ix_prompt_versions_workspace_id", "prompt_versions", ["workspace_id"])
    op.create_index("ix_prompt_versions_prompt_id", "prompt_versions", ["prompt_id"])
    op.create_index("ix_prompt_versions_created_by", "prompt_versions", ["created_by"])

    op.create_table(
        "model_configs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "key", "version", name="uq_model_configs_workspace_key_version"),
    )
    op.create_index("ix_model_configs_workspace_id", "model_configs", ["workspace_id"])
    op.create_index("ix_model_configs_created_by", "model_configs", ["created_by"])

    op.create_table(
        "workflow_evaluation_results",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("failure_reasons_json", sa.JSON(), nullable=False),
        sa.Column("evaluator", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_evaluation_results_workspace_id", "workflow_evaluation_results", ["workspace_id"])
    op.create_index("ix_workflow_evaluation_results_workflow_version_id", "workflow_evaluation_results", ["workflow_version_id"])
    op.create_index("ix_workflow_evaluation_results_definition_hash", "workflow_evaluation_results", ["definition_hash"])
    op.create_index("ix_workflow_evaluation_results_created_by", "workflow_evaluation_results", ["created_by"])
    op.create_index("ix_workflow_evaluation_results_evaluated_at", "workflow_evaluation_results", ["evaluated_at"])

    connection = op.get_bind()
    for table in WORKSPACE_SCOPED_TABLES[:-1]:
        _enable_workspace_rls(connection, table)
    _enable_append_only_rls(connection, "workflow_evaluation_results")

    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_published_workflow_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF OLD.status = 'published' THEN
                    RAISE EXCEPTION 'published workflow versions are immutable';
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
            CREATE TRIGGER workflow_versions_published_immutable
            BEFORE UPDATE OR DELETE ON workflow_versions
            FOR EACH ROW EXECUTE FUNCTION prevent_published_workflow_mutation()
            """
        )
    )
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
    for table, trigger in (
        ("workflow_nodes", "workflow_nodes_published_immutable"),
        ("workflow_edges", "workflow_edges_published_immutable"),
        ("workflow_thresholds", "workflow_thresholds_published_immutable"),
    ):
        connection.execute(
            sa.text(
                f'''CREATE TRIGGER "{trigger}"
                    BEFORE UPDATE OR DELETE ON "{table}"
                    FOR EACH ROW EXECUTE FUNCTION prevent_published_workflow_child_mutation()'''
            )
        )
    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_prompt_version_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'prompt versions are immutable';
            END;
            $$
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TRIGGER prompt_versions_immutable
            BEFORE UPDATE OR DELETE ON prompt_versions
            FOR EACH ROW EXECUTE FUNCTION prevent_prompt_version_mutation()
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DROP TRIGGER IF EXISTS prompt_versions_immutable ON prompt_versions"))
    connection.execute(sa.text("DROP TRIGGER IF EXISTS workflow_thresholds_published_immutable ON workflow_thresholds"))
    connection.execute(sa.text("DROP TRIGGER IF EXISTS workflow_edges_published_immutable ON workflow_edges"))
    connection.execute(sa.text("DROP TRIGGER IF EXISTS workflow_nodes_published_immutable ON workflow_nodes"))
    connection.execute(sa.text("DROP TRIGGER IF EXISTS workflow_versions_published_immutable ON workflow_versions"))
    connection.execute(sa.text("DROP FUNCTION IF EXISTS prevent_prompt_version_mutation()"))
    connection.execute(sa.text("DROP FUNCTION IF EXISTS prevent_published_workflow_child_mutation()"))
    connection.execute(sa.text("DROP FUNCTION IF EXISTS prevent_published_workflow_mutation()"))
    for table in reversed(WORKSPACE_SCOPED_TABLES):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_read" ON "{table}"'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_insert" ON "{table}"'))
    op.drop_table("workflow_evaluation_results")
    op.drop_table("model_configs")
    op.drop_table("prompt_versions")
    op.drop_table("prompts")
    op.drop_table("workflow_thresholds")
    op.drop_table("workflow_edges")
    op.drop_table("workflow_nodes")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
