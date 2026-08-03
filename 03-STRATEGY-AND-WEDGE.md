# Strategy, ICP and wedge selection

---

## 1. The strategic frame

Three businesses are available here. They look similar from the outside and are completely different to run.

| | A. Implementation firm | B. Vertical AI product | C. Delivery platform for implementers |
|---|---|---|---|
| Buyer | COO/CFO of a mid-market operator | Same, but buying software | Owner of a 5–30 person AI shop |
| Revenue | $50k–$250k/project | $2k–$15k/month + per-run | $500–$5k/month/seat-org |
| Margin | 35–60% | 70–85% | 75–85% |
| Scales with | Headcount | Product + sales | Product + channel |
| Time to first $ | 4–8 weeks | 6–12 months | 9–18 months |
| Moat | Reputation, references | Exception knowledge, integrations, switching cost | Workflow + evidence data across many firms |
| Risk | Capacity trap, no compounding | Starving before PMF | Buyers are poor and fragmented |
| Deployly is | this | claims this | not this |

**Recommendation: A → B, with C architected for but not built.**

Start as A because it is the only one that pays in 60 days and the only one that gives you the raw material (real workflows, real exceptions, real baselines) that B and C need. But run A *as if* you were building B: every engagement must produce reusable platform components, or you are just a consultancy with extra steps.

The discipline that keeps you out of the capacity trap:

> **Rule of thirds.** For every engagement, one third of the effort must produce something that ships into the platform and is reusable on the next engagement. If a project can't clear that bar, price it higher or decline it.

And the exit condition, defined now so you don't drift:

> **By month 12, ≥40% of build hours must be configuration rather than code, and ≥25% of revenue must be recurring.** If both hold, convert to B. If neither holds after 18 months, you are a consultancy — accept it, hire, and optimise for margin instead of pretending.

---

## 2. Positioning

Do **not** position as "AI workflow platform." That sentence puts you in a bucket with n8n, Gumloop, Lindy, Copilot Studio and 200 dead startups, and Relay.app just shut down in that bucket.

**Position on the evidence gap.** Draft positioning statement:

> For mid-market operators who have already been burned by an AI pilot, [Name] puts one high-volume workflow into production in six weeks and proves what it changed — every run baselined, every exception reviewed by a human, every dollar of savings traceable to the record that produced it. Unlike agencies, you keep the system. Unlike tools, you keep the evidence.

Three message pillars, in priority order:

1. **Proof.** "We will not tell you it saved 68%. We will show you the 4,312 runs." — differentiates against every agency *and* every tool.
2. **Exceptions.** "The demo always works. We build for the 20% that doesn't." — differentiates against pilots.
3. **Ownership.** "It runs in your cloud, on your data, and your team can operate it without us." — kills the retainer objection and the lock-in objection at once.

**Anti-positioning (say these out loud in sales calls):**
- We do not do AI strategy decks.
- We do not do chatbots on your website.
- We do not do 12-month transformations. (You cannot deliver these. Deployly can barely deliver these.)
- We do not compete with your ERP or your spend-management tool. We handle the work that never makes it into them.

---

## 3. ICP definition

**Firmographic**
- Revenue **$20M–$250M**. Below $20M there's no budget; above $250M you meet procurement, Accenture and now the JVs.
- **50–1,000 employees**, of which **≥15 do repetitive document/inbox work** in one function.
- Owns an ERP/system of record but **does not have an integration team**. NetSuite, Dynamics 365 BC, Epicor, Infor, Sage Intacct, Acumatica, or something older and worse.
- PE-owned or founder-owned with an operating mindset. PE-owned is faster (mandate + budget + board pressure) but check whether their sponsor has already signed with a JV.

