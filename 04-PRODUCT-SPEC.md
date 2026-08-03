# Product specification

Working name for the platform: **Ledger** (rename later). Internal delivery platform first, customer-facing product second.

---

## 1. The product in one diagram

```
                    ┌──────────────────────────────────────────┐
   DISCOVER  ──────▶│  Workflow Canvas + Baseline Capture      │
                    └──────────────────┬───────────────────────┘
                                       │  baseline_version (frozen)
                    ┌──────────────────▼───────────────────────┐
   BUILD     ──────▶│  Workflow Designer (versioned DAG)       │
                    │  nodes: trigger|parse|extract|rule|llm|   │
                    │         retrieve|tool|approve|notify|halt │
                    └──────────────────┬───────────────────────┘
                                       │  workflow_version (immutable)
    ┌──────────────────────────────────▼───────────────────────┐
    │  RUNTIME — durable, replayable, per-step audited          │
    │  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌───────────┐ │
    │  │ Ingest   │─▶│ Process   │─▶│ Decide  │─▶│ Act       │ │
    │  └──────────┘  └───────────┘  └────┬────┘  └───────────┘ │
    └───────────────────────────────────┬┴───────────────────── ┘
                        low confidence  │  high confidence
                    ┌──────────────────▼─────────┐        │
   REVIEW    ──────▶│  Human Review Desk         │        │
                    │  → correction + reason code │        │
                    └──────────────┬─────────────┘        │
                                   │                       │
                    ┌──────────────▼───────────────────────▼───┐
   MEASURE   ──────▶│  VALUE REALIZATION LEDGER                │
                    │  value_event per run, tied to baseline   │
                    │  → CFO report, audit export, SLA proof   │
                    └──────────────────┬───────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────┐
   IMPROVE   ──────▶│  Golden sets ← corrections               │
                    │  Eval runs gate every workflow_version   │
                    └──────────────────────────────────────────┘
```

The loop that matters: **corrections become golden cases become eval gates become higher automation rate become a bigger number in the ledger.** Everything else is plumbing.

---

## 2. Modules

### M1 — Workspace & tenancy
Organisations, workspaces (one per customer engagement), users, roles.

Roles: `owner`, `admin`, `builder`, `operator` (review desk only), `viewer` (dashboards only), `auditor` (read-only + export, sees everything including PII access logs).

Must support **your org operating a customer's workspace** (delivery mode) and **the customer operating it themselves** (handoff mode) with the same code path and a flag. Get this right on day one; retrofitting tenancy is a rewrite.

### M2 — Workflow discovery & baseline capture
This is the module nobody builds well and it is half your differentiation.

**Discovery intake** — structured, not a blank canvas:
- Trigger: what starts this? (email arrives / file dropped / schedule / someone notices)
- Inputs: what documents/systems/knowledge are needed?
- Steps: what does a person actually do, in order? (free text per step + system used + minutes)
- Decisions: what are they deciding, and on what basis?
- **Exceptions: what makes this one weird?** ← ask five times, keep asking
- Approvals: who signs off, and what would make them say no?
- Outputs: what exists at the end, and where does it live?
- Failure: what happens when it goes wrong, and how often?

**Baseline capture** — the part that makes you credible. Recorded *before* any build, signed off by the customer sponsor:
```
volume_per_month
minutes_per_instance (p50, p90)   ← get both; averages lie
fully_loaded_cost_per_hour
error_rate_pct + cost_per_error
rework_rate_pct
cycle_time_hours (received → done)
headcount_touching
peak_backlog
```
Signed baseline is a first-class object: `baseline_version`, frozen, hash-stamped, referenced by every value_event forever. **When the CFO challenges your savings number in month 9, you show them their own CFO's signature on the baseline.**

