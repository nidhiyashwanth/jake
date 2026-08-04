# R-01 runtime verification

`contract.json` is the tracked black-box contract for the durable execution
runtime. `scripts/verify-runtime.ps1` starts a bounded Compose project and proves
the HTTP contract against real PostgreSQL-backed services. `browser_smoke.py`
checks the operator surface with a fresh Playwright context.

The verifier never writes database rows directly, uses SQLite, shells into a
container, prints response bodies, or reads local secret values. It leaves the
named PostgreSQL volume in place and applies the repository's 32 GB Docker
storage guard.
