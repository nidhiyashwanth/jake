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

## D-005 — Keep the documented architecture stack for the MVP

- **Date:** 2026-08-03
- **Decision:** The first MVP uses the documented stack: Next.js/TypeScript for the review desk, FastAPI/Pydantic for the API, and PostgreSQL 16 running through Docker Desktop’s WSL 2 backend. No SQLite fallback is part of the product path.
- **Why:** The architecture is a product constraint, not a timeline estimate. Keeping the real database and service boundaries now prevents a fast demo from encoding the wrong persistence behavior.
- **Rejected alternative:** Replace PostgreSQL with SQLite to avoid installing the intended local runtime.
- **Remaining constraints:** Docker/WSL storage is explicitly capped; the MVP must run through the same Compose/Postgres path used for integration verification.

## D-006 — Ship the narrow Compose-backed F01 vertical slice

- **Date:** 2026-08-03
- **Decision:** Implement F01 as a small modular-monolith slice with a FastAPI API, Next.js review desk, PostgreSQL 16 migrations, deterministic document normalization/rules, human correction, append-only status snapshots, and an audit ledger. Use the repository Compose verifier as the release gate; do not add OCR, LLM credentials, connectors, authentication, or distributed infrastructure yet.
- **Why:** The first useful learning loop is intake → verification → review → evidence. Keeping that loop runnable and auditable gives the owner something testable to put in front of an operator quickly.
- **Rejected alternative:** Expand into the full platform architecture before the first workflow is exercised by a real operator.
- **Remaining constraints:** Preserve the PostgreSQL-only path, the 32 GB storage guard, WIP=1, and the three-layer completion gate. Select the next feature only after F01 feedback is captured.

## D-007 — Treat F01 as the foundation, not the product finish line

- **Date:** 2026-08-04
- **Decision:** Execute the remaining documented product modules through `task.md`: tenancy/RLS, discovery and signed baselines, workflow versioning, durable runtime, full review, connectors/vault, wedge rules/chasing, confidence, evals, inspection, ledger, governance, deployment, and launch acceptance. Keep one package active at a time and require real evidence before advancing.
- **Why:** F01 proves the narrow compliance loop, but it does not satisfy the product specification's multi-tenant, workflow, connector, runtime, measurement, governance, and deployment promises.
- **Rejected alternative:** Declare the F01 vertical slice to be the complete platform or create a broad unverified rewrite without dependency-ordered gates.
- **Remaining constraints:** Preserve the documented stack and explicit out-of-scope items, use isolated worktrees for parallel non-conflicting work, and keep all package state synchronized across `task.md`, `feature-list.json`, and `PROGRESS.md`.

## D-008 — Keep local credentials out of tracked configuration

- **Date:** 2026-08-04
- **Decision:** Local Compose and application configuration loads credentials from the ignored repository-root `.env`; `.env.example` contains placeholders only. Tracked Compose, settings, Alembic, README, and test files may not contain usable credential defaults.
- **Why:** A repository can be public or copied into a new environment at any time. Secret-like values in defaults create accidental disclosure and teach future contributors unsafe configuration habits.
- **Rejected alternative:** Keep convenient weak credential fallbacks in tracked files and rely on developers to remember not to reuse them.
- **Remaining constraints:** Production secrets must come from the deployment secret manager; local `.env` values must never appear in logs, screenshots, prompts, or commits.

## D-009 — Rotate the local database volume with the credential move

- **Date:** 2026-08-04
- **Decision:** The new ignored `.env` uses a local-only database identity and the Compose stack uses a new named volume. The previous development volume remains untouched until its contents are deliberately migrated or retired.
- **Why:** PostgreSQL initializes credentials only on first creation of a data directory. Reusing the old volume would silently keep the old weak identity even after the tracked configuration was cleaned.
- **Rejected alternative:** Delete the old volume or pretend changing Compose environment variables rotates an already-initialized PostgreSQL password.
- **Remaining constraints:** Keep the new volume inside the 32 GB Docker budget and document any future migration/retirement as a separate, recoverable operation.

## D-010 - Make tenancy and browser auth boundaries explicit

- **Date:** 2026-08-04
- **Decision:** T-01 uses a development-only hashed bearer-session boundary with explicit OIDC/JWT replacement seams, application-table RBAC, request-level workspace context, forced PostgreSQL RLS for workspace-owned rows, and explicit-origin credentialed CORS. The frontend must propagate the bearer token and active workspace on protected requests; production-like environments must disable the development provider.
- **Why:** The first real browser run exposed that compile-time UI behavior, CORS, and API authorization must be verified together. A UI-only session shell is not a tenant boundary, and a database RLS policy is not exercised by a superuser connection.
- **Rejected alternative:** Keep unauthenticated browser fallback as the only path, rely on frontend workspace headers without bearer authentication, or treat mocked browser responses as sufficient proof.
- **Remaining constraints:** Keep the local fallback clearly labeled, use a non-superuser application database role for production RLS enforcement, preserve the six-role capability matrix, and rerun the live Compose/API/browser gate whenever the auth or tenancy boundary changes.

## D-011 - Keep D-01 contract aliases and browser proof aligned with the canonical formula

- **Date:** 2026-08-04
- **Decision:** Expose the D-01 discovery contract through workspace-scoped aliases while retaining the existing service boundaries, send browser source ingestion as multipart form data, and use `opportunity.v1` with the same deterministic weights in the UI preview and API score request. Alternate verifier ports must be explicit CORS origins rather than an open-origin fallback.
- **Why:** The first real browser run found drift between the API contract, frontend payload shapes, source ingestion content type, and formula label. Contract-facing aliases keep the existing modular services reusable while the live browser gate proves the path users actually operate.
- **Rejected alternative:** Accept arbitrary frontend payloads, silently use a second formula identifier, or disable CORS checks to make the alternate-port verifier pass.
- **Remaining constraints:** Keep drafts human-editable and non-publishable, persist draft edits only after a real source interview exists, preserve signed-baseline immutability, and rerun the D-01 API plus browser gate when discovery or scoring changes.

## D-012 - Treat workflow version IDs and server-owned evaluation as the public W-01 contract

- **Date:** 2026-08-04
- **Decision:** W-01 exposes stable workflow keys, ID-addressable immutable version routes, canonical form-driven DAG payloads, versioned prompt/model references, and server-owned synthetic evaluation suites. The read-only graph remains an inspection surface; publication requires a passing result bound to the exact definition hash.
- **Why:** The live integration gate exposed drift between isolated frontend, backend, and verifier assumptions. A real product needs one durable ID contract, no client-forged evaluation result, and explicit proof that browser saves, workspace isolation, graph validation, and publish immutability operate against PostgreSQL.
- **Rejected alternative:** Hide route/payload mismatches behind client adapters only, accept client-supplied pass/fail results, or treat a static graph screenshot as workflow persistence evidence.
- **Remaining constraints:** Full golden-set evaluation, durable execution, connectors, review, ledger, governance, deployment, and launch packages remain separate dependency-gated work; published workflow children and evaluation results stay immutable.
