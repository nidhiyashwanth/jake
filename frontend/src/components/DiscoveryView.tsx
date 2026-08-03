"use client";

import { ChangeEvent, Dispatch, SetStateAction, useCallback, useEffect, useMemo, useState } from "react";

import { api, ApiRequestError } from "@/lib/api";
import type {
  DiscoveryDraft,
  DiscoveryMetrics,
  DiscoveryRecord,
  DiscoveryResponse,
  DiscoverySourceType,
  DiscoveryStep,
  OpportunityScore,
  SessionContext,
  SignedBaseline,
  WorkspaceContext,
} from "@/lib/types";
import { roleLabel } from "@/lib/tenancy";

type StageKey = "intake" | "draft" | "baseline" | "score";
type ApiState = "loading" | "ready" | "unavailable" | "error" | "denied";
type BusyAction = "save" | "generate" | "score" | "sign" | "export" | null;

type MetricDraft = { [key in keyof DiscoveryMetrics]: string };

interface StepDraft {
  id: string;
  title: string;
  description: string;
  system: string;
  minutes_p50: string;
  minutes_p90: string;
  is_decision: boolean;
}

interface ScoreInputDraft {
  structure_pct: string;
  rule_clarity_pct: string;
  exception_rate_pct: string;
  data_availability_pct: string;
  review_rate_pct: string;
  review_minutes: string;
  model_cost: string;
  infra_cost: string;
  effort_weeks: string;
  risk_multiplier: string;
}

interface DiscoveryFormState {
  processName: string;
  department: string;
  systemOfRecord: string;
  trigger: string;
  inputs: string;
  decisions: string;
  exceptions: string;
  approvals: string;
  outputs: string;
  failureModes: string;
  steps: StepDraft[];
  metrics: MetricDraft;
  scoreInputs: ScoreInputDraft;
  sourceType: DiscoverySourceType;
  sourceName: string;
  sourceText: string;
}

interface DraftMeta {
  state: "none" | "local" | "api";
  sourceName?: string;
  generatedAt?: string | null;
}

interface DiscoveryViewProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

const STAGES: Array<{ key: StageKey; number: string; label: string; description: string }> = [
  { key: "intake", number: "01", label: "Capture", description: "Structure the work" },
  { key: "draft", number: "02", label: "Review draft", description: "Keep the human in charge" },
  { key: "baseline", number: "03", label: "Freeze baseline", description: "Create the proof anchor" },
  { key: "score", number: "04", label: "Score opportunity", description: "Show the math" },
];

const METRIC_FIELDS: Array<{ key: keyof DiscoveryMetrics; label: string; unit: string; hint: string; step?: string }> = [
  { key: "volume_per_month", label: "Volume per month", unit: "items", hint: "Completed instances in a normal month" },
  { key: "minutes_p50", label: "Minutes per instance · p50", unit: "min", hint: "Typical hands-on time; do not use an average" },
  { key: "minutes_p90", label: "Minutes per instance · p90", unit: "min", hint: "The long tail that creates hidden capacity" },
  { key: "fully_loaded_cost_per_hour", label: "Fully loaded cost per hour", unit: "USD/hr", hint: "Labour plus benefits, management, and overhead", step: "0.01" },
  { key: "error_rate_pct", label: "Error rate", unit: "%", hint: "Observed errors before rework", step: "0.1" },
  { key: "cost_per_error", label: "Cost per error", unit: "USD", hint: "Recovery, delay, credit, or compliance cost", step: "0.01" },
  { key: "rework_rate_pct", label: "Rework rate", unit: "%", hint: "Instances that need a second pass", step: "0.1" },
  { key: "cycle_time_hours", label: "Cycle time", unit: "hours", hint: "Received to done, including waiting", step: "0.1" },
  { key: "headcount_touching", label: "Headcount touching", unit: "people", hint: "People who regularly touch the work", step: "1" },
  { key: "peak_backlog", label: "Peak backlog", unit: "items", hint: "Worst observed queue size", step: "1" },
  { key: "chase_volume_per_month", label: "Chase volume", unit: "items/mo", hint: "Follow-ups needed to complete the work", step: "1" },
  { key: "lapse_incidents_per_month", label: "Lapse incidents", unit: "incidents/mo", hint: "Missed deadlines or expired records", step: "1" },
  { key: "audit_prep_hours_per_month", label: "Audit-prep hours", unit: "hours/mo", hint: "Monthly effort to assemble evidence", step: "0.1" },
];

const SCORE_FIELDS: Array<{ key: keyof ScoreInputDraft; label: string; unit: string; hint: string; step?: string }> = [
  { key: "structure_pct", label: "Work structure", unit: "%", hint: "How consistent the path is", step: "1" },
  { key: "rule_clarity_pct", label: "Rule clarity", unit: "%", hint: "How explicitly decisions can be stated", step: "1" },
  { key: "exception_rate_pct", label: "Exception rate", unit: "%", hint: "Share of cases that leave the happy path", step: "0.1" },
  { key: "data_availability_pct", label: "Data availability", unit: "%", hint: "How accessible the needed inputs are", step: "1" },
  { key: "review_rate_pct", label: "Expected review rate", unit: "%", hint: "Share that still needs a person", step: "0.1" },
  { key: "review_minutes", label: "Review minutes", unit: "min/item", hint: "Hands-on time for a reviewed item", step: "0.1" },
  { key: "model_cost", label: "Annual model cost", unit: "USD/yr", hint: "Expected model spend at this volume", step: "0.01" },
  { key: "infra_cost", label: "Annual infrastructure cost", unit: "USD/yr", hint: "Expected hosting and connector cost", step: "0.01" },
  { key: "effort_weeks", label: "Delivery effort", unit: "weeks", hint: "Build and rollout effort", step: "0.1" },
  { key: "risk_multiplier", label: "Risk multiplier", unit: "x", hint: "Higher means more delivery or operational risk", step: "0.1" },
];

const EMPTY_METRICS: MetricDraft = {
  volume_per_month: "",
  minutes_p50: "",
  minutes_p90: "",
  fully_loaded_cost_per_hour: "",
  error_rate_pct: "",
  cost_per_error: "",
  rework_rate_pct: "",
  cycle_time_hours: "",
  headcount_touching: "",
  peak_backlog: "",
  chase_volume_per_month: "",
  lapse_incidents_per_month: "",
  audit_prep_hours_per_month: "",
};

const EMPTY_SCORE_INPUTS: ScoreInputDraft = {
  structure_pct: "",
  rule_clarity_pct: "",
  exception_rate_pct: "",
  data_availability_pct: "",
  review_rate_pct: "",
  review_minutes: "",
  model_cost: "",
  infra_cost: "",
  effort_weeks: "",
  risk_multiplier: "",
};

function emptyStep(index = 1): StepDraft {
  return {
    id: `local-step-${index}`,
    title: "",
    description: "",
    system: "",
    minutes_p50: "",
    minutes_p90: "",
    is_decision: false,
  };
}

