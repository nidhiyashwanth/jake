# PROGRESS

This is the living handoff for the AI Operations Deployment Platform. The harness baseline is verified and published; MVP feature F01 is the only active product work.

## Current state

- **Phase:** MVP vertical slice active; intended stack provisioning in progress
- **Latest commit:** harness baseline and published handoff (current `HEAD`)
- **Last verification:** `scripts/verify-harness.ps1 -Area All` passed on 2026-08-03
- **Branch:** `main`

## Feature status (source of truth: `feature-list.json`)

- **Passing:** H01, H02, H03
- **Active (WIP=1):** F01 — vendor compliance verification vertical slice
- **Blocked:** none
- **Not started:** none; expand only after F01 passes

## Known issues / blockers

- Docker Desktop is installed, but WSL and Virtual Machine Platform require a Windows restart before Docker can start; the user-level WSL storage cap is configured.
- The application runtime and test framework do not exist yet; F01 must create the smallest honest local run path and its real checks on PostgreSQL, not SQLite.
- GitHub remote `git@github.com:nidhiyashwanth/jake.git` contains the published harness baseline on `origin/main`.
- Founder-specific choices in `00-EXEC-SUMMARY.md` §7 remain open: capital/time mode, reachable vertical access, services appetite, and geography.

## Next actions (ordered; the next session starts at #1)

1. Restart Windows to activate WSL and Virtual Machine Platform.
2. Start Docker Desktop, set its disk usage limit to 32 GB, and verify Docker Compose/PostgreSQL readiness.
3. Build the backend contract and persistence slice defined in `docs/MVP-CONTRACT.md`.
4. Build the review-desk UI and black-box verification against that contract.
5. Integrate, run the real intake → verify → review → status → ledger path, and publish the first MVP checkpoint.
6. Resolve founder-specific execution choices before expanding beyond F01.

---

## Session Exit Checklist

- [ ] Relevant harness or product verification passes
- [ ] `PROGRESS.md` and `feature-list.json` contain current state and evidence
- [ ] New durable decisions are recorded in `DECISIONS.md`
- [ ] No debug code, temporary files, or stale TODOs remain
- [ ] One concrete next action is documented
- [ ] Git working tree is clean after repository initialization
