# PROGRESS

This is the living handoff for the AI Operations Deployment Platform. F01 is the verified foundation; the complete documented product build is active and governed by `task.md` with WIP=1.

## Current state

- **Phase:** Complete documented product package is passing through `LAUNCH-01`; no required work package remains open. Customer-specific secret-manager wiring, contacts, and real acceptance are deployment-owner inputs, not unchecked repository work.
- **Latest product checkpoint:** F01 foundation, SEC-01 secure configuration, H-01 full-product harness continuity, T-01 tenancy/auth/RLS, D-01 discovery/baseline/scoring, W-01 workflow definitions/versioning/designer/evaluation gate, R-01 durable runtime/workers/outbox/replay, V-01 review desk/queue/provenance/corrections, C-01 connectors/MCP/vault, P-01 rules/requirements/document taxonomy/chase, Q-01 confidence/routing/thresholds/sampled audit, E-01 golden-set evaluation/publish blocking/drift, I-01 execution inspection/replay/observability, L-01 value realization ledger, and G-01 governance/privacy controls are passing.
- **Last verification:** GitHub Actions run [`30888809656`](https://github.com/nidhiyashwanth/jake/actions/runs/30888809656) passed X-01 from a clean checkout on 2026-08-04: quality and locked audits, ephemeral PostgreSQL migrations/integration, staging/browser smoke, backup/restore drill, backend/frontend SPDX SBOMs, Trivy image gates, and exact Compose cleanup. The downloaded backend/frontend SARIF artifacts contained zero HIGH/CRITICAL results. The full local `scripts/verify-launch.ps1` then passed the isolated stack, 11-surface owner role tour, delivery/handoff mode switch, synthetic 10-business-day acceptance recomputation, and launch-owned cleanup; all stacks remained under the 32 GB storage guard.
- **Branch:** `feat/mvp-compliance-mvp`

## Feature status (source of truth: `feature-list.json`)

- **Passing:** H01, H02, H03, F01, SEC-01, H-01, T-01, D-01, W-01, R-01, V-01, C-01, P-01, Q-01, E-01, I-01, L-01, G-01, X-01
- **Active (WIP=1 maximum):** none; the product package board is complete
- **Blocked:** none
- **Not started:** none; any new work requires a new scoped package before implementation.

## Known issues / blockers

- Docker Desktop and WSL2 are running. `%UserProfile%\.wslconfig` caps newly created WSL VHDs at 32 GB with 2 GB swap and sparse VHD creation. The repository storage guard remains the source of truth before Compose startup.
- The local credential file is `.env` and ignored by Git; `.env.example` is a placeholder template. Do not paste `.env` values into tracked files, logs, screenshots, or prompts.
- A native Windows PostgreSQL process also listens on host port 5432. Compose services communicate over the Docker network and the F01 verifier passes; use a temporary `POSTGRES_PORT=15432` override for host-side tests when that native service is present.
- GitHub remote `git@github.com:nidhiyashwanth/jake.git` contains the published harness baseline on `origin/main`.
- Founder-specific choices in `00-EXEC-SUMMARY.md` section 7 remain open: capital/time mode, reachable vertical access, services appetite, and geography.

## Next actions (ordered; the next session starts at #1)

1. Supply customer-specific secret-manager values, support route keys, and named acceptance owners outside Git.
2. Replace the synthetic launch manifest with customer-owned, rights-approved evidence before live customer data is accepted.
3. Promote only the exact CI SHA/image digests after the customer signs the baseline and acceptance window.

---

## Session Exit Checklist

- [x] Relevant harness and product verification passes for the current package.
- [x] `task.md`, `PROGRESS.md`, and `feature-list.json` contain current state and evidence.
- [x] New durable decisions are recorded in `DECISIONS.md`.
- [x] No debug code, temporary files, or stale TODOs remain.
- [x] One concrete next action is documented.
- [ ] Git working tree is clean after the release checkpoint is committed and pushed.
