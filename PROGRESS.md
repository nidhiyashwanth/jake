# PROGRESS

This is the living handoff for the AI Operations Deployment Platform. F01 is the verified foundation; the complete documented product build is active and governed by `task.md` with WIP=1.

## Current state

- **Phase:** Full product execution active; `D-01` discovery and signed-baseline work is the current WIP item
- **Latest product checkpoint:** F01 foundation, SEC-01 secure configuration, H-01 full-product harness continuity, and T-01 tenancy/auth/RLS are passing
- **Last verification:** T-01 live Compose/API/browser gate, backend pytest (11 passed), frontend typecheck/build, F01 E2E, secret scan, fresh-session check, and Docker storage guard passed on 2026-08-04; T-01 used 7.33 GB / 32 GB at peak reported usage
- **Branch:** `feat/mvp-compliance-mvp`

## Feature status (source of truth: `feature-list.json`)

- **Passing:** H01, H02, H03, F01, SEC-01, H-01, T-01
- **Active (WIP=1):** D-01 — discovery, signed baselines, and opportunity scoring
- **Blocked:** none
- **Not started:** D-01 through LAUNCH-01 in dependency order; do not activate more than one package

## Known issues / blockers

- Docker Desktop and WSL2 are running. `%UserProfile%\.wslconfig` caps newly created WSL VHDs at 32 GB with 2 GB swap and sparse VHD creation; the repository storage guard reports 3.55 GB / 32 GB after the MVP build.
- The local credential file is now `.env` and ignored by Git; `.env.example` is a placeholder template. Do not paste `.env` values into tracked files, logs, screenshots, or prompts.
- A native Windows PostgreSQL process also listens on host port 5432. Compose services communicate over the Docker network and the F01 verifier passes; use a temporary `POSTGRES_PORT=15432` override for host-side tests when that native service is present.
- GitHub remote `git@github.com:nidhiyashwanth/jake.git` contains the published harness baseline on `origin/main`.
- Founder-specific choices in `00-EXEC-SUMMARY.md` §7 remain open: capital/time mode, reachable vertical access, services appetite, and geography.

## Next actions (ordered; the next session starts at #1)

1. Implement D-01 discovery intake, signed baselines, and deterministic opportunity scoring in an isolated workstream.
2. Run discovery signature, immutability, formula, and scoring evidence, then activate the next package in `task.md`.
3. Keep the Compose/PostgreSQL path, browser gate, and three-layer verification contract intact while extending the product.

---

## Session Exit Checklist

- [x] Relevant harness and product verification passes for the current package
- [x] `task.md`, `PROGRESS.md`, and `feature-list.json` contain current state and evidence
- [x] New durable decisions are recorded in `DECISIONS.md`
- [ ] No debug code, temporary files, or stale TODOs remain
- [x] One concrete next action is documented
- [ ] Git working tree is clean after repository initialization