**Opportunity scoring** — deterministic formula, not vibes:
```
current_annual_cost = volume/mo × 12 × p50_minutes/60 × loaded_rate
                    + volume/mo × 12 × error_rate × cost_per_error

automatable_pct     = f(structure, rule_clarity, exception_rate, data_availability)   [0..1]
projected_savings   = current_annual_cost × automatable_pct
                    − model_cost − infra_cost − (review_rate × review_minutes × loaded_rate)

priority_score      = (projected_savings × confidence)
                      / (effort_weeks × risk_multiplier)
```
Show the inputs. Let them argue with the inputs. Never show a score without its inputs — that's what makes it consulting rather than a black box.

**AI assist:** paste an SOP, a recorded interview transcript, or a screen-recording narration → draft workflow graph + draft exception list + suggested baseline questions. Human confirms. This is where an LLM earns its place — turning a 90-minute interview into a structured graph in 30 seconds is a genuine wow moment in the sales process.

### M3 — Workflow designer & versioning
A DAG, not a chat agent. Node types:

| Node | Purpose | Determinism |
|---|---|---|
| `trigger` | inbox, webhook, schedule, folder watch, manual | deterministic |
| `fetch` | pull document/record from source | deterministic |
| `parse` | PDF/image/email → text + layout + tables | deterministic (with a model inside) |
| `classify` | document/intent type | model, constrained enum output |
| `extract` | structured fields per schema | model, JSON-schema constrained |
| `retrieve` | RAG over policy/knowledge/master data | deterministic retrieval, cited |
| `rule` | validation, matching, arithmetic, policy checks | **pure code — no model** |
| `score` | confidence aggregation → route | deterministic function of signals |
| `llm` | bounded judgement with a written rubric | model |
| `tool` | write/act via MCP, API, or RPA of last resort | deterministic call |
| `approve` | create a review task, block until resolved | human |
| `notify` | email/Slack/Teams | deterministic |
| `halt` | dead-letter with reason | deterministic |

