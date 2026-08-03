# Risk, compliance and legal

---

## 1. Regulatory position (as of August 2026)

### EU AI Act
- **The high-risk deadline moved.** Digital Omnibus on AI: political agreement 7 May 2026, European Parliament approval 16 June 2026. Annex III (use-based high-risk) obligations shift from **2 Aug 2026 → 2 Dec 2027**. Annex I (product-regulated) from Aug 2027 → Aug 2028.
- **What did not move:** transparency obligations, governance provisions, national supervision, AI-literacy requirements, and existing GPAI obligations. These are live now.
- **Practical read for you:** document-processing workflows in back-office operations are generally *not* Annex III high-risk. Where you must be careful: anything touching **employment decisions, creditworthiness, access to essential services, or insurance pricing**. Two consequences:
  1. Keep your first three workflows away from those categories. (Also good commercial advice — those deals are slow.)
  2. Build the technical documentation, logging, human oversight and accuracy-monitoring capabilities anyway. They're the same features that sell to a CFO, and if you ever take a high-risk workflow you will not have 18 months to retrofit them.
- If you serve EU customers or process EU personal data, you also carry GDPR obligations regardless of the AI Act.

### ISO/IEC 42001 and SOC 2
- ISO 42001 is turning into a procurement gate: **83% of Fortune 500 procurement teams plan to require ISO 42001 alignment by 2027**. Certified already: Snowflake (Jun 2025), Salesforce (Oct 2025), ServiceNow (Dec 2025), BCG (Jan 2026).
- Consensus for 2026 procurement: **SOC 2 + ISO 42001 together**. 42001 is an AI *management system* standard (policies, objectives, roles, risk treatment, monitoring, documentation, continual improvement); SOC 2 is a controls attestation. They complement, not substitute.
- **Sequence for you:** SOC 2 Type I readiness at ~customer 3 (months 4–6), Type II at months 9–12, ISO 42001 gap assessment only when a specific deal requires it. Don't burn early cash on certification theatre — but do keep the evidence from day one, because the expensive part of both is retroactive evidence collection.
- **Product angle:** only **9% of PE firms are confident they could pass an AI audit within 90 days** (Grant Thornton, n=950). Your audit-pack export is a feature you can charge for and lead with in that channel.

### US / sectoral
- No comprehensive federal AI statute; state patchwork (Colorado, California, Texas, Illinois for employment/biometrics). Sectoral rules bite in healthcare (HIPAA — BAA required before you touch PHI), financial services, and insurance.
- If you touch payments/AP: SOX-relevant controls at any customer with an audit. Your immutable audit log and segregation of approval roles are directly relevant. Say so in sales.

---

## 2. Contracts — the clauses that matter

**MSA + SOW structure**, not a single agreement. Key positions:

| Clause | Your position | Why |
|---|---|---|
| Data ownership | Customer owns their data and their workflow configuration | Removes the biggest objection instantly |
| Derived rights ★ | You retain a licence to use **de-identified, aggregated statistics and derived exception patterns** to improve the platform | This is your moat. Negotiate it explicitly and never bury it — buried clauses get discovered and poison renewals |
| Training | Customer data is **not** used to train third-party models; provider-side fine-tuning only with specific written opt-in | Easy concession, big trust win, and true if you configure your providers correctly (check zero-retention/no-training settings and get them in writing from the provider) |
| IP in deliverables | You own the platform and all generic components; customer gets a perpetual licence to their configuration and an export of their data | Prevents the "we paid for it so we own it" fight |
| Accuracy / SLA | Availability SLA yes. **Accuracy warranty only against the agreed golden set and only for the document types in scope** | Never warrant accuracy on unseen document types. This clause has bankrupted agencies |
| Liability cap | Fees paid in the preceding 12 months; carve-outs only for confidentiality and IP infringement | Standard; hold the line on consequential damages |
| Human oversight | Explicit: the system proposes, a human approves above defined thresholds; customer configures thresholds | Shifts risk correctly and is your AI Act / governance story |
| Subprocessors | Listed, with notice of change | Model providers are subprocessors. List them |
| Termination | Data export in a documented format within 30 days; configuration export included | Removes lock-in fear, which mid-market buyers feel acutely after being burned |
| Insurance | E&O / professional liability **$1–2M**, plus cyber. Get it before customer 1 | Some customers require proof; all of them should |

