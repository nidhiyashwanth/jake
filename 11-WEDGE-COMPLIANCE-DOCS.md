# Wedge deep dive: vendor & subcontractor compliance documents

Chosen wedge. This document supersedes the summary in `03 §4` and contains one **correction to my own scoring**.

---

## 1. Correction to the scoring in `03`

I scored this wedge **5 on "incumbent-free at mid-market."** Follow-up research says that was too generous. **It's closer to a 3.5**, which moves the total from 4.45 to roughly 4.24 — still the top of the table alongside order intake, but no longer a free run.

There is a real, funded COI-tracking category:

| Vendor | Position |
|---|---|
| **Certificial** | Real-time policy monitoring via carrier connections; AI/OCR extraction of limits and expiry. Claims risk staff spend **<30 min/day vs 3–4 hrs manual** |
| **myCOI** | Cloud platform for requesting, storing, tracking COIs with automated chase workflows |
| **TrustLayer, Jones, Billy, Hashtag Certify** | Various niches — construction, property management, OCR-based validation and renewal alerts |
| **Avetta, ISNetworld, Veriforce** | The enterprise tier: full contractor prequalification (safety, insurance, licensing, training) as a network. *My search did not return vendor-level detail on these three — verify their mid-market pricing and coverage yourself before your first sales call. They are the most likely source of a "we already use X" objection.* |

**Why the wedge still holds** — four reasons, and you must be able to say all four in a sales call:

1. **They are COI point tools; the problem is not COI-shaped.** A mid-market operator chasing subcontractors needs COIs *and* W-9s, business licences, contractor licences by state, safety certifications, drug-test attestations, lien waivers, MSAs, bonding, and increasingly ESG/quality certs. The existing tools do one document type well and leave the other eight in a shared inbox. **Your unit of work is "is this vendor compliant, across everything we require," not "did the COI arrive."**
2. **They verify format; the work is judgement.** Extracting a coverage limit is solved. Deciding whether *this* certificate satisfies *this* contract's requirements — additional insured wording, waiver of subrogation, primary/non-contributory language, per-project aggregate, whether the named entity matches the subsidiary on the PO — is rules-plus-judgement and is exactly where a bounded LLM plus a review desk beats OCR.
3. **Nobody produces the evidence layer.** None of them can hand your risk manager an auditable statement of "we verified 1,847 vendors this quarter, 43 lapsed, here's who was non-compliant on the day they were on site, here's the record." That's the ledger, and in a liability context it is worth more than the automation.
4. **The enterprise networks are network plays with network pricing.** Avetta/ISN work when you can compel your suppliers onto their platform. A $60M mechanical contractor cannot compel anyone.

**Sharpen the positioning accordingly.** You are not selling COI tracking. You are selling **vendor compliance verification with proof** — and when a prospect says "we use myCOI," the answer is "for certificates, sure. What about the licences, the W-9s, and the lien waivers? And can myCOI tell your insurer who was verified on the day of the incident?"

---

## 2. Market

- **Contractor Access Compliance market: $3.95B in 2026 → $6.18B by 2030, 11.9% CAGR.**
- **Contractor Compliance Management: $3.06B in 2026.**
- North America $1.19B in 2025 = **42.5% of global share**, driven by OSHA mandates, prevailing-wage requirements, state contractor licensing.
- Growth drivers: contingent workforce expansion, regulatory enforcement, construction safety, infrastructure spend.

That's a credible, citable TAM anchor for a deck — a real category with real budget, growing double digits, not an invented market. Note that these numbers cover the whole compliance-management space, so use the **serviceable** slice in a deck (mid-market NA operators with 200+ vendors), not the headline.

---

## 3. The buyer and the workflow

**Who signs:** VP/Director of Risk, Controller, VP Operations, or in smaller firms the CFO. In construction and field services it is often a **Contracts Administrator** reporting to ops.
**Who does the work:** a compliance coordinator or AP clerk, usually one to four people, usually with a spreadsheet of expiry dates.
**Who feels the pain:** whoever got the last insurance claim denied because a sub's coverage had lapsed.

**Best industries (by density of the problem):**
1. Specialty trade contractors and GCs (subcontractor compliance is existential — an uninsured sub on site is a company-ending liability)
2. Field services roll-ups (HVAC, electrical, plumbing, facilities) — PE-owned, multi-entity, chaotic after acquisitions
3. Property management and REITs (vendor COIs across hundreds of buildings)
4. Manufacturing and distribution (supplier quality certs, W-9s, conflict-minerals, food safety)
5. Staffing and logistics (carrier insurance verification — adjacent and large)

