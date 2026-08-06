import type {
  EvaluationGate,
  EvaluationGateStatus,
  WorkflowDetail,
  WorkflowEdge,
  WorkflowListResponse,
  WorkflowModelConfigReference,
  WorkflowNode,
  WorkflowNodeType,
  WorkflowPromptReference,
  WorkflowSpec,
  WorkflowSummary,
  WorkflowThreshold,
  WorkflowValidationIssue,
  WorkflowVersion,
} from "./types.ts";
import { WORKFLOW_NODE_TYPES } from "./types.ts";

export interface WorkflowNodeTypeMeta {
  label: string;
  description: string;
  determinism: "deterministic" | "model" | "human";
}

export const NODE_TYPE_META: Record<WorkflowNodeType, WorkflowNodeTypeMeta> = {
  trigger: { label: "Trigger", description: "Start a run from an event, schedule, or manual action.", determinism: "deterministic" },
  fetch: { label: "Fetch", description: "Pull a document or record from a declared source.", determinism: "deterministic" },
  parse: { label: "Parse", description: "Turn a document into text, layout, and tables.", determinism: "deterministic" },
  classify: { label: "Classify", description: "Return a constrained document or intent class.", determinism: "model" },
  extract: { label: "Extract", description: "Return fields against a versioned output schema.", determinism: "model" },
  rule: { label: "Rule", description: "Evaluate deterministic validation or policy logic.", determinism: "deterministic" },
  score: { label: "Score", description: "Aggregate signals and route on configured thresholds.", determinism: "deterministic" },
  llm: { label: "LLM", description: "Run bounded judgement with a registered prompt and schema.", determinism: "model" },
  tool: { label: "Tool", description: "Call an allow-listed connector with write safety metadata.", determinism: "deterministic" },
  approve: { label: "Approve", description: "Pause for a human decision before continuing.", determinism: "human" },
  notify: { label: "Notify", description: "Send a declared message through a connector.", determinism: "deterministic" },
  halt: { label: "Halt", description: "Stop safely with a recorded reason.", determinism: "deterministic" },
};

export type WorkflowConfigFieldKind = "text" | "textarea" | "json" | "number" | "checkbox";

export interface WorkflowConfigField {
  key: string;
  label: string;
  hint: string;
  kind: WorkflowConfigFieldKind;
  required?: boolean;
}

export const NODE_CONFIG_FIELDS: Record<WorkflowNodeType, WorkflowConfigField[]> = {
  trigger: [
    { key: "event", label: "Event", hint: "For example: document.received or manual.start", kind: "text", required: true },
  ],
  fetch: [
    { key: "source", label: "Source", hint: "Reference a connector or data source key, never a secret value.", kind: "text", required: true },
  ],
  parse: [
    { key: "document_type", label: "Document type", hint: "The parser contract this node accepts.", kind: "text", required: true },
  ],
  classify: [
    { key: "output_labels", label: "Allowed labels", hint: "JSON array of the only labels the model may return.", kind: "json", required: true },
    { key: "model_config_key", label: "Model config key", hint: "Registered model configuration reference.", kind: "text" },
  ],
  extract: [
    { key: "fields", label: "Fields", hint: "JSON array of field names to extract.", kind: "json", required: true },
    { key: "output_schema", label: "Output schema", hint: "JSON object describing the schema-constrained response.", kind: "json", required: true },
    { key: "model_config_key", label: "Model config key", hint: "Registered model configuration reference.", kind: "text" },
  ],
  rule: [
    { key: "expression", label: "Expression", hint: "Deterministic expression; models cannot change control flow.", kind: "textarea", required: true },
  ],
  score: [
    { key: "signals", label: "Signals", hint: "JSON array of signal keys consumed by the deterministic scorer.", kind: "json", required: true },
    { key: "threshold_key", label: "Threshold key", hint: "Optional threshold reference for the route.", kind: "text" },
  ],
  llm: [
    { key: "prompt_key", label: "Prompt key", hint: "Registered prompt reference. Do not inline prompt text here.", kind: "text", required: true },
    { key: "model_config_key", label: "Model config key", hint: "Registered model configuration reference.", kind: "text", required: true },
    { key: "output_schema", label: "Output schema", hint: "JSON object. Free-text model output is not publishable.", kind: "json", required: true },
  ],
  tool: [
    { key: "tool_key", label: "Allow-listed tool", hint: "Connector tool key; raw credentials never belong in workflow config.", kind: "text", required: true },
    { key: "writes_external", label: "Writes to an external system", hint: "Write tools require idempotency and compensation metadata.", kind: "checkbox" },
    { key: "idempotency_key", label: "Idempotency key", hint: "Required for external writes.", kind: "text" },
    { key: "compensation", label: "Compensation", hint: "The safe compensating action for an external write.", kind: "textarea" },
  ],
  approve: [
    { key: "queue", label: "Review queue", hint: "Human queue or role that owns the decision.", kind: "text", required: true },
    { key: "reason_code", label: "Reason code", hint: "Optional default reason code for the review task.", kind: "text" },
  ],
  notify: [
    { key: "channel", label: "Channel", hint: "For example: email, slack, teams, or webhook.", kind: "text", required: true },
    { key: "template_key", label: "Template key", hint: "Registered message template reference.", kind: "text", required: true },
  ],
  halt: [
    { key: "reason", label: "Halt reason", hint: "Human-readable reason recorded in the execution ledger.", kind: "textarea", required: true },
  ],
};