function emptyForm(): DiscoveryFormState {
  return {
    processName: "",
    department: "",
    systemOfRecord: "",
    trigger: "",
    inputs: "",
    decisions: "",
    exceptions: "",
    approvals: "",
    outputs: "",
    failureModes: "",
    steps: [emptyStep()],
    metrics: { ...EMPTY_METRICS },
    scoreInputs: { ...EMPTY_SCORE_INPUTS },
    sourceType: "transcript",
    sourceName: "",
    sourceText: "",
  };
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function numberValue(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toMetricDraft(metrics?: Partial<DiscoveryMetrics> | null): MetricDraft {
  return METRIC_FIELDS.reduce((draft, field) => {
    draft[field.key] = stringValue(metrics?.[field.key]);
    return draft;
  }, { ...EMPTY_METRICS });
}

function toStepDraft(step: Partial<DiscoveryStep> | null | undefined, index: number): StepDraft {
  return {
    id: stringValue(step?.id) || `server-step-${index + 1}`,
    title: stringValue(step?.title),
    description: stringValue(step?.description),
    system: stringValue(step?.system),
    minutes_p50: stringValue(step?.minutes_p50),
    minutes_p90: stringValue(step?.minutes_p90),
    is_decision: Boolean(step?.is_decision),
  };
}

function recordFromResponse(response: DiscoveryResponse): DiscoveryRecord | null {
  const shaped = response as DiscoveryResponse & Partial<DiscoveryRecord>;
  return shaped.item ?? shaped.process ?? shaped.record ?? shaped.items?.[0] ?? (shaped.process_id ? (shaped as DiscoveryRecord) : null);
}

function baselineFromResponse(response: DiscoveryResponse): SignedBaseline | null {
  const shaped = response as DiscoveryResponse & { baseline?: SignedBaseline };
  const record = recordFromResponse(response);
  return shaped.baseline || record?.current_baseline || record?.baselines?.find((baseline) => baseline.status === "draft") || null;
}

function draftFromRecord(record: DiscoveryRecord): DiscoveryDraft | null {
  if (!record.draft) return null;
  return {
    ...record.draft,
    steps: (record.draft.steps || []).map((step, index) => ({
      ...step,
      title: stringValue(step.title),
      description: stringValue(step.description),
      system: stringValue(step.system),
      minutes_p50: numberOrNull(step.minutes_p50),
      minutes_p90: numberOrNull(step.minutes_p90),
      is_decision: Boolean(step.is_decision),
      id: step.id || `server-step-${index + 1}`,
    })),
    exceptions: record.draft.exceptions || [],
    baseline_questions: record.draft.baseline_questions || [],
  };
}

function metricsFromDraft(draft: MetricDraft): DiscoveryMetrics {
  return METRIC_FIELDS.reduce((metrics, field) => {
    metrics[field.key] = numberValue(draft[field.key]);
    return metrics;
  }, {} as DiscoveryMetrics);
}

function scoreInputsFromDraft(draft: ScoreInputDraft): Record<string, number | null> {
  return Object.entries(draft).reduce<Record<string, number | null>>((result, [key, value]) => {
    result[key] = numberValue(value);
    return result;
  }, {});
}

function toScoreInputDraft(score?: OpportunityScore | null): ScoreInputDraft {
  return Object.keys(EMPTY_SCORE_INPUTS).reduce((draft, key) => {
    const value = score?.inputs?.[key];
    draft[key as keyof ScoreInputDraft] = stringValue(value);
    return draft;
  }, { ...EMPTY_SCORE_INPUTS });
}

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function formatNumber(value: number | null | undefined, maximumFractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(value);
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(value * 100 % 1 === 0 ? 0 : 1)}%`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function apiStateLabel(state: ApiState): string {
  if (state === "ready") return "API connected";
  if (state === "unavailable") return "D-01 API not exposed";
  if (state === "denied") return "Workspace access denied";
  if (state === "error") return "API error";
  return "Checking D-01 API";
}

function calculateOpportunityScore(metricsDraft: MetricDraft, inputsDraft: ScoreInputDraft, baselineId: string | null): OpportunityScore | null {
  const metrics = metricsFromDraft(metricsDraft);
  const inputs = scoreInputsFromDraft(inputsDraft);
  const requiredMetricKeys: Array<keyof DiscoveryMetrics> = ["volume_per_month", "minutes_p50", "fully_loaded_cost_per_hour", "error_rate_pct", "cost_per_error"];
  const requiredInputKeys: Array<keyof ScoreInputDraft> = ["structure_pct", "rule_clarity_pct", "exception_rate_pct", "data_availability_pct", "review_rate_pct", "review_minutes", "model_cost", "infra_cost", "effort_weeks", "risk_multiplier"];
  if (requiredMetricKeys.some((key) => metrics[key] === null) || requiredInputKeys.some((key) => inputs[key] === null)) return null;

  const volumePerMonth = metrics.volume_per_month as number;
  const annualVolume = volumePerMonth * 12;
  const p50Minutes = metrics.minutes_p50 as number;
  const loadedRate = metrics.fully_loaded_cost_per_hour as number;
  const errorRate = (metrics.error_rate_pct as number) / 100;
  const costPerError = metrics.cost_per_error as number;
  const structure = (inputs.structure_pct as number) / 100;
  const ruleClarity = (inputs.rule_clarity_pct as number) / 100;
  const exceptionRate = (inputs.exception_rate_pct as number) / 100;
  const dataAvailability = (inputs.data_availability_pct as number) / 100;
  const reviewRate = (inputs.review_rate_pct as number) / 100;
  const reviewMinutes = inputs.review_minutes as number;
  const modelCost = inputs.model_cost as number;
  const infraCost = inputs.infra_cost as number;
  const effortWeeks = inputs.effort_weeks as number;
  const riskMultiplier = inputs.risk_multiplier as number;
  if (effortWeeks <= 0 || riskMultiplier <= 0) return null;

  const currentAnnualCost = annualVolume * (p50Minutes / 60) * loadedRate + annualVolume * errorRate * costPerError;
  const automatablePct = structure * 0.35 + ruleClarity * 0.30 + (1 - exceptionRate) * 0.20 + dataAvailability * 0.15;
  const confidence = structure * 0.25 + ruleClarity * 0.25 + (1 - exceptionRate) * 0.25 + dataAvailability * 0.25;
  const annualReviewCost = annualVolume * reviewRate * (reviewMinutes / 60) * loadedRate;
  const projectedSavings = currentAnnualCost * automatablePct - modelCost - infraCost - annualReviewCost;
  const priorityScore = (projectedSavings * confidence) / (effortWeeks * riskMultiplier);

  return {
    baseline_id: baselineId,
    current_annual_cost: currentAnnualCost,
    automatable_pct: automatablePct,
    projected_savings: projectedSavings,
    confidence,
    effort_weeks: effortWeeks,
    risk_multiplier: riskMultiplier,
    priority_score: priorityScore,
    model_cost: modelCost,
    infra_cost: infraCost,
    review_rate_pct: inputs.review_rate_pct as number,
    review_minutes: reviewMinutes,
    inputs,
    formula_version: "d01.v1",
    computed_at: null,
    provenance: baselineId ? `Deterministic preview tied to signed baseline ${baselineId}.` : "Deterministic preview from the current draft; sign a baseline to bind the score.",
  };
}

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  if (error instanceof Error) return error.message;
  return "The D-01 action could not be completed.";
}

function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
  disabled,
  hint,
  textarea = true,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled: boolean;
  hint?: string;
  textarea?: boolean;
}) {
  return (
    <label className="discovery-field" htmlFor={id}>
      <span className="discovery-field-label">{label}</span>
      {textarea ? (
        <textarea disabled={disabled} id={id} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} value={value} />
      ) : (
        <input disabled={disabled} id={id} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} value={value} />
      )}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function StepEditor({
  steps,
  disabled,
  onChange,
  onAdd,
  onRemove,
}: {
  steps: StepDraft[];
  disabled: boolean;
  onChange: (index: number, field: keyof StepDraft, value: string | boolean) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="step-editor">
      {steps.map((step, index) => (
        <article className="step-editor-row" key={step.id}>
          <span className="step-editor-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
          <div className="step-editor-fields">
            <label>
              <span>Step name</span>
              <input aria-label={`Step ${index + 1} name`} disabled={disabled} onChange={(event) => onChange(index, "title", event.target.value)} placeholder="e.g. Check the certificate holder" value={step.title} />
            </label>
            <label className="step-editor-description">
              <span>What happens</span>
              <textarea aria-label={`Step ${index + 1} description`} disabled={disabled} onChange={(event) => onChange(index, "description", event.target.value)} placeholder="Describe the action in the operator's words" value={step.description} />
            </label>
            <div className="step-editor-meta">
              <label><span>System / source</span><input aria-label={`Step ${index + 1} system`} disabled={disabled} onChange={(event) => onChange(index, "system", event.target.value)} placeholder="Shared inbox, ERP, spreadsheet" value={step.system} /></label>
              <label><span>p50 min</span><input aria-label={`Step ${index + 1} p50 minutes`} disabled={disabled} min="0" onChange={(event) => onChange(index, "minutes_p50", event.target.value)} placeholder="—" step="0.1" type="number" value={step.minutes_p50} /></label>
              <label><span>p90 min</span><input aria-label={`Step ${index + 1} p90 minutes`} disabled={disabled} min="0" onChange={(event) => onChange(index, "minutes_p90", event.target.value)} placeholder="—" step="0.1" type="number" value={step.minutes_p90} /></label>
              <label className="step-decision-toggle"><input checked={step.is_decision} disabled={disabled} onChange={(event) => onChange(index, "is_decision", event.target.checked)} type="checkbox" /><span>Decision point</span></label>
            </div>
          </div>
          <button aria-label={`Remove step ${index + 1}`} className="icon-button" disabled={disabled || steps.length === 1} onClick={() => onRemove(index)} type="button">×</button>
        </article>
      ))}
      <button className="text-button" disabled={disabled} onClick={onAdd} type="button">+ Add another step</button>
    </div>
  );
}

function MetricsEditor({ metrics, disabled, onChange }: { metrics: MetricDraft; disabled: boolean; onChange: (key: keyof DiscoveryMetrics, value: string) => void }) {
  return (
    <div className="metric-editor-grid">
      {METRIC_FIELDS.map((field) => (
        <label className="metric-input" key={field.key}>
          <span>{field.label}</span>
          <div className="metric-input-row"><input aria-label={field.label} disabled={disabled} min="0" onChange={(event) => onChange(field.key, event.target.value)} placeholder="Not captured" step={field.step || "1"} type="number" value={metrics[field.key]} /><em>{field.unit}</em></div>
          <small>{field.hint}</small>
        </label>
      ))}
    </div>
  );
}

function ScoreInputsEditor({ inputs, disabled, onChange }: { inputs: ScoreInputDraft; disabled: boolean; onChange: (key: keyof ScoreInputDraft, value: string) => void }) {
  return (
    <div className="score-input-grid">
      {SCORE_FIELDS.map((field) => (
        <label className="metric-input" key={field.key}>
          <span>{field.label}</span>
          <div className="metric-input-row"><input aria-label={field.label} disabled={disabled} min="0" onChange={(event) => onChange(field.key, event.target.value)} placeholder="Not captured" step={field.step || "1"} type="number" value={inputs[field.key]} /><em>{field.unit}</em></div>
          <small>{field.hint}</small>
        </label>
      ))}
    </div>
  );
}

function DiscoveryLoading() {
  return <section className="discovery-loading"><div className="loader-ring" /><p>Checking the D-01 API boundary…</p><small>No discovery records are rendered until the workspace response arrives.</small></section>;
}

function DiscoveryDenied({ role }: { role: WorkspaceContext["role"] }) {
  return <section className="discovery-denied" role="alert"><span className="access-state-mark">!</span><p className="eyebrow">403 / discovery boundary</p><h2>This workspace cannot open discovery.</h2><p>The API denied the current <strong>{roleLabel(role)}</strong> role. No process, baseline, or score data was loaded. Ask a workspace owner or admin to review this membership.</p></section>;
}

export default function DiscoveryView({ session, workspace, onAuthFailure }: DiscoveryViewProps) {
  const [stage, setStage] = useState<StageKey>("intake");
  const [apiState, setApiState] = useState<ApiState>("loading");
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<BusyAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState<DiscoveryFormState>(() => emptyForm());
  const [processId, setProcessId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [draftMeta, setDraftMeta] = useState<DraftMeta>({ state: "none" });
  const [draftExceptions, setDraftExceptions] = useState<string[]>([]);
  const [baselineQuestions, setBaselineQuestions] = useState<string[]>([]);
  const [baselines, setBaselines] = useState<SignedBaseline[]>([]);
  const [currentBaseline, setCurrentBaseline] = useState<SignedBaseline | null>(null);
  const [serverScore, setServerScore] = useState<OpportunityScore | null>(null);

  const canEdit = ["owner", "admin", "builder"].includes(workspace.role);
  const canSign = workspace.role === "owner" || workspace.role === "admin";

  const applyRecord = useCallback((record: DiscoveryRecord) => {
    const sourceDraft = draftFromRecord(record);
    const current = record.current_baseline || record.baselines?.find((baseline) => baseline.status === "signed") || null;
    setProcessId(record.process_id);
    setForm({
      processName: stringValue(record.name),
      department: stringValue(record.department),
      systemOfRecord: stringValue(record.system_of_record),
      trigger: stringValue(record.trigger),
      inputs: stringValue(record.inputs),
      decisions: stringValue(record.decisions),
      exceptions: stringValue(record.exceptions),
      approvals: stringValue(record.approvals),
      outputs: stringValue(record.outputs),
      failureModes: stringValue(record.failure_modes),
      steps: (record.steps || []).map((step, index) => toStepDraft(step, index)),
      metrics: toMetricDraft(record.metrics),
      scoreInputs: toScoreInputDraft(record.score),
      sourceType: sourceDraft?.source_type || "transcript",
      sourceName: sourceDraft?.source_name || "",
      sourceText: "",
    });
    setDraftMeta(sourceDraft ? { state: "api", sourceName: sourceDraft.source_name || undefined, generatedAt: sourceDraft.generated_at } : { state: "none" });
    setDraftExceptions(sourceDraft?.exceptions || []);
    setBaselineQuestions(sourceDraft?.baseline_questions || []);
    setBaselines(record.baselines || (current ? [current] : []));
    setCurrentBaseline(current);
    setServerScore(record.score || null);
    setDirty(false);
  }, []);

  const loadDiscovery = useCallback(async () => {
    setLoading(true);
    setApiState("loading");
    setError(null);
    try {
      const response = await api.getDiscovery();
      const record = recordFromResponse(response);
      if (record) {
        applyRecord(record);
      } else {
        setForm(emptyForm());
        setProcessId(null);
        setBaselines([]);
        setCurrentBaseline(null);
        setServerScore(null);
        setDirty(false);
      }
      setApiState("ready");
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) {
        onAuthFailure(loadError);
      } else if (loadError instanceof ApiRequestError && loadError.status === 403) {
        setApiState("denied");
        setError(loadError.message);
      } else if (loadError instanceof ApiRequestError && loadError.status === 404) {
        setApiState("unavailable");
        setError("The current API checkpoint does not expose D-01 routes yet. No saved process, baseline, or score was loaded; local edits remain unsaved until the route is deployed.");
      } else {
        setApiState("error");
        setError(errorText(loadError));
      }
    } finally {
      setLoading(false);
    }
  }, [applyRecord, onAuthFailure]);

  useEffect(() => {
    setStage("intake");
    setForm(emptyForm());
    setProcessId(null);
    setDirty(false);
    setDraftMeta({ state: "none" });
    setDraftExceptions([]);
    setBaselineQuestions([]);
    setBaselines([]);
    setCurrentBaseline(null);
    setServerScore(null);
    void loadDiscovery();
  }, [loadDiscovery, workspace.id]);

  const localScore = useMemo(() => calculateOpportunityScore(form.metrics, form.scoreInputs, currentBaseline?.id || null), [currentBaseline?.id, form.metrics, form.scoreInputs]);
  const score = serverScore || localScore;
  const scoreIsPreview = !serverScore;
  const completedIntakeFields = [form.trigger, form.inputs, form.decisions, form.exceptions, form.approvals, form.outputs, form.failureModes].filter((value) => value.trim()).length;
  const metricsComplete = METRIC_FIELDS.every((field) => numberValue(form.metrics[field.key]) !== null);
  const scoreReady = Boolean(localScore);
  const draftReady = form.steps.some((step) => step.title.trim() || step.description.trim()) || draftExceptions.some((value) => value.trim()) || baselineQuestions.some((value) => value.trim());
  const signedBaseline = baselines.find((baseline) => baseline.status === "signed") || currentBaseline;

  function markDirty() {
    setDirty(true);
    setNotice(null);
  }

  function updateText(key: keyof Pick<DiscoveryFormState, "processName" | "department" | "systemOfRecord" | "trigger" | "inputs" | "decisions" | "exceptions" | "approvals" | "outputs" | "failureModes">, value: string) {
    if (!canEdit) return;
    setForm((previous) => ({ ...previous, [key]: value }));
    markDirty();
  }

  function updateMetric(key: keyof DiscoveryMetrics, value: string) {
    if (!canEdit) return;
    setForm((previous) => ({ ...previous, metrics: { ...previous.metrics, [key]: value } }));
    markDirty();
  }

  function updateScoreInput(key: keyof ScoreInputDraft, value: string) {
    if (!canEdit) return;
    setForm((previous) => ({ ...previous, scoreInputs: { ...previous.scoreInputs, [key]: value } }));
    setServerScore(null);
    markDirty();
  }

  function updateStep(index: number, field: keyof StepDraft, value: string | boolean) {
    if (!canEdit) return;
    setForm((previous) => ({ ...previous, steps: previous.steps.map((step, stepIndex) => stepIndex === index ? { ...step, [field]: value } : step) }));
    setDraftMeta((previous) => previous.state === "api" ? { ...previous, state: "local" } : previous.state === "none" ? { state: "local" } : previous);
    markDirty();
  }

  function addStep() {
    if (!canEdit) return;
    setForm((previous) => ({ ...previous, steps: [...previous.steps, emptyStep(previous.steps.length + 1)] }));
    setDraftMeta((previous) => previous.state === "none" ? { state: "local" } : previous);
    markDirty();
  }

  function removeStep(index: number) {
    if (!canEdit || form.steps.length === 1) return;
    setForm((previous) => ({ ...previous, steps: previous.steps.filter((_, stepIndex) => stepIndex !== index) }));
    markDirty();
  }

  function updateListItem(setter: Dispatch<SetStateAction<string[]>>, index: number, value: string) {
    if (!canEdit) return;
    setter((previous) => previous.map((item, itemIndex) => itemIndex === index ? value : item));
    markDirty();
  }

  function addListItem(setter: Dispatch<SetStateAction<string[]>>, label: "exception" | "question") {
    if (!canEdit) return;
    setter((previous) => [...previous, ""]);
    setNotice(`${label === "exception" ? "Exception" : "Baseline question"} added to the unsaved draft.`);
    setDirty(true);
  }

  function removeListItem(setter: Dispatch<SetStateAction<string[]>>, index: number) {
    if (!canEdit) return;
    setter((previous) => previous.filter((_, itemIndex) => itemIndex !== index));
    markDirty();
  }

  function buildPayload() {
    return {
      process_id: processId,
      workspace_id: workspace.id,
      name: form.processName.trim(),
      department: form.department.trim(),
      system_of_record: form.systemOfRecord.trim(),
      trigger: form.trigger.trim(),
      inputs: form.inputs.trim(),
      decisions: form.decisions.trim(),
      exceptions: form.exceptions.trim(),
      approvals: form.approvals.trim(),
      outputs: form.outputs.trim(),
      failure_modes: form.failureModes.trim(),
      steps: form.steps.map((step) => ({ ...step, minutes_p50: numberValue(step.minutes_p50), minutes_p90: numberValue(step.minutes_p90) })),
      metrics: metricsFromDraft(form.metrics),
      score_inputs: scoreInputsFromDraft(form.scoreInputs),
      draft: { exceptions: draftExceptions, baseline_questions: baselineQuestions },
      source: { type: form.sourceType, name: form.sourceName.trim() || null },
    };
  }

  function handleActionError(action: string, actionError: unknown) {
    if (actionError instanceof ApiRequestError && actionError.status === 401) {
      onAuthFailure(actionError);
      return;
    }
    if (actionError instanceof ApiRequestError && actionError.status === 403) {
      setApiState("denied");
      setError(`The API denied ${action} for the current ${roleLabel(workspace.role)} role. The client did not claim success.`);
      return;
    }
    if (actionError instanceof ApiRequestError && actionError.status === 404) {
      setApiState("unavailable");
      setError(`The D-01 API route for ${action} is not exposed by this checkpoint. The client did not claim success; reload to confirm any prior server state.`);
      return;
    }
    setApiState("error");
    setError(errorText(actionError));
  }

  async function handleSave() {
    if (!canEdit) {
      setError("Your role can inspect discovery but cannot save a draft.");
      return;
    }
    if (!form.processName.trim()) {
      setError("Give this process a name before saving the discovery draft.");
      setStage("intake");
      return;
    }
    setBusyAction("save");
    setError(null);
    try {
      const response = await api.saveDiscovery(buildPayload(), processId);
      const record = recordFromResponse(response);
      if (!record) throw new ApiRequestError("The save response did not include the workspace-scoped discovery record.", "DISCOVERY_RESPONSE_INVALID", 502);
      applyRecord(record);
      setApiState("ready");
      setNotice("Draft saved by the D-01 API. It is still reviewable and not publishable from this surface.");
      setStage("draft");
    } catch (saveError) {
      handleActionError("saving this discovery", saveError);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleGenerateDraft() {
    if (!canEdit) {
      setError("Your role can inspect discovery but cannot generate or edit a draft.");
      return;
    }
    if (!form.sourceText.trim()) {
      setError("Paste an SOP or transcript, or load a text file, before asking the API for a draft.");
      return;
    }
    if (!processId) {
      setError("Save the discovery draft before ingesting a source. The ingestion and draft routes require a workspace-scoped process id.");
      return;
    }
    setBusyAction("generate");
    setError(null);
    try {
      const ingestion = await api.ingestDiscoverySource(processId, { source_type: form.sourceType, source_name: form.sourceName.trim() || undefined, content: form.sourceText });
      const response = ingestion.draft ? { draft: ingestion.draft } : await api.getDiscoveryDraft(processId);
      const draft = response.draft;
      setForm((previous) => ({ ...previous, steps: (draft.steps || []).map((step, index) => toStepDraft(step, index)) }));
      setDraftExceptions(draft.exceptions || []);
      setBaselineQuestions(draft.baseline_questions || []);
      setDraftMeta({ state: "api", sourceName: draft.source_name || form.sourceName || undefined, generatedAt: draft.generated_at || new Date().toISOString() });
      setDirty(true);
      setNotice("The API returned a draft. Review every step and exception before saving; nothing was published automatically.");
      setStage("draft");
    } catch (generateError) {
      handleActionError("generating the draft", generateError);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRefreshScore() {
    if (!processId) {
      setError("Save the discovery draft before asking the API to compute a baseline-bound score.");
      return;
    }
    if (!signedBaseline?.id) {
      setError("Sign a baseline before asking the API for an opportunity score. The local preview remains explicitly unbound.");
      return;
    }
    setBusyAction("score");
    setError(null);
    try {
      const response = await api.computeDiscoveryScore(processId, signedBaseline.id, { inputs: scoreInputsFromDraft(form.scoreInputs), formula_version: "d01.v1" });
      const record = recordFromResponse(response);
      const nextScore = response.score || record?.score || null;
      if (!nextScore?.id) throw new ApiRequestError("The score response did not include a deterministic opportunity score id.", "SCORE_RESPONSE_INVALID", 502);
      const scoreId = nextScore.id;
      const normalizedScore: OpportunityScore = nextScore.baseline_id ? nextScore : { ...nextScore, baseline_id: signedBaseline.id };
      const detail = await api.getOpportunityScore(scoreId);
      const detailRecord = recordFromResponse(detail);
      setServerScore(detail.score || detailRecord?.score || normalizedScore);
      setNotice("The API returned a score tied to the workspace discovery record.");
    } catch (scoreError) {
      handleActionError("refreshing the opportunity score", scoreError);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSignBaseline() {
    if (!canSign) {
      setError("Only an owner or admin can sign a baseline. Your current role can review the evidence only.");
      return;
    }
    if (!processId) {
      setError("Save the discovery draft before signing a baseline. The signature must reference a server record.");
      return;
    }
    if (!metricsComplete) {
      setError("Capture every baseline metric before signing. Missing values are still shown in the intake form.");
      return;
    }
    setBusyAction("sign");
    setError(null);
    try {
      const freezeResponse = await api.createDiscoveryBaseline(processId, {
        metrics: metricsFromDraft(form.metrics),
        supersedes_baseline_id: signedBaseline?.id || null,
        source: "discovery_studio",
      });
      const frozenBaseline = baselineFromResponse(freezeResponse);
      if (!frozenBaseline?.id) throw new ApiRequestError("The baseline freeze response did not include a baseline id.", "BASELINE_RESPONSE_INVALID", 502);
      const response = await api.signDiscoveryBaseline(processId, frozenBaseline.id, {
        signer: { id: session.user.id, name: session.user.display_name, email: session.user.email },
        confirm_immutable: true,
      });
      const record = recordFromResponse(response);
      if (record) {
        applyRecord(record);
      } else {
        const signed = baselineFromResponse(response);
        if (!signed) throw new ApiRequestError("The signing response did not include the immutable baseline record.", "BASELINE_RESPONSE_INVALID", 502);
        setCurrentBaseline(signed);
        setBaselines((previous) => [signed, ...previous.filter((baseline) => baseline.id !== signed.id)]);
        setServerScore(null);
        setDirty(false);
      }
      setApiState("ready");
      setNotice("Baseline signed by the API. Its version, hash, and signer are now immutable evidence.");
    } catch (signError) {
      handleActionError("signing the baseline", signError);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleExportBaseline() {
    if (!processId || !signedBaseline?.id) {
      setError("There is no signed baseline to export. A local draft is not an audit artifact.");
      return;
    }
    setBusyAction("export");
    setError(null);
    try {
      const blob = await api.exportDiscoveryBaseline(processId, signedBaseline.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `baseline-v${signedBaseline.version}-${processId}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setNotice("The signed baseline export was returned by the API.");
    } catch (exportError) {
      handleActionError("exporting the signed baseline", exportError);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSourceFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setForm((previous) => ({ ...previous, sourceName: file.name, sourceText: text }));
      setNotice(`${file.name} is loaded locally. Generate draft will send its text to the real D-01 API.`);
      setDirty(true);
    } catch {
      setError("This text source could not be read in the browser. Paste the transcript or SOP instead.");
    }
  }

  const apiBoundaryNote = apiState === "unavailable"
    ? "The T-01 auth/workspace boundary is live, but this checkpoint has not deployed D-01 persistence routes."
    : apiState === "ready"
      ? "Workspace-scoped records are loaded through the bearer session and active workspace header."
      : "No D-01 record is considered trusted until the API response is authorized and parsed.";

  if (loading) return <DiscoveryLoading />;
  if (apiState === "denied") return <DiscoveryDenied role={workspace.role} />;

  return (
    <div className="discovery-surface">
      <section className="discovery-hero">
        <div className="discovery-hero-copy">
          <div className="discovery-hero-kicker"><span className="discovery-kicker-mark">04</span><span>D-01 / Discovery studio</span><span className={`discovery-api-status discovery-api-status--${apiState}`}><i />{apiStateLabel(apiState)}</span></div>
          <h2>Turn the messy work into a signed starting point.</h2>
          <p>Capture what actually happens, let a bounded assist suggest structure, then freeze the evidence before you talk about automation.</p>
          <div className="discovery-hero-meta"><span>{workspace.organization.name}</span><b>/</b><span>{workspace.name}</span><b>/</b><span>{roleLabel(workspace.role)} access</span></div>
        </div>
        <div className="discovery-proof-card">
          <span className="discovery-proof-orbit" aria-hidden="true"><i /><i /><i /></span>
          <p>Proof anchor</p>
          <strong>{signedBaseline ? `Baseline v${signedBaseline.version}` : "No baseline signed"}</strong>
          <small>{signedBaseline ? `SHA-256 ${signedBaseline.hash ? signedBaseline.hash.slice(0, 16) : "pending hash"}…` : "Sign only after the discovery is complete."}</small>
          <span className={`proof-state ${signedBaseline ? "proof-state--signed" : ""}`}>{signedBaseline ? "Immutable" : "Draft state"}</span>
        </div>
      </section>

      {!canEdit && <div className="discovery-readonly" role="status"><strong>Read-only view.</strong> Your {roleLabel(workspace.role)} role can inspect the discovery, draft, baseline evidence, and score. Owner, admin, or builder access is required to edit; only owner/admin can sign.</div>}
      {dirty && <div className="discovery-dirty" role="status"><span className="dirty-dot" /> Unsaved local changes <small>Save draft uses the real D-01 API; this browser state is not a record.</small></div>}
      {error && <div className="alert alert--error" role="alert"><strong>Action paused.</strong> {error}<button onClick={() => setError(null)} type="button">Dismiss</button></div>}
      {notice && <div className="alert alert--success" role="status"><span>✓</span> {notice}<button onClick={() => setNotice(null)} type="button">Dismiss</button></div>}

      <nav className="discovery-stage-nav" aria-label="D-01 discovery stages">
        <div className="discovery-stage-nav-line" aria-hidden="true" />
        {STAGES.map((item) => {
          const ready = item.key === "intake" ? completedIntakeFields >= 5 : item.key === "draft" ? draftReady : item.key === "baseline" ? metricsComplete : scoreReady;
          return <button aria-current={stage === item.key ? "step" : undefined} className={`discovery-stage ${stage === item.key ? "discovery-stage--active" : ""} ${ready ? "discovery-stage--ready" : ""}`} key={item.key} onClick={() => setStage(item.key)} type="button"><span className="discovery-stage-number">{ready ? "✓" : item.number}</span><span><strong>{item.label}</strong><small>{item.description}</small></span></button>;
        })}
      </nav>

      <div className="discovery-layout">
        <main className="discovery-main">
          {stage === "intake" && (
            <>
              <section className="discovery-section-heading"><div><p className="eyebrow">01 / Structured intake</p><h3>Ask the questions that make the work legible.</h3><p>Keep answers in the operator's language. This becomes the source of truth for the draft, baseline, and later workflow work.</p></div><span className="completion-stamp">{completedIntakeFields}/7 captured</span></section>
              <section className="discovery-panel discovery-identity-panel">
                <div className="discovery-panel-heading"><div><p className="eyebrow">Process identity</p><h4>Name the unit of work.</h4></div><span className="field-source-badge">workspace scoped</span></div>
                <div className="discovery-identity-grid">
                  <TextField disabled={!canEdit} id="process-name" label="Process name" onChange={(value) => updateText("processName", value)} placeholder="e.g. Vendor COI verification" value={form.processName} textarea={false} />
                  <TextField disabled={!canEdit} id="department" label="Department / owner group" onChange={(value) => updateText("department", value)} placeholder="e.g. Risk operations" value={form.department} textarea={false} />
                  <TextField disabled={!canEdit} id="system-of-record" label="System of record" onChange={(value) => updateText("systemOfRecord", value)} placeholder="e.g. SharePoint, ERP, spreadsheet" value={form.systemOfRecord} textarea={false} />
                </div>
              </section>
              <section className="discovery-panel">
                <div className="discovery-panel-heading"><div><p className="eyebrow">The shape of the work</p><h4>Eight prompts. No blank canvas.</h4></div><span className="panel-note">Answers remain editable until sign-off.</span></div>
                <div className="discovery-question-grid">
                  <TextField disabled={!canEdit} hint="What event creates the work?" id="trigger" label="Trigger" onChange={(value) => updateText("trigger", value)} placeholder="An email arrives, a file drops, or someone notices a lapse…" value={form.trigger} />
                  <TextField disabled={!canEdit} hint="Documents, systems, and knowledge needed." id="inputs" label="Inputs" onChange={(value) => updateText("inputs", value)} placeholder="COI PDF, vendor master, policy matrix…" value={form.inputs} />
                  <TextField disabled={!canEdit} hint="What decision is made, and on what basis?" id="decisions" label="Decisions" onChange={(value) => updateText("decisions", value)} placeholder="Approve, reject, chase, or escalate based on…" value={form.decisions} />
                  <TextField disabled={!canEdit} hint="Ask what makes this case weird—then ask again." id="exceptions" label="Exceptions" onChange={(value) => updateText("exceptions", value)} placeholder="Missing endorsement, unknown vendor, conflicting dates…" value={form.exceptions} />
                  <TextField disabled={!canEdit} hint="Who signs off, and what would make them say no?" id="approvals" label="Approvals" onChange={(value) => updateText("approvals", value)} placeholder="Risk manager approves coverage exceptions…" value={form.approvals} />
                  <TextField disabled={!canEdit} hint="What exists at the end, and where does it live?" id="outputs" label="Outputs" onChange={(value) => updateText("outputs", value)} placeholder="Verified record, exception email, audit-ready status…" value={form.outputs} />
                  <TextField disabled={!canEdit} hint="What happens when it goes wrong?" id="failure-modes" label="Failure modes" onChange={(value) => updateText("failureModes", value)} placeholder="Queue grows, coverage lapses, or an auditor asks for proof…" value={form.failureModes} />
                </div>
              </section>
              <section className="discovery-panel">
                <div className="discovery-panel-heading"><div><p className="eyebrow">Sequence</p><h4>What does a person actually do?</h4></div><span className="panel-note">p50 and p90 keep the long tail visible.</span></div>
                <StepEditor disabled={!canEdit} onAdd={addStep} onChange={updateStep} onRemove={removeStep} steps={form.steps} />
              </section>
              <section className="discovery-source-panel">
                <div className="source-panel-copy"><div className="discovery-panel-heading"><div><p className="eyebrow">Bounded source assist</p><h4>Bring an SOP or transcript.</h4></div><span className="source-safety-chip">No autonomous publish</span></div><p>Paste a transcript, SOP, or screen-recording narration. The API may return a draft graph, exceptions, and baseline questions. A human must review and save every returned field.</p></div>
                <div className="source-panel-controls">
                  <div className="source-type-picker" role="group" aria-label="Source type">{(["transcript", "sop", "screen_recording"] as const).map((sourceType) => <button aria-pressed={form.sourceType === sourceType} className={form.sourceType === sourceType ? "source-type source-type--active" : "source-type"} disabled={!canEdit} key={sourceType} onClick={() => { setForm((previous) => ({ ...previous, sourceType })); markDirty(); }} type="button">{sourceType === "screen_recording" ? "Screen narration" : sourceType === "sop" ? "SOP" : "Transcript"}</button>)}</div>
                  <label className="source-file-picker" htmlFor="discovery-source-file"><span>Load .txt / .md</span><input accept=".txt,.md,text/plain,text/markdown" disabled={!canEdit} id="discovery-source-file" onChange={(event) => void handleSourceFile(event)} type="file" /></label>
                  <input aria-label="Source name" className="source-name-input" disabled={!canEdit} onChange={(event) => { setForm((previous) => ({ ...previous, sourceName: event.target.value })); markDirty(); }} placeholder="Source label (optional)" value={form.sourceName} />
                  <textarea aria-label="SOP or transcript content" disabled={!canEdit} onChange={(event) => { setForm((previous) => ({ ...previous, sourceText: event.target.value })); markDirty(); }} placeholder="Paste the operator interview or SOP here…" value={form.sourceText} />
                  <div className="source-panel-action"><small>Text is sent only when you request a draft.</small><button className="button button--primary" disabled={!canEdit || busyAction !== null || !form.sourceText.trim()} onClick={() => void handleGenerateDraft()} type="button">{busyAction === "generate" ? "Asking API…" : "Generate reviewable draft"}<span aria-hidden="true">→</span></button></div>
                </div>
              </section>
              <section className="discovery-panel">
                <div className="discovery-panel-heading"><div><p className="eyebrow">Baseline capture</p><h4>Measure the work before you change it.</h4></div><span className="panel-note">{metricsComplete ? "All metrics captured" : `${METRIC_FIELDS.filter((field) => numberValue(form.metrics[field.key]) !== null).length}/${METRIC_FIELDS.length} captured`}</span></div>
                <MetricsEditor disabled={!canEdit} metrics={form.metrics} onChange={updateMetric} />
              </section>
              <div className="discovery-action-bar"><div><strong>{dirty ? "This draft has local changes." : "Ready for a deliberate next step."}</strong><small>Save first, then review the graph and exception list.</small></div><div className="discovery-action-buttons"><button className="button button--quiet" disabled={!canEdit || busyAction !== null || !form.processName.trim()} onClick={() => void handleSave()} type="button">{busyAction === "save" ? "Saving…" : "Save draft"}</button><button className="button button--dark" onClick={() => setStage("draft")} type="button">Review draft <span aria-hidden="true">→</span></button></div></div>
            </>
          )}

          {stage === "draft" && (
            <>
              <section className="discovery-section-heading"><div><p className="eyebrow">02 / Reviewable draft</p><h3>Make the suggested graph answerable by a human.</h3><p>The draft is content, not control flow. Edit the steps, exceptions, and questions before anything can become a baseline.</p></div><span className={`draft-state-stamp draft-state-stamp--${draftMeta.state}`}>{draftMeta.state === "api" ? "API draft" : draftMeta.state === "local" ? "Local draft" : "No draft"}</span></section>
              <section className="discovery-panel graph-panel">
                <div className="discovery-panel-heading"><div><p className="eyebrow">Draft graph</p><h4>{form.processName || "Unnamed process"}</h4></div><span className="panel-note">{draftMeta.generatedAt ? `Generated ${formatDate(draftMeta.generatedAt)}` : "Not generated from a source"}</span></div>
                {draftReady ? <div className="draft-graph" aria-label="Reviewable draft graph">{form.steps.filter((step) => step.title.trim() || step.description.trim()).map((step, index, visibleSteps) => <div className="draft-node-wrap" key={step.id}><article className={`draft-node ${step.is_decision ? "draft-node--decision" : ""}`}><span>{step.is_decision ? "Decision" : `Step ${String(index + 1).padStart(2, "0")}`}</span><strong>{step.title || "Untitled step"}</strong><small>{step.system || "System not captured"} {step.minutes_p50 ? `· ${step.minutes_p50} min p50` : ""}</small></article>{index < visibleSteps.length - 1 && <span className="draft-graph-arrow" aria-hidden="true">↓</span>}</div>)}</div> : <div className="discovery-empty"><span>○</span><strong>No draft returned yet.</strong><p>Generate from an SOP/transcript or add a step in Capture. This area will never pretend a missing API response is a graph.</p></div>}
              </section>
              <section className="discovery-panel">
                <div className="discovery-panel-heading"><div><p className="eyebrow">Human edit</p><h4>Correct the sequence and the source language.</h4></div><span className="field-source-badge">unsaved until saved</span></div>
                <StepEditor disabled={!canEdit} onAdd={addStep} onChange={updateStep} onRemove={removeStep} steps={form.steps} />
              </section>
              <div className="discovery-two-column">
                <ListEditor disabled={!canEdit} items={draftExceptions} label="Exceptions" note="Keep the reason, not just the symptom." onAdd={() => addListItem(setDraftExceptions, "exception")} onChange={(index, value) => updateListItem(setDraftExceptions, index, value)} onRemove={(index) => removeListItem(setDraftExceptions, index)} placeholder="What makes this case leave the path?" />
                <ListEditor disabled={!canEdit} items={baselineQuestions} label="Baseline questions" note="Questions the sponsor must answer before sign-off." onAdd={() => addListItem(setBaselineQuestions, "question")} onChange={(index, value) => updateListItem(setBaselineQuestions, index, value)} onRemove={(index) => removeListItem(setBaselineQuestions, index)} placeholder="What is the measured rate or cost?" />
              </div>
              <section className="draft-safety-note"><span className="boundary-mark">i</span><div><strong>Drafts do not publish.</strong><p>The assist can suggest nodes and questions, but deterministic workflow control and signed-baseline approval remain separate steps. Save this version when the human review is complete.</p></div></section>
              <div className="discovery-action-bar"><div><strong>{dirty ? "Review changes before saving." : "This draft matches the last API response."}</strong><small>{draftMeta.sourceName ? `Source: ${draftMeta.sourceName}` : "No source response has been recorded."}</small></div><div className="discovery-action-buttons"><button className="button button--quiet" disabled={!canEdit || busyAction !== null} onClick={() => void handleSave()} type="button">{busyAction === "save" ? "Saving…" : "Save reviewed draft"}</button><button className="button button--dark" onClick={() => setStage("baseline")} type="button">Open baseline <span aria-hidden="true">→</span></button></div></div>
            </>
          )}

          {stage === "baseline" && (
            <>
              <section className="discovery-section-heading"><div><p className="eyebrow">03 / Signed baseline</p><h3>Freeze the numbers that future value must reference.</h3><p>A signature is an explicit approval boundary. The API must return the version, signer, timestamp, and hash before this screen calls it evidence.</p></div><span className={`completion-stamp ${metricsComplete ? "completion-stamp--good" : ""}`}>{metricsComplete ? "ready to sign" : "metrics incomplete"}</span></section>
              <section className="discovery-panel">
                <div className="discovery-panel-heading"><div><p className="eyebrow">Point-in-time inputs</p><h4>Baseline metrics</h4></div><span className="panel-note">Edits here create a superseding version after v1.</span></div>
                <MetricsEditor disabled={!canEdit} metrics={form.metrics} onChange={updateMetric} />
              </section>
              <div className="baseline-layout">
                <section className="baseline-proof-panel">
                  <div className="baseline-proof-panel-top"><span className="proof-seal" aria-hidden="true">{signedBaseline ? "✓" : "—"}</span><div><p className="eyebrow">Immutable proof</p><h4>{signedBaseline ? `Signed baseline v${signedBaseline.version}` : "No signed baseline yet"}</h4></div></div>
                  {signedBaseline ? <dl className="baseline-facts"><div><dt>Status</dt><dd><span className="proof-state proof-state--signed">Immutable</span></dd></div><div><dt>Signer</dt><dd>{signedBaseline.signed_by?.name || "Name not returned"}<small>{signedBaseline.signed_by?.email || "Email not returned"}</small></dd></div><div><dt>Signed at</dt><dd>{formatDate(signedBaseline.signed_at)}</dd></div><div><dt>SHA-256</dt><dd className="hash-value">{signedBaseline.hash || "Hash not returned"}</dd></div><div><dt>Version</dt><dd>v{signedBaseline.version}{signedBaseline.supersedes_baseline_id ? <small>supersedes {signedBaseline.supersedes_baseline_id}</small> : null}</dd></div></dl> : <div className="discovery-empty discovery-empty--small"><strong>Signing is still ahead.</strong><p>Save the process, capture every metric, then ask an owner or admin to sign through the API.</p></div>}
                  <div className="baseline-proof-actions"><button className="button button--dark" disabled={!canSign || busyAction !== null || !processId || !metricsComplete} onClick={() => void handleSignBaseline()} type="button">{busyAction === "sign" ? "Waiting for API…" : signedBaseline ? "Sign superseding version" : "Sign immutable baseline"}<span aria-hidden="true">→</span></button><button className="button button--quiet" disabled={busyAction !== null || !signedBaseline} onClick={() => void handleExportBaseline()} type="button">{busyAction === "export" ? "Preparing…" : "Export proof"}</button></div>
                  {!canSign && <small className="baseline-permission-note">Only owner/admin access can create a signature. Your {roleLabel(workspace.role)} role remains read-only at this approval boundary.</small>}
                </section>
                <section className="discovery-panel baseline-history-panel"><div className="discovery-panel-heading"><div><p className="eyebrow">Supersession chain</p><h4>Baseline history</h4></div><span className="tiny-label">append-only</span></div>{baselines.length ? <div className="baseline-history-list">{[...baselines].sort((a, b) => b.version - a.version).map((baseline) => <div className="baseline-history-row" key={baseline.id}><span className={`baseline-history-marker baseline-history-marker--${baseline.status}`} /><div><strong>Version {baseline.version} · {baseline.status}</strong><small>{baseline.hash ? `SHA-256 ${baseline.hash.slice(0, 16)}…` : "Hash not returned"} · {formatDate(baseline.signed_at)}</small></div><span>{baseline.superseded_by_baseline_id ? `→ v${baselines.find((item) => item.id === baseline.superseded_by_baseline_id)?.version || "?"}` : baseline.status === "signed" ? "current" : "—"}</span></div>)}</div> : <div className="discovery-empty discovery-empty--small"><span>○</span><p>The API has not returned any signed or superseded baseline.</p></div>}</section>
              </div>
              <section className="baseline-integrity-note"><span className="boundary-mark">#</span><div><strong>Integrity rule.</strong><p>Every future score and value event must carry this baseline id and formula version. If the inputs change, the API must create a new version and mark the old one superseded; the signed row is never mutated.</p></div></section>
              <div className="discovery-action-bar"><div><strong>{signedBaseline ? `Baseline v${signedBaseline.version} remains immutable.` : "Signature requires an API-backed process."}</strong><small>{signedBaseline ? "Edit the draft to prepare a superseding version." : "This browser cannot turn local values into a signature."}</small></div><div className="discovery-action-buttons"><button className="button button--quiet" onClick={() => setStage("draft")} type="button">Back to draft</button><button className="button button--dark" onClick={() => setStage("score")} type="button">Inspect score <span aria-hidden="true">→</span></button></div></div>
            </>
          )}

          {stage === "score" && (
            <>
              <section className="discovery-section-heading"><div><p className="eyebrow">04 / Opportunity score</p><h3>Show the economics, then show where they came from.</h3><p>The score is deterministic and inspectable. It is a preview until the API returns a score bound to a signed baseline.</p></div><span className={`score-source-stamp ${scoreIsPreview ? "score-source-stamp--preview" : ""}`}>{scoreIsPreview ? "local formula preview" : "API score"}</span></section>
              <section className="score-hero-panel"><div><p className="eyebrow">Priority score · {score?.formula_version || "d01.v1"}</p><strong>{score ? formatNumber(score.priority_score, 0) : "—"}</strong><p>{score ? "Projected annual value weighted by confidence, delivery effort, and risk." : "Capture baseline and score inputs to compute the priority."}</p></div><div className="score-hero-metrics"><div><span>Annual cost</span><strong>{formatMoney(score?.current_annual_cost)}</strong></div><div><span>Projected savings</span><strong className={score && score.projected_savings < 0 ? "value-negative" : ""}>{formatMoney(score?.projected_savings)}</strong></div><div><span>Confidence</span><strong>{formatPercent(score?.confidence)}</strong></div></div></section>
              <div className="score-layout">
                <section className="discovery-panel"><div className="discovery-panel-heading"><div><p className="eyebrow">Inputs, not vibes</p><h4>Scoring assumptions</h4></div><span className="panel-note">Customer / delivery estimate</span></div><ScoreInputsEditor disabled={!canEdit} inputs={form.scoreInputs} onChange={updateScoreInput} /></section>
                <aside className="discovery-panel score-binding-panel"><div className="discovery-panel-heading"><div><p className="eyebrow">Binding</p><h4>What this score means</h4></div></div><dl className="score-facts"><div><dt>Baseline</dt><dd>{signedBaseline ? `v${signedBaseline.version}` : "Not signed"}</dd></div><div><dt>Source</dt><dd>{scoreIsPreview ? "Current local draft" : "D-01 API response"}</dd></div><div><dt>Formula</dt><dd>{score?.formula_version || "d01.v1"}</dd></div><div><dt>Last computed</dt><dd>{formatDate(score?.computed_at)}</dd></div></dl>{!signedBaseline && <div className="score-binding-warning"><span>!</span><p>Do not use this preview in a value report until the baseline is signed and the score is returned with its baseline id.</p></div>}<button className="button button--quiet score-refresh-button" disabled={!processId || busyAction !== null} onClick={() => void handleRefreshScore()} type="button">{busyAction === "score" ? "Asking API…" : "Refresh score from API"}</button></aside>
              </div>
              <section className="discovery-panel formula-panel"><div className="discovery-panel-heading"><div><p className="eyebrow">Formula breakdown</p><h4>Every line has a source.</h4></div><span className="field-source-badge">d01.v1</span></div><div className="formula-list"><FormulaRow label="Current annual cost" formula="volume/mo × 12 × p50 min ÷ 60 × loaded rate + volume/mo × 12 × error rate × cost/error" value={formatMoney(score?.current_annual_cost)} source="Signed baseline metrics" /><FormulaRow label="Automatable percentage" formula="35% structure + 30% rule clarity + 20% (1 − exception rate) + 15% data availability" value={formatPercent(score?.automatable_pct)} source="Scoring assumptions" /><FormulaRow label="Projected savings" formula="annual cost × automatable % − model cost − infra cost − annual review cost" value={formatMoney(score?.projected_savings)} source="Baseline + scoring assumptions" /><FormulaRow label="Priority score" formula="projected savings × confidence ÷ (effort weeks × risk multiplier)" value={formatNumber(score?.priority_score, 0)} source={signedBaseline ? `Baseline v${signedBaseline.version}` : "Not bound to a signed baseline"} /></div></section>
              <section className="discovery-panel cost-bridge-panel"><div className="discovery-panel-heading"><div><p className="eyebrow">Cost bridge</p><h4>What moves the number?</h4></div><span className="panel-note">A negative result is useful evidence.</span></div>{score ? <div className="cost-bridge"><CostBridgeRow label="Current annual cost" value={score.current_annual_cost} tone="current" max={Math.max(Math.abs(score.current_annual_cost), Math.abs(score.projected_savings), 1)} /><CostBridgeRow label="Automation opportunity" value={score.current_annual_cost * score.automatable_pct} tone="opportunity" max={Math.max(Math.abs(score.current_annual_cost), Math.abs(score.projected_savings), 1)} /><CostBridgeRow label="Review + model + infra" value={score.projected_savings - score.current_annual_cost * score.automatable_pct} tone="cost" max={Math.max(Math.abs(score.current_annual_cost), Math.abs(score.projected_savings), 1)} /><CostBridgeRow label="Projected net savings" value={score.projected_savings} tone={score.projected_savings < 0 ? "negative" : "savings"} max={Math.max(Math.abs(score.current_annual_cost), Math.abs(score.projected_savings), 1)} /></div> : <div className="discovery-empty discovery-empty--small"><span>○</span><p>The cost bridge will appear after all baseline and scoring inputs are captured.</p></div>}</section>
              <div className="discovery-action-bar"><div><strong>{scoreIsPreview ? "Preview only until the API binds it." : `Score returned for baseline ${score?.baseline_id || "—"}.`}</strong><small>Scores and value events must retain their formula version.</small></div><div className="discovery-action-buttons"><button className="button button--quiet" onClick={() => setStage("baseline")} type="button">Back to baseline</button><button className="button button--dark" onClick={() => setStage("intake")} type="button">Edit intake <span aria-hidden="true">→</span></button></div></div>
            </>
          )}
        </main>

        <aside className="discovery-rail">
          <section className="discovery-rail-card discovery-rail-progress"><div className="discovery-rail-heading"><p className="eyebrow">Capture state</p><span>{Math.round(((completedIntakeFields / 7) + (draftReady ? 1 : 0) + (metricsComplete ? 1 : 0) + (scoreReady ? 1 : 0)) / 4 * 100)}%</span></div><div className="progress-track"><span style={{ width: `${Math.min(100, ((completedIntakeFields / 7) + (draftReady ? 1 : 0) + (metricsComplete ? 1 : 0) + (scoreReady ? 1 : 0)) / 4 * 100)}%` }} /></div><ol className="rail-checklist"><li className={completedIntakeFields >= 5 ? "rail-check--done" : ""}><span>01</span><div><strong>Structured intake</strong><small>{completedIntakeFields}/7 prompts answered</small></div></li><li className={draftReady ? "rail-check--done" : ""}><span>02</span><div><strong>Human-reviewed draft</strong><small>{draftReady ? `${form.steps.filter((step) => step.title.trim() || step.description.trim()).length} steps in view` : "Awaiting steps or API draft"}</small></div></li><li className={metricsComplete ? "rail-check--done" : ""}><span>03</span><div><strong>Baseline metrics</strong><small>{METRIC_FIELDS.filter((field) => numberValue(form.metrics[field.key]) !== null).length}/{METRIC_FIELDS.length} values captured</small></div></li><li className={scoreReady ? "rail-check--done" : ""}><span>04</span><div><strong>Score with inputs</strong><small>{scoreReady ? "Formula can run" : "Waiting for assumptions"}</small></div></li></ol></section>
          <section className="discovery-rail-card discovery-rail-boundary"><div className="discovery-rail-heading"><p className="eyebrow">Trust boundary</p><span className={`discovery-api-status discovery-api-status--${apiState}`}><i />{apiStateLabel(apiState)}</span></div><p>{apiBoundaryNote}</p><dl><div><dt>Workspace</dt><dd>{workspace.id}</dd></div><div><dt>Session</dt><dd>{session.user.email}</dd></div><div><dt>Process id</dt><dd>{processId || "Not created"}</dd></div></dl></section>
          <section className="discovery-rail-card discovery-rail-owner"><p className="eyebrow">Ownership + evidence</p><div className="owner-row"><span className="avatar">{session.user.initials}</span><div><strong>{session.user.display_name}</strong><small>{roleLabel(workspace.role)} · proposed operator</small></div></div><p>Discovery answers belong to the active workspace. The signature boundary belongs to the sponsor or delegated owner, not the draft assistant.</p>{signedBaseline ? <div className="rail-proof"><span>✓</span><div><strong>Baseline v{signedBaseline.version}</strong><small>{signedBaseline.signed_by?.name || "Signer returned by API"}</small></div></div> : <div className="rail-proof rail-proof--pending"><span>—</span><div><strong>No signed proof</strong><small>Local drafts are not exports.</small></div></div>}</section>
          <section className="discovery-rail-card discovery-rail-note"><span className="rail-note-mark">↗</span><strong>Next boundary</strong><p>D-01 prepares the evidence. W-01 may later use a signed baseline; it does not get to rewrite one.</p></section>
        </aside>
      </div>
    </div>
  );
}

