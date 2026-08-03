# Architecture rules

- **Source:** `05-ARCHITECTURE.md`, with wedge-specific additions from `11-WEDGE-COMPLIANCE-DOCS.md`.
- **Applicability:** all future product implementation and design work in this repository.
- **Expiry:** revisit when an ADR changes the runtime, domain boundaries, or deployment model.

## Baseline

Start as a modular monolith. The first implementation optimizes for correctness, auditability, and fast customer learning rather than distributed scale. The planned stack is Next.js and TypeScript for the app, FastAPI and Pydantic for the API, PostgreSQL for durable state, Redis plus a Postgres-backed outbox for queueing, object storage for documents, and OpenTelemetry-compatible observability.

Do not build a visual workflow editor, a custom trace store, Kubernetes infrastructure, or a vector database as core infrastructure in the first 90 days. These are explicit scope boundaries, not unfinished TODOs.

## Domain boundaries

The planned domains are `workflows`, `runtime`, `review`, `connectors`, `models`, `rules`, `ledger`, `evals`, and `governance`, with API routers and workers around them.

- API routers are thin and delegate to domain services.
- Domains communicate through explicit interfaces and stable schemas.
- `runtime` is the only domain that writes `execution` and `execution_step` state.
- `ledger` is the only domain that writes `value_event` records and derived rollups.
- `governance` owns audit, retention, and audit-pack concerns.
- `review` owns human tasks, corrections, reason codes, and queue state.
- Connector credentials are accessed through a vault boundary; domain code must not handle raw secrets casually.

## Runtime rules

Versioned workflow definitions are immutable after publish. The v1 executor is a Postgres-backed durable state machine: claim work transactionally, skip already-successful idempotent steps, execute with a timeout, and commit the step plus new context atomically. State transitions and external side effects must be auditable.

LangGraph may be used inside a single bounded node for judgment loops. It must not own top-level workflow control. Model providers are abstracted behind a versioned configuration; workflows must not hard-code a model identifier.

Revisit Temporal only when a workflow spans more than 24 hours, writes to more than two external systems, or requires retry/compensation logic for the third time. Do not add it pre-emptively.

## Wedge boundary

The first product workflow is vendor compliance verification across COIs, endorsements, W-9s, licences, safety certifications, MSAs, and lien waivers as defined in `11-WEDGE-COMPLIANCE-DOCS.md`. `compliance_status` is point-in-time and append-only. The system may explain observed requirements and escalate exceptions; it must not make an unreviewed legal or work-approval decision.

## Design gate

Before product code begins, the harness feature list must be passing, the MVP cut line must be recorded, and any change to these boundaries must be captured in `DECISIONS.md`. A plausible architecture diagram is not implementation evidence.
