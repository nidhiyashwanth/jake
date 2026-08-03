# DECISIONS

This is an append-only log of durable choices. The numbered research documents remain the detailed source material; this file records choices that govern future work.

## D-001 — Harness before product implementation

- **Date:** 2026-08-03
- **Decision:** Establish repository instructions, continuity state, executable verification, and WIP-limited scope before writing application code.
- **Why:** A fresh agent must know what the system is, how to verify it, and where work stands before product abstractions are introduced.
- **Rejected alternative:** Start building the runtime immediately from the research documents.
- **Remaining constraints:** The product runtime is not considered started until the harness feature list passes and a build plan is recorded.

## D-002 — Keep the research set as the product source material

- **Date:** 2026-08-03
- **Decision:** Preserve the numbered research documents and route to them from `AGENTS.md`; do not replace them with a large instruction file.
- **Why:** The set contains the evidence, product scope, architecture, wedge correction, delivery plan, risks, economics, and fundraising context.
- **Rejected alternative:** Copy the research into `AGENTS.md` or scatter duplicate summaries across agent instructions.
- **Remaining constraints:** Update the canonical document when a conclusion changes and record execution-impacting changes here.

## D-003 — Enforce WIP=1 through the feature list

- **Date:** 2026-08-03
- **Decision:** `feature-list.json` is the executable scope surface, with one active item maximum and verification evidence required for `passing`.
- **Why:** One verified unit at a time reduces cross-session drift and prevents a plausible but unfinished platform build.
- **Rejected alternative:** Track a broad roadmap as prose and allow multiple active tasks.
- **Remaining constraints:** The verifier owns structural checks; future product gates must own pass-state transitions.

## D-004 — Use the modular-monolith architecture as the initial implementation baseline

- **Date:** 2026-08-03
- **Decision:** Future code starts from the boundaries and runtime rules in `05-ARCHITECTURE.md`, refined by `docs/ARCHITECTURE-RULES.md`.
- **Why:** The plan prioritizes customer learning, auditability, and explicit seams over premature distributed infrastructure.
- **Rejected alternative:** Begin with microservices, Kubernetes, a visual workflow editor, or a custom trace platform.
- **Remaining constraints:** Any boundary or infrastructure exception needs a new decision and verification evidence.

## D-005 — Use SQLite for the zero-ops MVP development path

- **Date:** 2026-08-03
- **Decision:** The first local MVP uses SQLite behind a repository boundary; PostgreSQL 16 remains the production target in the architecture baseline.
- **Why:** Docker and Postgres are not installed in the workspace, and a zero-ops local path lets the real vertical slice ship without hiding integration work behind infrastructure setup.
- **Rejected alternative:** Block the first product slice on installing and operating a database service before the behavior exists.
- **Remaining constraints:** Keep persistence interfaces and migrations portable; do not treat SQLite-specific behavior as production proof.