const REQUIRED_CONFIG_KEYS: Partial<Record<WorkflowNodeType, string[]>> = Object.fromEntries(
  WORKFLOW_NODE_TYPES.map((type) => [
    type,
    NODE_CONFIG_FIELDS[type].filter((field) => field.required).map((field) => field.key),
  ]),
) as Partial<Record<WorkflowNodeType, string[]>>;

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringOf(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : value === null || value === undefined ? fallback : String(value);
}

function numberOf(value: unknown, fallback: number | null = null): number | null {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function arrayOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function objectOrEmpty(value: unknown): Record<string, unknown> {
  return recordOf(value);
}

function parseJsonValue(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

function hasValue(config: Record<string, unknown>, key: string): boolean {
  const value = config[key];
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(recordOf(value)).length > 0;
  return true;
}

function issue(code: string, path: string, message: string, nodeKey: string | null = null, severity: "error" | "warning" = "error"): WorkflowValidationIssue {
  return { code, path, message, severity, node_key: nodeKey };
}

export function emptyWorkflowSpec(): WorkflowSpec {
  return {
    schema_version: "workflow.v1",
    nodes: [],
    edges: [],
    thresholds: [
      { key: "theta_review", value: null, label: "Review threshold", unit: "confidence" },
      { key: "theta_auto", value: null, label: "Auto threshold", unit: "confidence" },
      { key: "value_at_risk_limit", value: null, label: "Value-at-risk limit", unit: "USD" },
    ],
    prompts: [],
    model_configs: [],
  };
}

export function defaultNodeConfig(type: WorkflowNodeType): Record<string, unknown> {
  switch (type) {
    case "classify": return { output_labels: [] };
    case "extract": return { fields: [], output_schema: {} };
    case "score": return { signals: [] };
    case "llm": return { output_schema: {} };
    case "tool": return { writes_external: false };
    default: return {};
  }
}

export function createLocalNode(type: WorkflowNodeType, index: number): WorkflowNode {
  const key = `${type}_${index}`;
  return { id: `local-${key}`, node_key: key, type, label: NODE_TYPE_META[type].label, config: defaultNodeConfig(type) };
}

export function validateWorkflowSpec(spec: WorkflowSpec): WorkflowValidationIssue[] {
  const issues: WorkflowValidationIssue[] = [];
  if (spec.schema_version !== "workflow.v1") {
    issues.push(issue("unsupported_schema", "schema_version", "This workflow uses an unsupported schema version."));
  }
  if (spec.nodes.length === 0) {
    issues.push(issue("empty_graph", "nodes", "Add at least one node before saving or publishing."));
  }

  const nodeKeys = new Set<string>();
  const nodeByKey = new Map<string, WorkflowNode>();
  spec.nodes.forEach((node, index) => {
    const path = `nodes[${index}]`;
    if (!node.node_key.trim()) issues.push(issue("node_key_required", `${path}.node_key`, "Every node needs a stable key.", node.node_key || null));
    if (nodeKeys.has(node.node_key)) issues.push(issue("duplicate_node_key", `${path}.node_key`, `Node key “${node.node_key}” is used more than once.`, node.node_key));
    nodeKeys.add(node.node_key);
    nodeByKey.set(node.node_key, node);
    if (!WORKFLOW_NODE_TYPES.includes(node.type)) issues.push(issue("unknown_node_type", `${path}.type`, `“${node.type}” is not a supported node type.`, node.node_key));
    if (!node.label.trim()) issues.push(issue("node_label_required", `${path}.label`, "Give the node a label operators can recognize.", node.node_key));

    for (const key of REQUIRED_CONFIG_KEYS[node.type] ?? []) {
      if (!hasValue(node.config, key)) issues.push(issue("node_config_required", `${path}.config.${key}`, `${NODE_TYPE_META[node.type].label} nodes require “${key}”.`, node.node_key));
    }
    for (const field of NODE_CONFIG_FIELDS[node.type] ?? []) {
      if (field.kind !== "json" || !hasValue(node.config, field.key)) continue;
      const parsed = parseJsonValue(node.config[field.key]);
      if (typeof node.config[field.key] === "string" && parsed === node.config[field.key]) {
        issues.push(issue("invalid_json_config", `${path}.config.${field.key}`, `“${field.label}” must be valid JSON.`, node.node_key));
      } else if (field.key === "output_schema" && (Array.isArray(parsed) || typeof parsed !== "object" || parsed === null)) {
        issues.push(issue("output_schema_object_required", `${path}.config.${field.key}`, "Schema-constrained output must be a JSON object.", node.node_key));
      }
    }
    if (node.type === "tool" && Boolean(node.config.writes_external)) {
      if (!hasValue(node.config, "idempotency_key")) issues.push(issue("idempotency_key_required", `${path}.config.idempotency_key`, "External writes require an idempotency key.", node.node_key));
      if (!hasValue(node.config, "compensation")) issues.push(issue("compensation_required", `${path}.config.compensation`, "External writes require a compensating action.", node.node_key));
    }
  });

  const edgeKeys = new Set<string>();
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  for (const node of spec.nodes) {
    outgoing.set(node.node_key, []);
    incoming.set(node.node_key, []);
  }
  spec.edges.forEach((edge, index) => {
    const path = `edges[${index}]`;
    if (!nodeByKey.has(edge.from_node)) issues.push(issue("edge_source_missing", `${path}.from_node`, `Source node “${edge.from_node}” does not exist.`));
    if (!nodeByKey.has(edge.to_node)) issues.push(issue("edge_target_missing", `${path}.to_node`, `Target node “${edge.to_node}” does not exist.`));
    if (edge.from_node === edge.to_node) issues.push(issue("self_cycle", path, "A node cannot point to itself.", edge.from_node));
    const edgeKey = `${edge.from_node}→${edge.to_node}→${edge.condition ?? ""}`;
    if (edgeKeys.has(edgeKey)) issues.push(issue("duplicate_edge", path, "This edge is duplicated."));
    edgeKeys.add(edgeKey);
    if (nodeByKey.has(edge.from_node) && nodeByKey.has(edge.to_node)) {
      outgoing.get(edge.from_node)?.push(edge.to_node);
      incoming.get(edge.to_node)?.push(edge.from_node);
    }
  });

  const triggerNodes = spec.nodes.filter((node) => node.type === "trigger");
  if (spec.nodes.length > 0 && triggerNodes.length === 0) issues.push(issue("trigger_required", "nodes", "A workflow needs at least one trigger node."));
  const visited = new Set<string>();
  const visiting = new Set<string>();
  const visit = (nodeKey: string) => {
    if (visiting.has(nodeKey)) {
      issues.push(issue("cycle_detected", "edges", "Cycles are not publishable. Route forward through rule or score nodes instead."));
      return;
    }
    if (visited.has(nodeKey)) return;
    visiting.add(nodeKey);
    for (const target of outgoing.get(nodeKey) ?? []) visit(target);
    visiting.delete(nodeKey);
    visited.add(nodeKey);
  };
  for (const node of spec.nodes) visit(node.node_key);

  const reachable = new Set<string>();
  const queue = triggerNodes.map((node) => node.node_key);
  while (queue.length > 0) {
    const nodeKey = queue.shift();
    if (!nodeKey || reachable.has(nodeKey)) continue;
    reachable.add(nodeKey);
    queue.push(...(outgoing.get(nodeKey) ?? []));
  }
  for (const node of spec.nodes) {
    if (triggerNodes.length > 0 && !reachable.has(node.node_key)) {
      issues.push(issue("unreachable_node", `nodes.${node.node_key}`, `Node “${node.label || node.node_key}” is not reachable from a trigger.`, node.node_key));
    }
    if (node.type === "halt" && (outgoing.get(node.node_key)?.length ?? 0) > 0) {
      issues.push(issue("halt_must_be_terminal", `nodes.${node.node_key}`, "A halt node cannot route to another node.", node.node_key));
    }
    if (node.type === "llm" && (outgoing.get(node.node_key)?.length ?? 0) > 0) {
      issues.push(issue("model_cannot_route", `nodes.${node.node_key}`, "Models may produce bounded output, but rule or score nodes must own routing.", node.node_key, "warning"));
    }
  }

  const thresholdMap = new Map<string, WorkflowThreshold>();
  spec.thresholds.forEach((threshold, index) => {
    if (thresholdMap.has(threshold.key)) issues.push(issue("duplicate_threshold", `thresholds[${index}].key`, `Threshold “${threshold.key}” is duplicated.`));
    thresholdMap.set(threshold.key, threshold);
    if (threshold.value === null || !Number.isFinite(threshold.value)) {
      issues.push(issue("threshold_value_required", `thresholds[${index}].value`, `Set a numeric value for “${threshold.key}”.`));
    } else if (["theta_review", "theta_auto"].includes(threshold.key) && (threshold.value < 0 || threshold.value > 1)) {
      issues.push(issue("threshold_range", `thresholds[${index}].value`, `“${threshold.key}” must be between 0 and 1.`));
    } else if (threshold.key === "value_at_risk_limit" && threshold.value < 0) {
      issues.push(issue("threshold_non_negative", `thresholds[${index}].value`, "Value-at-risk limit cannot be negative."));
    }
  });
  for (const key of ["theta_review", "theta_auto", "value_at_risk_limit"]) {
    if (!thresholdMap.has(key)) issues.push(issue("threshold_required", `thresholds.${key}`, `Add the required “${key}” threshold.`));
  }
  const review = thresholdMap.get("theta_review")?.value;
  const automatic = thresholdMap.get("theta_auto")?.value;
  if (review !== null && review !== undefined && automatic !== null && automatic !== undefined && review > automatic) {
    issues.push(issue("threshold_order", "thresholds", "Review threshold cannot be higher than the auto threshold."));
  }

  validateReferences(spec.prompts, "prompt", issues);
  validateReferences(spec.model_configs, "model_config", issues);
  const promptKeys = new Set(spec.prompts.map((prompt) => prompt.key));
  const modelConfigKeys = new Set(spec.model_configs.map((config) => config.key));
  for (const node of spec.nodes) {
    if (node.type === "llm" && hasValue(node.config, "prompt_key") && !promptKeys.has(String(node.config.prompt_key))) {
      issues.push(issue("prompt_reference_missing", `nodes.${node.node_key}.config.prompt_key`, `Prompt “${node.config.prompt_key}” is not registered.`, node.node_key));
    }
    const modelKey = node.config.model_config_key;
    if (["llm", "extract", "classify"].includes(node.type) && hasValue(node.config, "model_config_key") && !modelConfigKeys.has(String(modelKey))) {
      issues.push(issue("model_config_reference_missing", `nodes.${node.node_key}.config.model_config_key`, `Model config “${modelKey}” is not registered.`, node.node_key));
    }
  }

  return issues;
}

function validateReferences(values: Array<WorkflowPromptReference | WorkflowModelConfigReference>, kind: string, issues: WorkflowValidationIssue[]) {
  const keys = new Set<string>();
  values.forEach((value, index) => {
    if (!value.key.trim()) issues.push(issue(`${kind}_key_required`, `${kind}s[${index}].key`, `Every ${kind.replace("_", " ")} reference needs a key.`));
    if (keys.has(value.key)) issues.push(issue(`duplicate_${kind}`, `${kind}s[${index}].key`, `${kind.replace("_", " ")} “${value.key}” is duplicated.`));
    keys.add(value.key);
    if (value.version === null || value.version < 1) issues.push(issue(`${kind}_version_required`, `${kind}s[${index}].version`, `Pin ${kind.replace("_", " ")} “${value.key}” to a positive version.`));
  });
}

export function serializeWorkflowSpec(spec: WorkflowSpec): Record<string, unknown> {
  return {
    schema_version: spec.schema_version,
    nodes: spec.nodes.map((node) => ({ id: node.id, key: node.node_key, type: node.type, label: node.label, config: node.config })),
    edges: spec.edges.map((edge) => ({ id: edge.id, from_node: edge.from_node, to_node: edge.to_node, condition: edge.condition })),
    thresholds: spec.thresholds.filter((threshold) => threshold.value !== null).map((threshold) => ({ key: threshold.key, value: threshold.value, description: threshold.label || threshold.unit })),
    prompts: spec.prompts.map((prompt) => ({ key: prompt.key, version: prompt.version })),
    model_configs: spec.model_configs.map((modelConfig) => ({ key: modelConfig.key, provider: modelConfig.provider, version: modelConfig.version })),
  };
}

function normalizeNode(raw: unknown, index: number): WorkflowNode {
  const value = recordOf(raw);
  const rawType = stringOf(value.type, "halt");
  const type = (WORKFLOW_NODE_TYPES.includes(rawType as WorkflowNodeType) ? rawType : "halt") as WorkflowNodeType;
  const nodeKey = stringOf(value.node_key ?? value.key ?? value.id, `node_${index + 1}`);
  return {
    id: stringOf(value.id, `server-${nodeKey}`),
    node_key: nodeKey,
    type,
    label: stringOf(value.label, NODE_TYPE_META[type].label),
    config: objectOrEmpty(value.config ?? value.config_json),
  };
}

function normalizeEdge(raw: unknown, index: number): WorkflowEdge {
  const value = recordOf(raw);
  return {
    id: stringOf(value.id, `edge-${index + 1}`),
    from_node: stringOf(value.from_node ?? value.from ?? value.source),
    to_node: stringOf(value.to_node ?? value.to ?? value.target),
    condition: value.condition === null || value.condition === undefined ? null : stringOf(value.condition),
  };
}

function normalizeSpec(raw: unknown): WorkflowSpec {
  const value = recordOf(raw);
  const candidate = recordOf(value.spec ?? value.spec_json ?? value.definition ?? value);
  const nodes = arrayOf(candidate.nodes).map(normalizeNode);
  const edges = arrayOf(candidate.edges).map(normalizeEdge);
  const thresholds: WorkflowThreshold[] = arrayOf(candidate.thresholds).map((entry) => {
    const threshold = recordOf(entry);
    return { key: stringOf(threshold.key), value: numberOf(threshold.value), label: stringOf(threshold.label) || undefined, unit: stringOf(threshold.unit) || undefined };
  });
  const prompts: WorkflowPromptReference[] = arrayOf(candidate.prompts).map((entry) => {
    const prompt = recordOf(entry);
    return { key: stringOf(prompt.key), version: numberOf(prompt.version) };
  });
  const modelConfigs: WorkflowModelConfigReference[] = arrayOf(candidate.model_configs ?? candidate.modelConfigs).map((entry) => {
    const modelConfig = recordOf(entry);
    return { key: stringOf(modelConfig.key), provider: stringOf(modelConfig.provider), version: numberOf(modelConfig.version) };
  });
  const defaults = emptyWorkflowSpec();
  return {
    schema_version: stringOf(candidate.schema_version, "workflow.v1"),
    nodes,
    edges,
    thresholds: thresholds.length > 0 ? thresholds : defaults.thresholds,
    prompts,
    model_configs: modelConfigs,
  };
}

function normalizeGate(raw: unknown): EvaluationGate {
  const value = recordOf(raw);
  const status = stringOf(value.status, "not_run") as EvaluationGateStatus;
  const reasons = arrayOf(value.failure_reasons ?? value.failures ?? value.reasons).map((reason) => stringOf(reason)).filter(Boolean);
  const rawMetrics = recordOf(value.metric_deltas ?? value.metrics);
  const metricDeltas = Object.fromEntries(Object.entries(rawMetrics).map(([key, metric]) => [key, typeof metric === "string" || typeof metric === "number" ? metric : null]));
  return {
    status,
    run_id: value.run_id === null || value.run_id === undefined ? null : stringOf(value.run_id),
    evaluated_at: value.evaluated_at === null || value.evaluated_at === undefined ? null : stringOf(value.evaluated_at),
    failure_reasons: reasons,
    metric_deltas: metricDeltas,
  };
}

function normalizeIssues(raw: unknown): WorkflowValidationIssue[] {
  return arrayOf(raw).map((entry) => {
    const value = recordOf(entry);
    return {
      code: stringOf(value.code, "validation_error"),
      path: stringOf(value.path, "workflow"),
      message: stringOf(value.message, "The workflow has a validation error."),
      severity: value.severity === "warning" ? "warning" : "error",
      node_key: value.node_key === null || value.node_key === undefined ? null : stringOf(value.node_key),
    };
  });
}

export function normalizeWorkflowSummary(raw: unknown): WorkflowSummary {
  const value = recordOf(raw);
  return {
    id: stringOf(value.id),
    workspace_id: stringOf(value.workspace_id),
    process_id: value.process_id === null || value.process_id === undefined ? null : stringOf(value.process_id),
    key: value.key === null || value.key === undefined ? null : stringOf(value.key),
    name: stringOf(value.name, "Untitled workflow"),
    description: value.description === null || value.description === undefined ? null : stringOf(value.description),
    status: stringOf(value.status, "draft"),
    updated_at: value.updated_at === null || value.updated_at === undefined ? null : stringOf(value.updated_at),
    current_version_id: value.current_version_id === null || value.current_version_id === undefined ? null : stringOf(value.current_version_id),
    current_version: numberOf(value.current_version ?? value.version),
    latest_hash: value.latest_hash === null || value.latest_hash === undefined ? null : stringOf(value.latest_hash),
  };
}

export function normalizeWorkflowVersion(raw: unknown, workflowId: string, index = 0): WorkflowVersion {
  const wrapper = recordOf(raw);
  const nestedVersion = wrapper.version && typeof wrapper.version === "object" ? wrapper.version : wrapper.item && typeof wrapper.item === "object" ? wrapper.item : raw;
  const value = recordOf(nestedVersion);
  const spec = normalizeSpec(value);
  const version = numberOf(value.version ?? value.version_number, index + 1) ?? index + 1;
  return {
    id: stringOf(value.id, `version-${version}`),
    workflow_id: stringOf(value.workflow_id, workflowId),
    version,
    status: stringOf(value.status, "draft"),
    spec,
    immutable_hash: value.immutable_hash === null || value.immutable_hash === undefined ? (value.hash === null || value.hash === undefined ? null : stringOf(value.hash)) : stringOf(value.immutable_hash),
    created_at: value.created_at === null || value.created_at === undefined ? null : stringOf(value.created_at),
    published_at: value.published_at === null || value.published_at === undefined ? null : stringOf(value.published_at),
    published_by: value.published_by === null || value.published_by === undefined ? null : stringOf(value.published_by),
    eval_run_id: value.eval_run_id === null || value.eval_run_id === undefined ? null : stringOf(value.eval_run_id),
    eval_gate: normalizeGate(value.eval_gate ?? value.evaluation_gate ?? value.eval),
    validation_errors: normalizeIssues(value.validation_errors ?? value.errors),
  };
}

export function normalizeWorkflowDetail(raw: unknown): WorkflowDetail {
  const root = recordOf(raw);
  const rawWorkflow = root.workflow ?? root.item ?? raw;
  const workflowRecord = recordOf(rawWorkflow);
  const workflow = normalizeWorkflowSummary(workflowRecord);
  const rawVersions = arrayOf(root.versions ?? workflowRecord.versions ?? workflowRecord.workflow_versions ?? (root.version ? [root.version] : []));
  const versions = rawVersions.map((version, index) => normalizeWorkflowVersion(version, workflow.id, index));
  const rawDraft = root.draft_version ?? workflowRecord.draft_version ?? root.version ?? versions.find((version) => version.status === "draft");
  const draftVersion = rawDraft ? normalizeWorkflowVersion(rawDraft, workflow.id, versions.length) : null;
  return { workflow, versions, draft_version: draftVersion };
}

export function normalizeWorkflowList(raw: unknown): WorkflowListResponse {
  const root = recordOf(raw);
  return { items: arrayOf(root.items ?? root.workflows).map(normalizeWorkflowSummary).filter((workflow) => Boolean(workflow.id)) };
}

export function mergeWorkflowVersion(base: WorkflowVersion, raw: unknown): WorkflowVersion {
  const normalized = normalizeWorkflowVersion(raw, base.workflow_id, base.version - 1);
  return {
    ...base,
    ...normalized,
    spec: normalized.spec.nodes.length > 0 || normalized.spec.edges.length > 0 ? normalized.spec : base.spec,
    eval_gate: normalized.eval_gate,
    validation_errors: normalized.validation_errors,
  };
}
