# Unit economics and financial model

All figures are models, not forecasts. Replace every assumption with your own numbers — especially the labour rate, which changes by 3–5x between US and India delivery. **Verify current model pricing before using the compute numbers; the token rates below are illustrative placeholders.**

---

## 1. Per-unit economics (the number that decides whether this works)

Using the Wedge A baseline from `07 §2` (COI verification, 1,850 docs/month, 6.5 min p50, $38/hr loaded):

**Baseline cost per document**
```
6.5 min ÷ 60 × $38 = $4.12 per document
+ error cost: 2.8% × $410 = $11.48 amortised... (use with care — this is an estimate input)
Conservative baseline, labour only: $4.12/doc → $91,464/yr
```

**Your cost per document (illustrative — re-derive with current provider pricing)**
```
Parse/OCR                                       ~$0.010
Model calls (classify + extract + validate)
  ~8k input tokens, ~1k output across 3 calls
  at ~$3/M in, ~$15/M out (mid-tier frontier)   ~$0.039
Infra amortised (compute, storage, queue)       ~$0.006
                                                -------
Compute subtotal                                ~$0.055

Human review at 30% of volume × 1.5 min × $38/hr ~$0.285
                                                -------
Blended cost per document                       ~$0.34
```

**Gross value created per document: $4.12 − $0.34 ≈ $3.78 (92%).**

At 1,850/month that's ~$84k/year of value on one workflow at one mid-size customer. This is why a $65k build with a $6k/month retainer is an easy sell — and why you must show the arithmetic rather than assert a percentage.

**Sensitivities that matter more than model price:**
- Review rate is 5x more important than token cost. Going from 30% → 15% review saves $0.14/doc; halving token spend saves $0.02. **Optimise straight-through rate, not prompt length.** This is the single most common misallocation of engineering time in this category.
- p90 handling time is where the value hides. If p90 is 22 minutes and those are 15% of volume, the *real* baseline is closer to $6/doc.
- Below ~500 documents/month the retainer stops being justifiable on labour savings alone. Qualify on volume, or sell on error/compliance cost instead.

---

## 2. Project economics

| | Build #1 | Build #3 | Build #6 |
|---|---|---|---|
| Price | $55,000 | $70,000 | $85,000 |
| Elapsed | 8 weeks | 6 weeks | 5 weeks |
| Delivery effort (person-weeks) | 9.0 | 5.5 | 3.5 |
| Cost @ $3,000/person-week loaded | $27,000 | $16,500 | $10,500 |
| Infra + models during build | $1,500 | $1,200 | $1,000 |
| **Gross margin** | **48%** | **75%** | **86%** |
| Config vs code | 10% / 90% | 45% / 55% | 70% / 30% |

**The whole thesis of the business is that row-by-row progression.** If build #6 still costs 9 person-weeks, the platform is not real and you are a consultancy — which is a fine business, but a different one, and you should stop investing in the platform and start hiring delivery people instead.

Track `config %` as a first-class internal metric from build #1. It is your leading indicator of everything.

---

## 3. Recurring economics

```
Run & Improve, mid tier:            $6,000/month
Cost to serve:
  Infra + models (2k docs/mo)         ~$400
  Monitoring/drift review (3 hrs)      ~$450
  Support + monthly value report       ~$450
                                     -------
                                     ~$1,300
Gross margin                            78%
```

Retainer is the number that determines whether this is a business worth building. Rules:
- Attach it to **every** build.
- 12-month term, annual uplift clause.
- Second workflow at the same customer adds ~$2–4k/month at ~85% margin — the cheapest revenue you will ever get.
- Target: **retainer ARR ≥ 25% of total revenue by month 12, ≥50% by month 24.**

---

## 4. Year 1 model (bootstrapped, 1 → 2.5 people)

| Quarter | Builds closed | Build revenue | Retainer ARR added | Cash collected | Headcount |
|---|---|---|---|---|---|
| Q1 | 1 (+2 sprints) | $55k + $30k | $6k/mo | $85k | 1.0 |
| Q2 | 2 (+3 sprints) | $135k + $45k | $12k/mo | $180k | 1.5 |
| Q3 | 2 (+3 sprints) | $150k + $48k | $12k/mo | $198k | 2.0 |
| Q4 | 3 (+3 sprints) | $240k + $48k | $18k/mo | $288k | 2.5 |
| **Year 1** | **8 builds** | **$751k** | **$48k/mo = $576k ARR run-rate** | **~$751k** | 2.5 |

Costs, year 1:
```
People (blended $110k loaded × 1.75 avg FTE)      $193k
Infra, models, tooling                             $36k
  (hosting ~$800/mo, models ~$900/mo, Langfuse
   self-host, Sentry, CI, Vanta ~$12k/yr)
Insurance (E&O + cyber)                             $9k
Legal (MSA/DPA templates, entity)                  $12k
Sales/marketing (report, travel, trade shows)      $28k
Accounting/admin                                   $10k
                                                  -----
Total                                             $288k
```

**Year 1 contribution: ~$460k.** That funds a third and fourth hire in year 2 without raising, which is the point — this business does not need venture capital to reach $2M, and it is far more fundable at month 18 with a ledger full of measured outcomes than it is today with a deck.

**Cash timing warning:** the 40/30/30 payment schedule means Q1 cash lands ~3 weeks after you think it does, and mid-market companies pay net-30 to net-45 in practice. Model 8–10 weeks of runway buffer beyond what this table implies. The Proof Sprint fee (paid up front) is your working-capital instrument — another reason to always sell it.

---

## 5. Capacity constraints (the real ceiling)

- One experienced person can run **1.5 concurrent builds** at build #1 maturity, **2.5** at build #6 maturity.
- Discovery and sales take ~30% of a founder's week and cannot be delegated until ~customer 6, because the discovery interview *is* the product.
- The binding constraint in year 1 is not engineering. It is **your calendar in weeks 1–4 of each engagement.** Structure pricing so that overlapping kickoffs are rare — stagger starts by 3 weeks.
- First hire (month 5–7) must be a **forward-deployed engineer**: can run a discovery interview on Tuesday and ship an extraction schema on Wednesday. Not a salesperson (you have no repeatable pitch yet). Not a backend specialist (nothing to specialise in yet).

---

## 6. What "good" looks like at each stage

| Stage | Signal that you're on track | Signal to stop and rethink |
|---|---|---|
| Month 1 | 8 teardowns run, 2 sprints sold | <4 teardowns booked from 40 touches → wrong trigger or wrong vertical |
| Month 3 | 1 customer in production, ≥45% straight-through | Straight-through <30% → wrong workflow, too much variance |
| Month 6 | Build #3 at ≥40% config, retainer #1 renewed | Build #3 costs the same as #1 → platform isn't compounding |
| Month 9 | 5 customers, same vertical, referrals arriving | Every customer in a different industry → no compounding, you're an agency |
| Month 12 | $600k+ collected, ≥25% recurring, benchmark report published | <15% recurring → you're selling projects, not a product |
| Month 18 | Second workflow family live at 60% platform reuse; inbound from other agencies | Still bespoke per customer → accept the agency model and optimise it honestly |

---

## 7. The three numbers to put on a wall

1. **Straight-through rate** — drives customer value, your margin, and your pricing power. Every point matters.
2. **Config % of build effort** — the only proof the platform is real.
3. **Recurring % of revenue** — the only proof you're not a consultancy.

Everything else in these ten documents is in service of those three.
