# Fundraising path — and how it changes everything in docs 06–10

You chose **full-time, planning to raise.** That is a coherent choice, but it puts you in direct conflict with the services-led sequencing in `06`, `08` and `10`. This document resolves the conflict. **Read it before acting on the offer ladder in `06`.**

---

## 1. The conflict, stated plainly

The plan in `06`–`10` optimises for **cash collection**: big fixed-fee builds, retainer attached, no outside money, $751k collected in year 1. It is a good bootstrapping plan.

It is also a plan that makes you harder to fund. The 2026 bar:

- *"The difference between $2M in one-time consulting engagements and $2M in recurring API fees is the difference between seed extension and Series A conviction."*
- **Series A 2026:** ~$3.5M ARR, 10–15% MoM growth, **NRR >120%**, gross margin trending past 60% (investors target 70–80%), **burn multiple <1.5–2x**.
- **Seed 2026:** revenue not required, but *evidence someone will pay* is. Median pre-money ~$17.9M with AI startups carrying a ~42% valuation premium over non-AI peers — though treat that median as a ceiling for a well-networked repeat team, not a floor for a first-time founder in vertical compliance software.
- Diligence now takes **1–2 months**, and includes data licensing, privacy and compliance review. Your `09` work becomes a diligence asset.
- Multiples run 10–50x, median 20–30x, but *"the AI gap is a valuation gap, not a permanent premium — it compresses the moment retention or margin disappoints."*
- 2026 context: **$337B across 395 deals, 310 companies.** Enormous capital, extremely concentrated. Being mid-pack gets nothing.

**Conclusion: raise on the wedge before you have a services book, not after.** A year of project revenue does not build a fundable story — it builds a defensible small business and a confusing cap-table conversation. If you're raising, the services layer must be small, capped, honestly labelled, and gone within four quarters.

---

## 2. Five structural changes to make now

### Change 1 — Invert the offer ladder
| | Bootstrapped plan (`06`) | **Raise plan (use this)** |
|---|---|---|
| Implementation | $55k–$95k | **$25k–$40k, called onboarding** |
| Subscription | $3k–$9k/mo, attached | **$3k–$12k/mo, mandatory, 12-mo minimum, annual prepay preferred** |
| Revenue mix target, month 12 | 25% recurring | **≥70% recurring** |
| Contract | SOW per project | **Order form against an MSA, auto-renewing** |

Give up roughly $30k per customer in project cash. Get a story that a seed investor can underwrite. That trade is correct if and only if you are actually raising — if you drift back to bootstrapping, reverse it.

### Change 2 — The customer's staff runs the review desk, not yours
This is the non-obvious one and it matters more than the pricing.

From `10 §1`: at 30% review rate, human review is **~85% of your cost per document** ($0.285 of $0.34). If *your* people do that review, your gross margin lands in the 40–55% range and you become a BPO with software attached. Investors price BPOs at 1–3x revenue, not 20x.

So: **Managed Operations (`06` Offer 4) is off the table for now.** The product must be good enough that the customer's existing coordinator runs the desk. Every engineering decision follows from this — the keyboard-first desk, the provenance highlighting, the threshold simulator all exist to make *their* operator fast, not to make *your* operator cheap.

Revisit this only after Series A, when it becomes an expansion motion rather than a margin problem.

### Change 3 — Instrument gross margin from run #1
Inference is COGS. Build the reporting now, because you will be asked for it in diligence and reconstructing it later is painful:
```
COGS = model spend + parse/OCR + storage + compute + support hours + hosting
GM%  = (subscription + overage revenue − COGS) / revenue
```
Report GM per customer and per workflow, monthly. **Target trajectory: >55% at seed, >70% by Series A.** If a customer's GM is under 40%, either their thresholds are wrong or you mispriced — fix it before it becomes a pattern in a data room.