**Non-negotiable design rules:**
1. **The LLM never chooses the next node.** Routing is `rule`/`score`. Models produce content and judgements inside a node; the graph controls flow. (This is the difference between a demo and a production system, and it's the consensus of everyone who has shipped agents at scale.)
2. **Every model call is schema-constrained** and its schema is versioned with the workflow.
3. **Every `tool` node that writes declares an idempotency key** and a compensating action.
4. **Versions are immutable.** Publishing creates `workflow_version N+1`; running executions finish on the version they started on.
5. **A version cannot be published unless it passes its eval gate.** Enforced in the product, not in a checklist.

### M4 — Confidence & routing
The commercial heart of the system. Straight-through rate is what you sell; confidence calibration is what produces it.

Confidence is **not** the model's self-reported number. Compute it:
```
signals = {
  extraction:  per-field model logprob/consistency across n samples,
  validation:  count and severity of failed rules,
  matching:    master-data match score (exact / fuzzy / none),
  novelty:     distance from seen document layouts for this sender,
  history:     this sender/vendor's historical correction rate,
  amount:      value at risk in the transaction
}
confidence = calibrated_model(signals)          # start with a weighted rule, learn later
route = auto            if confidence ≥ θ_auto and value_at_risk < limit
        review          if θ_review ≤ confidence < θ_auto
        halt/escalate   otherwise
```
Thresholds are **per-customer, per-workflow, editable in the UI, versioned, and logged.** Let the customer choose their own risk posture — it converts a technical parameter into a governance conversation they feel in control of, and it makes every subsequent accuracy dispute a conversation about *their* setting.

Ship a **threshold simulator**: "at θ=0.85 you'd auto-process 71% with an estimated 1.2% error; at θ=0.92, 54% with 0.3%." Run against historical data. This one screen sells the product.

### M5 — Human Review Desk ★ (build this best)
Where the work gets finished and where your moat is generated.

Screen layout: document/source on the left, extracted+editable fields on the right, validation failures and the reason for review at the top, action bar at the bottom.

Must-haves:
- **Field-level provenance** — click a field, highlight where it came from in the source. Non-negotiable for trust.
- **Reason-for-review shown explicitly** — "vendor not in master data", "total ≠ sum of lines", "coverage limit below required $2M".
- **Keyboard-first.** Tab between fields, `Enter` approve, `E` edit, `R` reject, `?` help. Operators process hundreds a day; mouse-driven UIs get abandoned and abandonment kills your adoption metric.
- **Structured correction capture** — every edit records `field`, `old`, `new`, and a **reason code** from a per-workflow taxonomy (plus free text). This is the data asset. Make the reason code required but one keystroke.
- **Bulk actions** with guardrails — approve-all-matching for a batch of identical low-risk cases, with a hard cap and an audit entry.
- **Queue management** — assignment, SLA timers, aging, priority by value-at-risk.
- **Escalation path** — operator → supervisor → customer sponsor, each with a reason.
- Every review action writes to the audit log and emits a `value_event` (a human touch is a cost, and honest accounting of it is what makes your savings number believable).

### M6 — Connectors & credential vault
Strategy: **MCP-first.** Do not hand-write 30 integrations.

- **MCP gateway** — connect any MCP server; per-tool allow-list; per-workspace scoping; full call logging; Enterprise-Managed Authorization support for org-level authz.
- **First-party connectors (build only these):** email ingestion (Microsoft Graph / Gmail API — the trigger for both wedges), object storage (SharePoint/Drive/S3), outbound notify (Slack/Teams/SMTP), generic REST + webhook, SFTP, Postgres/MSSQL read, CSV/Excel in-out.
- **Credential vault** — envelope encryption, per-workspace DEK, KMS-backed KEK, no plaintext in DB or logs, OAuth token refresh, rotation, and an access log the auditor role can read.
- **RPA is the escape hatch of last resort** for ERPs with no API (Prophet 21, older Infor). Isolate it, budget it separately, and price it high — it is the most brittle thing you will own.

**Security stance for MCP** (this is now a documented attack surface): treat tool descriptions and tool outputs as untrusted input. Never let retrieved content or tool results modify the plan. Allow-list tools per workflow_version. Log every call with arguments. Read the CSA/CoSAI MCP security guidance before exposing this to a customer's systems.

### M7 — Execution inspector
Per run: state machine timeline, node-by-node input/output, model+prompt version, retrieval citations, tool calls with arguments and responses, retries, errors, human interventions, tokens, latency, cost, final outcome. Replay a run against a new workflow_version without side effects (dry-run mode with tools stubbed).

Build the *business* view of this yourself; delegate span storage to Langfuse (self-hosted, OTel) rather than writing a trace backend.

### M8 — Rules & policy
Customer-editable rules without code:
- field validators (required, format, range, cross-field arithmetic)
- master-data matching (vendor list, SKU catalogue, GL codes, approved carriers)
- policy checks ("COI must name us as additional insured", "coverage ≥ $2M", "expiry > 30 days out")
- routing rules (by amount, by entity, by department)
- Rules are versioned with the workflow, testable against historical data, and each has a human-readable statement used verbatim in the review desk explanation.

### M9 — Evaluation & golden sets
- Golden set per workflow, built from real corrected cases (with contractual rights — see `09`).
- Metrics: field-level precision/recall, exact-match rate, straight-through rate, false-auto rate (**the one that matters — auto-approved and wrong**), review-rate, cost/run.
- **Eval gate:** publishing a workflow_version runs the golden set; regression beyond threshold blocks publish.
- Drift watch: rolling correction-rate per sender/document-type; alert when a customer changes their PO template and accuracy quietly drops.

### M10 — Value Realization Ledger ★ (the differentiator)
Every execution emits one or more `value_event` rows:

```
value_event {
  execution_id, workflow_version_id, baseline_version_id,
  kind: touch_avoided | time_saved | error_prevented | cycle_time_reduced
      | human_touch_cost | model_cost | infra_cost | rework,
  quantity, unit,
  dollar_value,
  method: baseline_rate | measured_ab | customer_asserted | sampled_audit,
  confidence: high | medium | low,
  computed_at, formula_version
}
```

Rules that make it defensible:
- **Costs are recorded with the same rigour as savings.** Human review time, model spend, and rework are all negative value_events. A ledger that only counts wins is marketing; one that counts both is evidence.
- **Every number carries its method.** `baseline_rate` (multiply by the signed baseline) is weaker than `measured_ab` (holdout sample). Show the mix. When a CFO asks "how do you know", the answer is on the screen.
- **Sampled audit built in.** Continuously route a small random % of high-confidence runs to human review anyway. That gives you a *measured* true error rate rather than an assumed one — and it is the single most persuasive thing you can put in a QBR.
- **Immutable and exportable.** CSV/PDF export with run-level drill-down for the customer's auditors.

Dashboard surfaces: volume processed, straight-through rate, review rate, measured error rate, average cycle time vs baseline, hours saved, net dollars saved, cost per completed unit, cumulative ROI and payback date, adoption by user/department.

### M11 — Governance & audit
- Full audit log: who saw what, who changed what, who approved what, every credential access, every export.
- Data retention policy per workspace (delete source documents after N days, keep extracted fields + hashes).
- PII handling: detection, redaction before model calls where feasible, field-level access control.
- Model registry: which model/version/provider each node used, with a change log. Needed for AI Act transparency obligations and for ISO 42001 evidence.
- **Audit pack export** — one button producing a dated bundle: workflows in production, versions, model list, human oversight design, error rates, incidents, data flows. Given that only 9% of PE firms feel ready for an AI audit, this feature sells on its own.

---

## 3. MVP cut line

**In (weeks 1–10 of build, alongside your first paying engagement):**
M1 tenancy (basic), M2 discovery form + baseline + scoring, M3 designer with 8 node types (skip `retrieve` initially), M4 confidence + thresholds, **M5 review desk — full quality**, M6 email + storage + notify + REST + vault, M7 inspector (basic), M8 rules, M10 ledger (core events + one dashboard).

**Out of MVP, deliberately:**
- Drag-and-drop canvas (use a form + generated read-only React Flow view; a full editable canvas is 4 weeks you don't have)
- Self-serve signup and billing
- Marketplace, templates gallery
- Fine-tuning anything
- Multi-region
- Mobile app (review desk should be responsive, not native)
- Process mining / event-log ingestion (v2)
- Vector DB (only when a `retrieve` node is genuinely needed; pgvector when it is)

**The cut-line test:** does this feature appear in the first customer's weekly demo or in their ROI report? If neither, it waits.

---

## 4. Screens (build order)

1. **Review Desk** — build first, even before the designer. It is the product's soul and the demo that closes deals.
2. **Run Inspector**
3. **Workflow Discovery + Baseline**
4. **Opportunity Scoring / ROI**
5. **Workflow Designer (form-driven) + read-only graph**
6. **Rules Editor**
7. **Connections & Credentials**
8. **Outcome Dashboard**
9. **Threshold Simulator**
10. **Audit Log + Audit Pack Export**
11. **Versions & Eval Results**
12. **Org / Users / Roles**

---

## 5. User stories that define "done"

**Operator (the person whose day this changes)**
- I open the desk and see only what needs me, ordered by what matters, with the reason it needs me stated in one line.
- I can clear an item in under 20 seconds without touching the mouse.
- When I correct something, I never see that same mistake class again next month.

**Workflow owner (your buyer's deputy)**
- I can see this week's volume, what got through automatically, what didn't, and why.
- I can change a rule or a threshold myself and see the simulated effect before I commit.
- When something goes wrong I can find the exact run in under 60 seconds.

**CFO / sponsor (the person who renews you)**
- I can see, this quarter, how many units were processed, what it cost, what it used to cost, and how you calculated the difference.
- I can click any number and reach the individual records behind it.
- I can hand the export to my auditor without writing an explanation.

**You (delivery)**
- I can stand up a new customer's workflow from an existing template in under a day.
- I can ship a change and know it didn't regress, because the eval gate says so.
- I can prove what happened in a run from six weeks ago.
