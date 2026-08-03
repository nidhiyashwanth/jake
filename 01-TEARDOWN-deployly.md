# Teardown: deployly.ai

Fetched 2026-08-03. Everything below is from the live site unless marked **[inference]**.

---

## Site map

| Path | Purpose |
|---|---|
| `/` | Homepage — positioning, 3-step process, case studies, industries, contact form |
| `/point-builds/` | Fixed-fee single-workflow offer |
| `/full-deployment/` | 12-month transformation program |
| `/private-equity/` | Portfolio-scale offer for PE funds |
| `/report/` | AI Value Realization Report, Q3 2026 — thought leadership / demand gen |
| `/careers/` | 2 open roles |
| `/terms/`, `/privacy/` | Legal |
| `#cases`, `#industries`, `#contact` | Homepage anchors |

Footer: © 2026 DEPLOYLY AI INC. NEW YORK · REMOTE-FIRST

Notably absent: no `/origo/`, no product docs, no pricing page, no login, no blog beyond the report, no customer logos (only ex-employer logos), no team page.

---

## Positioning

- Headline: **"AI transformation for the real economy."**
- Sub: **"At factory speed."**
- Frame: *"There are two kinds of service businesses now: those being transformed around AI, and those being replaced by it. We do the transformation."*
- Core claim: deep operating expertise + proprietary platform **Origo** → "turn messy operational problems into intelligent workflows that drive measurable impact."
- Anti-pitch: *"The hard part of AI was never the model. It's the messy stuff around it: competing priorities, teams that have been burned by a failed pilot before, and the change management nobody budgets for."*

**Why this works:** it disqualifies the model vendors and the tool vendors in one sentence, and it names the buyer's actual scar tissue (a failed pilot). It sells to a CEO, not to an engineer.

**Three-step process:** 01 Map the work (Origo used here) → 02 Build the AI operating system (production, integrated, not pilots) → 03 We own the rollout (training, change management, feedback loops).

**Three reasons-to-believe:** operating backbone not another tool; weeks not months (Origo); change management included.

---

## Offer 1 — Point Builds (`/point-builds/`)

For teams who "already know what they want — an invoice agent, an RFP responder, a support copilot." Explicit anti-consulting framing: **"No retainer, no strategy tax, no slide decks."**

**6–10 weeks, three stages:**

| Stage | Timing | Content |
|---|---|---|
| 01 Validate | Week 1 | Confirm use case viability, data availability, baseline metrics. Deliverables: build plan, fixed scope, pricing. |
| 02 Build | Weeks 2–8 | Senior builder embeds with the workflow owner. Weekly demos on real data. Pilot users onboarded by week 5. |
| 03 Ship & Handoff | Weeks 9–10 | Production deploy, monitoring, documentation, 30-day post-launch check-in. Client owns it after. |

**Use case library (5 domains, with stated durations):**
- Back office & finance — invoice extraction, expense triage, vendor onboarding (4–6 wks)
- Customer support — tier-1 deflection, agent assist, ticket routing (4–8 wks)
- Sales & revenue ops — RFP response drafting, account research, CRM data capture (4–8 wks)
- Internal ops — enterprise search, IT helpdesk, HR self-service (5–8 wks)
- Engineering & product — PR review automation, doc generation, code copilots (4–10 wks)

**Published benchmark numbers:** ~70% touch reduction (invoice), ~80% auto-approval (expense), ~40% deflection (tier-1 support), ~30% AHT improvement (agent assist).

**Pricing:** "fixed fee, no retainer." One disclosed number: **$185K** for a specialty distributor's knowledge-grounded tier-1 reply agent, which cut average handle time 34% in month one.

**[inference]** $185K over 6–10 weeks with one embedded senior builder implies a blended rate around $3.5–5k/day. That is Bain-adjacent pricing for what is, technically, a RAG support assistant. The premium is being charged for certainty and change management, not for code. **This is the most important commercial fact on the whole site.**

---

## Offer 2 — Full Deployment (`/full-deployment/`)

12 months, four phases:

1. **Assess (wks 1–4)** — diagnostic across functions: AI readiness, workflow friction, data infrastructure, leadership appetite
2. **Prioritize (wks 3–6)** — ranked use-case backlog with impact sizing; governance framework established *before* coding
3. **Build & Pilot (months 2–6)** — 2–3 Wave 1 use cases to production, live pilots, baseline metrics, iteration
4. **Roll out & Operate (months 6–12+)** — change management, org-wide training, champion network, Wave 2 in parallel

**Deliverables:** 3–5 production builds by month 12; trained operators + champion network; functioning governance framework and operating model; measured P&L impact against baseline.

**Governance content:** usage policy, data handling, model selection, vendor approval.
**Change content:** role-based training tracks, shared prompt libraries and pattern catalogs, internal champion program, stakeholder mapping and comms plan.

No pricing, no team composition, no FAQ, **no mention of Origo**.

**[inference]** At 3–5 builds/year plus a change program, this is a $600k–$1.5M/yr engagement. Sold to the CEO or PE operating partner, not to IT.

---

## Offer 3 — Private Equity (`/private-equity/`)

Framing: *"10 or 20 companies, each at a different stage of AI readiness, all with pressure to show P&L impact."*

- Weeks 1–4: diagnostic across every portco on five dimensions — current AI adoption, data infrastructure readiness, workflow friction, leadership appetite, value pathways → prioritised roadmap of who goes first
- Months 1–4: Wave 1 at 2–3 high-readiness companies → standardised playbooks
- Later waves reuse shared governance, standardised tooling, trained champions
- Governance framework by month 2; developer productivity programs deployed within 90 days
- 12-month portfolio program

No pricing, no metrics, **no mention of Origo**.

