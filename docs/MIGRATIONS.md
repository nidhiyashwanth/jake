# Migration policy

- **Source:** Alembic files under `backend/migrations/versions/` and the
  deployment contract in `docs/DEPLOYMENT.md`.
- **Applicability:** every schema change after `0019_mcp_request_hash`.
- **Expiry:** update when the database engine or migration runner changes.

The production migration mode is forward-only. There must be one linear Alembic
head, and production deploys apply `upgrade head` before traffic is admitted.
Never use `alembic downgrade` as a production rollback. Repair an incompatible
schema with a new forward migration.

Changes to `executions`, `execution_steps`, `value_events`, or governance source
metadata use expand/contract sequencing: add nullable or additive structures,
deploy code that can read both shapes, backfill with an observable job, switch
reads/writes, and only then remove obsolete structures in a later reviewed
migration. The policy manifest is `deploy/migrations-policy.json` and the
executable check is `scripts/verify-migrations.ps1`.