### Change 4 — Secure data rights in the first contract
Your moat claim in a pitch is the exception taxonomy and golden sets. An investor will ask: *do you have the right to use that?* The derived-rights clause in `09 §2` must be in **every** contract from customer #1. A retroactive amendment across five customers during diligence is a bad week.

### Change 5 — Pick the category name before the first check
You are not "an AI implementation platform." Two viable framings, pick one and commit:

- **"The system of record for vendor compliance."** Vertical SaaS framing. Clean comps (Certificial, myCOI, Avetta), clear TAM ($3.95B contractor access compliance, 11.9% CAGR), obvious buyer. Easier to sell, lower ceiling, and you'll be asked "why hasn't Avetta done this."
- **"The evidence layer for AI-run operations."** Platform framing: compliance is the first workflow, the ledger is the product, expansion is horizontal. Bigger story, harder to prove at seed, and the one that matches what's actually differentiated.

**Recommendation: lead with the vertical framing, hold the platform framing as the "and here's why this is bigger than it looks" slide.** Investors fund a specific painful problem and *then* get excited about the expansion. The reverse order reads as unfocused.

---

## 3. Revised timeline

### Now → Month 4: Pre-seed / design-partner phase
Fund it yourself or with a small pre-seed ($300–750k on a SAFE). Goal is not revenue — it's **three design partners paying real money on a subscription**.

- 8–10 teardowns → 3 Proof Sprints ($12k each = $36k, your working capital)
- Convert all 3 to paid pilots: $25k onboarding + $4k/month
- Build in this order: review desk → compliance rules engine → `compliance_status` ledger → chase agent
- Instrument everything (`§4`) from day one

**Month 4 position:** 3 logos, ~$144k ARR, one production reference with measured straight-through rate, an exception taxonomy with 60+ codes, GM visible.

### Month 4–6: Seed round
Raise **$1.5M–$3M** on that. Realistic pre-money for a first-time founder with 3 paying logos in a defined vertical: **$8M–$15M** (the $17.9M median skews to repeat founders and hot categories — plan for the lower half and be pleasantly surprised).

Use of funds: 2 forward-deployed engineers, 1 design/product, SOC 2, 18–24 months of runway.

**What you're actually selling in that round:** not the ARR (it's small). You're selling (a) a wedge with a countable, urgent, liability-backed pain, (b) evidence that you convert pilots to subscriptions, (c) a compounding data asset with rights secured, (d) a credible path from one workflow to a platform.

### Month 6–18: get to Series A shape
- 15–25 customers, **$1.5M–$3.5M ARR**
- NRR >120% via seat growth, volume growth, and workflow #2 at existing accounts (**expansion is where NRR comes from — plan the second workflow as a revenue motion, not a product whim**)
- GM >70%
- CAC payback <12 months
- Burn multiple <2x
- SOC 2 Type II done; ISO 42001 gap assessment if selling to PE-owned accounts

---

## 4. The metrics dashboard to build for yourself in week 1

Not for investors — for you. But it becomes the data room.

**Growth:** ARR, new/expansion/churned ARR by month, logos, pipeline by stage, teardown→sprint→subscription conversion rates.
**Retention:** NRR, GRR, logo retention, expansion revenue %.
**Efficiency:** CAC, CAC payback, burn multiple, magic number, months of runway.
**Margin:** GM overall, GM per customer, COGS split (model / parse / infra / support).
**Product (your differentiated ones — these are what make the deck memorable):**
- straight-through rate by customer, trended
- measured error rate on auto-processed items (from sampled audit)
- review minutes per document, trended down
- config-% of each new implementation
- time-to-first-verified-document for a new customer
- golden set size and exception taxonomy size

That last block is the slide nobody else in your category will have. *"Our fourth customer went live in 9 days instead of 47, because build #1 taught the platform 43 exception types"* is a defensibility argument with a chart behind it.

---

## 5. Investor targeting

