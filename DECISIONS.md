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

## D-013 â€” Derive runtime order from the published DAG, not canonical storage order

- **Date:** 2026-08-04
- **Decision:** R-01 creates execution steps from a deterministic topological traversal of the published workflow edges. Canonical node sorting remains available for stable definition hashes, but it is never treated as execution order.
- **Why:** The live runtime gate exposed that lexicographic storage order could execute an approval node before the tool it was intended to gate. Edge-owned sequencing is required for durable retries, human waits, and side-effect fences to mean what the workflow author configured.
- **Rejected alternative:** Use the sorted node rows as the queue order or let a model infer the next node at runtime.
- **Remaining constraints:** Published workflow validation must continue to reject cycles; independent branches use stable node-key tie-breaking until explicit parallel-join semantics are introduced.

## D-014 — Make review priority and provenance deterministic before adding model-assisted extraction

- **Date:** 2026-08-04
- **Decision:** V-01 derives queue priority, SLA, aging, and escalation state from versioned reason-code weights. Text-readable documents receive page/line/character provenance and matched-text highlighting; the API explicitly reports when a visual bounding box is unavailable.
- **Why:** Operators need a predictable order of work and an honest source locator before model-assisted extraction or OCR is introduced. A false visual locator would weaken the proof contract.
- **Rejected alternative:** Sort by insertion order, expose model confidence as queue priority, or fabricate page/bounding-box precision for text fixtures.
- **Remaining constraints:** Connector and document-type packages may add richer locators later, but they must preserve the current provenance schema, reason-coded corrections, append-only task events, workspace scope, and browser/API evidence.

## D-015 — Keep connectors provider-agnostic and make the local vault boundary explicit

- **Date:** 2026-08-04
- **Decision:** C-01 uses explicit connector and MCP gateway interfaces with deterministic sandbox adapters for local verification. Connector configuration cannot contain secret-like fields. Credentials use AES-GCM ciphertext under a per-workspace DEK wrapped by a deployment KEK/KMS seam; local development derives a non-production key only when the environment is explicitly development-like.
- **Why:** The product needs real workspace, authorization, logging, redaction, approval, and failure behavior before customer provider credentials are available. The boundary must be testable without inventing external integrations or leaking secrets.
- **Rejected alternative:** Store provider secrets in connector JSON, call arbitrary URLs from the verifier, treat MCP output as trusted control input, or build one bespoke integration per provider before the gateway contract exists.
- **Remaining constraints:** Production-like environments must provide `VAULT_KEK_BASE64` from their secret manager; first-party adapters remain behind the same interface, and external egress requires an explicit deployment allow-list and provider configuration.

## D-016 -- Make the compliance wedge a versioned policy and bounded chase boundary

- **Date:** 2026-08-04
- **Decision:** P-01 stores workspace-scoped requirement-set versions, deterministic rule JSON, human-readable explanations, reason-code taxonomy, vendor/project bindings, document supersession, and point-in-time verification evidence. Chase threads may request a specific document through a customer-owned email connector in a sandbox, but never negotiate coverage or state approval; sends require explicit approval, a weekly cap, escalation CC, attachment matching, and a `compliant_and_verified` success event.
- **Why:** The wedge is a vendor compliance decision with proof, not a COI-only inbox. Policy must be editable and historical without embedding customer rules in code, while outreach must remain bounded and separate from the authorization decision.
- **Rejected alternative:** Keep six COI checks hard-coded, treat all documents as interchangeable, close a chase when an attachment arrives, or let a model generate approval/coverage decisions.
- **Remaining constraints:** OCR/image-only documents remain outside the local text-fixture gate; provider delivery remains behind the connector interface, and confidence/routing, evals, governance, and deployment packages must consume the immutable P-01 evidence rather than duplicate it.

## D-017 -- Route from observable evidence and close the loop with sampled audits

