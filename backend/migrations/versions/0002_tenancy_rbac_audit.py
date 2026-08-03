"""Add workspace tenancy, local auth sessions, RBAC records, and RLS."""

from alembic import op
import sqlalchemy as sa


revision = "0002_tenancy_rbac_audit"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000003"
DEFAULT_MEMBERSHIP_ID = "00000000-0000-0000-0000-000000000004"

WORKSPACE_SCOPED_TABLES = (
    "vendors",
    "compliance_documents",
    "compliance_checks",
    "review_tasks",
    "compliance_status",
    "audit_events",
)


def _enable_workspace_rls(connection: sa.Connection, table: str) -> None:
    connection.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    connection.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    policy = f"{table}_workspace_isolation"
    connection.execute(
        sa.text(
            f'''CREATE POLICY "{policy}" ON "{table}"
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
        "organizations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('internal', 'customer', 'partner')", name="ck_organizations_kind"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False),
        sa.Column("delivery_mode", sa.String(length=20), nullable=False),
        sa.Column("handoff_mode", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("environment IN ('development', 'staging', 'production')", name="ck_workspaces_environment"),
        sa.CheckConstraint("delivery_mode IN ('delivery', 'handoff')", name="ck_workspaces_delivery_mode"),
        sa.CheckConstraint("handoff_mode IN ('operator', 'customer')", name="ck_workspaces_handoff_mode"),
        sa.UniqueConstraint("organization_id", "name", name="uq_workspaces_organization_name"),
    )
    op.create_index("ix_workspaces_organization_id", "workspaces", ["organization_id"])
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("external_subject", name="uq_users_external_subject"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'builder', 'operator', 'reviewer', 'viewer', 'auditor')",
            name="ck_memberships_role",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_memberships_status"),
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_memberships_user_workspace"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_workspace_id", "auth_sessions", ["workspace_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "workspace_contexts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("auth_sessions.id"), nullable=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workspace_contexts_session_id", "workspace_contexts", ["session_id"])
    op.create_index("ix_workspace_contexts_user_id", "workspace_contexts", ["user_id"])
    op.create_index("ix_workspace_contexts_workspace_id", "workspace_contexts", ["workspace_id"])

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO organizations (id, name, kind, created_at)
            VALUES (:id, 'Local Development Organization', 'internal', CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": DEFAULT_ORGANIZATION_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, organization_id, name, environment, delivery_mode, handoff_mode, created_at)
            VALUES (:id, :organization_id, 'Local Development Workspace', 'development', 'delivery', 'operator', CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": DEFAULT_WORKSPACE_ID, "organization_id": DEFAULT_ORGANIZATION_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, email, name, created_at)
            VALUES (:id, 'local-dev@example.invalid', 'Local Development User', CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": DEFAULT_USER_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO memberships (id, user_id, workspace_id, role, status, invited_at)
            VALUES (:id, :user_id, :workspace_id, 'owner', 'active', CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": DEFAULT_MEMBERSHIP_ID, "user_id": DEFAULT_USER_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )

    for table in WORKSPACE_SCOPED_TABLES:
        op.add_column(table, sa.Column("workspace_id", sa.String(length=36), nullable=True))

    connection.execute(
        sa.text("UPDATE vendors SET workspace_id = :workspace_id WHERE workspace_id IS NULL"),
        {"workspace_id": DEFAULT_WORKSPACE_ID},
    )
    for table in ("compliance_documents", "compliance_checks", "review_tasks", "compliance_status"):
        connection.execute(
            sa.text(f"UPDATE {table} SET workspace_id = (SELECT workspace_id FROM vendors WHERE vendors.id = {table}.vendor_id) WHERE workspace_id IS NULL")
        )
    connection.execute(
        sa.text(
            "UPDATE audit_events SET workspace_id = (SELECT workspace_id FROM vendors WHERE vendors.id = audit_events.vendor_id) WHERE workspace_id IS NULL"
        )
    )
    for table in WORKSPACE_SCOPED_TABLES:
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
        op.create_foreign_key(f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"])

    connection.execute(sa.text("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS vendors_legal_name_key"))
    op.create_unique_constraint("uq_vendors_workspace_legal_name", "vendors", ["workspace_id", "legal_name"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_workspace_id", "audit_logs", ["workspace_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_table(
        "data_access_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("purpose", sa.String(length=160), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_data_access_logs_workspace_id", "data_access_logs", ["workspace_id"])
    op.create_index("ix_data_access_logs_actor_id", "data_access_logs", ["actor_id"])
    op.create_index("ix_data_access_logs_artifact_id", "data_access_logs", ["artifact_id"])
    op.create_index("ix_data_access_logs_occurred_at", "data_access_logs", ["occurred_at"])

    for table in WORKSPACE_SCOPED_TABLES:
        _enable_workspace_rls(connection, table)
    _enable_append_only_rls(connection, "audit_logs")
    _enable_append_only_rls(connection, "data_access_logs")
    connection.execute(sa.text('DROP POLICY "audit_logs_workspace_read" ON "audit_logs"'))
    connection.execute(
        sa.text(
            '''CREATE POLICY "audit_logs_workspace_read" ON "audit_logs" FOR SELECT
               USING (workspace_id IS NOT NULL AND workspace_id = current_setting('app.workspace_id', true))'''
        )
    )
    connection.execute(sa.text('DROP POLICY "audit_logs_workspace_insert" ON "audit_logs"'))
    connection.execute(
        sa.text(
            '''CREATE POLICY "audit_logs_workspace_insert" ON "audit_logs" FOR INSERT
               WITH CHECK (workspace_id IS NULL OR workspace_id = current_setting('app.workspace_id', true))'''
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("data_access_logs", "audit_logs"):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_read" ON "{table}"'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_insert" ON "{table}"'))
    op.drop_table("data_access_logs")
    op.drop_table("audit_logs")

    op.drop_constraint("uq_vendors_workspace_legal_name", "vendors", type_="unique")
    for table in reversed(WORKSPACE_SCOPED_TABLES):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_column(table, "workspace_id")
    op.create_unique_constraint("vendors_legal_name_key", "vendors", ["legal_name"])

    op.drop_table("workspace_contexts")
    op.drop_table("auth_sessions")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("workspaces")
    op.drop_table("organizations")
