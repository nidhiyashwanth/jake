# PROGRESS

This is the living handoff for the AI Operations Deployment Platform. F01 is the verified foundation; the complete documented product build is active and governed by `task.md` with WIP=1.

## Current state

- **Phase:** Full product execution active; `X-01` CI, environments, deployment, and recovery is the current WIP item.
- **Latest product checkpoint:** F01 foundation, SEC-01 secure configuration, H-01 full-product harness continuity, T-01 tenancy/auth/RLS, D-01 discovery/baseline/scoring, W-01 workflow definitions/versioning/designer/evaluation gate, R-01 durable runtime/workers/outbox/replay, V-01 review desk/queue/provenance/corrections, C-01 connectors/MCP/vault, P-01 rules/requirements/document taxonomy/chase, Q-01 confidence/routing/thresholds/sampled audit, E-01 golden-set evaluation/publish blocking/drift, I-01 execution inspection/replay/observability, L-01 value realization ledger, and G-01 governance/privacy controls are passing.
- **Last verification:** G-01 static and real Compose/PostgreSQL HTTP/browser gate passed PII field-path classification/redaction, legal-hold retention, source deletion with derived metadata retained, no-training model history, incident lifecycle, export access logging, redacted audit-pack download, and append-only database trigger rejection. Pure G-01/L-01 tests, frontend typecheck/tests/build, migration to `0017_governance`, and the full harness path passed on 2026-08-04. Isolated stacks preserved named PostgreSQL volumes under the 32 GB guard.
- **Branch:** `feat/mvp-compliance-mvp`

## Feature status (source of truth: `feature-list.json`)

- **Passing:** H01, H02, H03, F01, SEC-01, H-01, T-01, D-01, W-01, R-01, V-01, C-01, P-01, Q-01, E-01, I-01, L-01, G-01
- **Active (WIP=1):** X-01 - CI, environments, deployment, and recovery
- **Blocked:** none
- **Not started:** X-01 and LAUNCH-01 in dependency order; do not activate more than one package.

## Known issues / blockers

- Docker Desktop and WSL2 are running. `%UserProfile%\.wslconfig` caps newly created WSL VHDs at 32 GB with 2 GB swap and sparse VHD creation. The repository storage guard remains the source of truth before Compose startup.
- The local credential file is `.env` and ignored by Git; `.env.example` is a placeholder template. Do not paste `.env` values into tracked files, logs, screenshots, or prompts.
- A native Windows PostgreSQL process also listens on host port 5432. Compose services communicate over the Docker network and the F01 verifier passes; use a temporary `POSTGRES_PORT=15432` override for host-side tests when that native service is present.
- GitHub remote `git@github.com:nidhiyashwanth/jake.git` contains the published harness baseline on `origin/main`.
- Founder-specific choices in `00-EXEC-SUMMARY.md` section 7 remain open: capital/time mode, reachable vertical access, services appetite, and geography.

## Next actions (ordered; the next session starts at #1)

1. Read the X-01 section of `task.md` and the deployment/recovery sections of `05-ARCHITECTURE.md`, `08-ROADMAP-90-DAY.md`, and `09-RISKS-COMPLIANCE.md`, then inventory the current images, migrations, CI, and backup seams.
2. Add the smallest complete CI, deployment, migration, storage-budget, and recovery package without changing the documented stack.
3. Keep the Compose/PostgreSQL path, browser gate, and three-layer verification contract intact while extending the product.

---

## Session Exit Checklist

- [x] Relevant harness and product verification passes for the current package.
- [x] `task.md`, `PROGRESS.md`, and `feature-list.json` contain current state and evidence.
- [x] New durable decisions are recorded in `DECISIONS.md`.
- [x] No debug code, temporary files, or stale TODOs remain.
- [x] One concrete next action is documented.
- [ ] Git working tree is clean after repository initialization.