**Psychographic — the qualifying questions**
- Has someone here already tried an AI pilot that went nowhere? (**Yes is good.** They've had the fantasy beaten out of them.)
- Is there a named person whose number would move? (No owner = no deal, every time.)
- Is the work currently done in a shared inbox or a spreadsheet? (Shared inbox is the single best signal in this whole document.)

**Disqualify immediately**
- "We want to explore AI." No workflow, no deal.
- Regulated clinical/credit decisioning as the *first* project — high-risk under EU AI Act frameworks, long procurement, and you have no reference yet.
- Anyone who wants you to start with data cleanup. That is a 6-month project with no visible win.
- Anyone whose sponsor's PE firm is an LP in one of the deployment JVs, unless you are subcontracting to them.

**The five industries worth targeting** (Deployly's list is right; here's why, ranked for a small team):
1. **Wholesale distribution** — highest density of unstructured-document work per employee, weakest software, oldest ERPs
2. **Industrial / specialty manufacturing** — quotes, specs, RFQs, warranty, supplier docs
3. **Field services** (HVAC, electrical, facilities, roofing) — huge PE roll-up activity, hideous back office, compliance docs everywhere
4. **Logistics & 3PL** — freight audit, POD reconciliation, exception-heavy by nature
5. **Healthcare multi-site operators** — real pain, real money, but slowest sales and highest compliance load. Third project, not first.

---

## 4. Wedge selection: scoring the candidate workflows

Criteria (1–5, higher is better), weighted:

| Criterion | Weight | What a 5 looks like |
|---|---|---|
| Volume/repetition | 15% | Thousands of instances/month, same shape |
| Baseline is measurable | 20% | Current cost is countable *before* you build |
| Incumbent-free at mid-market | 20% | No $44B company gives this away free |
| Exception richness | 15% | Exceptions are the value; they're what you learn |
| Integration surface is shallow | 10% | 1–2 systems, read-heavy, ideally API or email |
| Blast radius if wrong | 10% | A mistake is embarrassing, not catastrophic |
| Reusable across customers | 10% | Same shape at the next 20 companies |

### Scores

| Workflow | Vol | Base | Incumb | Excep | Integ | Blast | Reuse | **Total** |
|---|---|---|---|---|---|---|---|---|
| **Order & quote intake → ERP** (distribution/mfg) | 5 | 5 | 4 | 5 | 3 | 3 | 5 | **4.35** |
| **Compliance-doc chase & verify** (COI, W-9, licences, lien waivers) | 4 | 5 | 5 | 4 | 4 | 4 | 5 | **4.45** |
| **Freight/vendor invoice audit & dispute** | 5 | 5 | 4 | 5 | 3 | 3 | 4 | **4.25** |
| **RFQ/RFP & bid response** (industrial) | 3 | 3 | 4 | 4 | 4 | 4 | 4 | **3.65** |
| **Warranty / claims intake & adjudication** | 4 | 5 | 5 | 5 | 2 | 2 | 3 | **3.90** |
| **Tier-1 support deflection** | 5 | 4 | 1 | 3 | 4 | 3 | 4 | **3.35** |
| **Invoice intake / AP coding** (your note's pick) | 5 | 5 | **1** | 3 | 2 | 3 | 5 | **3.35** |
| **Enterprise knowledge search** | 3 | 1 | 2 | 2 | 3 | 5 | 3 | **2.45** |

### Reading the table

**Invoice/AP scores 3.35 and it is the worst kind of 3.35** — it scores 1 on the most important structural criterion. Ramp gives AP agents away to win the payment flow; Rossum starts at $18k/yr with prebuilt NetSuite/SAP/Oracle/Dynamics connectors; Bill and Tipalti own the mid-market install base. You would be selling a worse product into a saturated category against people who can price at zero. **Drop it as the wedge.** (It's fine as workflow #3 for an existing customer who already trusts you — just never as the thing you lead with.)

**Enterprise knowledge search scores worst** and is the most commonly attempted. There is no baseline, so there is no provable value, so there is no renewal. Avoid.

**The two winners:**

### Wedge A — Compliance document chase & verification (4.45)
*Vendor/subcontractor certificates of insurance, W-9s, licences, safety certs, lien waivers, food-safety and quality certs.*

The work today: someone maintains a spreadsheet of expiry dates, emails vendors, receives PDFs, eyeballs coverage limits and named insureds, files them, and gets it wrong sometimes. In field services and construction this is a compliance *and* insurance-liability issue, so mistakes cost real money.

Why it wins:
- **No incumbent at mid-market.** COI-tracking tools exist (myCOI, Jones, Billy) but are narrow, expensive, and don't handle the general case across doc types.
- The whole workflow is email + PDF + a rules table. **Shallow integration.** You can deliver value before touching the ERP.
- Verification is genuinely a rules-plus-judgement problem — exactly the shape where a bounded LLM plus a human review desk beats both pure OCR and pure human.
- The baseline is trivially countable: N vendors × M documents × expiry cadence × minutes each, plus the cost of the last compliance failure.
- Chasing (outbound email follow-up until the doc arrives) is a genuinely agentic task with an unambiguous success event — perfect for outcome pricing and perfect for the ledger.

Risk: deal sizes may be smaller; it can read as "narrow tool" rather than "AI transformation."

### Wedge B — Sales order & quote intake into ERP (4.35)
*Emailed POs, PDFs, spreadsheets, and "same as last time but 3 of the blue ones" from customers → validated ERP order.*

Why it wins:
- Market facts: **60–70% of B2B orders arrive as unstructured documents**; **10–30 minutes per order**; **3–5% error rate**. Every mis-keyed order becomes a mis-shipment, a credit note and a late payment. CFOs feel this.
- Conexiom and Esker prove the category is real and valuable — and both are enterprise-priced and ERP-gated, leaving the sub-$150M distributor unserved.
- Customer-specific part numbers, unit conversions, pricing agreements and "the way this one customer writes their POs" is a huge, per-customer exception corpus. **Massive switching cost once you've learned it.** This is the most defensible exception knowledge on the list.
- Direct revenue impact, not just cost: faster order entry = faster shipment = faster cash.

Risk: writing into an ERP is a higher-consequence action and a deeper integration. Mitigate by phasing — **Phase 1 writes nothing**: it produces a validated, human-approved order draft with a copy-paste/CSV handoff. Prove accuracy for 60 days, *then* earn write access.

### Recommendation

**Lead with Wedge A (compliance documents), design the platform for Wedge B, and land Wedge B as the second engagement at the same customer or in the same vertical.**

Reasoning: A gets you into production fastest with the least integration risk and the cleanest proof story, which is what you need for reference #1. B is the bigger, more defensible business, but it wants a reference and an ERP conversation you have not yet earned. Both live in the same industries (field services, construction, distribution, manufacturing) and share ~70% of the platform: email ingestion, document classification, extraction, rules validation, confidence scoring, human review, chase/notify, audit trail, ledger.

**If your personal network is strongest in distribution or manufacturing, invert this and lead with B.** Network access beats a 0.10 difference in a scoring matrix. Run the matrix against your own contacts before committing.

---

## 5. The compounding assets (what you are actually accumulating)

Ranked by defensibility:

1. **Exception taxonomy per workflow family.** Every human correction in the review desk is labelled with a reason code. After 50,000 reviews you know the 200 ways a COI can be non-compliant or a PO can be ambiguous, and you can test against all of them. Nobody can buy this.
2. **Golden evaluation sets from real customer documents** (rights secured contractually — see `09`). This is what makes build #10 faster and more accurate than build #1.
3. **Baseline + outcome corpus.** After 20 deployments you can say: *"this workflow shape typically reaches 71% straight-through by week 8, with payback in 4.1 months."* That statement closes deals no competitor can close.
4. **Vertical connector depth.** The specific horrors of Epicor Prophet 21, Infor CSD, Acumatica. Boring, high-value, and the JVs will never do it.
5. **Delivery templates.** Least defensible (copyable), highest immediate margin impact.

Note the ordering: your moat is data your *review desk* produces. Design the review desk as a data-collection instrument that happens to also get the work done — not as an afterthought UI. This is the single most important product decision in this whole document.

---

## 6. Naming and brand notes

- Avoid `*ly.ai` and `*deploy*`. The space is full of them, and you'd be reading as a Deployly knockoff to anyone who knows the category.
- Name should point at *evidence* or *operations*, not at *AI*. Directions worth exploring: the ledger/proof metaphor, the "shop floor / back office" metaphor, or a plain industrial word.
- Reserve the "Origo equivalent" name for the internal platform **and actually ship docs for it**. Their weakness is that Origo is a claim; your version should be a URL with a changelog. That contrast is a sales asset.