**Right fit:** vertical SaaS and applied-AI seed funds; construction/proptech/insurtech-adjacent specialists; funds with a thesis on "services-as-software" or AI in non-tech industries; angels who are risk managers, GC executives, or insurance brokers (they validate the pain instantly and open doors).

**Wrong fit:** infrastructure/dev-tool funds (you're not a platform yet), generalist funds looking for consumer-scale growth, anyone whose last five AI investments were model or agent-framework companies.

**Underrated:** insurance brokers and carriers as strategic angels. They have the distribution channel described in `11 §6`, and their interest is a signal that the liability pain is real.

### The five objections, with answers

| Objection | Answer |
|---|---|
| **"Isn't this a services business?"** | "Onboarding is 20% of contract value and falling — 40% of implementation is configuration today, versus 10% on our first build. Here's the chart. Recurring is 74% of revenue." *Have the chart. This objection kills more rounds than any other.* |
| **"Certificial and myCOI already do this."** | "They track certificates. We verify compliance across nine document types against contract-specific requirements, and we produce a point-in-time defensible record. Our first three customers all use a COI tool and still had 3 FTEs doing this." *Verify that last claim is true before you say it.* |
| **"What stops a COI incumbent from adding AI?"** | "Extraction, nothing. The requirement-matching logic and the exception taxonomy took 8,000 human corrections to build, and it compounds per customer. Also, they'd have to build an evidence layer that makes their own historical numbers auditable, which they don't want to do." |
| **"Why won't the model vendors eat this?"** | "OpenAI and Anthropic just put $14B into deployment JVs aimed at PE portfolios and large enterprises. Neither will build ACORD 25 endorsement-matching for $60M mechanical contractors. The model is a component; the vertical rules, the integrations and the liability record are the product." |
| **"How big can this get?"** | Vertical answer: $3.95B contractor access compliance growing 11.9% to $6.18B by 2030, plus adjacent supplier-compliance spend. Platform answer: every regulated document workflow in the mid-market needs the same baseline→verify→review→prove loop. Show the vertical number; tell the platform story. |

---

## 6. What kills this round (avoid all six)

1. **Services >30% of revenue** at the time you raise. Cap it deliberately.
2. **Gross margin you can't decompose.** "Roughly 60%" is a red flag; per-customer COGS breakdown is a green one.
3. **No expansion evidence.** One workflow at one price with flat accounts = no NRR = no Series A. Land workflow #2 or a seat/volume expansion at one account before you raise.
4. **Data rights not secured.** Your moat claim collapses in legal diligence.
5. **A single customer >40% of revenue.**
6. **Pitching the platform before proving the wedge.** "We're building the operating system for AI work" from a founder with 3 customers reads as unfocused. Earn it.

---

## 7. Amendments to the other documents

- **`06-GTM-PRICING`** — replace the offer ladder with `11 §5` (lower onboarding, mandatory subscription). Offer 4 (Managed Operations) is deferred until post-Series A. Everything on sales motion, trigger events and objection handling still stands.
- **`08-ROADMAP-90-DAY`** — same weekly cadence, different targets. Day-90 scorecard becomes: 10 teardowns, 3 Proof Sprints, **3 subscriptions signed**, ~$144k ARR run-rate, 1 in production. Cash collected drops to ~$110k and that is fine — it's runway, not the metric.
- **`10-UNIT-ECONOMICS`** — the per-document maths holds. The project-economics table becomes less relevant; track ARR, GM and NRR instead. **The row that matters most is now "review minutes per document, trended down," because that is your gross margin.**
- **`09-RISKS-COMPLIANCE`** — promoted from insurance policy to diligence asset. Do SOC 2 Type I readiness at 3 customers, not 5. Get the derived-rights clause right on the very first contract.
- **`03-STRATEGY-AND-WEDGE §1`** — the "month 12 exit condition" (40% config, 25% recurring) is superseded by the tighter raise-path targets: **≥40% config and ≥70% recurring by month 12.**
