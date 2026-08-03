# Executive Summary — What to build, and what changed since your research note

Date: 2026-08-03
Status: research complete; the high-level wedge and operating mode are recorded in the README. Founder-specific execution decisions remain open (see §7).

---

## 1. What I verified about Deployly

I read every public page on deployly.ai (`/`, `/point-builds/`, `/full-deployment/`, `/private-equity/`, `/report/`, `/careers/`). Your note was substantially correct. Three corrections and one big addition:

**Correction 1 — Origo is thinner than your note assumes.**
"Origo" appears on the homepage only. It is absent from `/full-deployment/`, `/private-equity/`, `/careers/`, and the Q3 2026 report. A company with a real platform mentions it in the job specs. The two open roles ("AI Engineer", "Product Engineer") describe *client* work: "Build and deploy production AI features across client products", "Partner with clients to translate problems into features." There is no platform-engineering role. Origo is most likely a small internal toolkit plus a naming device that makes a services business sound like a software business. **Do not build against your imagination of Origo. There is a real gap there you can occupy.**

**Correction 2 — their strongest asset is not the platform, it is the report.**
`/report/` is a genuinely good piece of demand generation: the AI Value Realization Report, Q3 2026, synthesising PwC (n=4,454), MIT NANDA, BCG (n=1,800), McKinsey, S&P Global, Grant Thornton (n=950), Bain. Its argument — "stop counting pilots, start counting workflows in production with measured results" — *is* the sales pitch. The services are the product; the report is the funnel. This is copyable and you should copy the mechanism, not the content.

**Correction 3 — they are a very small team.** "A small team shipping AI systems to production quickly", NYC + remote-first, two open roles, ex-Google/Microsoft/Bain/Meta credibility logos. The case studies (15-company PE portfolio, 40-location healthcare operator, 60-person Series C) are consistent with 5–15 people. This is reachable. It is not a moat you need $10M to attack.

**Addition — the market moved under them in May 2026, and this is the single most important fact in this document.**
On 4 May 2026, OpenAI finalised **The Deployment Company**, a $10B JV with $4B raised from 19 PE firms (TPG, Brookfield, Bain Capital, Advent, Dragoneer, SoftBank), with OpenAI guaranteeing backers a 17.5% annual return for five years in exchange for their portfolio companies becoming a captive customer base. Anthropic announced a parallel venture the same day with Blackstone, Hellman & Friedman and Goldman Sachs ($1.5B committed).

Deployly's own report cites this as validation of their thesis. It is also an extinction-level event for their PE-portfolio wedge. **The exact motion Deployly sells — "we deploy AI across your PE portfolio" — is now being run by the two model vendors with $14B and direct LP relationships.** Do not build your business on that hill. Build where those JVs structurally will not go: sub-$250M-revenue operating companies, unglamorous verticals, and workflows where the hard part is domain exception handling rather than model access.

---

## 2. The core insight to build on

Every serious source now says the same thing, and none of them ship a product for it:

- 95% of GenAI pilots showed zero P&L impact (MIT NANDA, 2025)
- 56% of CEOs report no revenue increase or cost reduction (PwC, Jan 2026)
- 42% of companies abandoned most AI projects in 2025 (S&P Global)
- <20% of pilots reach enterprise scale (McKinsey)
- 9% of PE firms are confident they could pass an AI audit within 90 days (Grant Thornton, n=950)
- Fewer than 1 in 10 enterprises can point to a deployment with measurable, sustained value

The bottleneck is not the model, not the agent framework, and not the connectors — all three are commodities in 2026. The bottleneck is that **nobody can prove what an AI deployment actually did**, and boards have started asking.

That gap is your product. Not "build an agent." Not "map a workflow." The thing that does not exist is:

> **A system of record for AI work: baseline the workflow before you touch it, run the work through a governed engine, keep a human in the loop where it matters, and emit an auditable ledger of what changed — per run, per exception, per dollar.**

Call it the **Value Realization Ledger**. It is the piece Deployly argues for in its report and does not sell. It is the piece Ramp, Rossum, n8n and Copilot Studio will never build, because proving your own product's marginal value is against their interest. And it is the piece a CFO, a PE operating partner, and an internal AI lead all need in order to keep their job.

Everything else in the platform — the workflow engine, the review queue, the connectors — is table stakes you need in order to be *allowed* to own the ledger.

---

## 3. What I recommend you build (three layers, in this order)

**Layer 1 — the delivery business (months 0–6).**
You are a boutique AI implementation firm with a fixed-fee, evidence-backed offer. This funds everything, sources your workflow data, and forces the platform to be real. See `06-GTM-PRICING.md` and `07-DELIVERY-PLAYBOOK.md`.

**Layer 2 — the internal platform (months 0–9, built while delivering).**
The thing that makes build #3 take 40% of the time build #1 took. Workflow engine + review desk + connectors + evidence ledger. See `04-PRODUCT-SPEC.md` and `05-ARCHITECTURE.md`.

