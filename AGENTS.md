# AI Operations Deployment Platform

This workspace contains the research, product plan, and the runnable foundation of the AI Operations Deployment Platform. The chosen first wedge is vendor and subcontractor compliance-document verification with proof. F01 is the passing foundation; the complete product is tracked and executed through `task.md`.

## Current phase

The harness baseline, F01 foundation, T-01 tenancy, D-01 discovery, W-01 workflow-definition slice, R-01 durable runtime, V-01 review desk, C-01 connectors/MCP/vault, P-01 rules/requirements/document taxonomy/chase, Q-01 confidence/routing/thresholds/sampled audit, E-01 golden-set evaluation/release evidence, and I-01 execution inspection/replay/observability are passing. The full documented product build is active: `L-01` is the current WIP item, and every subsequent package must be selected from `task.md` one at a time. The numbered research documents are the product and market source material. `PROGRESS.md`, `DECISIONS.md`, `feature-list.json`, and `task.md` are the operational source of truth for agent work.

## Start here

1. Read `PROGRESS.md` and identify the one active feature, if any.
2. Read `DECISIONS.md` before revisiting an architectural or product choice.
3. Read `task.md` and work only on its single active package and its dependencies.
4. Read the relevant numbered research document only after the routing map below points to it.
5. Run the harness check before making changes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1
```

## Run it

Run the full local path, including Compose startup, PostgreSQL migrations, API flow, review correction, historical status, ledger evidence, and cleanup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

To leave the services running for manual review, use `-KeepRunning`; stop that exact Compose project with:

```powershell
docker compose --project-name ai-ops-platform-mvp --env-file .env --file docker-compose.yml down --remove-orphans
```

## Verify it

The current Definition of Done is the three harness checks passing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area Instructions
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area State
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area Verification
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area All
```

Future product work must add and pass static, runtime, and end-to-end checks before a feature can be marked `passing`. See `docs/VERIFICATION.md`.

The current F01 product gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

The current W-01 workflow-definition gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-workflows.ps1
```

The current R-01 durable-runtime gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-runtime.ps1
```

The current C-01 connector/MCP/vault gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-connectors.ps1
```

The current P-01 compliance rules and chase gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-compliance.ps1
```

The current Q-01 confidence, threshold, simulator, and sampled-audit gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-confidence.ps1
```

The current E-01 golden-set, publish-block, canary, and drift gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-evaluations.ps1
```

The current I-01 execution inspector, replay, redaction, trace, and degraded-mode gate is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-inspector.ps1
```

The complete-product gate is the task board plus the relevant package checks. Do not mark a package passing until its row in `task.md`, its row in `feature-list.json`, and its executable evidence agree.

The final release gate refuses to pass while any required package is open:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-product.ps1
```

## Hard constraints

1. Finish the harness gate before starting each new product feature.
2. Work on exactly one feature at a time; WIP is 1.
3. Only the verifier may justify a transition to `passing`; attach command evidence.
4. Do not refactor, optimize, or restyle before the current behavior passes its functional checks.
5. Keep one canonical home for each durable fact; link to it instead of duplicating it.
6. Treat the numbered research files as dated source material; preserve claims and cite new evidence when changing them.
7. Use the modular-monolith boundaries in `docs/ARCHITECTURE-RULES.md`; do not introduce microservices or infrastructure without a recorded decision.
8. Keep domain dependencies behind explicit interfaces and preserve ownership of execution and ledger writes.
9. Never hard-code credentials, provider secrets, or customer data into the repository.
10. Use bounded model calls inside deterministic workflow control; models do not own top-level orchestration.
11. Require end-to-end verification for work crossing domain, worker, storage, connector, or UI boundaries.
12. Do not claim an application command, test, deployment, or performance result until it has run in this workspace.
13. Update `task.md`, `PROGRESS.md`, and record new durable choices in `DECISIONS.md` at clock-out.

## Working agreement

- Scope and state live in `feature-list.json`; do not maintain a competing task list in chat or a long instruction file.
- Detailed product scope, dependencies, workstream prompt, and package Definition of Done live in `task.md`.
- Session continuity lives in `PROGRESS.md`; the next action must be concrete and executable.
- The architecture baseline is `05-ARCHITECTURE.md`, refined by `docs/ARCHITECTURE-RULES.md`.
- The current verification contract is `docs/VERIFICATION.md` and `scripts/verify-harness.ps1`.
- Keep commits atomic. After the initial baseline is published, use a feature branch for product work and leave merge decisions to the owner.

## Routing map

- Project map and current phase → `README.md`, `PROGRESS.md`
- Product scope and MVP cut line → `04-PRODUCT-SPEC.md`, `11-WEDGE-COMPLIANCE-DOCS.md`
- Active MVP contract and API boundary → `docs/MVP-CONTRACT.md`
- Local Docker/WSL/PostgreSQL setup → `docs/LOCAL-ENVIRONMENT.md`
- ICP, positioning, and wedge choice → `03-STRATEGY-AND-WEDGE.md`, `11-WEDGE-COMPLIANCE-DOCS.md`
- Runtime, data model, security, and ADRs → `05-ARCHITECTURE.md`, `docs/ARCHITECTURE-RULES.md`
- Delivery and customer workflow → `07-DELIVERY-PLAYBOOK.md`
- Roadmap and gates → `08-ROADMAP-90-DAY.md`
- Risk, compliance, and contracts → `09-RISKS-COMPLIANCE.md`
- Pricing, economics, and fundraising → `06-GTM-PRICING.md`, `10-UNIT-ECONOMICS.md`, `12-FUNDRAISING-PATH.md`
- Verification and completion gates → `docs/VERIFICATION.md`
- Complete product execution backlog → `task.md`
- Clock-in, clock-out, and handoff → `docs/WORKFLOW.md`

## Clean exit

Before ending a session, run the verifier, update `task.md`/state/evidence, remove temporary artifacts without deleting `.env`, and leave one clear next action. A session is not complete merely because files were edited.