function ListEditor({ items, label, note, placeholder, disabled, onChange, onAdd, onRemove }: { items: string[]; label: string; note: string; placeholder: string; disabled: boolean; onChange: (index: number, value: string) => void; onAdd: () => void; onRemove: (index: number) => void }) {
  return <section className="discovery-panel list-editor"><div className="discovery-panel-heading"><div><p className="eyebrow">Editable list</p><h4>{label}</h4></div><span className="panel-note">{note}</span></div>{items.length ? <div className="list-editor-items">{items.map((item, index) => <div className="list-editor-row" key={`${label}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><input aria-label={`${label} ${index + 1}`} disabled={disabled} onChange={(event) => onChange(index, event.target.value)} placeholder={placeholder} value={item} /><button aria-label={`Remove ${label.toLowerCase()} ${index + 1}`} className="icon-button" disabled={disabled} onClick={() => onRemove(index)} type="button">×</button></div>)}</div> : <p className="list-editor-empty">Nothing captured yet. Add the first item or generate a source draft.</p>}<button className="text-button" disabled={disabled} onClick={onAdd} type="button">+ Add {label.toLowerCase().replace(/s$/, "")}</button></section>;
}

function FormulaRow({ label, formula, value, source }: { label: string; formula: string; value: string; source: string }) {
  return <div className="formula-row"><div><strong>{label}</strong><small>{formula}</small></div><span>{value}</span><em>{source}</em></div>;
}

function CostBridgeRow({ label, value, tone, max }: { label: string; value: number; tone: "current" | "opportunity" | "cost" | "negative" | "savings"; max: number }) {
  const width = Math.min(100, Math.max(4, Math.abs(value) / max * 100));
  return <div className="cost-bridge-row"><div className="cost-bridge-copy"><span>{label}</span><strong className={tone === "negative" ? "value-negative" : ""}>{formatMoney(value)}</strong></div><div className={`cost-bar cost-bar--${tone}`}><span style={{ width: `${width}%` }} /></div></div>;
}
