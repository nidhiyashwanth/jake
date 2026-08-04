# Durable runtime contract

R-01 is the execution boundary between a published workflow definition and
the side effects it is allowed to produce. The runtime is a PostgreSQL-backed
module of the FastAPI monolith. It does not let a model choose the next node,
write application state, or bypass authorization.

## Invariants

- An execution can reference only a published workflow version in the active
  workspace. The immutable version hash is copied onto the execution and is
  the replay/audit anchor.
- Node order is derived from the published DAG edges. Canonical definition
  storage may sort nodes for hashing, but storage order is never execution
  order.
- Every execution step is durable before it is claimed. Workers claim pending
  steps with PostgreSQL row locks and `SKIP LOCKED`; a stale claim can be
  returned to the queue.
- A workspace-scoped idempotency key returns the original execution when the
  request is identical and is rejected when the workflow version or input
  differs.
- External writes have a durable workspace-scoped receipt keyed by the
  resolved execution/step idempotency key. A duplicate payload is acknowledged
  as duplicate delivery; a different payload is rejected.
- Human approval is a durable state transition. A tool configured as an
  external writer performs its write only when the waiting step is resumed with
  a decision. Compensation metadata is stored with the step for later connector
  policy work.
- Replays pin the original workflow version, run with `dry_run=true`, and
  never create external-write receipts. The replay timeline records that the
  side-effect boundary was disabled.
- Outbox records are written in the same transaction as the state change.
  Dispatch marks a durable handoff as delivered; a future connector package
  owns provider delivery and its failure taxonomy.

## State model

Executions move through `queued`, `running`, `waiting_human`, and one of
`completed`, `halted`, `failed`, or `dead_letter`. `replayed` is reserved for a
dry-run replay that reaches completion. Steps separately record pending,
claimed, running, waiting-human, completed, failed, dead-letter, or skipped
states. A worker crash does not erase the execution or its timeline.

## HTTP surface

The protected routes live under `/api/runtime`:

- `POST /executions` creates an idempotent run against a published version.
- `GET /executions` and `GET /executions/{id}` provide scoped list/detail and
  timeline evidence.
- `POST /executions/{id}/advance` runs bounded deterministic steps.
- `POST /executions/{id}/retry` manually requeues a failed/waiting step.
- `POST /executions/{id}/resume` records a human decision.
- `POST /executions/{id}/replay` creates a safe dry-run replay.
- `POST /workers/recover` recovers stale claims.
- `POST /outbox/dispatch` claims and records outbox handoffs.

All protected requests require the bearer session and active workspace
context. Responses include `X-Correlation-ID` on execution mutations.

## Verification

Run the focused gate from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-runtime.ps1
```

The gate starts an isolated Compose project using the ignored `.env`, applies
the PostgreSQL migration, checks HTTP behavior and database-backed invariants,
runs the browser smoke, and cleans only that project while preserving the
named PostgreSQL volume. Run it sequentially with other Compose verifiers
because the repository intentionally uses one explicit named volume under the
32 GB storage guard.
