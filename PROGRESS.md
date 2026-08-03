# PROGRESS

This is the living handoff for the AI Operations Deployment Platform. F01 is the verified foundation; the complete documented product build is active and governed by `task.md` with WIP=1.

## Current state

- **Phase:** Full product execution active; `R-01` durable execution runtime and worker boundary is the current WIP item.
- **Latest product checkpoint:** F01 foundation, SEC-01 secure configuration, H-01 full-product harness continuity, T-01 tenancy/auth/RLS, D-01 discovery/baseline/scoring, and W-01 workflow definitions/versioning/designer/evaluation gate are passing.
- **Last verification:** W-01 static and real Compose/PostgreSQL HTTP E2E, live browser smoke, backend/frontend checks, F01 `scripts/verify-mvp.ps1`, T-01 `scripts/verify-tenancy.ps1`, harness, and secret checks passed on 2026-08-04. Isolated stacks preserved named PostgreSQL volumes under the 32 GB guard.
- **Branch:** `feat/mvp-compliance-mvp`

## Feature status (source of truth: `feature-list.json`)

- **Passing:** H01, H02, H03, F01, SEC-01, H-01, T-01, D-01, W-01
- **Active (WIP=1):** R-01 - durable runtime, workers, outbox, and model boundary
- **Blocked:** none
- **Not started:** V-01 through LAUNCH-01 in dependency order; do not activate more than one package.

## Known issues / blockers

- Docker Desktop and WSL2 are running. `%UserProfile%\.wslconfig` caps newly created WSL VHDs at 32 GB with 2 GB swap and sparse VHD creation. The repository storage guard remains the source of truth before Compose startup.
- The local credential file is `.env` and ignored by Git; `.env.example` is a placeholder template. Do not paste `.env` values into tracked files, logs, screenshots, or prompts.
- A native Windows PostgreSQL process also listens on host port 5432. Compose services communicate over the Docker network and the F01 verifier passes; use a temporary `POSTGRES_PORT=15432` override for host-side tests when that native service is present.
- GitHub remote `git@github.com:nidhiyashwanth/jake.git` contains the published harness baseline on `origin/main`.
- Founder-specific choices in `00-EXEC-SUMMARY.md` section 7 remain open: capital/time mode, reachable vertical access, services appetite, and geography.

## Next actions (ordered; the next session starts at #1)

1. Implement R-01 Postgres-backed execution state, worker claims, retries, idempotency, outbox, and replay in new isolated workstreams.
2. Run R-01 static, runtime, integration, crash-recovery, and browser evidence before activating V-01.
3. Keep the Compose/PostgreSQL path, browser gate, and three-layer verification contract intact while extending the product.

---

## Session Exit Checklist

- [x] Relevant harness and product verification passes for the current package.
- [x] `task.md`, `PROGRESS.md`, and `feature-list.json` contain current state and evidence.
- [x] New durable decisions are recorded in `DECISIONS.md`.
- [ ] No debug code, temporary files, or stale TODOs remain.
- [x] One concrete next action is documented.
- [ ] Git working tree is clean after repository initialization.
