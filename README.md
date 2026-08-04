# AI Operations Deployment Platform — research and build plan

Research completed 2026-08-03. Source: full teardown of deployly.ai (all 6 public pages) plus market research across the deployment-services, agent-platform, IDP, process-intelligence, observability, pricing and regulatory landscapes.

## Current operating phase

This workspace has a **passing F01 foundation, passing W-01 workflow-definition slice, passing R-01 durable runtime, passing E-01 evaluation/release evidence, and an active full-product execution plan**. The research set is complete, the vendor/subcontractor compliance-document wedge and full-time/raise operating mode are selected, and the remaining application is decomposed in [task.md](task.md). Read [AGENTS.md](AGENTS.md) before changing anything.

Run the current harness check with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-harness.ps1
```

Run the real local MVP path with Docker Desktop and PostgreSQL 16:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

Run the durable runtime gate with real Compose/PostgreSQL and browser evidence:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-runtime.ps1
```

Run the passing C-01 connector/MCP/vault gate with real Compose/PostgreSQL and browser evidence:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-connectors.ps1
```

Run the passing P-01 compliance rules and chase gate with real Compose/PostgreSQL evidence:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-compliance.ps1
```

Run the passing Q-01 confidence, threshold, simulator, and sampled-audit gate with real Compose/PostgreSQL evidence:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-confidence.ps1
```

Run the passing E-01 golden-set, publish-block, and drift gate with real Compose/PostgreSQL evidence:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-evaluations.ps1
```

The complete product backlog, reusable workstream prompt, dependencies, and package gates live in [task.md](task.md). F01 is the foundation checkpoint; it is not the whole product.

The current WIP package is `I-01` execution inspection, replay, and observability. E-01 golden sets, evaluation gates, and drift is a passing checkpoint. WIP remains one package at a time.

The harness state lives in [PROGRESS.md](PROGRESS.md), durable reasoning lives in [DECISIONS.md](DECISIONS.md), and executable scope lives in [feature-list.json](feature-list.json).

## Read in this order

| # | File | One line |
|---|---|---|
| 00 | [Executive summary](00-EXEC-SUMMARY.md) | The decisions, and where I disagree with the original research note |
| 01 | [Deployly teardown](01-TEARDOWN-deployly.md) | What they actually sell, verified page by page, and where they're exposed |
| 02 | [Market](02-MARKET.md) | The 2026 landscape with sources; the $14B event that changes the plan |
| 03 | [Strategy and wedge](03-STRATEGY-AND-WEDGE.md) | ICP, positioning, and a scored comparison of eight candidate first workflows |
| 04 | [Product spec](04-PRODUCT-SPEC.md) | Eleven modules, the MVP cut line, screens, user stories |
| 05 | [Architecture](05-ARCHITECTURE.md) | Stack, runtime, full data model, security, ten ADRs |
| 06 | [GTM and pricing](06-GTM-PRICING.md) | Offer ladder, price points, sales motion, objection handling |
| 07 | [Delivery playbook](07-DELIVERY-PLAYBOOK.md) | Discovery script, baseline template, build cadence, SOW skeleton |
| 08 | [90-day roadmap](08-ROADMAP-90-DAY.md) | Week by week, with gates and a day-90 scorecard |
| 09 | [Risk and compliance](09-RISKS-COMPLIANCE.md) | EU AI Act, ISO 42001, SOC 2, contract clauses, risk registers |
| 10 | [Unit economics](10-UNIT-ECONOMICS.md) | Per-document, per-project, per-retainer, year-1 model |
| 11 | [Wedge deep dive](11-WEDGE-COMPLIANCE-DOCS.md) | **Chosen wedge:** vendor/subcontractor compliance documents — market, incumbents, rules library, exception taxonomy, pricing |
| 12 | [Fundraising path](12-FUNDRAISING-PATH.md) | **Read before acting on 06.** How raising changes the offer ladder, margins, timeline and product |

## Decisions made (2026-08-03)

- **Wedge:** vendor & subcontractor compliance documents (COIs, licences, W-9s, lien waivers) — see `11`
- **Operating mode:** full-time, planning to raise — see `12`, which amends `03`, `06`, `08`, `09` and `10`

## The thesis in five sentences

Deployly is a well-marketed implementation boutique whose claimed platform ("Origo") shows no evidence of existing, selling into a segment that OpenAI and Anthropic just attacked with $14B of PE-backed deployment ventures.

The category's real unsolved problem is not building agents — runtimes, connectors and models are all commodities in 2026 — it is that nobody can prove what an AI deployment actually changed, while every survey shows buyers now demanding exactly that proof.

So the product is a **Value Realization Ledger**: baseline the workflow before you touch it, run it through a deterministic engine with bounded model calls, keep a human review desk that captures structured corrections, and emit an auditable, per-run record of what changed and what it cost.

Sell it services-first into mid-market operators under $250M revenue in unglamorous verticals the deployment JVs will never visit, starting with one document-heavy workflow family — **not** invoices, which Ramp, Bill, Tipalti and Rossum have already commoditised.

The compounding asset is the exception taxonomy and golden sets the review desk produces as a byproduct; the exit condition from the services trap is defined in advance — 40% of build effort as configuration and 25% of revenue recurring by month 12, or accept you're an agency and optimise for that instead.
