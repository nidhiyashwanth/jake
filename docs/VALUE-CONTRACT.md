# L-01 Value Realization Contract

L-01 is the read-only sponsor and CFO evidence surface over the execution runtime. It does not create a second execution ledger or allow a browser to claim savings. Server-owned code appends one idempotent `value_event` per measured outcome or cost, and the database rejects updates and deletes.

## Event contract

Each event is workspace-scoped and carries:

- an immutable event key and source artifact;
- execution, immutable workflow-version hash, and signed baseline/hash references when the run has them;
- `kind`, quantity, unit, dollar value, valuation method, confidence, formula version, metadata, and timestamps;
- links back to the execution, review task, and audit event where applicable.

The event kinds are `unit_processed`, `touch_avoided`, `time_saved`, `error_prevented`, `cycle_time_reduced`, `human_touch_cost`, `model_cost`, `infra_cost`, and `rework`. A missing baseline or rate produces count-only/unpriced evidence; it never invents a dollar amount.

## Rollup contract

The dashboard and API calculate from the same event rows. The reconciliation invariant is:

```text
auto + reviewed + halted = ingested
```

The rollup reports straight-through and review rates, measured error only when sampled evidence exists, cycle time versus the signed baseline, hours saved, gross benefit, costs, net dollars, cost per completed unit, ROI, payback, adoption, event count, and orphan-event count. `value.v1` is the canonical formula identifier.

Every headline metric has a drill-down route under `/api/value/drilldown`; the event rows expose source links. CSV and PDF packs include the reconciliation status and baseline hash before event detail.

## Authorization and export

All workspace roles can read the dashboard according to the existing workspace context. Owner, admin, and auditor roles can export. Export actions append an audit log and a data-access log. Raw secret-like fields and PII-shaped metadata are redacted before persistence or response.

## Verification

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-value-ledger.ps1
```

The gate exercises PostgreSQL migrations/RLS and the immutable trigger, creates a signed baseline, publishes auto and reviewed workflows, generates real execution events, proves parity and drill-down, rejects a signed-baseline mutation, validates CSV and PDF output, and runs the authenticated browser smoke.
