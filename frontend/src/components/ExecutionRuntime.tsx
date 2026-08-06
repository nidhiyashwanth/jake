"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiRequestError, api } from "@/lib/api";
import type { RuntimeExecution, RuntimeObservability, WorkflowSummary, WorkflowVersion, SessionContext, WorkspaceContext } from "@/lib/types";

interface ExecutionRuntimeProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  return error instanceof Error ? error.message : "The runtime request failed. Retry from the server boundary.";
}

function formatDate(value?: string | null): string {
  if (!value) return "Not yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function statusLabel(status: string): string {
  return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function makeIdempotencyKey(): string {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function ExecutionRuntime({ session, workspace, onAuthFailure }: ExecutionRuntimeProps) {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [executions, setExecutions] = useState<Array<{ id: string; workflow_id: string; status: string; workflow_version_id: string; workflow_version_hash: string; created_at: string; correlation_id: string; dry_run: boolean }>>([]);
  const [selected, setSelected] = useState<RuntimeExecution | null>(null);
  const [observability, setObservability] = useState<RuntimeObservability | null>(null);
  const [replayVersions, setReplayVersions] = useState<WorkflowVersion[]>([]);
  const [replayVersionId, setReplayVersionId] = useState("");
  const [workflowId, setWorkflowId] = useState("");
  const [version, setVersion] = useState<WorkflowVersion | null>(null);
  const [inputText, setInputText] = useState('{"document_id":"operator-input"}');
  const [idempotencyKey, setIdempotencyKey] = useState(makeIdempotencyKey);
  const [decision, setDecision] = useState("approve");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const canRun = !["viewer", "auditor"].includes(workspace.role);
  const publishedWorkflows = useMemo(() => workflows.filter((item) => item.status === "published" || item.current_version_id), [workflows]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [workflowResponse, executionResponse, observabilityResponse] = await Promise.all([api.listWorkflows(), api.listExecutions(), api.getRuntimeObservability()]);
      setWorkflows(workflowResponse.items);
      setExecutions(executionResponse.items);
      setObservability(observabilityResponse);
      const nextWorkflowId = workflowId || workflowResponse.items[0]?.id || "";
      setWorkflowId(nextWorkflowId);
      if (nextWorkflowId) {
        const detail = await api.getWorkflow(nextWorkflowId);
        const published = detail.versions.find((item) => item.status === "published") || null;
        setVersion(published);
      }
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) onAuthFailure(loadError);
      else setError(errorText(loadError));
    } finally {
      setLoading(false);
    }
  }, [onAuthFailure, workflowId]);

  useEffect(() => { void load(); }, [load]);

  async function selectWorkflow(nextId: string) {
    setWorkflowId(nextId);
    setVersion(null);
    if (!nextId) return;
    try {
      const detail = await api.getWorkflow(nextId);
      setVersion(detail.versions.find((item) => item.status === "published") || null);
    } catch (loadError) {
      setError(errorText(loadError));
    }
  }

  async function launch() {
    if (!version) { setError("Choose a workflow with a published immutable version before launching."); return; }
    let input: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(inputText);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Input must be a JSON object.");
      input = parsed as Record<string, unknown>;
    } catch (parseError) {
      setError(parseError instanceof Error ? parseError.message : "Input must be valid JSON.");
      return;
    }
    setBusy("launch"); setError(null); setNotice(null);
    try {
      const response = await api.createExecution({ workflow_version_id: version.id, input, idempotency_key: idempotencyKey, max_retries: 3 });
      setSelected(response.execution);
      setNotice(response.idempotent ? "The existing run was returned for this idempotency key." : "Execution queued against the pinned workflow version.");
      setIdempotencyKey(makeIdempotencyKey());
      await load();
    } catch (launchError) {
      if (launchError instanceof ApiRequestError && launchError.status === 401) onAuthFailure(launchError);
      else setError(errorText(launchError));
    } finally { setBusy(null); }
  }

  async function refreshExecution(id: string) {
    try {
      const execution = await api.getExecution(id);
      setSelected(execution);
      setReplayVersionId(execution.workflow_version_id);
      const detail = await api.getWorkflow(execution.workflow_id);
      setReplayVersions(detail.versions.filter((item) => item.status === "published"));
    } catch (refreshError) { setError(errorText(refreshError)); }
  }

  async function runAction(action: string, callback: () => Promise<unknown>) {
    setBusy(action); setError(null); setNotice(null);
    try { await callback(); setNotice(action === "replay" ? "Replay created against the selected immutable version with tools stubbed and writes disabled." : "The server accepted the runtime action."); if (selected) await refreshExecution(selected.id); await load(); }
    catch (actionError) { if (actionError instanceof ApiRequestError && actionError.status === 401) onAuthFailure(actionError); else setError(errorText(actionError)); }
    finally { setBusy(null); }
  }

  const waitingStep = selected?.steps.find((step) => step.status === "waiting_human");
  const retryableStep = selected?.steps.find((step) => step.status === "dead_letter" || step.status === "failed");

  return (
    <main className="runtime-surface" aria-labelledby="runtime-heading">
      <div className="runtime-heading">
        <div>
          <p className="eyebrow">R-01 / durable execution</p>
          <h2 id="runtime-heading">Execution runtime</h2>
          <p>Launch real runs from an immutable workflow version, watch each server-owned step, and recover deliberately when a worker or human boundary interrupts the path.</p>
        </div>
        <div className="runtime-proof"><span className="live-dot" /> <strong>PostgreSQL state</strong><small>workspace-scoped · {workspace.role}</small></div>
      </div>
      {error && <div className="alert alert--error" role="alert"><span>!</span>{error}<button onClick={() => void load()} type="button">Retry</button></div>}
      {observability?.status === "degraded" && <div className="runtime-degraded" role="status"><strong>Degraded runtime signals</strong><span>{observability.degraded_signals.join(" · ")}</span></div>}
      {notice && <div className="alert alert--success" role="status"><span>✓</span>{notice}</div>}
      {loading ? <section className="loading-state"><div className="loader-ring" /><p>Loading execution state from the API…</p></section> : (
        <div className="runtime-grid">
          <section className="panel runtime-launcher">
            <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">01 / Launch</p><h3>Start a pinned run</h3></div><span className="runtime-state-chip">No invented records</span></div>
            {!canRun && <div className="runtime-boundary" role="status"><strong>Read-only runtime view.</strong><p>Your {workspace.role} role can inspect runs but cannot launch, retry, resume, or replay them.</p></div>}
            <label className="runtime-field"><span>Published workflow</span><select disabled={!canRun} onChange={(event) => void selectWorkflow(event.target.value)} value={workflowId}><option value="">Choose a workflow</option>{publishedWorkflows.map((item) => <option key={item.id} value={item.id}>{item.name}{item.key ? ` · ${item.key}` : ""}</option>)}</select></label>
            <div className="runtime-version-card">{version ? <><span className="runtime-version-mark">v{version.version}</span><div><strong>Immutable version pinned</strong><small>{version.immutable_hash || "Hash returned by API"}</small></div><span className="status-pill status-pill--good">Published</span></> : <><span className="runtime-version-mark">—</span><div><strong>No published version selected</strong><small>Publishing remains a workflow-owner action.</small></div></>}</div>
            <label className="runtime-field"><span>Input JSON</span><textarea disabled={!canRun} onChange={(event) => setInputText(event.target.value)} value={inputText} /></label>
            <label className="runtime-field"><span>Idempotency key</span><input disabled={!canRun} onChange={(event) => setIdempotencyKey(event.target.value)} value={idempotencyKey} /><small>Repeat this key to safely return the same execution instead of duplicating a run.</small></label>
            <button className="button button--dark runtime-launch-button" disabled={!canRun || busy !== null || !version} onClick={() => void launch()} type="button">{busy === "launch" ? "Queueing…" : "Launch execution"}<span aria-hidden="true">→</span></button>
            <div className="runtime-safety-note"><span>i</span><p>Routing, retries, permissions, connector fences, and writes stay server-owned. The model boundary can only return bounded node output.</p></div>
          </section>
          <section className="panel runtime-list-panel">
            <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">02 / Runs</p><h3>Recent executions</h3></div><button className="button button--quiet" onClick={() => void load()} type="button">Refresh</button></div>
            {executions.length === 0 ? <div className="panel-empty"><span>○</span><p>No real executions have been created in this workspace yet.</p></div> : <div className="runtime-run-list">{executions.map((item) => <button className={`runtime-run-row ${selected?.id === item.id ? "runtime-run-row--active" : ""}`} key={item.id} onClick={() => void refreshExecution(item.id)} type="button"><span className={`runtime-status-dot runtime-status-dot--${item.status}`} /><span><strong>{statusLabel(item.status)}</strong><small>{item.workflow_version_hash.slice(0, 12)} · {formatDate(item.created_at)}</small></span><b>{item.dry_run ? "Replay" : "Run"}</b></button>)}</div>}
          </section>
          <section className="panel runtime-inspector">
            {selected && <div className="runtime-trace"><div><span>Trace correlation</span><code>{selected.trace?.trace_id || selected.correlation_id}</code></div><div><span>Span root</span><code>{selected.trace?.span_id || "Not available"}</code></div><div><span>Data handling</span><strong>{selected.redaction?.applied ? `Redacted · ${selected.redaction.policy_version}` : "Redaction status unavailable"}</strong></div></div>}
            <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">03 / Inspector</p><h3>{selected ? "Run timeline" : "Select a run"}</h3></div>{selected && <span className={`status-pill ${selected.status === "completed" || selected.status === "halted" || selected.status === "replayed" ? "status-pill--good" : selected.status === "waiting_human" || selected.status === "dead_letter" ? "status-pill--warn" : "status-pill--quiet"}`}>{statusLabel(selected.status)}</span>}</div>
            {!selected ? <div className="panel-empty panel-empty--wide"><span>⌁</span><p>Choose an execution to inspect pinned version evidence, state transitions, retry metadata, and outbox delivery.</p></div> : <>
              <div className="runtime-facts"><div><span>Version hash</span><strong>{selected.workflow_version_hash}</strong></div><div><span>Correlation</span><strong>{selected.correlation_id}</strong></div><div><span>External writes</span><strong>{selected.external_write_count} durable receipt{selected.external_write_count === 1 ? "" : "s"}</strong></div><div><span>Cost</span><strong>${selected.steps.reduce((sum, step) => sum + step.cost_usd, 0).toFixed(6)}</strong></div></div>
              <div className="runtime-actions"><button className="button button--dark" disabled={!canRun || busy !== null || ["completed", "halted", "dead_letter", "failed", "replayed"].includes(selected.status)} onClick={() => void runAction("advance", () => api.advanceExecution(selected.id, 5))}>{busy === "advance" ? "Advancing…" : "Advance worker"}</button><button className="button button--quiet" disabled={!canRun || busy !== null} onClick={() => void runAction("replay", () => api.replayExecution(selected.id, undefined, replayVersionId || selected.workflow_version_id))}>Safe replay</button>{retryableStep && <button className="button button--quiet" disabled={!canRun || busy !== null} onClick={() => void runAction("retry", () => api.retryExecution(selected.id, "Operator requested a bounded retry", retryableStep.id))}>Retry step</button>}</div>
              <label className="runtime-field runtime-replay-field"><span>Replay against immutable version</span><select disabled={!canRun || busy !== null} onChange={(event) => setReplayVersionId(event.target.value)} value={replayVersionId || selected.workflow_version_id}>{replayVersions.length === 0 && <option value={selected.workflow_version_id}>{selected.workflow_version_hash.slice(0, 16)} · current pinned version</option>}{replayVersions.map((item) => <option key={item.id} value={item.id}>v{item.version} · {(item.immutable_hash || item.id).slice(0, 16)}</option>)}</select><small>Replay stays in the same workflow family, pins the chosen published hash, stubs tools, and disables connector writes.</small></label>
              {waitingStep && <div className="runtime-human-gate"><div><p className="eyebrow">Human boundary</p><strong>{waitingStep.wait_reason || "Decision required"}</strong><small>The worker is paused. Record the decision before the deterministic graph can continue.</small></div><div className="runtime-human-controls"><input aria-label="Human decision" onChange={(event) => setDecision(event.target.value)} value={decision} /><button className="button button--dark" disabled={!canRun || busy !== null} onClick={() => void runAction("resume", () => api.resumeExecution(selected.id, decision, { approved: decision === "approve" }, "Recorded in the runtime desk"))} type="button">Record decision</button></div></div>}
              <ol className="runtime-timeline">{selected.steps.map((step) => <li className={`runtime-timeline-item runtime-timeline-item--${step.status}`} key={step.id}><span className="runtime-timeline-mark" /><div><div className="runtime-step-heading"><strong>{step.sequence + 1}. {step.node_key}</strong><span>{statusLabel(step.status)}</span></div><small>{step.node_type} · attempt {step.attempt} · {step.input_tokens + step.output_tokens} tokens · ${step.cost_usd.toFixed(6)}</small>{step.error && <p className="runtime-step-error">{String(step.error.message || step.error.code || "Step failed")}</p>}{step.status === "completed" && step.output && <code>{JSON.stringify(step.output).slice(0, 240)}</code>}</div></li>)}</ol>
              <div className="runtime-step-evidence"><p className="eyebrow">Step evidence</p>{selected.steps.map((step) => <details className="runtime-step-detail" key={`${step.id}-detail`}><summary>{step.node_key} · trace and payload evidence</summary><div><span>Trace / span</span><code>{step.trace_id || selected.trace?.trace_id || "Not available"} / {step.span_id || "Not available"}</code></div>{step.citations && step.citations.length > 0 && <div><span>Citations</span><code>{JSON.stringify(step.citations)}</code></div>}{step.tool_call && <div><span>Tool call boundary</span><code>{JSON.stringify(step.tool_call)}</code></div>}</details>)}</div>
              {selected.events.length > 0 && <div className="runtime-event-list"><p className="eyebrow">Event timeline</p><ul>{selected.events.map((event) => <li key={event.id}><div><strong>{statusLabel(event.type)}</strong><small>{formatDate(event.occurred_at)} · {event.correlation_id}</small></div><code>{JSON.stringify(event.payload).slice(0, 320)}</code></li>)}</ul></div>}
              <div className="runtime-inspector-footer"><span>Outbox: {selected.outbox.filter((event) => event.status === "delivered").length}/{selected.outbox.length} delivered</span><span>Created {formatDate(selected.queued_at)}</span><span>{selected.dry_run ? "No side effects" : "Connector writes fenced"}</span></div>
            </>}
          </section>
        </div>
      )}
    </main>
  );
}
