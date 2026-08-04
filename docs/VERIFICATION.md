# Verification contract

- **Source:** harness-engineering completion-gate guidance plus the product requirements in `04-PRODUCT-SPEC.md`, `05-ARCHITECTURE.md`, and `11-WEDGE-COMPLIANCE-DOCS.md`.
- **Applicability:** harness maintenance and all product work packages in `task.md`, including the passing F01 foundation.
- **Expiry:** update when the test runner, deployment target, or critical user flow changes.

## Current gates

The harness gate remains required for every session:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area All
```

The passing F01 product gate is the real Docker/PostgreSQL path:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

The complete-product gate is package-specific: `task.md`, `feature-list.json`, and the package's static/runtime/E2E/security evidence must agree before the package can move to `passing`.

A missing runtime command is a recorded gap, not a passing check. Do not create placeholder commands that only print success. F01's runtime and end-to-end command now exists and has passed; future features must add equivalent evidence.

R-01's focused gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-runtime.ps1
```

It must pass static contract checks, real Compose/PostgreSQL HTTP checks, and
the authenticated browser smoke. The R-01 backend integration test is marked
`integration` and requires a reachable PostgreSQL `DATABASE_URL`; the focused
Compose gate remains the required evidence when the local test runner is not
configured with that connection.

L-01's focused gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-value-ledger.ps1
```

It must pass the static contract, pure reconciliation tests, real Compose/PostgreSQL
HTTP path, signed-baseline/hash provenance, dashboard/event parity, CFO drill-down,
CSV/PDF render checks, signed-baseline mutation fence, and authenticated browser smoke.

G-01's focused gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-governance.ps1
```

It must pass the static contract, pure governance tests, real Compose/PostgreSQL
HTTP path, authenticated browser smoke, PII field-path classification, redaction,
retention dry-run and source deletion, legal-hold skip/release, model no-training
history, incident lifecycle, export access logging, audit-pack completeness, and
database append-only mutation fences. The durable contract is documented in
`docs/GOVERNANCE.md`.

## Three-layer Definition of Done

Every future feature must stop at the first failed layer:

1. **Layer 1 — Static:** parse, lint, typecheck, schema and architecture checks pass.
2. **Layer 2 — Runtime:** the relevant service starts, migrations apply, health checks pass, and focused tests exercise real configuration.
3. **Layer 3 — End-to-end:** the real user path crosses its boundaries and verifies side effects, cleanup, and audit evidence.

Cross-component work requires all three layers. Unit tests are necessary but never sufficient for a feature that crosses storage, workers, connectors, models, review, or UI.

For durable runtime work, the layer-specific contract is:

1. Static: Python compilation, runtime contract markers, migration/table
   markers, worker wiring, frontend typecheck/tests/build, and secret hygiene.
2. Runtime: PostgreSQL migration `0009_runtime`, healthy backend/worker, row
   lock claim path, retry/recovery seams, and transactional outbox tables.
3. End-to-end: pinned published version, graph order, idempotent execution,
   human wait/resume, one external-write receipt, safe replay, outbox dispatch,
   RBAC, workspace isolation, and browser request scoping.

## Critical wedge path

The first meaningful system-level flow is document intake → parse/classify → schema-constrained extraction → rules evaluation → human review/correction → point-in-time compliance status → value ledger and audit export. The E2E check must use representative documents and assert both the decision and its evidence.

## Evidence and failure messages

Each passing feature in `feature-list.json` must contain the exact command and a dated result, commit, or artifact reference. A worker may request verification but may not replace it with confidence or a prose claim.

Failures must identify what failed, where to look, why it matters, and the next repair action. Prefer `POST /... returned 500; check ...` over `test failed`.

## Harness acceptance

The harness baseline is complete only when the Instructions, State, Verification, and All areas of `scripts/verify-harness.ps1` pass; `PROGRESS.md` records those results; and the repository has a clean, recoverable checkpoint. F01 additionally requires `scripts/verify-mvp.ps1` to pass against the real Compose services.