- **Date:** 2026-08-04
- **Decision:** Q-01 computes confidence with a deterministic weighted formula over extraction consistency, validation quality, matching, novelty quality, sender history, and value-at-risk. Thresholds are immutable, workspace/workflow-version scoped, and versioned. High-confidence auto-runs are sampled at a configured rate with a hard two-percent floor; a false-auto audit opens an alert and rolls the active policy back to its recorded predecessor.
- **Why:** Self-reported model confidence is not an accountable control signal. Operators need a visible auto/review/halt tradeoff, a simulator tied to known outcomes, and a measured false-auto loop before automatic processing can be trusted.
- **Rejected alternative:** Let the model choose its confidence or route, use unversioned environment thresholds, or treat a sampled audit as an informal dashboard metric without a rollback path.
- **Remaining constraints:** The simulator consumes historical/golden cases without copying their canonical evidence; threshold changes remain auditable; E-01 must add publish-blocking golden evaluation and drift alerts before confidence policies are used as a release gate.

## D-018 -- Make release evidence immutable, server-owned, and operationally observable

- **Date:** 2026-08-04
- **Decision:** E-01 stores rights-labelled golden sets and cases as immutable provenance, computes reproducible field/route/cost/correction metrics on the server, binds evaluation results to the exact workflow definition hash, and reuses the existing workflow publish gate. Canary failures, regression deltas, and rolling sender/document correction drift produce explicit failure or alert evidence and audit events. The frontend exposes the same boundary without accepting client-supplied pass/fail metrics.
- **Why:** Confidence thresholds alone cannot establish release quality. A customer needs to see what cases were authorized for evaluation, why a release is blocked, which metrics changed, and where live corrections drift after publish. One server-owned gate avoids competing release decisions in the UI or a parallel evaluation table.
- **Rejected alternative:** Trust browser-supplied evaluation metrics, store golden cases without rights metadata, allow a failed regression to publish, or create a separate release gate disconnected from the W-01 exact-hash contract.
- **Remaining constraints:** The canonical 100-case wedge source and release-size policy remain test fixtures until the customer curation workflow is connected; I-01 must add run inspection and safe replay before release evidence is considered fully operable.

## D-019 -- Keep inspection evidence in the runtime contract and provider traces optional

- **Date:** 2026-08-04
- **Decision:** I-01 keeps the durable business timeline in the existing execution, step, event, outbox, and receipt records; the inspector adds redacted node/event detail, stable trace/span correlation, selected immutable-version dry-run replay, and a scoped observability health endpoint. OpenTelemetry exports optional OTLP/Langfuse spans, and Sentry-compatible error reporting is optional. Worker heartbeats and failed/dead-letter counts provide explicit degraded-mode signals when external sinks or workers are unavailable.
- **Why:** Operators need a sub-minute answer to what ran, which version ran, what it changed, and whether it is safe to replay. A second trace database would create competing evidence and increase retention/PII risk, while silently dropping provider telemetry would hide degraded operation.
- **Rejected alternative:** Store a custom trace graph, allow replay to mutate the original execution or invoke live connector writes, return raw inputs/tool arguments, or treat missing Langfuse/Sentry configuration as healthy.
- **Remaining constraints:** Provider sink credentials remain in ignored `.env`/deployment secret management; OTel/Langfuse connectivity is not required for local correctness, and L-01 must consume the immutable execution/cost evidence without duplicating runtime ownership.

## D-020 -- Make value realization append-only and server-calculated

- **Date:** 2026-08-04
- **Decision:** L-01 stores immutable, workspace-scoped `value_events` keyed by an idempotency key. Runtime terminal transitions append execution volume, benefit, and cost evidence; review corrections append a zero-dollar or priced human-touch record. The database enforces RLS and rejects update/delete mutations. Rollups, drill-downs, CSV, and PDF exports are calculated from those same event rows and retain signed baseline and immutable workflow hashes.
- **Why:** A sponsor needs to reconcile every dollar and unit to a source execution or review without allowing a UI or model to forge savings. Count-only and unpriced events make missing rates explicit instead of fabricating certainty, while one ledger avoids divergence between dashboards and exports.
- **Rejected alternative:** Let the frontend submit value totals, update prior events when a baseline changes, store a second custom analytics database, or infer error prevention and dollar value without sampled or signed evidence.
- **Remaining constraints:** `value.v1` is the current formula contract; measured error and payback remain null/unpriced when the required evidence or implementation cost is absent. G-01 must add the broader retention, PII, incident, and dated audit-pack controls without weakening this append-only boundary.
