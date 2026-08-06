"""Add workspace-scoped connectors, MCP pins, and envelope-encrypted vault records."""

from alembic import op
import sqlalchemy as sa


revision = "0011_connectors_vault"
down_revision = "0010_review_desk"
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
    op.create_table(
        "connectors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("egress_hosts_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('email', 'object_storage', 'notify', 'rest', 'webhook', 'sftp', 'database', 'csv_excel', 'rpa')",
            name="ck_connectors_kind",
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_connectors_workspace_name"),
    )
    op.create_index("ix_connectors_workspace_id", "connectors", ["workspace_id"])
    op.create_index("ix_connectors_created_by", "connectors", ["created_by"])

    op.create_table(
        "workspace_key_envelopes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("dek_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("encrypted_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_key_envelopes_workspace"),
    )
    op.create_index("ix_workspace_key_envelopes_workspace_id", "workspace_key_envelopes", ["workspace_id"])

    op.create_table(
        "credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("connector_id", sa.String(length=36), sa.ForeignKey("connectors.id"), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("secret_type", sa.String(length=40), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("dek_id", sa.String(length=80), nullable=False),
        sa.Column("key_version", sa.String(length=80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credentials_workspace_id", "credentials", ["workspace_id"])
    op.create_index("ix_credentials_connector_id", "credentials", ["connector_id"])
    op.create_index("ix_credentials_dek_id", "credentials", ["dek_id"])

    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("auth_mode", sa.String(length=40), nullable=False),
        sa.Column("server_version", sa.String(length=120), nullable=False),
        sa.Column("metadata_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("allowed_tools_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("workflow_version_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("egress_hosts_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_mcp_servers_workspace_name"),
    )
    op.create_index("ix_mcp_servers_workspace_id", "mcp_servers", ["workspace_id"])
    op.create_index("ix_mcp_servers_created_by", "mcp_servers", ["created_by"])

    op.create_table(
        "connector_calls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("connector_id", sa.String(length=36), sa.ForeignKey("connectors.id"), nullable=True),
        sa.Column("mcp_server_id", sa.String(length=36), sa.ForeignKey("mcp_servers.id"), nullable=True),
        sa.Column("workflow_version_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("call_type", sa.String(length=40), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("result_untrusted", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("egress_host", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=240), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_connector_calls_workspace_idempotency"),
    )
    op.create_index("ix_connector_calls_workspace_id", "connector_calls", ["workspace_id"])
    op.create_index("ix_connector_calls_connector_id", "connector_calls", ["connector_id"])
    op.create_index("ix_connector_calls_mcp_server_id", "connector_calls", ["mcp_server_id"])
    op.create_index("ix_connector_calls_workflow_version_id", "connector_calls", ["workflow_version_id"])
    op.create_index("ix_connector_calls_actor_id", "connector_calls", ["actor_id"])
    op.create_index("ix_connector_calls_created_at", "connector_calls", ["created_at"])

    op.create_table(
        "credential_access_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("credential_id", sa.String(length=36), sa.ForeignKey("credentials.id"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("purpose", sa.String(length=180), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credential_access_logs_workspace_id", "credential_access_logs", ["workspace_id"])
    op.create_index("ix_credential_access_logs_credential_id", "credential_access_logs", ["credential_id"])
    op.create_index("ix_credential_access_logs_actor_id", "credential_access_logs", ["actor_id"])
    op.create_index("ix_credential_access_logs_created_at", "credential_access_logs", ["created_at"])

    connection = op.get_bind()
    for table in (
        "connectors",
        "workspace_key_envelopes",
        "credentials",
        "mcp_servers",
        "connector_calls",
        "credential_access_logs",
    ):
        _enable_workspace_rls(connection, table)


def downgrade() -> None:
    connection = op.get_bind()
    tables = (
        "credential_access_logs",
        "connector_calls",
        "mcp_servers",
        "credentials",
        "workspace_key_envelopes",
        "connectors",
    )
    for table in tables:
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
        op.drop_table(table)
