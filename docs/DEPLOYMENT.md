# Deployment and environment contract

- **Source:** `05-ARCHITECTURE.md` §7 and `docs/LOCAL-ENVIRONMENT.md`.
- **Applicability:** X-01 local, staging, production, and rollback work.
- **Expiry:** update when the deployment target or secret manager changes.

## Boundaries

| Environment | Runtime | Authentication | Data | Secret source |
|---|---|---|---|---|
| development | local Docker Compose | development identity | synthetic/local named volume | ignored root `.env` |
| staging | Docker deployment or Compose overlay | OIDC/JWT | synthetic data plus connector sandboxes | staging secret manager |
| production | Render Docker target in `render.yaml` | OIDC/JWT | customer-scoped data | production secret manager/KMS |

Staging and production reject development authentication, require an explicit
non-wildcard origin list, and require a 32-byte `VAULT_KEK_BASE64` value. No
environment template contains a usable password, token, private key, or database
credential. Public Next.js values are build-time configuration, not a place for
secrets.

## Release and rollback

1. Build the backend, runtime-worker, and frontend images from the exact Git SHA.
2. Run the static gates, migration policy check, image SBOM/CVE report, and the
   staging synthetic/connector smoke before promotion.
   CI blocks fixable HIGH/CRITICAL image findings. Findings without an upstream
   fix are retained in the Trivy SARIF artifact and reviewed during release;
   base images and dependency locks are refreshed on every release candidate.
3. Apply Alembic migrations forward-only. Migrations touching execution or ledger
   state use expand/contract sequencing; production never runs `downgrade`.
4. Promote the same image digests to production and record the release SHA and
   migration head in the handover pack.
5. For an application rollback, redeploy the last known-good image digest only
   after checking that the database head is compatible. A schema rollback is not
   an application rollback; use a forward repair migration.

Render is the first production target because it runs the checked-in Docker
images without changing the application stack. `autoDeploy: false` makes release
promotion deliberate. The worker and API share the same image and database
contract; the worker command is the only process-type difference.

## Required operational evidence

- CI runs Python quality/integration checks, frontend typecheck/tests/build,
  migration checks, security audits, and golden evaluation checks on workflow or
  model changes.
- `scripts/backup-postgres.ps1` creates a PostgreSQL custom-format backup plus a
  SHA-256 manifest. Store production copies in versioned object storage with
  server-side encryption and an independent retention policy.
- `scripts/restore-postgres.ps1` restores a named backup into a temporary isolated
  database and verifies the schema head and durable workspace records without
  touching the source database.
- PostgreSQL production uses provider PITR with an RPO target of 15 minutes and
  an RTO target of 60 minutes. The restore drill runs quarterly and after a
  storage/provider change; local verification remains bounded by the 32 GB
  Docker/WSL budget.
- `scripts/check-docker-storage.ps1` is required before image pulls/builds. Do
  not use a broad volume prune while development data matters.
