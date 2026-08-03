# AI Operations Deployment Platform

This workspace contains the research, product plan, and future implementation contract for an AI operations deployment platform. The chosen first wedge is vendor and subcontractor compliance-document verification with proof; product code is intentionally not started until the harness baseline passes.

## Current phase

We are setting up the harness before building the application. The numbered research documents are the product and market source material. `PROGRESS.md`, `DECISIONS.md`, and `feature-list.json` are the operational source of truth for agent work.

## Start here

1. Read `PROGRESS.md` and identify the one active feature, if any.
2. Read `DECISIONS.md` before revisiting an architectural or product choice.
3. Read the relevant numbered research document only after the routing map below points to it.
4. Run the harness check before making changes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1
```

## Run it

The application runtime does not exist yet. Do not invent a start command or claim runtime readiness. The current runnable surface is the harness verifier above.

## Verify it

The current Definition of Done is the three harness checks passing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area Instructions
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area State
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area Verification
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1 -Area All
```

Future product work must add and pass static, runtime, and end-to-end checks before a feature can be marked `passing`. See `docs/VERIFICATION.md`.

## Hard constraints

1. Finish the harness gate before implementing product code.
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
13. Update `PROGRESS.md` and record new durable choices in `DECISIONS.md` at clock-out.

## Working agreement

- Scope and state live in `feature-list.json`; do not maintain a competing task list in chat or a long instruction file.
- Session continuity lives in `PROGRESS.md`; the next action must be concrete and executable.
- The architecture baseline is `05-ARCHITECTURE.md`, refined by `docs/ARCHITECTURE-RULES.md`.
- The current verification contract is `docs/VERIFICATION.md` and `scripts/verify-harness.ps1`.
- Keep commits atomic. After the initial baseline is published, use a feature branch for product work and leave merge decisions to the owner.

## Routing map

- Project map and current phase → `README.md`, `PROGRESS.md`
- Product scope and MVP cut line → `04-PRODUCT-SPEC.md`, `11-WEDGE-COMPLIANCE-DOCS.md`
- ICP, positioning, and wedge choice → `03-STRATEGY-AND-WEDGE.md`, `11-WEDGE-COMPLIANCE-DOCS.md`
- Runtime, data model, security, and ADRs → `05-ARCHITECTURE.md`, `docs/ARCHITECTURE-RULES.md`
- Delivery and customer workflow → `07-DELIVERY-PLAYBOOK.md`
- Roadmap and gates → `08-ROADMAP-90-DAY.md`
- Risk, compliance, and contracts → `09-RISKS-COMPLIANCE.md`
- Pricing, economics, and fundraising → `06-GTM-PRICING.md`, `10-UNIT-ECONOMICS.md`, `12-FUNDRAISING-PATH.md`
- Verification and completion gates → `docs/VERIFICATION.md`
- Clock-in, clock-out, and handoff → `docs/WORKFLOW.md`

## Clean exit

Before ending a session, run the verifier, update state and evidence, remove temporary artifacts, and leave one clear next action. A session is not complete merely because files were edited.
