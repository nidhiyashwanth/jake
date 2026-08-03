# Go-to-market and pricing

---

## 1. Offer ladder

Three offers, deliberately mirroring Deployly's structure because the structure is good, with prices set for a small unknown firm rather than an ex-Bain NYC boutique.

### Offer 0 — Workflow Teardown (the door opener)
**$0, 45 minutes, live.** You map one of their workflows on a call, in your product, and hand them the graph + baseline + estimated annual cost + a ranked list of what to automate. They keep it whether or not they buy.

Why free: you have no reputation. The teardown *is* the credibility. It also populates your platform with real workflow data from day one, which is your compounding asset. Cap it at 8/month so it stays scarce.

### Offer 1 — Proof Sprint
**$12,000–$20,000, 2 weeks, fixed fee.**

Deliverables:
- Signed baseline for one workflow (volume, minutes, error rate, loaded cost)
- Working prototype running against **their real historical documents** (50–200 samples), in your platform, that they can log into
- Measured accuracy report: field-level precision/recall, projected straight-through rate at three confidence thresholds
- Threshold simulator output: "at θ=0.88 you auto-process 68% at an estimated 0.9% error"
- Fixed-price proposal for the production build, with a stated automation-rate target

Why this shape: it converts "will AI work on our messy documents?" from a debate into a measurement, in two weeks, for less than a month of the salary they're trying to redeploy. **Credit 100% of the sprint fee against the build if they proceed within 30 days.** Target conversion: 50%+.

### Offer 2 — Production Build
**$45,000–$95,000, 6–8 weeks, fixed fee.** (Deployly charges $185k. You are not Deployly yet. Price to win references, and raise 20% after every successful reference.)

Scope:
- One workflow, production, in their environment or your isolated tenant
- 2–3 integrations (email/storage/notify + one system of record, read-only unless earned)
- Rules and validation configured to their policy
- Human review desk, with their operators trained
- Value Realization Ledger live with signed baseline
- Audit pack + runbook + handover documentation
- 30 days hypercare included

Explicitly out of scope (write it in the SOW): net-new ERP modules, data warehouse work, anything requiring their IT to build something, and workflow #2.

### Offer 3 — Run & Improve
**$3,000–$9,000/month, 12-month term**, tiered by volume, plus optional per-unit above an included band.

Includes: hosting, monitoring, model costs up to a cap, accuracy maintenance (when their vendor changes a PO template, you fix it), monthly value report, quarterly business review with the ledger, one workflow change per month.

**This is the line item that turns you from an agency into a company.** Never sell Offer 2 without Offer 3 attached; if a customer refuses the retainer, price Offer 2 30% higher and expect them to churn to nothing.

### Offer 4 — Managed Operations (optional, high margin, later)
You supply the reviewers too. Priced **per successfully completed unit** (e.g. $0.60–$2.50 per verified document, per validated order). Market context: agent products now routinely price per outcome ($0.50–$2.00 per resolution across Quickchat, Fin, Zendesk, Agentforce, HubSpot). Gartner expects ≥40% of enterprise SaaS spend on usage/agent/outcome pricing by 2030.

Only offer this once your straight-through rate is above ~70% and your measured error rate is stable, because you're now taking the labour risk. When you can, it's the best business in this document: high margin, high switching cost, and the customer stops comparing you to software.

---

## 2. Pricing principles

1. **Fixed fee, always.** Your buyer has been burned. Hourly rates re-open that wound. You absorb the estimation risk; that's what the Proof Sprint is for.
2. **Price against the baseline, not against your cost.** If the workflow costs them $340k/year and you can take 65% of it, a $75k build with a $6k/month retainer is a 4-month payback. Lead with the payback month, not the price.
3. **Never discount the build. Discount the retainer's first quarter.** Protects the reference price and the perceived value of the software.
4. **Model costs are passed through with a cap and a floor markup.** Transparent, in the ledger, capped so they aren't exposed to a pricing change from a lab.
5. **Publish a price band on the website.** Mid-market buyers self-qualify on price and hate "contact us". Deployly's one disclosed number ($185K) does more sales work than the rest of their site.

---

## 3. The sales motion

**Stage 0 — Trigger events (build a list of these, not a list of companies).**
- PE add-on acquisition closed (integration pain, mandate to show synergies)
- New CFO or COO in the first 6 months (needs a visible win)
- Job posting for "AP clerk", "order entry specialist", "compliance coordinator" — literally an advertisement that the workflow is manual and they're about to spend $55k/year on it
- Failed AI pilot mentioned in a podcast/LinkedIn post
- ERP migration announced (everything is in flux, budget exists)
- New compliance requirement in their industry

