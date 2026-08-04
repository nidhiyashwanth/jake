# Local environment contract

- **Source:** `05-ARCHITECTURE.md`, Docker Desktop and Microsoft WSL documentation.
- **Applicability:** local development and F01 integration verification on Windows.
- **Expiry:** update when the runtime stack or storage policy changes.

## Required stack

- Docker Desktop for Windows using the WSL 2 backend.
- PostgreSQL 16 through the repository's Docker Compose configuration.
- Python 3.12 for FastAPI tooling.
- Node/npm for the Next.js review desk.

Copy `.env.example` to the ignored repository-root `.env` and set both the
owner credentials (`POSTGRES_USER`/`POSTGRES_PASSWORD`) and the separate
application credentials (`POSTGRES_APP_USER`/`POSTGRES_APP_PASSWORD`). Compose
uses the owner only for role preparation and migrations; the API and worker
connect through the non-superuser application role.

Docker and WSL are infrastructure prerequisites, not optional substitutes. Do not replace PostgreSQL with SQLite to avoid setup work.

## Storage policy

This machine has limited storage. The user-level `%UserProfile%\\.wslconfig` is configured with a 32 GB `defaultVhdSize`, 2 GB swap, and sparse VHD creation. With Docker Desktop's WSL 2 backend, the repository-enforced guard is the operational budget: run it before building or pulling images.

Do not enable Kubernetes or pull unrelated images. Keep only the Postgres and project images needed for the current MVP. Check usage with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-docker-storage.ps1 -MaxGb 32
docker system df
```

Do not run a broad volume prune while the database contains development data. Remove only named resources that have been identified and backed up.

For local credential rotation, update `.env`, stop the Compose project, and use a deliberate database migration or a new named volume. Changing `POSTGRES_PASSWORD` does not rotate a password in an already-initialized PostgreSQL data directory. Production credentials must be rotated by the deployment secret manager.

## Readiness gate

The environment is ready only when all of these pass:

```powershell
wsl --version
docker version
docker compose version
docker compose --env-file .env --file docker-compose.yml config --quiet
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-docker-storage.ps1 -MaxGb 32
```

For direct integration runs, set `DATABASE_URL` to the application-role URL
and `DATABASE_ADMIN_URL` to the owner URL so test setup and cleanup retain the
least-privilege application boundary.

Then the application health check and the F01 verifier must pass. If WSL reports a pending restart, restart Windows before launching Docker Desktop. If host port 5432 is occupied by a native PostgreSQL service, set `$env:POSTGRES_PORT = "15432"` for a host-side test run; the application services still use the Compose network internally.
