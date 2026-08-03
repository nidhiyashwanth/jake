# Verification contract

- **Source:** harness-engineering completion-gate guidance plus the product requirements in `04-PRODUCT-SPEC.md`, `05-ARCHITECTURE.md`, and `11-WEDGE-COMPLIANCE-DOCS.md`.
- **Applicability:** harness setup now; all product features once an application runtime exists.
- **Expiry:** update when the test runner, deployment target, or critical user flow changes.

## Current gate: harness only

The application is not implemented, so there is no honest app start, unit-test, integration-test, or E2E command yet. The current executable gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area All
```

A missing runtime command is a recorded gap, not a passing check. Do not create placeholder commands that only print success.

## Three-layer Definition of Done

Every future feature must stop at the first failed layer:

1. **Layer 1 — Static:** parse, lint, typecheck, schema and architecture checks pass.
2. **Layer 2 — Runtime:** the relevant service starts, migrations apply, health checks pass, and focused tests exercise real configuration.
3. **Layer 3 — End-to-end:** the real user path crosses its boundaries and verifies side effects, cleanup, and audit evidence.

Cross-component work requires all three layers. Unit tests are necessary but never sufficient for a feature that crosses storage, workers, connectors, models, review, or UI.

## Critical wedge path

The first meaningful system-level flow is document intake → parse/classify → schema-constrained extraction → rules evaluation → human review/correction → point-in-time compliance status → value ledger and audit export. The E2E check must use representative documents and assert both the decision and its evidence.

## Evidence and failure messages

Each passing feature in `feature-list.json` must contain the exact command and a dated result, commit, or artifact reference. A worker may request verification but may not replace it with confidence or a prose claim.

Failures must identify what failed, where to look, why it matters, and the next repair action. Prefer `POST /... returned 500; check ...` over `test failed`.

## Harness acceptance

The harness baseline is complete only when the Instructions, State, Verification, and All areas of `scripts/verify-harness.ps1` pass; `PROGRESS.md` records those results; and the repository has a clean, recoverable checkpoint.
