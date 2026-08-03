"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiRequestError } from "@/lib/api";
import { roleLabel } from "@/lib/tenancy";
import type {
  EvaluationGate,
  SessionContext,
  WorkflowEdge,
  WorkflowModelConfigReference,
  WorkflowNode,
  WorkflowNodeType,
  WorkflowPromptReference,
  WorkflowSpec,
  WorkflowSummary,
  WorkflowValidationIssue,
  WorkflowVersion,
  WorkspaceContext,
} from "@/lib/types";
import {
  createLocalNode,
  defaultNodeConfig,
  emptyWorkflowSpec,
  NODE_CONFIG_FIELDS,
  NODE_TYPE_META,
  normalizeWorkflowVersion,
  validateWorkflowSpec,
} from "@/lib/workflow-contract";
import { WORKFLOW_NODE_TYPES } from "@/lib/types";

type ApiState = "loading" | "ready" | "unavailable" | "error" | "denied";
type StudioTab = "edit" | "graph";

interface WorkflowStudioProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

interface WorkflowMetadataDraft {
  key: string;
  name: string;
  description: string;
  processId: string;
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function numberValue(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function formatHash(value: string | null | undefined): string {
  if (!value) return "Hash assigned on publish";
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  if (error instanceof Error) return error.message;
  return "The workflow action could not be completed.";
}

function statusLabel(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isEditorRole(workspace: WorkspaceContext): boolean {
  return ["owner", "admin", "builder"].includes(workspace.role);
}

function mergeIssues(...groups: WorkflowValidationIssue[][]): WorkflowValidationIssue[] {
  const seen = new Set<string>();
  return groups.flat().filter((item) => {
    const key = `${item.code}:${item.path}:${item.message}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function responseVersion(response: unknown, workflowId: string, fallback: WorkflowVersion | null): WorkflowVersion | null {
  if (!response || typeof response !== "object") return fallback;
  const value = response as { version?: unknown; item?: unknown };
  const candidate = value.version ?? value.item;
  if (!candidate) return fallback;
  const normalized = normalizeWorkflowVersion(candidate, workflowId, fallback ? fallback.version - 1 : 0);
  if (fallback && normalized.spec.nodes.length === 0 && normalized.spec.edges.length === 0) {
    return { ...normalized, spec: fallback.spec };
  }
  return normalized;
}

function responseGate(response: unknown, fallback: EvaluationGate): EvaluationGate {
  if (!response || typeof response !== "object") return fallback;
  const value = response as { evaluation_gate?: EvaluationGate; eval_gate?: EvaluationGate; version?: WorkflowVersion };
  return value.evaluation_gate ?? value.eval_gate ?? value.version?.eval_gate ?? fallback;
}

function updateVersionInDetail(detail: { workflow: WorkflowSummary; versions: WorkflowVersion[]; draft_version?: WorkflowVersion | null }, next: WorkflowVersion) {
  const versions = detail.versions.some((version) => version.id === next.id)
    ? detail.versions.map((version) => version.id === next.id ? next : version)
    : [...detail.versions, next];
  return {
    ...detail,
    versions,
    draft_version: next.status === "draft" ? next : detail.draft_version,
  };
}

function initialMetadata(workflow: WorkflowSummary | null): WorkflowMetadataDraft {
  return { key: workflow?.key ?? "", name: workflow?.name ?? "", description: workflow?.description ?? "", processId: workflow?.process_id ?? "" };
}

export default function WorkflowStudio({ session, workspace, onAuthFailure }: WorkflowStudioProps) {
  const [apiState, setApiState] = useState<ApiState>("loading");
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof api.getWorkflow>> | null>(null);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [draftSpec, setDraftSpec] = useState<WorkflowSpec>(emptyWorkflowSpec());
  const [metadata, setMetadata] = useState<WorkflowMetadataDraft>({ key: "", name: "", description: "", processId: "" });
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [studioTab, setStudioTab] = useState<StudioTab>("edit");
  const [localIssues, setLocalIssues] = useState<WorkflowValidationIssue[]>([]);
  const [serverIssues, setServerIssues] = useState<WorkflowValidationIssue[]>([]);
  const [evaluationStale, setEvaluationStale] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newWorkflowOpen, setNewWorkflowOpen] = useState(false);
  const [newWorkflowKey, setNewWorkflowKey] = useState("");
  const [newWorkflowName, setNewWorkflowName] = useState("");
  const [newWorkflowDescription, setNewWorkflowDescription] = useState("");
  const [newProcessId, setNewProcessId] = useState("");
  const [newNodeType, setNewNodeType] = useState<WorkflowNodeType>("trigger");
  const [newNodeKey, setNewNodeKey] = useState("");
  const [edgeFrom, setEdgeFrom] = useState("");
  const [edgeTo, setEdgeTo] = useState("");
  const [edgeCondition, setEdgeCondition] = useState("");
  const workspaceIdRef = useRef(workspace.id);
  const canEdit = isEditorRole(workspace);

  const reportError = useCallback((operationError: unknown) => {
    if (operationError instanceof ApiRequestError && operationError.status === 401) {
      onAuthFailure(operationError);
      return;
    }
    setError(errorMessage(operationError));
  }, [onAuthFailure]);

  const loadList = useCallback(async (preferredId?: string | null) => {
    setApiState("loading");
    try {
      const response = await api.listWorkflows();
      if (workspaceIdRef.current !== workspace.id) return;
      setWorkflows(response.items);
      setSelectedWorkflowId((current) => {
        if (preferredId && response.items.some((workflow) => workflow.id === preferredId)) return preferredId;
        if (current && response.items.some((workflow) => workflow.id === current)) return current;
        return response.items[0]?.id ?? null;
      });
      if (response.items.length === 0) {
        setSelectedWorkflowId(null);
        setDetail(null);
      }
      setApiState("ready");
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) {
        onAuthFailure(loadError);
        return;
      }
      if (loadError instanceof ApiRequestError && [403].includes(loadError.status)) setApiState("denied");
      else if (loadError instanceof ApiRequestError && [404, 405].includes(loadError.status)) setApiState("unavailable");
      else setApiState("error");
      reportError(loadError);
    }
  }, [onAuthFailure, reportError, workspace.id]);

  const loadDetail = useCallback(async (workflowId: string) => {
    setDetailLoading(true);
    setError(null);
    try {
      const nextDetail = await api.getWorkflow(workflowId);
      if (workspaceIdRef.current !== workspace.id) return;
      setDetail(nextDetail);
      setMetadata(initialMetadata(nextDetail.workflow));
    } catch (loadError) {
      reportError(loadError);
    } finally {
      if (workspaceIdRef.current === workspace.id) setDetailLoading(false);
    }
  }, [reportError, workspace.id]);

  useEffect(() => {
    workspaceIdRef.current = workspace.id;
    setWorkflows([]);
    setSelectedWorkflowId(null);
    setDetail(null);
    setActiveVersionId(null);
    setDraftSpec(emptyWorkflowSpec());
    setMetadata({ key: "", name: "", description: "", processId: "" });
    setLocalIssues([]);
    setServerIssues([]);
    setError(null);
    setNotice(null);
    void loadList();
  }, [loadList, workspace.id]);

  useEffect(() => {
    if (!selectedWorkflowId) return;
    void loadDetail(selectedWorkflowId);
  }, [loadDetail, selectedWorkflowId]);

  const versions = useMemo(() => {
    if (!detail) return [];
    const byId = new Map(detail.versions.map((version) => [version.id, version]));
    if (detail.draft_version && !byId.has(detail.draft_version.id)) byId.set(detail.draft_version.id, detail.draft_version);
    return [...byId.values()].sort((left, right) => right.version - left.version);
  }, [detail]);

  const activeVersion = versions.find((version) => version.id === activeVersionId) ?? null;
  const editorVersion = activeVersion?.status === "draft" ? { ...activeVersion, spec: draftSpec } : activeVersion;
  const effectiveSpec = editorVersion?.spec ?? draftSpec;
  const validationIssues = mergeIssues(localIssues, serverIssues);
  const blockingIssues = validationIssues.filter((item) => item.severity === "error");
  const evaluationGate = activeVersion?.eval_gate ?? { status: "not_run", failure_reasons: [] };
  const hasSavedDraft = Boolean(activeVersion && activeVersion.status === "draft");
  const canEditActiveVersion = canEdit && hasSavedDraft;
  const publishReady = canEditActiveVersion && blockingIssues.length === 0 && evaluationGate.status === "passed" && !evaluationStale;

  useEffect(() => {
    if (!detail) return;
    const nextVersion = versions.find((version) => version.id === activeVersionId) ?? versions[0] ?? null;
    if (!nextVersion) {
      setActiveVersionId(null);
      setDraftSpec(emptyWorkflowSpec());
      setSelectedNodeKey(null);
      setLocalIssues(validateWorkflowSpec(emptyWorkflowSpec()));
      return;
    }
    if (nextVersion.id !== activeVersionId) setActiveVersionId(nextVersion.id);
    setDraftSpec(nextVersion.spec);
    setSelectedNodeKey((current) => current && nextVersion.spec.nodes.some((node) => node.node_key === current) ? current : nextVersion.spec.nodes[0]?.node_key ?? null);
    setLocalIssues(validateWorkflowSpec(nextVersion.spec));
    setServerIssues(nextVersion.validation_errors);
    setEvaluationStale(false);
  }, [activeVersionId, detail, versions]);

  function updateSpec(updater: (current: WorkflowSpec) => WorkflowSpec) {
    if (!canEditActiveVersion) return;
    setDraftSpec((current) => {
      const next = updater(current);
      setLocalIssues(validateWorkflowSpec(next));
      return next;
    });
    setServerIssues([]);
    setEvaluationStale(true);
  }

  async function handleCreateWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEdit) {
      setError("Your role can inspect workflows but cannot create workflow definitions.");
      return;
    }
    const name = newWorkflowName.trim();
    const key = newWorkflowKey.trim();
    if (!name || !key) {
      setError("Give the workflow a stable key and name before creating it.");
      return;
    }
    setActionBusy("create-workflow");
    setError(null);
    try {
      const created = await api.createWorkflow({ key, name, description: newWorkflowDescription.trim() || null, process_id: newProcessId.trim() || null });
      const workflowId = created.workflow.id;
      if (!workflowId) throw new Error("The workflow API did not return a workflow id.");
      setNewWorkflowName("");
      setNewWorkflowKey("");
      setNewWorkflowDescription("");
      setNewProcessId("");
      setNewWorkflowOpen(false);
      await loadList(workflowId);
      setNotice("Workflow created. Add a trigger, shape the draft, and save before evaluation.");
    } catch (createError) {
      reportError(createError);
    } finally {
      setActionBusy(null);
    }
  }

  async function handleSaveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail || !canEdit) return;
    const name = metadata.name.trim();
    const key = metadata.key.trim();
    if (!name || !key) {
      setError("Workflow key and name cannot be empty.");
      return;
    }
    setActionBusy("metadata");
    setError(null);
    try {
      await api.updateWorkflow(detail.workflow.id, { key, name, description: metadata.description.trim() || null, process_id: metadata.processId.trim() || null });
      await loadList(detail.workflow.id);
      await loadDetail(detail.workflow.id);
      setNotice("Workflow metadata saved.");
    } catch (saveError) {
      reportError(saveError);
    } finally {
      setActionBusy(null);
    }
  }

  async function handleCreateDraft() {
    if (!detail || !canEdit) return;
    setActionBusy("create-draft");
    setError(null);
    try {
      const sourceVersion = activeVersion?.status === "published" ? activeVersion : versions[0];
      const nextVersion = await api.createWorkflowVersion(detail.workflow.id, sourceVersion?.spec ?? emptyWorkflowSpec(), sourceVersion?.id ?? null);
      setDetail((current) => current ? updateVersionInDetail(current, nextVersion) : current);
      setActiveVersionId(nextVersion.id);
      setNotice(`Draft version ${nextVersion.version} created. Published versions remain immutable.`);
    } catch (draftError) {
      reportError(draftError);
    } finally {
      setActionBusy(null);
    }
  }

  async function handleSaveDraft() {
    if (!detail || !activeVersion || !canEditActiveVersion) return;
    setActionBusy("save-draft");
    setError(null);
    try {
      const saved = await api.updateWorkflowVersion(detail.workflow.id, activeVersion.id, draftSpec);
      setDetail((current) => current ? updateVersionInDetail(current, { ...saved, spec: saved.spec.nodes.length > 0 || saved.spec.edges.length > 0 ? saved.spec : draftSpec }) : current);
      setServerIssues(saved.validation_errors);
      setEvaluationStale(false);
      setNotice(`Draft version ${activeVersion.version} saved. Run validation and evaluation before publish.`);
    } catch (saveError) {
      reportError(saveError);
    } finally {
      setActionBusy(null);
    }
  }

  async function handleValidate() {
    if (!detail || !activeVersion || !hasSavedDraft) return;
    const currentIssues = validateWorkflowSpec(draftSpec);
    setLocalIssues(currentIssues);
    if (currentIssues.some((item) => item.severity === "error")) {
      setNotice("Schema validation found blocking issues. Fix them in the editor before asking the API to validate.");
      return;
    }
    setActionBusy("validate");
    setError(null);
    try {
      const response = await api.validateWorkflowVersion(detail.workflow.id, activeVersion.id);
      const responseIssues = response.validation_errors ?? response.errors ?? response.version?.validation_errors ?? [];
      setServerIssues(responseIssues);
      if (response.version) {
        const nextVersion = normalizeWorkflowVersion(response.version, detail.workflow.id, activeVersion.version - 1);
        setDetail((current) => current ? updateVersionInDetail(current, { ...activeVersion, ...nextVersion, spec: nextVersion.spec.nodes.length > 0 ? nextVersion.spec : draftSpec }) : current);
      }
      setNotice(responseIssues.some((item) => item.severity === "error") ? "The API rejected this draft schema. See the validation reasons below." : "Schema validation passed at the API boundary.");
    } catch (validationError) {
      reportError(validationError);
    } finally {
      setActionBusy(null);
    }
  }

  async function handleEvaluate() {
    if (!detail || !activeVersion || !hasSavedDraft) return;
    const currentIssues = validateWorkflowSpec(draftSpec);
    setLocalIssues(currentIssues);
    if (currentIssues.some((item) => item.severity === "error")) {
      setNotice("Evaluation is blocked until the workflow schema is valid.");
      return;
    }
    if (evaluationStale) {
      setNotice("Save the current draft before running the evaluation gate.");
      return;
    }
    setActionBusy("evaluate");
    setError(null);
    try {
      const response = await api.evaluateWorkflowVersion(detail.workflow.id, activeVersion.id);
      const nextVersion = responseVersion(response, detail.workflow.id, activeVersion);
      const nextGate = responseGate(response, nextVersion?.eval_gate ?? evaluationGate);
      if (nextVersion) setDetail((current) => current ? updateVersionInDetail(current, { ...activeVersion, ...nextVersion, spec: nextVersion.spec.nodes.length > 0 ? nextVersion.spec : draftSpec, eval_gate: nextGate }) : current);
      setEvaluationStale(false);
      setNotice(nextGate.status === "passed" ? "Evaluation gate passed. This version can be published." : "Evaluation gate failed. Publish remains blocked; review the reasons below.");
    } catch (evaluationError) {
      reportError(evaluationError);
    } finally {
      setActionBusy(null);
    }
  }

  async function handlePublish() {
    if (!detail || !activeVersion) return;
    if (!publishReady) {
      setError(evaluationGate.status !== "passed" ? "Evaluation gate blocks publish until this exact version has a passing server evaluation." : "Evaluation gate blocks publish while schema errors or unsaved draft changes remain.");
      return;
    }
    setActionBusy("publish");
    setError(null);
    try {
      const response = await api.publishWorkflowVersion(detail.workflow.id, activeVersion.id);
      const nextGate = responseGate(response, evaluationGate);
      const nextVersion = responseVersion(response, detail.workflow.id, activeVersion);
      if (nextGate.status !== "passed" || response.published === false) {
        if (nextVersion) setDetail((current) => current ? updateVersionInDetail(current, { ...activeVersion, ...nextVersion, eval_gate: nextGate }) : current);
        setNotice(`Publish blocked by the evaluation gate: ${response.failure_reasons?.join(" ") || nextGate.failure_reasons.join(" ") || "the API did not confirm a passing gate."}`);
        return;
      }
      await loadDetail(detail.workflow.id);
      await loadList(detail.workflow.id);
      setNotice(`Version ${activeVersion.version} published with an immutable hash.`);
    } catch (publishError) {
      reportError(publishError);
    } finally {
      setActionBusy(null);
    }
  }

  function handleNodeAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEditActiveVersion) return;
    const suggestedKey = newNodeKey.trim() || `${newNodeType}_${draftSpec.nodes.length + 1}`;
    if (draftSpec.nodes.some((node) => node.node_key === suggestedKey)) {
      setError(`Node key “${suggestedKey}” already exists. Choose a unique key.`);
      return;
    }
    const node = createLocalNode(newNodeType, draftSpec.nodes.length + 1);
    updateSpec((current) => ({ ...current, nodes: [...current.nodes, { ...node, node_key: suggestedKey, label: NODE_TYPE_META[newNodeType].label, config: defaultNodeConfig(newNodeType) }] }));
    setSelectedNodeKey(suggestedKey);
    setNewNodeKey("");
    setNotice(`${NODE_TYPE_META[newNodeType].label} node added to the draft.`);
  }

  function handleNodeUpdate(nodeKey: string, updater: (node: WorkflowNode) => WorkflowNode) {
    updateSpec((current) => ({ ...current, nodes: current.nodes.map((node) => node.node_key === nodeKey ? updater(node) : node) }));
  }

  function handleNodeRemove(nodeKey: string) {
    updateSpec((current) => ({
      ...current,
      nodes: current.nodes.filter((node) => node.node_key !== nodeKey),
      edges: current.edges.filter((edge) => edge.from_node !== nodeKey && edge.to_node !== nodeKey),
    }));
    setSelectedNodeKey((current) => current === nodeKey ? draftSpec.nodes.find((node) => node.node_key !== nodeKey)?.node_key ?? null : current);
  }

  function handleEdgeAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEditActiveVersion || !edgeFrom || !edgeTo) return;
    const edge: WorkflowEdge = { id: `local-edge-${Date.now()}`, from_node: edgeFrom, to_node: edgeTo, condition: edgeCondition.trim() || null };
    updateSpec((current) => ({ ...current, edges: [...current.edges, edge] }));
    setEdgeFrom("");
    setEdgeTo("");
    setEdgeCondition("");
  }

  function updateThreshold(key: string, value: string) {
    updateSpec((current) => ({
      ...current,
      thresholds: current.thresholds.map((threshold) => threshold.key === key ? { ...threshold, value: numberValue(value) } : threshold),
    }));
  }

  function updatePrompt(index: number, field: keyof WorkflowPromptReference, value: string) {
    updateSpec((current) => ({
      ...current,
      prompts: current.prompts.map((prompt, promptIndex) => promptIndex === index ? { ...prompt, [field]: field === "version" ? numberValue(value) : value } : prompt),
    }));
  }

  function updateModelConfig(index: number, field: keyof WorkflowModelConfigReference, value: string) {
    updateSpec((current) => ({
      ...current,
      model_configs: current.model_configs.map((config, configIndex) => configIndex === index ? { ...config, [field]: field === "version" ? numberValue(value) : value } : config),
    }));
  }

  function currentNodeIssues(nodeKey: string): WorkflowValidationIssue[] {
    return validationIssues.filter((item) => item.node_key === nodeKey || item.path.includes(nodeKey));
  }

  const selectedNode = effectiveSpec.nodes.find((node) => node.node_key === selectedNodeKey) ?? null;

  return (
    <main className="workflow-studio">
      <section className="workflow-hero">
        <div>
          <p className="eyebrow">W-01 / workflow control</p>
          <h2>Workflow builder</h2>
          <p>Turn an operating path into an immutable runbook. Build a deterministic DAG with bounded model nodes, explicit thresholds, and a publish gate that leaves proof behind.</p>
          <div className="workflow-hero-meta"><span className="workflow-live-mark" /><span>Workspace scoped · {roleLabel(workspace.role)} access</span><span>·</span><span>{session.user.display_name}</span></div>
        </div>
        <div className="workflow-proof-card">
          <span className="workflow-proof-index">03</span>
          <div><p className="eyebrow">Release contract</p><strong>Draft → validate → evaluate → publish</strong><small>Published versions are immutable and executions stay pinned to their starting version.</small></div>
        </div>
      </section>

      {!canEdit && <div className="workflow-read-only" role="status"><strong>Read-only workflow view.</strong> Your {roleLabel(workspace.role)} role can inspect versions, graph structure, and evaluation evidence. Ask a builder or workspace admin to edit.</div>}
      {error && <div className="alert alert--error workflow-alert" role="alert"><strong>Workflow action paused.</strong> {error}<button onClick={() => setError(null)} type="button">Dismiss</button></div>}
      {notice && <div className="alert alert--success workflow-alert" role="status"><span aria-hidden="true">✓</span> {notice}<button onClick={() => setNotice(null)} type="button">Dismiss</button></div>}

      {apiState === "loading" && <div className="workflow-loading"><div className="loader-ring" /><p>Loading workflow definitions…</p><small>Reading only the active workspace context.</small></div>}
      {apiState === "unavailable" && <WorkflowBoundaryState kind="unavailable" />}
      {apiState === "denied" && <WorkflowBoundaryState kind="denied" />}
      {apiState === "error" && <WorkflowBoundaryState kind="error" onRetry={() => void loadList()} />}

      {apiState === "ready" && (
        <div className="workflow-layout">
          <aside className="workflow-index-panel">
            <div className="workflow-index-heading"><div><p className="eyebrow">Definitions</p><h3>Workflow index</h3></div><span className="count-badge">{String(workflows.length).padStart(2, "0")}</span></div>
            {workflows.length === 0 ? (
              <div className="workflow-index-empty"><span>+</span><strong>No definitions yet.</strong><p>Create the first workflow in this workspace. The list never uses placeholder records.</p></div>
            ) : (
              <div className="workflow-list" aria-label="Workflow definitions">
                {workflows.map((workflow) => (
                  <button className={`workflow-list-row ${workflow.id === selectedWorkflowId ? "workflow-list-row--active" : ""}`} key={workflow.id} onClick={() => { setNotice(null); setSelectedWorkflowId(workflow.id); }} type="button">
                    <span className="workflow-list-mark" aria-hidden="true">{workflow.status === "published" ? "●" : "○"}</span>
                    <span><strong>{workflow.name}</strong><small>{workflow.current_version ? `Version ${workflow.current_version}` : "No version yet"} · {statusLabel(workflow.status)}</small></span>
                    <span className="row-arrow" aria-hidden="true">↗</span>
                  </button>
                ))}
              </div>
            )}
            {canEdit && (
              <div className="workflow-create-block">
                <button className="button button--dark workflow-create-toggle" onClick={() => setNewWorkflowOpen((current) => !current)} type="button">{newWorkflowOpen ? "Close" : "New workflow"}<span aria-hidden="true">{newWorkflowOpen ? "−" : "+"}</span></button>
                {newWorkflowOpen && (
                  <form className="workflow-create-form" onSubmit={handleCreateWorkflow}>
                    <label htmlFor="workflow-new-key">Workflow key</label>
                    <input id="workflow-new-key" onChange={(event) => setNewWorkflowKey(event.target.value.replace(/\s+/g, "-"))} placeholder="vendor-compliance" value={newWorkflowKey} />
                    <label htmlFor="workflow-new-name">Workflow name</label>
                    <input autoFocus id="workflow-new-name" onChange={(event) => setNewWorkflowName(event.target.value)} placeholder="Vendor compliance verification" value={newWorkflowName} />
                    <label htmlFor="workflow-new-description">Description</label>
                    <textarea id="workflow-new-description" onChange={(event) => setNewWorkflowDescription(event.target.value)} placeholder="What this workflow governs" rows={3} value={newWorkflowDescription} />
                    <label htmlFor="workflow-new-process">Discovery process id <span>(optional)</span></label>
                    <input id="workflow-new-process" onChange={(event) => setNewProcessId(event.target.value)} placeholder="process UUID" value={newProcessId} />
                    <button className="button button--primary" disabled={actionBusy === "create-workflow" || !newWorkflowName.trim() || !newWorkflowKey.trim()} type="submit">{actionBusy === "create-workflow" ? "Creating…" : "Create workflow"}<span aria-hidden="true">→</span></button>
                  </form>
                )}
              </div>
            )}
            <div className="workflow-index-note"><span className="boundary-mark" aria-hidden="true">i</span><p>Control flow belongs to the graph. Model nodes return schema-constrained content; they never select the next node.</p></div>
          </aside>

          <section className="workflow-workbench">
            {detailLoading && <div className="workflow-detail-loading"><div className="loader-ring" /><span>Loading definition and immutable history…</span></div>}
            {!detailLoading && !detail && <section className="workflow-empty-state"><span className="workflow-empty-glyph">⌁</span><p className="eyebrow">Choose a definition</p><h3>One graph, one release trail.</h3><p>Select a workflow from the index or create a new definition to start the form-driven build.</p></section>}
            {!detailLoading && detail && (
              <>
                <form className="workflow-panel workflow-metadata-panel" onSubmit={handleSaveMetadata}>
                  <div className="workflow-panel-heading"><div><p className="eyebrow">Definition metadata</p><h3>{detail.workflow.name}</h3><p>Metadata is mutable; published version content is not.</p></div><span className={`workflow-status-chip workflow-status-chip--${detail.workflow.status}`}>{statusLabel(detail.workflow.status)}</span></div>
                  <div className="workflow-metadata-grid">
                    <label className="workflow-field"><span>Workflow key</span><input disabled={!canEdit} onChange={(event) => setMetadata((current) => ({ ...current, key: event.target.value.replace(/\s+/g, "-") }))} value={metadata.key} /><small>Stable identifier used by connectors and audit exports.</small></label>
                    <label className="workflow-field"><span>Name</span><input disabled={!canEdit} onChange={(event) => setMetadata((current) => ({ ...current, name: event.target.value }))} value={metadata.name} /><small>Displayed to operators and in audit exports.</small></label>
                    <label className="workflow-field workflow-field--wide"><span>Description</span><textarea disabled={!canEdit} onChange={(event) => setMetadata((current) => ({ ...current, description: event.target.value }))} rows={3} value={metadata.description} /><small>Explain the governed operating path without placing credentials in the definition.</small></label>
                    <label className="workflow-field"><span>Discovery process id</span><input disabled={!canEdit} onChange={(event) => setMetadata((current) => ({ ...current, processId: event.target.value }))} placeholder="Optional signed-baseline link" value={metadata.processId} /><small>Keep the opportunity and workflow traceable.</small></label>
                  </div>
                  {canEdit && <div className="workflow-panel-actions"><span>Workspace: {workspace.name}</span><button className="button button--quiet" disabled={actionBusy === "metadata"} type="submit">{actionBusy === "metadata" ? "Saving…" : "Save metadata"}</button></div>}
                </form>

                <div className="workflow-release-grid">
                  <VersionHistory activeVersionId={activeVersionId} versions={versions} onSelect={(version) => { setActiveVersionId(version.id); setStudioTab("graph"); }} />
                  <EvaluationPanel gate={evaluationGate} stale={evaluationStale} canRun={canEditActiveVersion} busy={actionBusy} onEvaluate={() => void handleEvaluate()} />
                </div>

                <section className="workflow-panel workflow-version-panel">
                  <div className="workflow-panel-heading workflow-panel-heading--version"><div><p className="eyebrow">Version {activeVersion?.version ?? "—"} / {activeVersion?.status ? statusLabel(activeVersion.status) : "not created"}</p><h3>{activeVersion?.immutable_hash ? "Pinned release evidence" : "Shape the next version"}</h3><p>{activeVersion?.immutable_hash ? "This hash is the server-issued identity of the immutable version." : "The draft is editable through forms. Saving does not publish it."}</p></div><div className="workflow-version-actions">{activeVersion?.immutable_hash && <code title={activeVersion.immutable_hash}>{formatHash(activeVersion.immutable_hash)}</code>}{canEdit && activeVersion?.status === "published" && <button className="button button--primary" disabled={actionBusy === "create-draft"} onClick={() => void handleCreateDraft()} type="button">{actionBusy === "create-draft" ? "Creating…" : "Create editable draft"}<span aria-hidden="true">＋</span></button>}{canEditActiveVersion && <><button className="button button--quiet" disabled={actionBusy === "save-draft"} onClick={() => void handleSaveDraft()} type="button">{actionBusy === "save-draft" ? "Saving…" : "Save draft"}</button><button className="button button--quiet" disabled={actionBusy === "validate"} onClick={() => void handleValidate()} type="button">{actionBusy === "validate" ? "Checking…" : "Validate workflow"}</button><button className="button button--primary" disabled={actionBusy === "publish"} onClick={() => void handlePublish()} type="button">{actionBusy === "publish" ? "Publishing…" : "Publish workflow"}<span aria-hidden="true">↗</span></button></>}</div></div>
                  <div className="workflow-version-trail"><span>Created {formatDate(activeVersion?.created_at)}</span><span>·</span><span>Hash: {formatHash(activeVersion?.immutable_hash)}</span><span>·</span><span>{activeVersion?.published_at ? `Published ${formatDate(activeVersion.published_at)}` : "Not published"}</span></div>
                  <ValidationSummary issues={validationIssues} />
                  <div className="workflow-tab-row" role="tablist" aria-label="Workflow definition views"><button aria-selected={studioTab === "edit"} className={studioTab === "edit" ? "workflow-tab workflow-tab--active" : "workflow-tab"} onClick={() => setStudioTab("edit")} role="tab" type="button">Form editor</button><button aria-selected={studioTab === "graph"} className={studioTab === "graph" ? "workflow-tab workflow-tab--active" : "workflow-tab"} onClick={() => setStudioTab("graph")} role="tab" type="button">Read-only graph</button><span className="workflow-tab-note">{canEditActiveVersion ? "Keyboard-first editing" : "Published content is locked"}</span></div>
                  {studioTab === "graph" ? <ReadOnlyWorkflowGraph spec={effectiveSpec} selectedNodeKey={selectedNodeKey} onSelectNode={setSelectedNodeKey} /> : (
                    <div className="workflow-form-stack">
                      <label className="workflow-contract-label" htmlFor="workflow-node-type" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Node type</label>
                      <label className="workflow-contract-label" htmlFor="workflow-node-key" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Node key</label>
                      <section className="workflow-editor-section"><div className="workflow-section-heading"><div><p className="eyebrow">01 / Nodes</p><h4>Typed node definitions</h4><p>Each node declares its own safe configuration. No drag/drop state is stored.</p></div><span>{effectiveSpec.nodes.length} nodes</span></div>{canEditActiveVersion && <form className="workflow-add-node" onSubmit={handleNodeAdd}><label htmlFor="workflow-node-type">Type</label><select id="workflow-node-type" onChange={(event) => setNewNodeType(event.target.value as WorkflowNodeType)} value={newNodeType}>{WORKFLOW_NODE_TYPES.map((type) => <option key={type} value={type}>{NODE_TYPE_META[type].label}</option>)}</select><label htmlFor="workflow-node-key">Stable key</label><input id="workflow-node-key" onChange={(event) => setNewNodeKey(event.target.value.replace(/\s+/g, "_"))} placeholder={`${newNodeType}_1`} value={newNodeKey} /><button className="button button--dark" type="submit">Add node <span aria-hidden="true">+</span></button></form>}<div className="workflow-node-editor-layout"><div className="workflow-node-list" aria-label="Workflow nodes">{effectiveSpec.nodes.length === 0 ? <div className="workflow-sub-empty"><span>+</span><strong>Add the trigger node first.</strong><p>The graph stays empty until a real node is added to this draft.</p></div> : effectiveSpec.nodes.map((node) => { const nodeIssues = currentNodeIssues(node.node_key); return <button className={`workflow-node-list-item ${node.node_key === selectedNodeKey ? "workflow-node-list-item--active" : ""}`} key={node.node_key} onClick={() => setSelectedNodeKey(node.node_key)} type="button"><span className={`node-type-mark node-type-mark--${node.type}`}>{node.type.slice(0, 2).toUpperCase()}</span><span><strong>{node.label}</strong><small>{node.node_key} · {NODE_TYPE_META[node.type].determinism}</small></span>{nodeIssues.length > 0 && <em aria-label={`${nodeIssues.length} validation issues`}>{nodeIssues.length}</em>}</button>; })}</div><div className="workflow-node-form-wrap">{selectedNode ? <NodeEditor node={selectedNode} issues={currentNodeIssues(selectedNode.node_key)} readOnly={!canEditActiveVersion} onRemove={() => handleNodeRemove(selectedNode.node_key)} onUpdate={(updater) => handleNodeUpdate(selectedNode.node_key, updater)} /> : <div className="workflow-sub-empty workflow-sub-empty--large"><span>⌁</span><strong>Select a node to edit its schema.</strong><p>Node keys, typed config, and validation feedback stay visible together.</p></div>}</div></div></section>
                      <section className="workflow-editor-section"><div className="workflow-section-heading"><div><p className="eyebrow">02 / Edges</p><h4>Explicit routing</h4><p>Edges carry control flow. Conditions remain data for deterministic rule/score handling.</p></div><span>{effectiveSpec.edges.length} edges</span></div>{canEditActiveVersion && <form className="workflow-add-edge" onSubmit={handleEdgeAdd}><label htmlFor="workflow-edge-from">From<select id="workflow-edge-from" onChange={(event) => setEdgeFrom(event.target.value)} value={edgeFrom}><option value="">Choose node</option>{effectiveSpec.nodes.map((node) => <option key={node.node_key} value={node.node_key}>{node.label}</option>)}</select></label><span className="edge-arrow" aria-hidden="true">→</span><label htmlFor="workflow-edge-to">To<select id="workflow-edge-to" onChange={(event) => setEdgeTo(event.target.value)} value={edgeTo}><option value="">Choose node</option>{effectiveSpec.nodes.map((node) => <option key={node.node_key} value={node.node_key}>{node.label}</option>)}</select></label><label htmlFor="workflow-edge-condition">Condition <span>(optional)</span><input id="workflow-edge-condition" onChange={(event) => setEdgeCondition(event.target.value)} placeholder="approved == true" value={edgeCondition} /></label><button className="button button--dark" disabled={!edgeFrom || !edgeTo} type="submit">Add edge <span aria-hidden="true">+</span></button></form>}<div className="workflow-edge-table">{effectiveSpec.edges.length === 0 ? <div className="workflow-sub-empty"><span>→</span><strong>No routing edges yet.</strong><p>Add edges after defining the nodes they connect.</p></div> : effectiveSpec.edges.map((edge, index) => <div className="workflow-edge-row" key={edge.id || `${edge.from_node}-${edge.to_node}-${index}`}><span>{effectiveSpec.nodes.find((node) => node.node_key === edge.from_node)?.label || edge.from_node}</span><b aria-hidden="true">→</b><span>{effectiveSpec.nodes.find((node) => node.node_key === edge.to_node)?.label || edge.to_node}</span><small>{edge.condition || "unconditional"}</small>{canEditActiveVersion && <button aria-label={`Remove edge from ${edge.from_node} to ${edge.to_node}`} className="icon-button" onClick={() => updateSpec((current) => ({ ...current, edges: current.edges.filter((candidate) => candidate.id !== edge.id) }))} type="button">×</button>}</div>)}</div></section>
                      <div className="workflow-editor-two-column"><ThresholdEditor thresholds={effectiveSpec.thresholds} readOnly={!canEditActiveVersion} onChange={updateThreshold} /><ReferenceEditor kind="prompts" modelConfigs={effectiveSpec.model_configs} prompts={effectiveSpec.prompts} readOnly={!canEditActiveVersion} onModelChange={updateModelConfig} onPromptChange={updatePrompt} onChange={(next) => updateSpec((current) => ({ ...current, ...next }))} /></div>
                    </div>
                  )}
                </section>
              </>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

function WorkflowBoundaryState({ kind, onRetry }: { kind: "unavailable" | "denied" | "error"; onRetry?: () => void }) {
  const copy = {
    unavailable: { eyebrow: "W-01 / unavailable", title: "The workflow API is not available here yet.", body: "No placeholder definitions were loaded. Start the backend W-01 routes for this workspace, then retry to inspect real version history." },
    denied: { eyebrow: "403 / workflow boundary", title: "This workspace cannot expose workflow definitions.", body: "The API denied the current workspace context. Nothing was rendered from another tenant." },
    error: { eyebrow: "Workflow read failed", title: "The definition index could not be loaded.", body: "The client preserved the error boundary and did not invent workflow records. Retry after repairing the API or workspace context." },
  }[kind];
  return <section className="workflow-boundary-state" role="alert"><span className="workflow-boundary-mark" aria-hidden="true">{kind === "unavailable" ? "…" : "!"}</span><p className="eyebrow">{copy.eyebrow}</p><h3>{copy.title}</h3><p>{copy.body}</p>{onRetry && <button className="button button--dark" onClick={onRetry} type="button">Retry read <span aria-hidden="true">↗</span></button>}</section>;
}

function VersionHistory({ activeVersionId, versions, onSelect }: { activeVersionId: string | null; versions: WorkflowVersion[]; onSelect: (version: WorkflowVersion) => void }) {
  return <section className="workflow-panel workflow-history-panel"><div className="workflow-panel-heading workflow-panel-heading--compact"><div><p className="eyebrow">Immutable history</p><h3>Version ledger</h3></div><span className="workflow-panel-note">{versions.length} recorded</span></div>{versions.length === 0 ? <div className="workflow-history-empty">No version has been created yet.</div> : <div className="workflow-history-list">{versions.map((version) => <button className={`workflow-history-row ${version.id === activeVersionId ? "workflow-history-row--active" : ""}`} key={version.id} onClick={() => onSelect(version)} type="button"><span className={`history-version-mark history-version-mark--${version.status}`} aria-hidden="true">{version.status === "published" ? "✓" : "·"}</span><span><strong>Version {version.version}</strong><small>{statusLabel(version.status)} · {formatDate(version.created_at)}</small></span><code title={version.immutable_hash || "No immutable hash assigned"}>{formatHash(version.immutable_hash)}</code><span className="row-arrow" aria-hidden="true">→</span></button>)}</div>}</section>;
}

function EvaluationPanel({ gate, stale, canRun, busy, onEvaluate }: { gate: EvaluationGate; stale: boolean; canRun: boolean; busy: string | null; onEvaluate: () => void }) {
  const blocked = gate.status !== "passed" || stale;
  return <section className={`workflow-panel workflow-evaluation-panel workflow-evaluation-panel--${gate.status}`}><div className="workflow-panel-heading workflow-panel-heading--compact"><div><p className="eyebrow">E-01 / release gate</p><h3>Evaluation evidence</h3></div><span className="evaluation-status">{statusLabel(gate.status)}</span></div><p className="workflow-evaluation-copy">Publish is allowed only after the server evaluates this exact immutable draft candidate.</p>{stale && <div className="workflow-gate-warning" role="status"><span>!</span><p>The draft changed after the last evaluation. Save it and run the gate again.</p></div>}{gate.failure_reasons.length > 0 ? <ul className="workflow-failure-list">{gate.failure_reasons.map((reason) => <li key={reason}><span>×</span>{reason}</li>)}</ul> : <div className="workflow-gate-empty"><span aria-hidden="true">{gate.status === "passed" ? "✓" : "·"}</span><p>{gate.status === "passed" ? "No failing reasons recorded for this run." : "No evaluation result is recorded for this version."}</p></div>}<div className="workflow-evaluation-footer"><small>{gate.run_id ? `Run ${gate.run_id}` : "Evaluation run required"}{gate.evaluated_at ? ` · ${formatDate(gate.evaluated_at)}` : ""}</small>{canRun && <button className="button button--quiet" disabled={busy === "evaluate" || (gate.status === "passed" && !stale)} onClick={onEvaluate} type="button">{busy === "evaluate" ? "Running…" : blocked ? "Run evaluation" : "Evaluation passed"}</button>}</div></section>;
}

function ValidationSummary({ issues }: { issues: WorkflowValidationIssue[] }) {
  const errors = issues.filter((issueItem) => issueItem.severity === "error");
  const warnings = issues.filter((issueItem) => issueItem.severity === "warning");
  return <section className={`workflow-validation-summary ${errors.length > 0 ? "workflow-validation-summary--error" : "workflow-validation-summary--ok"}`} aria-live="polite"><div><span className="validation-mark" aria-hidden="true">{errors.length > 0 ? "!" : "✓"}</span><div><strong>{errors.length > 0 ? `${errors.length} blocking schema issue${errors.length === 1 ? "" : "s"}` : "No blocking schema issues"}</strong><small>{warnings.length > 0 ? `${warnings.length} warning${warnings.length === 1 ? "" : "s"} remain visible below.` : "Deterministic validation runs in the browser before the API gate."}</small></div></div>{issues.length > 0 && <ul>{issues.map((issueItem) => <li key={`${issueItem.code}:${issueItem.path}:${issueItem.message}`}><span className={issueItem.severity === "warning" ? "validation-item-mark validation-item-mark--warning" : "validation-item-mark"}>{issueItem.severity === "warning" ? "i" : "!"}</span><span><strong>{issueItem.path}</strong>{issueItem.message}</span></li>)}</ul>}</section>;
}

function NodeEditor({ node, issues, readOnly, onUpdate, onRemove }: { node: WorkflowNode; issues: WorkflowValidationIssue[]; readOnly: boolean; onUpdate: (updater: (node: WorkflowNode) => WorkflowNode) => void; onRemove: () => void }) {
  const fields = NODE_CONFIG_FIELDS[node.type];
  const issueFor = (key: string) => issues.filter((issueItem) => issueItem.path.includes(key));
  function updateConfig(key: string, rawValue: string | boolean) {
    onUpdate((current) => ({ ...current, config: { ...current.config, [key]: rawValue } }));
  }
  return <div className="workflow-node-editor"><div className="workflow-node-editor-heading"><div><span className={`node-type-mark node-type-mark--${node.type}`}>{node.type.slice(0, 2).toUpperCase()}</span><div><p className="eyebrow">{NODE_TYPE_META[node.type].determinism} node</p><h4>{NODE_TYPE_META[node.type].label}</h4></div></div>{!readOnly && <button className="button button--danger-quiet" onClick={onRemove} type="button">Remove</button>}</div><label className="workflow-field"><span>Stable key</span><input disabled value={node.node_key} /><small>Keys are immutable identifiers for edges and execution evidence.</small></label><label className="workflow-field"><span>Operator label</span><input aria-invalid={issues.some((issueItem) => issueItem.code === "node_label_required") || undefined} disabled={readOnly} onChange={(event) => onUpdate((current) => ({ ...current, label: event.target.value }))} value={node.label} /><small>{NODE_TYPE_META[node.type].description}</small></label><div className="workflow-config-fields">{fields.map((field) => { const fieldIssues = issueFor(field.key); const rawValue = node.config[field.key]; const value = field.kind === "checkbox" ? Boolean(rawValue) : field.kind === "json" && typeof rawValue === "object" ? JSON.stringify(rawValue, null, 2) : stringValue(rawValue); const inputValue = typeof value === "boolean" ? String(value) : value; return <label className={`workflow-field workflow-config-field workflow-config-field--${field.kind}`} key={field.key}><span>{field.label}{field.required && <em>required</em>}</span>{field.kind === "checkbox" ? <input aria-describedby={`${node.node_key}-${field.key}-hint`} checked={Boolean(rawValue)} disabled={readOnly} onChange={(event) => updateConfig(field.key, event.target.checked)} type="checkbox" /> : field.kind === "textarea" || field.kind === "json" ? <textarea aria-describedby={`${node.node_key}-${field.key}-hint`} aria-invalid={fieldIssues.length > 0 || undefined} disabled={readOnly} onChange={(event) => updateConfig(field.key, event.target.value)} rows={field.kind === "json" ? 5 : 3} value={inputValue} /> : <input aria-describedby={`${node.node_key}-${field.key}-hint`} aria-invalid={fieldIssues.length > 0 || undefined} disabled={readOnly} onChange={(event) => updateConfig(field.key, event.target.value)} type={field.kind === "number" ? "number" : "text"} value={inputValue} />}<small id={`${node.node_key}-${field.key}-hint`}>{field.hint}</small>{fieldIssues.map((issueItem) => <span className="workflow-field-error" key={`${issueItem.code}:${issueItem.path}`}>{issueItem.message}</span>)}</label>; })}</div>{issues.length > 0 && <div className="workflow-node-issues"><strong>Validation for this node</strong>{issues.map((issueItem) => <p key={`${issueItem.code}:${issueItem.path}`}>{issueItem.message}</p>)}</div>}</div>;
}

function ReadOnlyWorkflowGraph({ spec, selectedNodeKey, onSelectNode }: { spec: WorkflowSpec; selectedNodeKey: string | null; onSelectNode: (nodeKey: string) => void }) {
  const levels = useMemo(() => layoutGraph(spec), [spec]);
  const graphWidth = Math.max(520, levels.reduce((max, column) => Math.max(max, column.length), 0) * 260);
  const graphHeight = Math.max(230, Math.max(...levels.map((column) => column.length), 1) * 132 + 32);
  const position = new Map<string, { x: number; y: number }>();
  levels.forEach((column, level) => column.forEach((node, index) => position.set(node.node_key, { x: level * 260 + 28, y: index * 132 + 26 })));
  return <section className="workflow-graph-wrap" data-read-only="true" data-testid="workflow-graph" aria-label="Read-only workflow graph"><div className="workflow-graph-header"><div><p className="eyebrow">Read-only representation</p><h4>Control flow at a glance</h4></div><span>{spec.nodes.length} nodes · {spec.edges.length} edges</span></div>{spec.nodes.length === 0 ? <div className="workflow-sub-empty workflow-sub-empty--large"><span>⌁</span><strong>No nodes to visualize.</strong><p>Add a real node to the draft; this view never fabricates a graph.</p></div> : <div className="workflow-graph-scroller"><div className="workflow-graph-canvas" style={{ height: graphHeight, minWidth: graphWidth }}><svg aria-hidden="true" className="workflow-graph-edges" height={graphHeight} viewBox={`0 0 ${graphWidth} ${graphHeight}`} width={graphWidth}>{spec.edges.map((edge) => { const from = position.get(edge.from_node); const to = position.get(edge.to_node); if (!from || !to) return null; const startX = from.x + 192; const startY = from.y + 46; const endX = to.x; const endY = to.y + 46; const bend = Math.max(26, (endX - startX) / 2); return <path d={`M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`} key={edge.id} />; })}</svg>{spec.nodes.map((node) => { const point = position.get(node.node_key) ?? { x: 0, y: 0 }; return <button className={`workflow-graph-node ${node.node_key === selectedNodeKey ? "workflow-graph-node--active" : ""}`} key={node.node_key} onClick={() => onSelectNode(node.node_key)} style={{ left: point.x, top: point.y }} type="button"><span className={`node-type-mark node-type-mark--${node.type}`}>{node.type.slice(0, 2).toUpperCase()}</span><span><strong>{node.label}</strong><small>{node.node_key}</small></span></button>; })}</div></div>}<p className="workflow-graph-note"><span aria-hidden="true">↳</span> Nodes are positioned from deterministic graph order for inspection. This is intentionally not a drag/drop canvas.</p></section>;
}

function layoutGraph(spec: WorkflowSpec): WorkflowNode[][] {
  if (spec.nodes.length === 0) return [];
  const outgoing = new Map(spec.nodes.map((node) => [node.node_key, [] as string[]]));
  const incoming = new Map(spec.nodes.map((node) => [node.node_key, 0]));
  spec.edges.forEach((edge) => { outgoing.get(edge.from_node)?.push(edge.to_node); incoming.set(edge.to_node, (incoming.get(edge.to_node) ?? 0) + 1); });
  const depth = new Map<string, number>();
  const queue = spec.nodes.filter((node) => (incoming.get(node.node_key) ?? 0) === 0).map((node) => node.node_key);
  if (queue.length === 0) queue.push(spec.nodes[0].node_key);
  while (queue.length > 0) { const key = queue.shift(); if (!key) continue; const nextDepth = depth.get(key) ?? 0; for (const target of outgoing.get(key) ?? []) { depth.set(target, Math.max(depth.get(target) ?? 0, nextDepth + 1)); queue.push(target); } }
  spec.nodes.forEach((node, index) => { if (!depth.has(node.node_key)) depth.set(node.node_key, index); });
  const maxDepth = Math.max(...depth.values(), 0);
  return Array.from({ length: maxDepth + 1 }, (_, level) => spec.nodes.filter((node) => depth.get(node.node_key) === level));
}

function ThresholdEditor({ thresholds, readOnly, onChange }: { thresholds: WorkflowSpec["thresholds"]; readOnly: boolean; onChange: (key: string, value: string) => void }) {
  return <section className="workflow-editor-card"><div className="workflow-section-heading"><div><p className="eyebrow">03 / Thresholds</p><h4>Customer risk posture</h4><p>Thresholds are versioned with the graph and never hidden in model output.</p></div><span>3 controls</span></div><div className="workflow-threshold-list">{thresholds.map((threshold) => <label className="workflow-field" key={threshold.key}><span>{threshold.label || threshold.key}</span><div className="workflow-input-suffix"><input aria-label={threshold.label || threshold.key} disabled={readOnly} min={threshold.key.startsWith("theta_") ? 0 : undefined} max={threshold.key.startsWith("theta_") ? 1 : undefined} onChange={(event) => onChange(threshold.key, event.target.value)} step="0.01" type="number" value={threshold.value ?? ""} /><em>{threshold.unit || "value"}</em></div><small>{threshold.key}</small></label>)}</div></section>;
}

function ReferenceEditor({ kind, prompts, modelConfigs, readOnly, onPromptChange, onModelChange, onChange }: { kind: "prompts"; prompts: WorkflowPromptReference[]; modelConfigs: WorkflowModelConfigReference[]; readOnly: boolean; onPromptChange: (index: number, field: keyof WorkflowPromptReference, value: string) => void; onModelChange: (index: number, field: keyof WorkflowModelConfigReference, value: string) => void; onChange: (next: Pick<WorkflowSpec, "prompts" | "model_configs">) => void }) {
  return <section className="workflow-editor-card"><div className="workflow-section-heading"><div><p className="eyebrow">04 / Registries</p><h4>Prompt + model references</h4><p>Nodes pin registry keys and versions; no credential or inline prompt values are accepted.</p></div><span>{prompts.length + modelConfigs.length} refs</span></div><div className="workflow-reference-group"><div className="workflow-reference-heading"><strong>Prompt versions</strong>{!readOnly && <button className="text-button" onClick={() => onChange({ prompts: [...prompts, { key: "", version: null }], model_configs: modelConfigs })} type="button">+ Add</button>}</div>{prompts.length === 0 ? <p className="workflow-reference-empty">No prompt reference declared.</p> : prompts.map((prompt, index) => <div className="workflow-reference-row" key={`prompt-${index}`}><input aria-label={`Prompt key ${index + 1}`} disabled={readOnly} onChange={(event) => onPromptChange(index, "key", event.target.value)} placeholder="prompt.key" value={prompt.key} /><input aria-label={`Prompt version ${index + 1}`} disabled={readOnly} min="1" onChange={(event) => onPromptChange(index, "version", event.target.value)} placeholder="v" type="number" value={prompt.version ?? ""} />{!readOnly && <button aria-label={`Remove prompt reference ${index + 1}`} className="icon-button" onClick={() => onChange({ prompts: prompts.filter((_, promptIndex) => promptIndex !== index), model_configs: modelConfigs })} type="button">×</button>}</div>)}</div><div className="workflow-reference-group"><div className="workflow-reference-heading"><strong>Model configurations</strong>{!readOnly && <button className="text-button" onClick={() => onChange({ prompts, model_configs: [...modelConfigs, { key: "", provider: "", version: null }] })} type="button">+ Add</button>}</div>{modelConfigs.length === 0 ? <p className="workflow-reference-empty">No model configuration reference declared.</p> : modelConfigs.map((config, index) => <div className="workflow-reference-row workflow-reference-row--model" key={`model-${index}`}><input aria-label={`Model config key ${index + 1}`} disabled={readOnly} onChange={(event) => onModelChange(index, "key", event.target.value)} placeholder="model.config.key" value={config.key} /><input aria-label={`Model provider ${index + 1}`} disabled={readOnly} onChange={(event) => onModelChange(index, "provider", event.target.value)} placeholder="provider" value={config.provider} /><input aria-label={`Model config version ${index + 1}`} disabled={readOnly} min="1" onChange={(event) => onModelChange(index, "version", event.target.value)} placeholder="v" type="number" value={config.version ?? ""} />{!readOnly && <button aria-label={`Remove model configuration ${index + 1}`} className="icon-button" onClick={() => onChange({ prompts, model_configs: modelConfigs.filter((_, configIndex) => configIndex !== index) })} type="button">×</button>}</div>)}</div></section>;
}