**[inference]** This is the highest-leverage sale on the site — one relationship, 10–20 deployments — and it is exactly the segment OpenAI's Deployment Company and the Anthropic/Blackstone JV were built to take. See `02-MARKET.md §2`.

---

## Case studies (homepage)

| # | Client shape | Outcomes claimed |
|---|---|---|
| 1 | PE portfolio, 15-company vertical SaaS | 6 workflow categories automated; 68% reduction in manual processing; Wave 2 portcos 40% faster to production; FTE redeployed across 9 companies |
| 2 | Healthcare, 40-location specialty care, 8,000+ invoices/month | 74% reduction in manual invoice processing; 3 FTEs redeployed; 7-week deployment |
| 3 | B2B SaaS, 60-person Series C engineering org | 80% active tool adoption in 8 weeks; 31% PR cycle reduction; code review agent |

All anonymised. No logos, no named references, no methodology for the percentages.

**What to steal:** the metric shape. Every case has (a) a scope anchor, (b) a % reduction against a baseline, (c) a headcount consequence, (d) a time-to-production. That is the four-part structure a mid-market CEO can repeat to their board. Build your product to emit exactly these four numbers automatically — see the Value Realization Ledger in `04-PRODUCT-SPEC.md`.

**What to beat:** none of it is auditable. "68% reduction in manual processing" against what baseline, measured how, over what period, excluding what? If your platform can produce that number with a click-through to the underlying runs, you have a demo that no competitor can match and a compliance story on top.

---

## The report (`/report/`) — their best asset

*The AI Value Realization Report — Q3 2026.* Thesis: implementation capability, not model technology, is the binding constraint. *"The next wave of AI winners will not be the companies that buy the most AI. They will be the companies that deploy it best."*

Data synthesised (all third-party, all citable):

| Finding | Data point | Source |
|---|---|---|
| AI infra spend | $675B in 2026, +63% YoY | Hyperscaler capex |
| CEOs seeing both revenue and cost gains | 12% | PwC (n=4,454), Jan 2026 |
| CEOs seeing neither | 56% | PwC |
| GenAI pilots with zero P&L impact | 95% | MIT NANDA, 2025 |
| Companies abandoning most AI projects | 42% | S&P Global, 2025 |
| Companies with measurable returns | 26% | BCG 2026 (n=1,800) |
| Pilots reaching enterprise scale | <20% | McKinsey State of AI |
| Orgs facing adoption challenges | 79% | Writer/Workplace Intelligence (n=2,400) |
| C-suite saying AI adoption is "tearing the company apart" | 54% | same |
| PE portcos with a GenAI use case in production | ~20% | Bain |
| PE firms confident of passing an AI audit in 90 days | 9% | Grant Thornton (n=950) |

**Effort allocation argument (the money slide):**

| | What success requires | What companies actually spend |
|---|---|---|
| Technology / licenses | 20% | ~60% |
| Data | 30% | ~20% |
| Workflow redesign | 25% | ~10% |
| Change management | 25% | ~10% |

**Seven-step operating system:** identify economic bottlenecks from the P&L → map current workflows → redesign around AI → embed into existing systems → drive adoption → measure realized value → scale what works.

**Recommendations:** operators — *"stop counting pilots and start counting workflows in production with measured results."* Boards — stop asking "what is our AI strategy" and start asking *"which workflows run on AI today, what did they measurably change, and who owns the number."*

No email gate, no lead form on the report page. **[inference]** That is a mistake on their part and a gift to you: they are giving away the demand-gen asset without capturing the demand. Gate yours, or at minimum instrument it.

---

## Careers (`/careers/`)

Two roles, both full-time, NYC or remote, no comp bands, no requirements listed:

- **AI Engineer** — "Build and deploy production AI features across client products. Own model integration, evaluation, and performance tuning. Collaborate directly with founders and product teams."
- **Product Engineer** — "Ship end-to-end product experiences from idea to production. Work across frontend, backend, and AI-powered workflows. Partner with clients to translate problems into features."

Self-description: *"a small team shipping AI systems to production quickly."*

**[inference]** Both roles are billable delivery roles. There is no platform/infra role, no data engineer, no forward-deployed *solutions architect* title, and no Origo product manager. For a company whose homepage claims a proprietary platform is the source of its speed, that is the tell.

---

## Assessment

**What they are genuinely good at**
1. Positioning. "AI transformation for the real economy, at factory speed" is better than anything the Big 4 has.
2. Offer architecture. Three cleanly separated offers at three price points with three different buyers, and an explicit path between them (Point Build → Full Deployment → Portfolio).
3. Demand generation. The report is a credible, well-sourced argument that happens to conclude "hire someone like us."
4. Credibility transfer. Ex-Google/Microsoft/Bain/Meta logos substituting for client logos, which is the standard play when you are 8 people and under NDA.

**Where they are exposed**
1. **Origo is unproven and probably thin.** No docs, no demo, no login, no platform hiring, and absent from 3 of 5 substantive pages.
2. **Their best segment is under attack by $14B of model-vendor capital** (see `02-MARKET.md`).
3. **No auditable evidence layer.** They sell "measured impact" and publish unverifiable percentages. Their own report says buyers should demand better. That contradiction is your opening.
4. **Capacity-bound.** 6–10 week embedded builds with senior people do not scale past ~2 concurrent per builder. Revenue is linear in headcount unless Origo is real.
5. **No self-serve, no product-led motion, nothing that compounds** except templates in someone's head.

**The one-line summary:** Deployly is a well-positioned, well-marketed, capacity-bound implementation boutique whose stated moat (Origo) does not appear to exist yet, operating in a segment that two of the world's best-funded AI companies just entered. The opportunity is not to copy their website. It is to build the product they are pretending to have, and to sell it into the segments the JVs will ignore.