**Stage 1 — Outreach.** The job-posting trigger is the strongest cold angle available to you:

> Subject: your order entry opening
>
> Saw you're hiring an order entry specialist. Before you fill it — we mapped this exact workflow at [similar company type] and 68% of the volume turned out to be machine-processable, with a person reviewing the rest.
>
> Not pitching a platform. I'll map your version of it live in 45 minutes and send you the cost breakdown whether or not we work together.
>
> Worth 45 minutes?

**Stage 2 — Teardown call (Offer 0).** Screen-share your discovery module. Ask the exception questions five times. End with the baseline number *they* gave you and a ranked list. Do not pitch. Send the artifact within 24h.

**Stage 3 — Proof Sprint.** Small enough to sign without procurement in most mid-market firms. Get their real documents under an NDA + data-processing agreement.

**Stage 4 — Build.** Weekly demo on real data, non-negotiable. This cadence is why fixed-fee works — no surprises in week 7.

**Stage 5 — Value review at day 30, 60, 90.** Ledger export. This is where the retainer renews and where the second workflow gets sold — never pitch workflow #2 before day 60 of workflow #1.

**Stage 6 — Referral.** Mid-market operators in the same vertical all know each other. One happy distributor is worth more than 500 cold emails. Ask explicitly at the 90-day review, with a specific name.

---

## 4. Demand generation (copy the mechanism, not the content)

Deployly's report works. Build your own, but narrower and with a lead gate.

**Your report: "The [Vertical] Back Office Benchmark."**
Survey/interview 30–50 operators in your chosen vertical. Publish: how many documents a month, how many minutes each, error rates, what people actually use, what failed. Nobody has this data for wholesale distribution or field services. It is cheap to produce (it's your discovery interviews, aggregated and anonymised) and it makes you the person who knows the industry's numbers.

Update it quarterly with your own anonymised ledger data. By year two you can say *"across 23 deployments, this workflow shape reaches 71% straight-through by week 8 with a 4.1-month payback"* — a sentence no competitor can say, backed by a database.

**Supporting assets, in build order:**
1. ROI calculator on the site (ungated, captures email for the PDF) — the same maths as the platform's opportunity scoring
2. The benchmark report (gated)
3. 3 workflow teardown write-ups (anonymised, with real numbers and real failure modes — include what didn't work; it is the most credible thing you can publish)
4. A public changelog for the platform — the direct contrast with Deployly's unverifiable Origo
5. Short screen recordings of the review desk. Ops leaders buy the review desk, not the architecture.

**Channels, ranked for a small team:** warm network in one vertical > industry associations and trade shows (distribution and field services still run on these — the ROI is unfashionable and excellent) > targeted outbound on trigger events > LinkedIn founder-led content > PE operating-partner networks (slow, high value, but check JV exposure) > paid (last, if ever).

---

## 5. Handling the five objections you will get every time

| Objection | Response |
|---|---|
| "We tried AI and it didn't work." | "What was the accuracy target and who measured it?" Almost always: no target, no measurement. Then: "That's the difference here — we baseline first and you can see every run." |
| "Our documents are too messy / we're different." | "Send me 100 of the worst ones. Two weeks, fixed fee, and you get the accuracy number whether it's good or bad." The Proof Sprint exists entirely to convert this objection into revenue. |
| "Can't we just use ChatGPT / Copilot / n8n?" | "For the 60% that's easy, yes. The 40% that's exceptions is where the cost is, and that needs rules, review and an audit trail. Also — who tells you when it silently starts getting it wrong?" |
| "What if it makes a mistake?" | Threshold simulator + value-at-risk limits + human review + sampled audit + incident log. Then: "Your current error rate is 3–5%. What's your target?" Most buyers have never measured their own error rate and the question reframes the entire conversation. |
| "Why you and not [big firm / the OpenAI JV]?" | "They're building for 5,000-person companies. You'd be their smallest account and their most junior team. This workflow is the only thing we do, and you'll have my mobile number." |

---

## 6. First 20 target accounts — how to build the list

1. Pick the vertical (see `03`).
2. Filter: revenue $20–250M, US or your geography, PE-owned or founder-led.
3. Enrich with trigger events: hiring for the manual role, recent acquisition, new CFO/COO, ERP migration.
4. Find the *workflow owner*, not the CIO. Titles: Director of Operations, Controller, AP/AR Manager, Order Management Manager, Compliance Coordinator, VP Supply Chain.
5. Find the warm path. Trade association, shared vendor, LinkedIn 2nd degree, former colleague.
6. Track in a simple CRM with the trigger event as the key field — the trigger is what makes the first line of the email work.

Target for month 1: 20 accounts, 40 contacts, 8 teardown calls, 2 Proof Sprints sold.
