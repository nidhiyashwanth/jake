"""Add governance, PII classification, retention, incidents, and audit packs."""

from alembic import op
import sqlalchemy as sa


revision = "0017_governance"
down_revision = "0016_value_ledger"
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


def _create_append_only_trigger(connection: sa.Connection, table: str, trigger: str) -> None:
    connection.execute(
        sa.text(
            f'''CREATE TRIGGER "{trigger}"
               BEFORE UPDATE OR DELETE ON "{table}"
               FOR EACH ROW EXECUTE FUNCTION prevent_governance_append_only_mutation()'''
        )
    )


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("training_policy", sa.String(length=32), nullable=False, server_default="no_training"),
    )
    op.add_column("model_configs", sa.Column("opt_in_reference", sa.String(length=240), nullable=True))
    op.create_check_constraint(
        "ck_model_configs_training_policy",
        "model_configs",
        "training_policy IN ('no_training', 'customer_opt_in') AND (training_policy <> 'customer_opt_in' OR opt_in_reference IS NOT NULL)",
    )

    op.create_table(
        "governance_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("artifact_id", sa.String(length=120), nullable=False),
        sa.Column("storage_ref", sa.String(length=500), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("pii_status", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("pii_flags_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("classification", sa.String(length=24), nullable=False, server_default="confidential"),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("pii_status IN ('unknown', 'clear', 'detected', 'redacted')", name="ck_governance_artifacts_pii_status"),
        sa.CheckConstraint("classification IN ('public', 'internal', 'confidential', 'restricted')", name="ck_governance_artifacts_classification"),
        sa.UniqueConstraint("workspace_id", "artifact_type", "artifact_id", name="uq_governance_artifacts_scope_ref"),
    )
    for column in ("workspace_id", "artifact_type", "artifact_id", "retention_until", "created_at"):
        op.create_index(f"ix_governance_artifacts_{column}", "governance_artifacts", [column])

    op.create_table(
        "retention_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False, server_default="delete_source_keep_derived"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("retention_days BETWEEN 1 AND 3650", name="ck_retention_policies_days"),
        sa.CheckConstraint("action IN ('delete_source_keep_derived', 'retain')", name="ck_retention_policies_action"),
        sa.UniqueConstraint("workspace_id", "artifact_type", "version", name="uq_retention_policies_scope_version"),
    )
    op.create_index("ix_retention_policies_workspace_id", "retention_policies", ["workspace_id"])
    op.create_index("ix_retention_policies_artifact_type", "retention_policies", ["artifact_type"])
    op.create_index("ix_retention_policies_active", "retention_policies", ["active"])

    op.create_table(
        "legal_holds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("artifact_id", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("placed_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("released_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'released')", name="ck_legal_holds_status"),
    )
    for column in ("workspace_id", "artifact_type", "artifact_id", "status", "placed_by", "placed_at"):
        op.create_index(f"ix_legal_holds_{column}", "legal_holds", [column])

    op.create_table(
        "retention_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("held_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("workspace_id", "as_of", "actor_id", "created_at"):
        op.create_index(f"ix_retention_runs_{column}", "retention_runs", [column])

    op.create_table(
        "governance_incidents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("executions.id"), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("customer_notification_status", sa.String(length=24), nullable=False, server_default="not_started"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("postmortem_link", sa.String(length=500), nullable=True),
        sa.Column("timeline_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_governance_incidents_severity"),
        sa.CheckConstraint("status IN ('open', 'investigating', 'contained', 'resolved')", name="ck_governance_incidents_status"),
        sa.CheckConstraint("customer_notification_status IN ('not_started', 'not_required', 'pending', 'sent')", name="ck_governance_incidents_notification"),
    )
    for column in ("workspace_id", "workflow_id", "execution_id", "severity", "status", "detected_at", "created_by", "updated_by"):
        op.create_index(f"ix_governance_incidents_{column}", "governance_incidents", [column])

    op.create_table(
        "model_change_history",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("model_config_id", sa.String(length=36), sa.ForeignKey("model_configs.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("prompt_key", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("change_type", sa.String(length=40), nullable=False, server_default="registered"),
        sa.Column("change_summary", sa.String(length=1000), nullable=True),
        sa.Column("training_policy", sa.String(length=32), nullable=False, server_default="no_training"),
        sa.Column("opt_in_reference", sa.String(length=240), nullable=True),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("training_policy IN ('no_training', 'customer_opt_in') AND (training_policy <> 'customer_opt_in' OR opt_in_reference IS NOT NULL)", name="ck_model_change_history_training_policy"),
    )
    for column in ("workspace_id", "model_config_id", "key", "created_by", "created_at"):
        op.create_index(f"ix_model_change_history_{column}", "model_change_history", [column])

    op.create_table(
        "audit_packs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False, server_default="audit-pack.v1"),
        sa.Column("redaction_policy_version", sa.String(length=40), nullable=False, server_default="pii.v1"),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("generated_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("workspace_id", "generated_by", "generated_at", "created_at"):
        op.create_index(f"ix_audit_packs_{column}", "audit_packs", [column])

    connection = op.get_bind()
    for table in (
        "governance_artifacts",
        "retention_policies",
        "legal_holds",
        "retention_runs",
        "governance_incidents",
        "model_change_history",
        "audit_packs",
    ):
        _enable_workspace_rls(connection, table)

    connection.execute(
        sa.text(
            '''CREATE OR REPLACE FUNCTION prevent_governance_append_only_mutation() RETURNS trigger AS $$
               BEGIN
                 RAISE EXCEPTION 'governance evidence is append-only';
               END;
               $$ LANGUAGE plpgsql'''
        )
    )
    for table, trigger in (
        ("audit_logs", "audit_logs_immutable"),
        ("data_access_logs", "data_access_logs_immutable"),
        ("credential_access_logs", "credential_access_logs_immutable"),
        ("model_change_history", "model_change_history_immutable"),
        ("retention_runs", "retention_runs_immutable"),
        ("audit_packs", "audit_packs_immutable"),
    ):
        _create_append_only_trigger(connection, table, trigger)


def downgrade() -> None:
    connection = op.get_bind()
    for table, trigger in (
        ("audit_packs", "audit_packs_immutable"),
        ("retention_runs", "retention_runs_immutable"),
        ("model_change_history", "model_change_history_immutable"),
        ("credential_access_logs", "credential_access_logs_immutable"),
        ("data_access_logs", "data_access_logs_immutable"),
        ("audit_logs", "audit_logs_immutable"),
    ):
        connection.execute(sa.text(f'DROP TRIGGER IF EXISTS "{trigger}" ON "{table}"'))
    connection.execute(sa.text("DROP FUNCTION IF EXISTS prevent_governance_append_only_mutation()"))
    for table in (
        "audit_packs",
        "model_change_history",
        "governance_incidents",
        "retention_runs",
        "legal_holds",
        "retention_policies",
        "governance_artifacts",
    ):
        connection.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
        connection.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_workspace_isolation" ON "{table}"'))
        op.drop_table(table)
    op.drop_constraint("ck_model_configs_training_policy", "model_configs", type_="check")
    op.drop_column("model_configs", "opt_in_reference")
    op.drop_column("model_configs", "training_policy")