**Layer 3 — the product (months 9–18).**
Two possible exits from the services trap, decided by evidence you will have by then:
- **3a. Vertical product** — one workflow family, sold as a subscription with a per-run/outcome component, to the segment where you have 5 references.
- **3b. Picks and shovels** — license the delivery platform to other implementation firms. The OpenAI/Anthropic JVs are about to certify thousands of partner shops who will all need exactly this and cannot build it.

Do not decide 3a vs 3b now. Decide it in month 9 with revenue data.

---

## 4. Where I disagree with your research note

| Your note | My position | Why |
|---|---|---|
| MVP wedge = invoice intake / AP | **No.** Pick a different first workflow. | AP is the single most contested surface in the market. Ramp hit a $44B valuation in June 2026 shipping four named AP agents (auto-coding, fraud, approval routing, payment optimisation) plus AI receipt chasers. Bill, Tipalti, Rossum ($18k/yr entry), Esker, and every ERP are in the same lane. You will be a worse invoice product at a higher price. |
| "Build the software layer that could make a company like Deployly operate" | Right instinct, wrong sequence | If you build a delivery platform before you have delivered anything, you will build the wrong abstractions. Deliver 3 projects manually-ish, then extract the platform from what actually repeated. |
| Temporal vs custom state machine "consider Temporal" | **Use Temporal, but not on day 1** | Postgres-backed state machine for the first two builds; migrate to Temporal when you have a workflow that spans >24h or >2 external systems. Temporal's own LangGraph plugin now exists and OpenAI runs Temporal for Codex, so the migration path is well-trodden and not urgent. |
| Build a connector framework (Gmail, Drive, Slack, REST, webhook, Postgres, CSV) | **Build an MCP gateway instead, plus 2 first-party connectors** | MCP is now a Linux Foundation project (Agentic AI Foundation, donated Dec 2025), ~97M SDK downloads/month, 10,000+ public servers, and the Enterprise-Managed Authorization extension went stable in 2026 with Anthropic/Microsoft/Okta adoption. Writing your own Slack connector in 2026 is burning weeks on a solved problem. |
| Build execution observability | **Buy/self-host it** | Langfuse self-hosted (OTel-native) or Braintrust. Your differentiation is *business* outcome measurement, not span storage. Spending three weeks on a trace viewer is three weeks not spent on the ledger. |
| Positioning: "AI workflow implementation platform for agencies, consultants, internal teams" | Too early, and three ICPs is zero ICPs | That is the month-18 product. Month-0 you have one ICP and one workflow family, or you have nothing. |

---

## 5. Where your note is right and I would not change it

- Deterministic engine around bounded LLM calls, not an LLM driving the whole process. Correct and increasingly the consensus.
- Human review queue as a first-class product surface, with corrections feeding evaluation data. This is the highest-leverage thing in the whole system.
- The separation of `workflow` / `workflow_version` / `execution` / `execution_step`. Keep it. Add `baseline_version` to that list.
- Services-led go-to-market, not self-serve SaaS at launch. Correct.
- Your existing assets (LangGraph lifecycle handling, state/history APIs, cancellation, cost tracking, MCP integrations, auth/scopes, audit logs, streaming UI) are genuinely most of the runtime. Reuse them aggressively.

---

## 6. The document set

| File | What it is | Read it when |
|---|---|---|
| `01-TEARDOWN-deployly.md` | Everything verifiable about Deployly, page by page | Now |
| `02-MARKET.md` | Competitive landscape, 2026 facts, where the white space is | Now |
| `03-STRATEGY-AND-WEDGE.md` | ICP selection, wedge scoring matrix, positioning | Before you talk to anyone |
| `04-PRODUCT-SPEC.md` | Modules, screens, user stories, MVP cut line | Before you write code |
| `05-ARCHITECTURE.md` | Stack, data model, runtime design, ADRs | Before you write code |
| `06-GTM-PRICING.md` | Offers, price points, sales motion, outbound assets | Week 1 |
| `07-DELIVERY-PLAYBOOK.md` | Discovery script, ROI model, SOW skeleton, build cadence | First customer call |
| `08-ROADMAP-90-DAY.md` | Week-by-week, what to do Monday | Monday |
| `09-RISKS-COMPLIANCE.md` | EU AI Act, ISO 42001, SOC 2, contracts, insurance, failure modes | Before first contract |
| `10-UNIT-ECONOMICS.md` | Capacity math, margins, cash plan, the numbers that decide viability | This week |

---

## 7. Decisions only you can make

1. **Capital and time.** Solo/nights-and-weekends, full-time bootstrapped, or raising? This changes the roadmap more than any technical choice. `08` and `10` assume *full-time, bootstrapped, 1–2 people*.
2. **Vertical access.** Which industry can you get five conversations in this month through people who already know you? The wedge should be chosen partly by your network, not purely by market attractiveness. `03` gives you a scoring matrix to run against your own list.
3. **Services appetite.** Are you willing to sit in workshops with an operations manager for six weeks? If not, the whole model changes and you should go straight at 3b (picks and shovels) with a much longer runway.
4. **Geography.** US mid-market (Deployly's field) vs India/EU. Affects pricing by 3–5x and compliance posture materially.

Answer those four and the roadmap in `08` becomes specific rather than generic.
