# Architecture

Assumes 1–3 engineers, first paying customer in weeks, correctness and auditability over scale.

---

## 1. Stack decisions (with the reasoning, so you can revisit them)

| Layer | Choice | Why | Revisit when |
|---|---|---|---|
| Frontend | Next.js + TypeScript, TanStack Query, shadcn/ui, React Flow (read-only at first) | You know it; review desk needs a real app, not a notebook | never |
| API | FastAPI + Pydantic v2 + SQLAlchemy 2.0 | Python keeps you in one language with the AI code; Pydantic is your schema-constrained-output layer for free | if you need >5k rps (you won't) |
| DB | PostgreSQL 16 (+ pgvector only when needed) | One database for config, runs, ledger, queue. Boring is correct here | when a single table passes ~500M rows |
| Cache/queue | Redis + a Postgres-backed outbox | Simple, debuggable | with Temporal, Redis stays for cache only |
| Orchestration (v1) | **Postgres-backed durable state machine** (see §3) | 2–3 days of work, zero ops, full visibility, replayable | see trigger below |
| Orchestration (v2) | **Temporal** (self-hosted or Cloud) | Durable execution is the actual hard problem; Temporal is the standard, OpenAI runs it for Codex, and there's a first-party LangGraph plugin | **Trigger: first workflow spanning >24h, OR >2 external write systems, OR the third time you hand-write retry/compensation logic** |
| Agent inner loop | LangGraph, only inside a single node | Bounded judgement loops (multi-step extraction, chase-email negotiation). Never for top-level control flow | — |
| Object storage | S3-compatible (R2/S3/MinIO) | Documents, with per-workspace prefixes and SSE-KMS | — |
| Models | Provider abstraction over Anthropic / OpenAI / Google, with structured outputs | Never hard-code a model id in a workflow. Model is a versioned config value | — |
| Observability (LLM) | **Langfuse self-hosted** (OTel-native) | Don't build a trace store. Self-host so customer data doesn't leave your boundary — this matters in sales | if Braintrust's eval UX saves more time than the SaaS-data objection costs |
| Observability (app) | OpenTelemetry → Grafana/Tempo or Datadog; Sentry | — | — |
| Auth | Better-Auth / Auth.js or Clerk for app; per-workspace RBAC in your own tables | Don't outsource authorization, only authentication | — |
| Deploy | Docker + Fly.io/Render/ECS; Terraform from month 3 | Speed now, reproducibility soon | when a customer demands VPC deployment (plan for it, see §7) |

**Explicitly rejected:**
- Building your own trace/eval UI (weeks of work, zero differentiation)
- Kubernetes before customer #3
- A vector database as core infrastructure (pgvector when you actually need retrieval, and you may not for either wedge)
- A visual node editor as an MVP feature
- n8n/Temporal-as-the-product (they're infrastructure, not your surface)

---

## 2. Service decomposition

Start as a **modular monolith** with hard internal boundaries, not microservices.

```
app/
  api/            FastAPI routers (thin; no logic)
  domain/
    workflows/    definition, versioning, publish, eval gate
    runtime/      executor, node handlers, state machine
    review/       queue, tasks, corrections, reason codes
    connectors/   mcp gateway, first-party connectors, vault
    models/       provider abstraction, prompt registry, structured output
    rules/        rule engine, evaluation of validators
    ledger/       baselines, value_events, rollups, exports
    evals/        golden sets, runs, gates, drift
    governance/   audit log, retention, audit pack
  workers/        queue consumers (one process type per class of work)
  migrations/
```

Rules: domains talk through explicit interfaces; only `runtime` writes `execution*`; only `ledger` writes `value_event`. When you eventually split services, the seams are already there.

---

## 3. The runtime (the part to get right)

### v1 — durable state machine on Postgres

```
executions(id, workflow_version_id, status, current_node, context_ref, attempt, ...)
execution_steps(id, execution_id, node_id, seq, status, input_ref, output_ref,
                started_at, ended_at, error, attempt, idempotency_key)
```

Loop:
1. Worker claims an execution with `SELECT ... FOR UPDATE SKIP LOCKED`.
2. Loads node definition from the **immutable** `workflow_version`.
3. Checks `execution_steps` for an existing successful step with the same `(execution_id, node_id, attempt_group)` → **skip if already done** (this is what makes replay safe).
4. Executes the node handler with a timeout.
5. Writes the step row and the new context **in one transaction** with the execution state update.
6. Emits `value_event`s and audit rows via the outbox.
7. Advances via the routing function; on `approve` node → creates a review task and sets status `waiting_human`; on failure → retry policy or `halt`.

Properties you get cheaply: crash-safe (worker dies mid-node → step is not committed → retried), replayable, inspectable in SQL, and every state transition is auditable.

Properties you don't get: timers beyond a polling loop, cross-service sagas, signals, multi-day sleeps at scale, versioned in-flight migration. **Those are the Temporal triggers.**

### v2 — Temporal
When triggered: one Temporal Workflow per execution; each node becomes an Activity; human approval becomes a Signal; SLA timers become Timers; the LangGraph inner loop runs inside an Activity via the official plugin. Your `execution_steps` table stays as the *business* record (Temporal's history is for the engine, yours is for the auditor and the customer). Do not throw away the tables when you migrate.

### Node handler contract
```python
class NodeResult(BaseModel):
    outputs: dict
    confidence: float | None
    signals: dict          # feeds the confidence model
    value_events: list[ValueEvent]
    citations: list[Citation] | None
    cost: CostRecord
    next_hint: str | None  # advisory only; routing rules decide

async def handle(node: NodeSpec, ctx: ExecContext) -> NodeResult: ...
```
Every handler is: pure w.r.t. its declared inputs, idempotent given `idempotency_key`, and time-bounded.

### Model call discipline
- All model calls go through one client that enforces: schema-constrained output, prompt-version stamping, timeout, retry with backoff, token+cost recording, trace emission, and PII redaction hooks.
- Prompts live in a registry (`prompts`, `prompt_versions`), referenced by id+version from the workflow_version. **Never inline a prompt in code.** You will need to answer "what exactly did you send the model on 14 March" and you will need to A/B prompt versions.
- Structured output first, free text never. If a node needs prose, it still returns `{"text": ..., "rationale": ..., "flags": [...]}`.

---

## 4. Data model

Core, with the additions your original list was missing marked ★.

```sql
-- tenancy
organizations(id, name, kind)                       -- kind: internal|customer|partner
workspaces(id, org_id, name, environment)           -- one per engagement
users(id, email, name)
memberships(user_id, workspace_id, role)

-- discovery & value  ★ this cluster is the differentiator
processes(id, workspace_id, name, department, owner_user_id, system_of_record)
process_interviews(id, process_id, transcript_ref, captured_by, captured_at)
process_steps(id, process_id, seq, description, system, minutes_p50, minutes_p90, is_decision)
★ baselines(id, process_id, version, status, signed_by, signed_at, hash)
★ baseline_metrics(baseline_id, key, value, unit, source)   -- volume, minutes, rate, error_rate...
★ opportunity_scores(id, process_id, baseline_id, projected_savings, automatable_pct,
                     effort_weeks, risk_multiplier, priority_score, inputs_json, computed_at)

-- definition
workflows(id, workspace_id, process_id, name, status)
workflow_versions(id, workflow_id, version, spec_json, published_at, published_by,
                  eval_run_id, immutable_hash)
workflow_nodes(id, workflow_version_id, node_key, type, config_json)
workflow_edges(id, workflow_version_id, from_node, to_node, condition_json)
★ thresholds(id, workflow_version_id, key, value)   -- θ_auto, θ_review, value_at_risk_limit

-- integration
connectors(id, workspace_id, kind, config_json)      -- kind: mcp|graph|gmail|s3|rest|sftp|db
credentials(id, connector_id, ciphertext, dek_id, rotated_at)
★ mcp_servers(id, workspace_id, url, auth_mode, allowed_tools_json)
data_sources(id, workspace_id, connector_id, path, schema_json)

-- execution
executions(id, workflow_version_id, trigger_ref, status, started_at, ended_at,
           outcome, context_ref, correlation_key)
execution_steps(id, execution_id, node_key, seq, status, input_ref, output_ref,
                confidence, signals_json, error, attempt, idempotency_key, cost_json)
tool_calls(id, execution_step_id, tool_name, args_json, result_ref, latency_ms, error)
artifacts(id, workspace_id, kind, storage_ref, sha256, mime, pii_flags, retention_until)
★ citations(id, execution_step_id, artifact_id, locator_json, quoted_text)

-- human
review_tasks(id, execution_id, workflow_version_id, reason_codes, assigned_to,
             status, sla_due_at, value_at_risk, created_at, resolved_at)
★ corrections(id, review_task_id, field_path, old_value, new_value,
              reason_code, note, corrected_by, corrected_at)
★ reason_code_taxonomy(id, workflow_id, code, label, category, active)
approvals(id, review_task_id, decision, decided_by, decided_at, rationale)

-- models & quality
prompts(id, workspace_id, key)
prompt_versions(id, prompt_id, version, body, variables_json, created_at)
model_configs(id, workspace_id, key, provider, model_id, params_json)
★ golden_sets(id, workflow_id, name, created_from)   -- created_from: corrections|manual
★ golden_cases(id, golden_set_id, input_ref, expected_json, source_execution_id, tags)
eval_runs(id, workflow_version_id, golden_set_id, metrics_json, passed, run_at)

-- value  ★ the ledger
★ value_events(id, execution_id, workflow_version_id, baseline_id, kind, quantity, unit,
               dollar_value, method, confidence, formula_version, occurred_at)
★ value_rollups(id, workspace_id, workflow_id, period, metrics_json, computed_at)
cost_records(id, execution_id, provider, tokens_in, tokens_out, usd, at)

-- governance
audit_logs(id, workspace_id, actor_id, action, target_type, target_id,
           before_json, after_json, ip, at)
★ data_access_logs(id, workspace_id, actor_id, artifact_id, purpose, at)
retention_policies(id, workspace_id, artifact_kind, days, action)
★ incidents(id, workspace_id, workflow_id, severity, summary, detected_at,
            resolved_at, root_cause, customer_notified_at)
```

**Design notes worth defending:**
- `baseline_id` on `value_events` — savings are always relative to a *specific signed baseline*. Non-negotiable.
- `formula_version` on `value_events` — when you improve the savings formula, old events keep their old maths. Otherwise your historical ROI silently rewrites itself, which is the fastest way to lose a CFO's trust permanently.
- `reason_code_taxonomy` is per-workflow and versioned — this table becomes your exception knowledge asset.
- `corrections` links to `golden_cases` — the loop is a foreign key, not a process document.
- `citations` with a locator (page, bbox, char range) — powers field-level provenance in the review desk.
- `incidents` — you will have them; a customer-visible incident record with root cause is worth more in a renewal conversation than any dashboard.

---

## 5. Multi-tenancy and isolation

Three tiers, priced accordingly:

1. **Shared (default)** — one database, `workspace_id` on every table, RLS policies in Postgres enforced at the connection level (set `app.workspace_id` per request), separate S3 prefixes and per-workspace DEKs.
2. **Isolated schema** — dedicated Postgres schema per customer. For customers who ask "is our data mixed with others?" Cheap to offer, expensive to describe as anything else.
3. **Customer VPC / single tenant** — full deployment in their cloud. Charge a large premium; automate with Terraform modules from the start so this doesn't become a bespoke nightmare.

**Do the RLS work in week 1.** Retrofitting row-level security after 10 customers is a security incident waiting to happen.

---

## 6. Security architecture

- **Secrets:** envelope encryption. KEK in cloud KMS, per-workspace DEK, ciphertext in Postgres. No secret ever in logs, traces, or LLM prompts. Automatic redaction in the model client, tested.
- **PII:** classify artifacts on ingest; redact-before-model where the workflow allows; field-level access control in the review desk; `data_access_logs` for anything a human opened.
- **Prompt injection is your #1 technical risk.** Both wedges ingest attacker-influenceable documents (anyone can email you a PDF). Defences, layered:
  - Documents and tool outputs are **data**, never instructions. Structural separation in prompts, plus explicit system instruction that content in the document channel is untrusted.
  - The LLM cannot choose tools or routing — only `rule` nodes can. This eliminates most of the impact.
  - Tool allow-lists per workflow_version; write tools require an idempotency key and, for high-value actions, an `approve` node.
  - Value-at-risk limits: any action above a threshold routes to human regardless of confidence.
  - Egress allow-list for outbound HTTP from workers.
  - Injection canaries in the golden set — cases containing "ignore previous instructions"-style payloads that must be handled correctly, run on every publish.
- **MCP-specific:** treat server tool descriptions as untrusted (they are model-visible text from a third party), pin server versions, allow-list tools, log every call. Follow the CSA/CoSAI MCP security guidance.
- **Supply chain:** pin dependencies, SBOM, Dependabot, no `curl | sh` in Dockerfiles.

---

## 7. Environments and deployment

- `dev` (local docker-compose) → `staging` (real connectors, synthetic data) → `prod`.
- **Per-customer sandbox workspace** is a product feature, not just an environment: they can safely replay historical documents against a new workflow_version before it goes live. This is how you get customers comfortable with changes and it costs you almost nothing once dry-run mode exists.
- CI: lint, types, unit, integration against ephemeral Postgres, **golden-set eval on any change to prompts/workflows**, migration check.
- Migrations: Alembic, forward-only, expand-contract for anything touching `executions`.
- Backups: PITR on Postgres, versioned object storage, restore drill once a quarter (do it once, write the runbook, you'll need it in a security questionnaire anyway).

---

## 8. ADRs to write down on day one

Keep these in `/docs/adr/` in the repo. Each one paragraph.

1. **ADR-001** Deterministic DAG owns control flow; models operate inside nodes only.
2. **ADR-002** Postgres state machine now, Temporal at defined triggers; business step records stay ours either way.
3. **ADR-003** MCP-first integration; hand-written connectors only for email, storage, notify, REST, SFTP, DB.
4. **ADR-004** Buy/self-host LLM observability (Langfuse); build business-outcome measurement.
5. **ADR-005** Workflow versions are immutable; publishing requires a passing eval gate.
6. **ADR-006** Value events reference a signed baseline and a formula version; costs are recorded alongside savings.
7. **ADR-007** Row-level security from day one; three isolation tiers offered.
8. **ADR-008** No customer data used for training or cross-customer models without a signed, specific opt-in.
9. **ADR-009** Every model call is schema-constrained and prompt-version stamped.
10. **ADR-010** Human review is a product surface, not a fallback; it is instrumented as the primary data-collection mechanism.

---

## 9. What you already have and can reuse

From your existing work (SellingAgent and related): LangGraph lifecycle handling, state and history APIs, cancellation, token/cost tracking, MCP integrations, auth and scopes, audit logging, rate limiting, streaming UI, deployment and monitoring.

Mapped onto this architecture, that covers most of §3's model-call discipline, most of M7 (inspector), and the M6 MCP gateway. **What is genuinely new work:** the durable state machine with human-wait states (M3/M4), the review desk (M5), the rules engine (M8), and the ledger (M10). Estimate: 8–12 focused weeks for a competent MVP of those four, assuming reuse everywhere else. The review desk alone is 3 of those weeks and deserves them.