**The current-state workflow, in detail:**

```
Contract/PO created → requirements defined (usually in a Word template, often inconsistent)
   ↓
Coordinator emails vendor asking for documents
   ↓
Vendor sends PDFs (or doesn't — 40–60% require 2+ chases)
   ↓
Coordinator opens PDF, reads ACORD 25 form, checks:
     - correct named insured (matches vendor legal name? DBA? subsidiary?)
     - certificate holder = correct legal entity
     - GL / auto / umbrella / workers comp limits ≥ contract requirement
     - additional insured endorsement present (often a separate form!)
     - waiver of subrogation, primary & non-contributory
     - policy dates cover the work period
     - carrier AM Best rating acceptable
   ↓
Records expiry in spreadsheet → sets reminder → files PDF somewhere
   ↓
Repeats forever, misses some, discovers the gap during an audit or a claim
```

Every one of those checks is a rule. Every ambiguity in them is an exception. **This is an almost perfect fit for the architecture in `05`.**

---

## 4. Product spec deltas for this wedge

### Document types (v1 scope — put exactly this list in the SOW)
ACORD 25 (COI), ACORD 855/additional-insured endorsements, W-9, state contractor licence, business licence, workers-comp exemption forms, safety certifications (OSHA 10/30), MSA/subcontract agreements, lien waivers (conditional/unconditional, progress/final).

Everything else is v2 and out of scope. Scope discipline here is the difference between an 8-week build and a 20-week one.

### Core domain objects (extend the data model in `05 §4`)

```sql
vendors(id, workspace_id, legal_name, dba_names[], tax_id_hash, status, risk_tier)
vendor_entities(id, vendor_id, name, relationship)         -- subsidiaries, DBAs, JVs
requirement_sets(id, workspace_id, name, version)           -- "Tier 1 subcontractor"
requirements(id, requirement_set_id, doc_type, rule_json, severity, effective_from)
vendor_requirements(vendor_id, requirement_set_id, project_id, overrides_json)

compliance_documents(id, vendor_id, doc_type, artifact_id, issued_at, expires_at,
                     issuer, extracted_json, status, superseded_by)
coverage_lines(id, compliance_document_id, line_type, occurrence_limit,
               aggregate_limit, deductible, carrier, am_best_rating,
               effective_from, effective_to, endorsements_json)

compliance_checks(id, compliance_document_id, requirement_id, result,
                  observed_value, required_value, confidence, explanation, checked_at)
★ compliance_status(vendor_id, project_id, as_of, status, failing_requirements[],
                    computed_by_version)      -- point-in-time, never overwritten
chase_threads(id, vendor_id, requirement_id, channel, attempts, last_sent_at,
              status, next_action_at)
```

**`compliance_status` is the money table.** It is append-only and answers the question that gets asked in litigation and audits: *"was this vendor compliant on 14 March, and how do you know?"* No incumbent can answer that. Build it first.

### Rules library (ship ~35 of these; they're your template asset)
- Named insured matches vendor legal name or a registered DBA (fuzzy match → confidence signal)
- Certificate holder matches the contracting entity (multi-entity customers break every competitor here)
- GL occurrence ≥ required; GL aggregate ≥ required; per-project aggregate present if required
- Auto liability combined single limit ≥ required; hired/non-owned included
- Umbrella/excess ≥ required and sits over the correct underlying policies
- Workers comp present or a valid state exemption on file
- Additional insured endorsement present, on the right form edition, covering ongoing **and** completed operations
- Waiver of subrogation present; primary & non-contributory wording present
- Policy period covers the entire contract/work period
- Carrier AM Best rating ≥ threshold; carrier admitted in the state of work
- Cancellation notice provision meets contract terms
- Expiry ≥ N days out; auto-generate the chase at expiry − 45/30/15/5 days

Each rule stores a human-readable statement used verbatim in the review desk ("Umbrella limit is $1M; contract requires $5M") — this is what makes the operator trust it and what makes the audit export readable.

### The chase agent (your genuinely agentic component)
- Multi-touch email sequence to the vendor and their broker, escalating
- Parses the reply, matches the attachment to the open requirement, closes the loop or re-asks specifically ("you sent the GL cert; we still need the additional insured endorsement")
- Escalates to the internal owner after N attempts
- **Unambiguous success event = compliant document received and verified.** That is the unit you can charge for and the cleanest possible entry in the ledger.

Guardrails: never negotiate coverage terms, never state whether a vendor is approved to work, always send from a mailbox the customer owns, always CC the internal owner on escalation, hard cap on messages per vendor per week.

