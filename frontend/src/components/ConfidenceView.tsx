"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiRequestError, api } from "@/lib/api";
import type {
  ConfidenceAssessmentRecord,
  ConfidenceAuditRecord,
  ConfidenceSimulationResult,
  ConfidenceThresholdSetRecord,
  SessionContext,
  WorkflowDetail,
  WorkflowSummary,
  WorkspaceContext,
} from "@/lib/types";

interface ConfidenceViewProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : "The confidence control plane returned an error.";
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function money(value: number): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
}

function roleCanManage(role: WorkspaceContext["role"]): boolean {
  return role === "owner" || role === "admin" || role === "builder";
}

function roleCanAssess(role: WorkspaceContext["role"]): boolean {
  return roleCanManage(role) || role === "operator";
}

function roleCanAudit(role: WorkspaceContext["role"]): boolean {
  return role === "owner" || role === "admin" || role === "operator";
}

const defaultCase = {
  extraction_consistency: 0.9,
  validation_severity: 0.05,
  matching_score: 0.9,
  novelty_score: 0.05,
  sender_history_score: 0.9,
  value_at_risk: 500,
};

export default function ConfidenceView({ session, workspace, onAuthFailure }: ConfidenceViewProps) {
  const [thresholds, setThresholds] = useState<ConfidenceThresholdSetRecord[]>([]);
  const [audits, setAudits] = useState<ConfidenceAuditRecord[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [versions, setVersions] = useState<WorkflowDetail["versions"]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [thresholdForm, setThresholdForm] = useState({ auto: "0.85", review: "0.65", halt: "0.45", risk: "10000", sample: "0.02" });
  const [assessmentForm, setAssessmentForm] = useState({ ...defaultCase, reported: "0.01" });
  const [assessment, setAssessment] = useState<ConfidenceAssessmentRecord | null>(null);
  const [assessmentAudit, setAssessmentAudit] = useState<ConfidenceAuditRecord | null>(null);
  const [simulation, setSimulation] = useState<ConfidenceSimulationResult[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const manager = roleCanManage(workspace.role);
  const assessor = roleCanAssess(workspace.role);
  const auditor = roleCanAudit(workspace.role);

  const activeThreshold = useMemo(
    () => thresholds.find((item) => item.status === "active" && item.workflow_version_id === (selectedVersionId || null)) || thresholds.find((item) => item.status === "active") || null,
    [selectedVersionId, thresholds],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [thresholdResponse, auditResponse, workflowResponse] = await Promise.all([api.listConfidenceThresholdSets(), api.listConfidenceAudits(), api.listWorkflows()]);
      setThresholds(thresholdResponse.items);
      setAudits(auditResponse.items);
      setWorkflows(workflowResponse.items);
      setSelectedWorkflowId((current) => current || workflowResponse.items[0]?.id || "");
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) onAuthFailure(loadError);
      else setError(errorText(loadError));
    } finally {
      setLoading(false);
    }
  }, [onAuthFailure]);

  useEffect(() => { void load(); }, [load, workspace.id]);

  useEffect(() => {
    let cancelled = false;
    async function loadVersions() {
      if (!selectedWorkflowId) {
        setVersions([]);
        setSelectedVersionId("");
        return;
      }
      try {
        const detail = await api.getWorkflow(selectedWorkflowId);
        if (cancelled) return;
        setVersions(detail.versions);
        setSelectedVersionId((current) => current && detail.versions.some((item) => item.id === current) ? current : detail.draft_version?.id || detail.versions[detail.versions.length - 1]?.id || "");
      } catch (loadError) {
        if (!cancelled) setError(errorText(loadError));
      }
    }
    void loadVersions();
    return () => { cancelled = true; };
  }, [selectedWorkflowId]);

  async function publishThreshold(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manager) return;
    setBusy("threshold");
    setError(null);
    try {
      await api.createConfidenceThresholdSet({
        workflow_version_id: selectedVersionId || null,
        status: "active",
        auto_threshold: Number(thresholdForm.auto),
        review_threshold: Number(thresholdForm.review),
        halt_threshold: Number(thresholdForm.halt),
        value_at_risk_limit: Number(thresholdForm.risk),
        sample_rate: Math.max(0.02, Number(thresholdForm.sample)),
        reason: "Operator threshold change from Confidence Lab",
      });
      await load();
      setNotice("Threshold version published and the change was written to the audit log.");
    } catch (publishError) { setError(errorText(publishError)); } finally { setBusy(null); }
  }

  async function runAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assessor) return;
    setBusy("assessment");
    setError(null);
    try {
      const response = await api.assessConfidence({
        assessment_key: `confidence-lab-${Date.now()}`,
        workflow_version_id: selectedVersionId || null,
        extraction_consistency: Number(assessmentForm.extraction_consistency),
        validation_severity: Number(assessmentForm.validation_severity),
        matching_score: Number(assessmentForm.matching_score),
        novelty_score: Number(assessmentForm.novelty_score),
        sender_history_score: Number(assessmentForm.sender_history_score),
        value_at_risk: Number(assessmentForm.value_at_risk),
        model_confidence: Number(assessmentForm.reported),
        evidence: { surface: "confidence-lab" },
      });
      setAssessment(response.assessment);
      setAssessmentAudit(response.audit);
      await load();
      setNotice("Decision recorded from observable signals. The reported model confidence was ignored by the policy.");
    } catch (assessmentError) { setError(errorText(assessmentError)); } finally { setBusy(null); }
  }

  async function runSimulation() {
    setBusy("simulation");
    setError(null);
    try {
      const response = await api.simulateConfidence({
        cases: [
          { case_key: "golden-high-confidence", ...defaultCase, known_correct: false },
          { case_key: "golden-review", extraction_consistency: 0.75, validation_severity: 0.25, matching_score: 0.75, novelty_score: 0.25, sender_history_score: 0.75, value_at_risk: 500, known_correct: true },
          { case_key: "injection-canary", extraction_consistency: 0.1, validation_severity: 0.95, matching_score: 0.1, novelty_score: 0.95, sender_history_score: 0.1, value_at_risk: 500, required_halt: true, known_correct: true },
        ],
        thresholds: [
          { label: "Conservative", auto_threshold: 0.95, review_threshold: 0.75, halt_threshold: 0.5, value_at_risk_limit: 10000 },
          { label: "Current", auto_threshold: Number(thresholdForm.auto), review_threshold: Number(thresholdForm.review), halt_threshold: Number(thresholdForm.halt), value_at_risk_limit: Number(thresholdForm.risk) },
        ],
      });
      setSimulation(response.results);
      setNotice(`Compared ${response.case_count} historical/golden cases across ${response.results.length} threshold candidates.`);
    } catch (simulationError) { setError(errorText(simulationError)); } finally { setBusy(null); }
  }

  async function resolveAudit(item: ConfidenceAuditRecord, actualCorrect: boolean) {
    if (!auditor) return;
    setBusy(`audit-${item.id}`);
    setError(null);
    try {
      await api.completeConfidenceAudit(item.id, actualCorrect, actualCorrect ? "Sampled auto-run matched the operator outcome." : "Sampled auto-run was corrected by the operator.");
      await load();
      setNotice(actualCorrect ? "Sampled audit closed as correct." : "False-auto alert recorded and the prior threshold was restored.");
    } catch (auditError) { setError(errorText(auditError)); } finally { setBusy(null); }
  }

  if (loading) return <section className="confidence-surface"><div className="panel-empty"><span>…</span><strong>Loading confidence controls</strong><p>Reading threshold versions, workflow scopes, and sampled audit state.</p></div></section>;

  return (
    <section className="confidence-surface">
      <header className="confidence-hero">
        <div>
          <p className="eyebrow">Q-01 / live calibration boundary</p>
          <h2>Make the route explainable before it becomes automatic.</h2>
          <p>Confidence is computed from observable evidence, not a model’s self-reported number. Thresholds are versioned per workflow and sampled auto-runs create a measured error loop.</p>
        </div>
        <div className="confidence-hero-meta"><strong>{thresholds.filter((item) => item.status === "active").length}</strong><span>active policies</span><b>·</b><strong>{audits.length}</strong><span>sampled audits</span></div>
      </header>

      {error && <div className="alert alert--error" role="alert"><strong>Calibration boundary.</strong> {error}</div>}
      {notice && <div className="alert alert--success" role="status"><strong>Recorded.</strong> {notice}</div>}

      <div className="confidence-grid">
        <section className="panel confidence-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Versioned policy</p><h3>Routing thresholds</h3></div><span className="panel-note">2% minimum sample</span></div>
          <div className="confidence-scope-form">
            <label>Workflow<select disabled={!manager} onChange={(event) => setSelectedWorkflowId(event.target.value)} value={selectedWorkflowId}><option value="">Workspace default</option>{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</select></label>
            <label>Version<select disabled={!manager || versions.length === 0} onChange={(event) => setSelectedVersionId(event.target.value)} value={selectedVersionId}><option value="">Workspace default</option>{versions.map((version) => <option key={version.id} value={version.id}>v{version.version} · {version.status}</option>)}</select></label>
          </div>
          {manager && <form className="confidence-threshold-form" onSubmit={publishThreshold}>
            <label>Auto ≥<input max="1" min="0" onChange={(event) => setThresholdForm((current) => ({ ...current, auto: event.target.value }))} step="0.01" type="number" value={thresholdForm.auto} /></label>
            <label>Review ≥<input max="1" min="0" onChange={(event) => setThresholdForm((current) => ({ ...current, review: event.target.value }))} step="0.01" type="number" value={thresholdForm.review} /></label>
            <label>Halt &lt;<input max="1" min="0" onChange={(event) => setThresholdForm((current) => ({ ...current, halt: event.target.value }))} step="0.01" type="number" value={thresholdForm.halt} /></label>
            <label>Auto risk cap<input min="0" onChange={(event) => setThresholdForm((current) => ({ ...current, risk: event.target.value }))} step="100" type="number" value={thresholdForm.risk} /></label>
            <label>Sample %<input max="1" min="0.02" onChange={(event) => setThresholdForm((current) => ({ ...current, sample: event.target.value }))} step="0.01" type="number" value={thresholdForm.sample} /></label>
            <button className="button button--dark" disabled={busy === "threshold"} type="submit">{busy === "threshold" ? "Publishing…" : "Publish version"}</button>
          </form>}
          <div className="confidence-policy-list">{thresholds.length === 0 ? <div className="panel-empty"><span>+</span><strong>No policy published.</strong><p>Choose a workflow scope and publish the first conservative policy.</p></div> : thresholds.slice(0, 8).map((item) => <article className={`confidence-policy-row ${item.status === "active" ? "confidence-policy-row--active" : ""}`} key={item.id}><div><strong>v{item.version} · {item.scope_key}</strong><small>{item.status} · auto {pct(item.auto_threshold)} · review {pct(item.review_threshold)} · halt {pct(item.halt_threshold)}</small></div><b>{item.status === "active" ? "LIVE" : item.status.toUpperCase()}</b></article>)}</div>
          {activeThreshold && <p className="confidence-boundary-note">Active boundary: auto only below {money(activeThreshold.value_at_risk_limit)} value-at-risk; high-risk cases remain human-owned.</p>}
        </section>

        <section className="panel confidence-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Control-plane decision</p><h3>Test a route</h3></div><span className="panel-note">Model confidence ignored</span></div>
          {assessor ? <form className="confidence-assessment-form" onSubmit={runAssessment}>
            <div className="confidence-signal-grid">
              <label>Extraction consistency<input max="1" min="0" onChange={(event) => setAssessmentForm((current) => ({ ...current, extraction_consistency: Number(event.target.value) }))} step="0.01" type="number" value={assessmentForm.extraction_consistency} /></label>
              <label>Validation severity<input max="1" min="0" onChange={(event) => setAssessmentForm((current) => ({ ...current, validation_severity: Number(event.target.value) }))} step="0.01" type="number" value={assessmentForm.validation_severity} /></label>
              <label>Matching score<input max="1" min="0" onChange={(event) => setAssessmentForm((current) => ({ ...current, matching_score: Number(event.target.value) }))} step="0.01" type="number" value={assessmentForm.matching_score} /></label>
              <label>Novelty score<input max="1" min="0" onChange={(event) => setAssessmentForm((current) => ({ ...current, novelty_score: Number(event.target.value) }))} step="0.01" type="number" value={assessmentForm.novelty_score} /></label>
              <label>Sender history<input max="1" min="0" onChange={(event) => setAssessmentForm((current) => ({ ...current, sender_history_score: Number(event.target.value) }))} step="0.01" type="number" value={assessmentForm.sender_history_score} /></label>
              <label>Value at risk<input min="0" onChange={(event) => setAssessmentForm((current) => ({ ...current, value_at_risk: Number(event.target.value) }))} step="100" type="number" value={assessmentForm.value_at_risk} /></label>
            </div>
            <label className="confidence-reported-input">Reported model confidence <input max="1" min="0" onChange={(event) => setAssessmentForm((current) => ({ ...current, reported: event.target.value }))} step="0.01" type="number" value={assessmentForm.reported} /><small>Captured only to demonstrate the safety boundary; it never enters the formula.</small></label>
            <button className="button button--primary" disabled={busy === "assessment"} type="submit">{busy === "assessment" ? "Routing…" : "Compute route"}</button>
          </form> : <div className="confidence-readonly-note">Your role can inspect policy and audit evidence, but cannot run a routing decision.</div>}
          {assessment && <article className={`confidence-decision confidence-decision--${assessment.route}`}><div><small>Decision</small><strong>{assessment.route.toUpperCase()}</strong></div><div><small>Computed confidence</small><strong>{pct(assessment.confidence)}</strong></div><p>{String(assessment.evidence.reason || "Deterministic policy result")}. {assessment.sampled_for_audit ? "This auto-run was selected for sampled audit." : "No sample was selected for this run."}</p>{assessmentAudit && <span>Sampled audit pending · {pct(assessmentAudit.sample_rate)} configured rate</span>}</article>}
        </section>
      </div>

      <div className="confidence-grid confidence-grid--lower">
        <section className="panel confidence-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Historical / golden set</p><h3>Threshold simulator</h3></div><button className="button button--quiet" disabled={busy === "simulation"} onClick={() => void runSimulation()} type="button">{busy === "simulation" ? "Running…" : "Compare thresholds"}</button></div>
          <p className="confidence-copy">Auto + review + halt must equal ingested. Estimated error is measured only from cases with a known operator outcome.</p>
          {simulation.length === 0 ? <div className="panel-empty"><span>↗</span><strong>No curve calculated yet.</strong><p>Run the simulator against the seeded representative cases.</p></div> : <div className="confidence-simulation-list">{simulation.map((result) => <article className="confidence-simulation-row" key={result.label}><div><strong>{result.label}</strong><small>{result.total} cases · {result.reconciles ? "reconciled" : "check failed"}</small></div><span><b>{pct(result.auto_rate)}</b><small>auto</small></span><span><b>{pct(result.review_rate)}</b><small>review</small></span><span><b>{result.estimated_error === null ? "—" : pct(result.estimated_error)}</b><small>error</small></span><span><b>{money(result.estimated_cost_usd)}</b><small>cost</small></span></article>)}</div>}
        </section>

        <section className="panel confidence-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Measured oversight</p><h3>Sampled audits</h3></div><span className="panel-note">False-auto rollback</span></div>
          <div className="confidence-audit-list">{audits.length === 0 ? <div className="panel-empty"><span>◎</span><strong>No sampled auto-runs yet.</strong><p>High-confidence runs are selected deterministically at the configured rate.</p></div> : audits.slice(0, 8).map((item) => <article className={`confidence-audit-row confidence-audit-row--${item.status}`} key={item.id}><div><strong>{item.status === "alerted" ? "False auto" : "Sampled auto-run"}</strong><small>{item.status} · {pct(item.sample_rate)} rate</small></div>{item.status === "pending" && auditor ? <div className="confidence-audit-actions"><button className="button button--quiet" disabled={busy === `audit-${item.id}`} onClick={() => void resolveAudit(item, true)} type="button">Correct</button><button className="button button--danger" disabled={busy === `audit-${item.id}`} onClick={() => void resolveAudit(item, false)} type="button">False auto</button></div> : <span>{item.rollback_threshold_set_id ? "Rolled back" : item.actual_correct ? "Confirmed" : item.status}</span>}</article>)}</div>
        </section>
      </div>

      <footer className="confidence-footer"><span>Workspace scoped · {session.user.email}</span><span>Every threshold change, route, sample, alert, and rollback is auditable.</span></footer>
    </section>
  );
}
