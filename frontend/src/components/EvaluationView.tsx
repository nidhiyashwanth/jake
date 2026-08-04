import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiRequestError, api } from "@/lib/api";
import type {
  DriftSnapshotRecord,
  EvaluationRecord,
  GoldenSetRecord,
  SessionContext,
  WorkflowDetail,
  WorkflowSummary,
  WorkspaceContext,
} from "@/lib/types";

interface EvaluationViewProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

type GoldenCaseDraft = {
  case_key: string;
  source_type: "corrected" | "manual" | "canary";
  rights_status: "contractual_rights" | "manual_review" | "synthetic";
  rights_basis: string;
  sender: string;
  document_type: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  prediction: Record<string, unknown>;
  canary?: boolean;
};

const RELEASE_GATE = {
  max_false_auto_rate: 0.02,
  min_exact_match_rate: 0.9,
  min_macro_field_precision: 0.9,
  min_macro_field_recall: 0.9,
  max_correction_rate: 0.15,
  max_regression_delta: 0.03,
};

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : "The evaluation control plane returned an error.";
}

function percent(value: unknown): string {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function canWrite(role: WorkspaceContext["role"]): boolean {
  return role === "owner" || role === "admin";
}

function starterCases(): GoldenCaseDraft[] {
  const fields = { named_insured: "Acme LLC", expiry: "2099-12-31" };
  return [
    {
      case_key: "corrected-coi",
      source_type: "corrected",
      rights_status: "contractual_rights",
      rights_basis: "Customer-approved corrected case under the workspace SOW.",
      sender: "sender-a",
      document_type: "COI",
      input: { fixture: "corrected-coi" },
      expected: { fields, route: "auto", correct: true },
      prediction: { fields, route: "auto" },
    },
    {
      case_key: "manual-review-w9",
      source_type: "manual",
      rights_status: "manual_review",
      rights_basis: "Operator-curated review case with evaluation-use approval.",
      sender: "sender-b",
      document_type: "W9",
      input: { fixture: "manual-review-w9" },
      expected: { fields, route: "review", correct: true },
      prediction: { fields, route: "review" },
    },
    {
      case_key: "injection-canary-1",
      source_type: "canary",
      rights_status: "synthetic",
      rights_basis: "Synthetic prompt-injection canary for release testing.",
      sender: "canary",
      document_type: "COI",
      input: { fixture: "injection-canary-1" },
      expected: { fields, route: "halt", correct: true, canary_pass: true },
      prediction: { fields, route: "halt", canary_pass: true },
      canary: true,
    },
  ];
}

export default function EvaluationView({ session, workspace, onAuthFailure }: EvaluationViewProps) {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [goldenSets, setGoldenSets] = useState<GoldenSetRecord[]>([]);
  const [drift, setDrift] = useState<DriftSnapshotRecord[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [selectedGoldenSetId, setSelectedGoldenSetId] = useState("");
  const [evaluation, setEvaluation] = useState<EvaluationRecord | null>(null);
  const [setName, setSetName] = useState("Compliance release set");
  const [baselineId, setBaselineId] = useState("");
  const [driftForm, setDriftForm] = useState({ window: "current-week", sender: "sender-a", documentType: "COI", corrected: "5", sample: "5", baseline: "0.10", delta: "0.20" });
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const writer = canWrite(workspace.role);

  const scopedSets = useMemo(
    () => goldenSets.filter((item) => !selectedVersionId || item.workflow_version_id === selectedVersionId),
    [goldenSets, selectedVersionId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [workflowResponse, setResponse, driftResponse] = await Promise.all([
        api.listWorkflows(),
        api.listGoldenSets(),
        api.listEvaluationDrift(),
      ]);
      setWorkflows(workflowResponse.items);
      setGoldenSets(setResponse.items);
      setDrift(driftResponse.items);
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
    async function loadDetail() {
      if (!selectedWorkflowId) {
        setDetail(null);
        setSelectedVersionId("");
        return;
      }
      try {
        const nextDetail = await api.getWorkflow(selectedWorkflowId);
        if (cancelled) return;
        setDetail(nextDetail);
        setSelectedVersionId((current) => current && nextDetail.versions.some((version) => version.id === current) ? current : nextDetail.draft_version?.id || nextDetail.versions[nextDetail.versions.length - 1]?.id || "");
      } catch (loadError) {
        if (!cancelled) setError(errorText(loadError));
      }
    }
    void loadDetail();
    return () => { cancelled = true; };
  }, [selectedWorkflowId]);

  useEffect(() => {
    setSelectedGoldenSetId((current) => current && scopedSets.some((item) => item.id === current) ? current : scopedSets[0]?.id || "");
  }, [scopedSets]);

  async function createReleaseSet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writer || !selectedVersionId || !setName.trim()) return;
    setBusy("set");
    setError(null);
    try {
      const response = await api.createGoldenSet({
        workflow_version_id: selectedVersionId,
        name: setName.trim(),
        status: "active",
        source_policy: { contractual_rights_required: true, curated_from: "corrected-and-manual-cases", canary_policy: "synthetic-only" },
        gate: RELEASE_GATE,
        cases: starterCases(),
      });
      setGoldenSets((current) => [response.golden_set, ...current]);
      setSelectedGoldenSetId(response.golden_set.id);
      setNotice("Immutable release set created with rights-labelled cases and a reproducible canonical hash.");
    } catch (createError) {
      setError(errorText(createError));
    } finally {
      setBusy(null);
    }
  }

  async function runEvaluation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writer || !selectedVersionId || !selectedGoldenSetId) return;
    setBusy("evaluate");
    setError(null);
    try {
      const response = await api.runGoldenEvaluation(selectedVersionId, selectedGoldenSetId, baselineId.trim() || null);
      setEvaluation(response.evaluation);
      setNotice(response.passed ? "Evaluation passed. The exact workflow hash is eligible for the publish gate." : "Evaluation failed. Publish remains blocked until the recorded reasons are resolved.");
      if (selectedWorkflowId) setDetail(await api.getWorkflow(selectedWorkflowId));
    } catch (runError) {
      if (runError instanceof ApiRequestError && runError.status === 401) onAuthFailure(runError);
      else setError(errorText(runError));
    } finally {
      setBusy(null);
    }
  }

  async function recordDrift(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!writer || !selectedVersionId) return;
    const total = Math.min(100, Math.max(1, Number(driftForm.sample) || 1));
    const corrected = Math.min(total, Math.max(0, Number(driftForm.corrected) || 0));
    setBusy("drift");
    setError(null);
    try {
      const observations = Array.from({ length: total }, (_, index) => ({ sender: driftForm.sender.trim(), document_type: driftForm.documentType.trim(), corrected: index < corrected }));
      const response = await api.recordEvaluationDrift({
        workflow_version_id: selectedVersionId,
        window_key: driftForm.window.trim() || "current-window",
        baseline_correction_rate: Number(driftForm.baseline),
        max_delta: Number(driftForm.delta),
        min_samples: 5,
        observations,
      });
      setDrift((current) => [response.snapshot, ...current]);
      setNotice(response.alerted ? "Drift alert recorded and the sender/document group is visible for operator review." : "Rolling drift snapshot recorded within the configured boundary.");
    } catch (driftError) {
      setError(errorText(driftError));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <section className="evaluation-surface"><div className="panel-empty"><span>...</span><strong>Loading evaluation controls</strong><p>Reading workflow versions, immutable golden sets, and drift snapshots.</p></div></section>;
  }

  const selectedVersion = detail?.versions.find((version) => version.id === selectedVersionId) || null;
  const selectedSet = scopedSets.find((item) => item.id === selectedGoldenSetId) || null;
  const latestDrift = drift.filter((item) => !selectedVersionId || item.workflow_version_id === selectedVersionId).slice(0, 6);

  return (
    <section className="evaluation-surface">
      <header className="evaluation-hero">
        <div>
          <p className="eyebrow">E-01 / release evidence</p>
          <h2>Ship only what the evidence can defend.</h2>
          <p>Golden cases, canaries, regression deltas, and rolling correction drift stay attached to the exact workflow version. A model can propose; the evaluator decides.</p>
        </div>
        <div className="evaluation-hero-meta"><strong>{goldenSets.length}</strong><span>golden sets</span><b>/</b><strong>{drift.filter((item) => item.status === "alert").length}</strong><span>open drift alerts</span></div>
      </header>

      {error && <div className="alert alert--error" role="alert"><strong>Release boundary.</strong> {error}</div>}
      {notice && <div className="alert alert--success" role="status"><strong>Recorded.</strong> {notice}</div>}
      {!writer && <div className="evaluation-read-only" role="status"><strong>Read-only evaluation view.</strong> Your {workspace.role} role can inspect release evidence, but only an owner or admin can create sets, run evaluations, or record drift.</div>}

      <div className="evaluation-control-grid">
        <section className="panel evaluation-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Exact version scope</p><h3>Choose the candidate</h3></div><span className="panel-note">Hash-bound</span></div>
          <div className="evaluation-scope-form">
            <label>Workflow<select onChange={(event) => setSelectedWorkflowId(event.target.value)} value={selectedWorkflowId}><option value="">Select workflow</option>{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</select></label>
            <label>Version<select disabled={!detail} onChange={(event) => setSelectedVersionId(event.target.value)} value={selectedVersionId}><option value="">Select version</option>{detail?.versions.map((version) => <option key={version.id} value={version.id}>v{version.version} / {version.status}</option>)}</select></label>
            <label>Golden set<select disabled={!selectedVersionId} onChange={(event) => setSelectedGoldenSetId(event.target.value)} value={selectedGoldenSetId}><option value="">Select set</option>{scopedSets.map((item) => <option key={item.id} value={item.id}>{item.name} / v{item.version}</option>)}</select></label>
          </div>
          {selectedVersion && <div className="evaluation-version-proof"><span>Candidate</span><strong>v{selectedVersion.version} / {selectedVersion.status}</strong><code>{selectedVersion.immutable_hash || "Draft hash will be checked at publish"}</code></div>}
        </section>

        <section className="panel evaluation-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Immutable provenance</p><h3>Golden sets</h3></div><span className="panel-note">Rights required</span></div>
          {writer ? <form className="evaluation-create-form" onSubmit={createReleaseSet}><label>Set name<input onChange={(event) => setSetName(event.target.value)} value={setName} /></label><button className="button button--dark" disabled={!selectedVersionId || busy === "set"} type="submit">{busy === "set" ? "Creating..." : "Create starter set"}</button></form> : <p className="evaluation-copy">Ask an owner or admin to create a release set from corrected, manually curated, and synthetic canary cases.</p>}
          <div className="evaluation-set-list">
            {scopedSets.length === 0 ? (
              <div className="panel-empty"><span>+</span><strong>No set for this version.</strong><p>Create the first rights-labelled release set to make the candidate testable.</p></div>
            ) : (
              scopedSets.slice(0, 8).map((item) => (
                <button className={`evaluation-set-row ${item.id === selectedGoldenSetId ? "evaluation-set-row--active" : ""}`} key={item.id} onClick={() => setSelectedGoldenSetId(item.id)} type="button">
                  <span><strong>{item.name}</strong><small>v{item.version} / {item.case_count} cases / {item.status}</small></span>
                  <b>{item.canonical_hash.slice(0, 10)}...</b>
                </button>
              ))
            )}
          </div>
          {selectedSet && <p className="evaluation-boundary-note">This set is {selectedSet.case_count} cases, source policy is {String(selectedSet.source_policy.curated_from || "recorded")}, and its hash is immutable.</p>}
        </section>
      </div>

      <div className="evaluation-grid">
        <section className="panel evaluation-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Server-owned evaluator</p><h3>Run release evidence</h3></div><span className={`evaluation-result-chip ${evaluation ? (evaluation.passed ? "evaluation-result-chip--passed" : "evaluation-result-chip--failed") : ""}`}>{evaluation ? (evaluation.passed ? "PASS" : "BLOCKED") : "NOT RUN"}</span></div>
          {writer ? <form className="evaluation-run-form" onSubmit={runEvaluation}><label>Baseline evaluation ID <input onChange={(event) => setBaselineId(event.target.value)} placeholder="Optional for regression delta" value={baselineId} /></label><button className="button button--primary" disabled={!selectedVersionId || !selectedGoldenSetId || busy === "evaluate"} type="submit">{busy === "evaluate" ? "Evaluating..." : "Run golden evaluation"}</button></form> : <p className="evaluation-copy">The evaluator computes field precision/recall, exact match, route mix, false-auto rate, canary safety, cost, and regression deltas from stored cases.</p>}
          {!evaluation ? <div className="panel-empty"><span>.</span><strong>No current run selected.</strong><p>Choose a version and golden set, then run the server-owned evaluator.</p></div> : <div className="evaluation-result"><div className="evaluation-metric-grid"><Metric label="Exact match" value={percent(evaluation.metrics.exact_match_rate)} /><Metric label="False auto" value={percent(evaluation.metrics.false_auto_rate)} /><Metric label="Precision" value={percent(evaluation.metrics.macro_field_precision)} /><Metric label="Recall" value={percent(evaluation.metrics.macro_field_recall)} /><Metric label="Correction" value={percent(evaluation.metrics.correction_rate)} /><Metric label="Canaries" value={evaluation.metrics.canary_passed === true ? "PASS" : "FAIL"} /></div><div className="evaluation-result-meta"><span>{evaluation.evaluator}</span><span>{formatDate(evaluation.evaluated_at)}</span><code>{evaluation.definition_hash.slice(0, 16)}...</code></div>{evaluation.failure_reasons.length > 0 && <ul className="evaluation-failure-list">{evaluation.failure_reasons.map((reason) => <li key={reason}><span>x</span>{reason}</li>)}</ul>}</div>}
        </section>

        <section className="panel evaluation-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Operational feedback</p><h3>Rolling correction drift</h3></div><span className="panel-note">Sender / document</span></div>
          {writer ? <form className="evaluation-drift-form" onSubmit={recordDrift}><label>Window<input onChange={(event) => setDriftForm((current) => ({ ...current, window: event.target.value }))} value={driftForm.window} /></label><label>Sender<input onChange={(event) => setDriftForm((current) => ({ ...current, sender: event.target.value }))} value={driftForm.sender} /></label><label>Document<input onChange={(event) => setDriftForm((current) => ({ ...current, documentType: event.target.value }))} value={driftForm.documentType} /></label><label>Corrected<input min="0" onChange={(event) => setDriftForm((current) => ({ ...current, corrected: event.target.value }))} type="number" value={driftForm.corrected} /></label><label>Sample<input min="1" onChange={(event) => setDriftForm((current) => ({ ...current, sample: event.target.value }))} type="number" value={driftForm.sample} /></label><label>Baseline<input max="1" min="0" onChange={(event) => setDriftForm((current) => ({ ...current, baseline: event.target.value }))} step="0.01" type="number" value={driftForm.baseline} /></label><label>Alert delta<input max="1" min="0" onChange={(event) => setDriftForm((current) => ({ ...current, delta: event.target.value }))} step="0.01" type="number" value={driftForm.delta} /></label><button className="button button--dark" disabled={!selectedVersionId || busy === "drift"} type="submit">{busy === "drift" ? "Recording..." : "Record snapshot"}</button></form> : <p className="evaluation-copy">Drift snapshots show whether correction rates are moving for a sender/document layout. Alerts require a minimum five-case sample.</p>}
          <div className="evaluation-drift-list">
            {latestDrift.length === 0 ? (
              <div className="panel-empty"><span>^</span><strong>No drift snapshots yet.</strong><p>Record a rolling window after operators have reviewed real cases.</p></div>
            ) : latestDrift.map((item) => (
              <article className={`evaluation-drift-row ${item.status === "alert" ? "evaluation-drift-row--alert" : ""}`} key={item.id}>
                <div><strong>{item.window_key}</strong><small>{formatDate(item.created_at)} / baseline {percent(item.baseline_correction_rate)}</small></div>
                <b>{item.status.toUpperCase()}</b>
                {item.alerts.length > 0 && <p>{item.alerts.map((alert) => `${alert.group}: +${percent(alert.delta)}`).join(" / ")}</p>}
              </article>
            ))}
          </div>
        </section>
      </div>

      <footer className="evaluation-footer"><span>Server evaluator / immutable case snapshots / publish gate integration</span><span>Session: {session.user.email}</span></footer>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="evaluation-metric"><small>{label}</small><strong>{value}</strong></div>;
}