**DPA** required whenever personal data flows (vendor contacts, employee data in invoices, customer names in orders — this is almost always). **BAA** if healthcare PHI, and don't take that engagement before you're ready for it.

---

## 3. Technical risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Prompt injection via ingested documents** | High | High | LLM cannot select tools or route; rules own control flow; tool allow-lists; egress allow-list; injection canaries in every golden set; value-at-risk limits force human review |
| **Silent accuracy drift** (customer changes a template) | Very high | High | Rolling correction-rate per sender/doc-type with alerting; sampled audit; monthly drift review is a Run & Improve deliverable |
| **False-auto** (auto-approved and wrong) | Medium | Very high | This is *the* metric. Conservative θ_auto at launch; value-at-risk cap; sampled audit at ≥2%; incident process with customer notification |
| **Model deprecation / price change** | Certain | Medium | Provider abstraction; model as versioned config; eval gate re-runs on model change; cost pass-through capped in contract |
| **Data leakage across tenants** | Low | Catastrophic | RLS from day one, per-workspace DEKs, separate S3 prefixes, tenancy tests in CI, no cross-tenant queries in code review checklist |
| **Credential compromise** | Low | Catastrophic | KMS envelope encryption, no plaintext in logs/traces, rotation, access logging, least-privilege scopes on every OAuth grant |
| **Runaway cost** | Medium | Medium | Per-workspace token budgets with hard stops; cost recorded per execution; alert at 80% of monthly cap |
| **Vendor lock (Temporal/Langfuse/provider)** | Low | Low | All three are self-hostable or replaceable; keep your own `execution_steps` as the business record |
| **Backlog/queue collapse under a volume spike** | Medium | Medium | Queue depth alerts, priority by value-at-risk, documented degraded mode (route everything to human, tell the customer immediately) |

---

## 4. Business risk register

| Risk | Mitigation |
|---|---|
| **The capacity trap** — services revenue crowds out product | Rule of thirds (`03 §1`); month-12 exit condition defined in advance; never take an out-of-vertical project for cash |
| **Wedge is wrong** | The 8-teardown gate at week 4. If nobody buys a Proof Sprint, change the wedge, not the pitch |
| **A model vendor or incumbent absorbs the workflow** | Stay where they won't go (sub-$250M revenue, unglamorous verticals, exception-heavy work); own the *evidence layer*, which is structurally against an incumbent's interest to build |
| **The JVs come downmarket** | Realistic in 24–36 months. Answer: by then you own vertical exception data and integrations they'd have to buy. Also — become a partner rather than a competitor if the option appears |
| **Single-customer concentration** | No customer >40% of revenue after month 9 |
| **Reference dependency** | Get written permission for a named reference in the *first* SOW, not after |
| **Key-person risk (you)** | Runbooks, ADRs, recorded walkthroughs from month 1. Also an insurance and diligence requirement later |
| **Operators sabotage the pilot** | Interview Q26 in `07 §1`; make the operator a named stakeholder; never sell a project whose stated purpose is layoffs in the first engagement |
| **Fixed-fee overrun** | Proof Sprint de-risks estimation; customer-obligations clause; strict change control; 10-day acceptance windows defined up front |

---

## 5. Ethics and stance (write this down before someone asks)

You will be asked, by operators and eventually by press or a customer's works council: *"is this taking jobs?"* Have a real answer, not a slogan.

Suggested stance, and one you can actually defend:
- You automate **work**, and you are explicit with the sponsor about whether the plan is redeployment or reduction. You ask in discovery (Q26) and you record the answer.
- You do not sell "headcount reduction" as the headline outcome in the first engagement. It poisons adoption, and adoption is what makes the numbers real.
- Human review is a permanent design feature, not a transitional phase. The people who did the work become the people who supervise and improve it — and their corrections are, literally, the most valuable data in your company. Pay that forward by naming them in the value reports.
- You publish measured error rates, including your own. A vendor who only reports wins is not measuring.

This is not decoration. In field services and distribution, the operators you're automating around are often long-tenured and well-liked, and the sponsor's real constraint is "I can't be seen to fire Debbie." Knowing that changes how you scope, price and present the work.
