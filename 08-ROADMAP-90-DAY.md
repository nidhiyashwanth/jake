# 90-day roadmap

Assumption: 1–2 people, full-time, bootstrapped. If you're part-time, double everything and cut §4 entirely.

**The organising principle: sell before you build, and build only what the sale demands.** The failure mode for a technical founder here is nine months of platform followed by zero customers. The counter-discipline is that every week has both a sales action and a build action, and the sales action goes first.

---

## Phase 0 — Week 0 (this week)

- [ ] Answer the four decisions in `00-EXEC-SUMMARY §7` (capital, vertical, services appetite, geography)
- [ ] Choose the wedge using the matrix in `03` **run against your own network**, not in the abstract
- [ ] List 20 target accounts and 40 named contacts with a trigger event each
- [ ] Register the entity, domain, business email, and a one-page site (positioning + ROI calculator + contact). One page is enough. Deployly has six and only two do work.
- [ ] Set up the repo, CI, and `docs/adr/` with ADR-001..010 from `05 §8`
- [ ] Write the discovery interview script into a form you can screen-share

---

## Phase 1 — Weeks 1–4: prove there's a buyer

**Sales (the priority)**
- Week 1: 40 outbound touches on trigger events. Target 4 teardown calls.
- Week 2: run teardowns. Deliver the artifact within 24h every time. Target 4 more booked.
- Week 3: 8 teardowns total; ask for the Proof Sprint on every one where a named owner exists.
- Week 4: **close 2 Proof Sprints.** If you have zero after 8 teardowns, stop building and diagnose — wrong vertical, wrong workflow, or wrong buyer. That signal is worth more than a month of code.

**Build (the minimum that makes the teardown and sprint possible)**
- Week 1: repo skeleton, auth, orgs/workspaces/RLS, artifacts + S3, audit log
- Week 2: discovery module — interview capture, workflow graph (read-only React Flow), baseline capture with signature, opportunity scoring with visible inputs. **This is the sales tool. It pays for itself immediately.**
- Week 3: ingestion (email + upload), parse, classify, extract with schema-constrained output, executions/execution_steps state machine
- Week 4: rules engine + confidence scoring + threshold simulator over a static historical set

**Week 4 gate:** can you take 100 of a prospect's real documents and produce an accuracy report and a threshold curve in under a day? If yes, the Proof Sprint is a product, not a heroic effort.

---

## Phase 2 — Weeks 5–8: deliver the Proof Sprints, build the desk

**Delivery**
- Run both Proof Sprints (2 weeks each, overlapping). Real documents, real accuracy numbers, real proposals.
- Publish the anonymised teardown write-ups as content.

**Build**
- Weeks 5–7: **Review Desk.** Three full weeks. Provenance highlighting, keyboard-first, reason codes, queue management, bulk actions with caps. Do not compromise here — this is the demo that closes and the instrument that builds your moat.
- Week 8: corrections → golden sets → eval runs → publish gate. Close the improvement loop before you have customers depending on it.

**Week 8 gate:** ≥1 Production Build signed. Target 2.

---

## Phase 3 — Weeks 9–13: first production deployment

**Delivery**
- Run the 6–8 week build cadence from `07 §3` on customer #1. Weekly demos, non-negotiable.
- Shadow mode in week 5 of the engagement.

**Build (driven by the engagement, not by a wishlist)**
- Connectors the customer actually needs: Microsoft Graph or Gmail, SharePoint/Drive, Slack/Teams notify, generic REST
- MCP gateway + credential vault
- Value Realization Ledger: value_events, rollups, the CFO dashboard, CSV/PDF export
- Run inspector + Langfuse self-hosted
- Sampled audit loop
- Audit pack export

**Week 13 gate:** one customer in production, ledger live, first monthly value report delivered, and a written reference quote in hand.

---

## Day 90 scorecard

| Metric | Target | Minimum acceptable |
|---|---|---|
| Teardown calls run | 16 | 10 |
| Proof Sprints sold | 4 | 2 |
| Production Builds signed | 2 | 1 |
| Cash collected | $110k | $55k |
| Customers in production | 1 | 1 |
| Straight-through rate achieved | ≥60% | ≥45% |
| Golden set size (wedge workflow) | 300 cases | 100 |
| Reason codes in taxonomy | 40 | 20 |
| Reusable platform % of build #2 effort | 40% | 25% |

If you hit the minimum column, you have a business. If you miss on **teardowns and sprints** but hit the build targets, you have a hobby — change the sales approach, not the code.

---

## Months 4–6

- Customers 2 and 3, same vertical, same workflow family. **Resist the temptation to take a different workflow for a bigger cheque** — the second and third instance of the *same* workflow is where the platform leverage is proven or disproven.
- Measure build #3's config-vs-code ratio. Target ≥40% configuration.
- Convert customer 1 to Run & Improve. This is the moment the business model changes.
- Publish the vertical benchmark report with real data from three deployments.
- Start SOC 2 Type I readiness (Vanta/Drata class tooling; ~$8–15k/yr + effort). You will hit the first security questionnaire around customer 3.
- Hire decision point: first hire is a **forward-deployed engineer** who can run discovery *and* build, not a salesperson and not a backend specialist.

## Months 7–12

- Customers 4–8. Raise prices 20% after customer 3 and again after customer 6.
- Temporal migration if the triggers in `05 §1` have fired.
- Second workflow family (the other wedge from `03`) — reusing 60%+ of the platform.
- SOC 2 Type II. ISO 42001 gap assessment if you're selling into PE-owned or EU-exposed accounts.
- **Month 9 decision: Layer 3a (vertical product) vs 3b (platform for implementers).** Decide on evidence: if ≥40% of build effort is configuration and ≥25% of revenue is recurring, go 3a. If other agencies have been asking to use your tooling (they will, once you publish the benchmark), evaluate 3b.
- Target run-rate by month 12: **$600k–$900k**, of which $150–250k recurring.

---

## What to explicitly NOT do in the first 90 days

- Build a drag-and-drop workflow canvas
- Build a trace viewer
- Build billing, self-serve signup, or a pricing page with tiers
- Build more than four connectors
- Take a customer outside your chosen vertical because the cheque is big (this is the single most common way this business dies — you become a generic agency with a half-built platform)
- Raise money (you have nothing to raise on yet, and this business is fundable at month 12 on ledger data in a way it is not fundable today)
- Write the marketing site before you've run 8 teardowns — you don't know the words yet
- Hire