### Baseline template for this wedge
```
active_vendors                     N
requirements_per_vendor            N       (usually 3–7)
verifications_per_month            N
minutes_per_verification p50/p90   N / N   (observe 40; typically 6–8 / 20–30)
chase_emails_per_month             N
pct_requiring_2plus_chases         %       (usually 40–60%)
loaded_cost_per_hour               $
lapse_incidents_last_12mo          N
cost_of_last_lapse                 $       (claim denial, stop-work, audit finding)
audit_prep_hours_per_year          N       ← often the single biggest number, and always forgotten
```

**Ask for `audit_prep_hours_per_year` explicitly.** It's usually 80–200 hours nobody has ever counted, and it converts your product from a labour-savings story to an audit-readiness story, which is a much better story for a risk buyer.

### Exception taxonomy starter (seed `reason_code_taxonomy` with these)
`NAMED_INSURED_MISMATCH`, `DBA_VARIANT`, `HOLDER_WRONG_ENTITY`, `LIMIT_BELOW_REQUIRED`, `AGGREGATE_SHARED_NOT_PER_PROJECT`, `AI_ENDORSEMENT_MISSING`, `AI_FORM_EDITION_WRONG`, `COMPLETED_OPS_NOT_INCLUDED`, `WAIVER_SUBRO_MISSING`, `PRIMARY_NONCONTRIB_MISSING`, `WC_EXEMPTION_INVALID_STATE`, `POLICY_EXPIRES_MID_CONTRACT`, `CARRIER_RATING_LOW`, `CARRIER_NOT_ADMITTED`, `ILLEGIBLE_SCAN`, `WRONG_DOC_TYPE_SENT`, `MULTI_POLICY_SPLIT_ACROSS_PAGES`, `MANUAL_ALTERATION_SUSPECTED`, `EXPIRED_ON_ARRIVAL`, `DUPLICATE_SUPERSEDED`.

That list alone, shown in a first sales call, will do more to establish credibility than any deck. It says *we have done this before* — and after three customers it will have 80 entries nobody else has.

---

## 5. Pricing for this wedge

Different shape from `06` because this wedge is subscription-friendly and — critically for a raise — **you want the recurring line to dominate from day one.**

| | Price | Note |
|---|---|---|
| Proof Sprint | $12,000, 2 weeks | 200 historical documents, accuracy report, threshold curve, requirement-set config. Credited against year 1. |
| Implementation | **$25,000–$40,000** | Deliberately lower than `06`'s $55–95k. See `12` — you are optimising for recurring revenue, not project cash. |
| **Platform subscription** | **$3,000–$12,000/month** | Tiered by active vendors: <250 / 250–1,000 / 1,000–3,000 / 3,000+. Includes verification volume band, review desk seats, ledger, audit pack. |
| Overage / managed verification | $1.50–$4.00 per verified document beyond band | The outcome-priced line. Consistent with the 2026 norm of per-outcome pricing. |
| Audit pack + attestation | $5,000/yr add-on | Sells itself to risk and to PE-owned firms |

**Rough customer value:** 3 coordinators × ~40% of their time on this × $75k loaded ≈ $90k/yr labour, plus audit prep, plus the tail risk of one denied claim. A $60k/yr subscription against that is an easy yes if — and only if — you can prove the numbers. Which is the whole point of the ledger.

---

## 6. First 20 accounts for this wedge

Filter: US, $20–250M revenue, uses 200+ vendors/subcontractors, PE-owned or multi-entity.

Segments in priority order: specialty trade contractors ($30–150M), field-service roll-ups, multi-site property managers, mid-market GCs, food & beverage manufacturers (supplier certs), 3PLs (carrier insurance verification).

**Trigger events, strongest first:**
1. Hiring a "Contracts Administrator", "Compliance Coordinator", or "Risk Analyst" — a literal advertisement for this problem
2. Recent acquisition (two vendor lists, two requirement standards, no reconciliation — acute, urgent, budgeted)
3. Insurance renewal within 90 days (broker asks hard questions about subcontractor controls; your buyer needs an answer)
4. A published OSHA citation or a public claim dispute
5. New state/market entry (new licensing requirements)

**Warm paths:** insurance brokers serving mid-market contractors are the single best referral channel in this entire wedge. The broker's account manager is the person who tells the client "your COI tracking is a mess." Take three brokers to lunch before you send a single cold email. A broker referral partnership — where they recommend you and you make their book less risky — is worth more than any marketing you could do, and it is defensible.
