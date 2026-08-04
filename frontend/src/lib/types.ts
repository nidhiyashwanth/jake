export type ComplianceStatus = "compliant" | "needs_review";
export type CheckResult = "pass" | "fail" | "uncertain";

export type UserRole = "owner" | "admin" | "builder" | "operator" | "viewer" | "auditor";
export type MembershipStatus = "active" | "disabled" | "invited";
export type WorkspaceMode = "delivery" | "handoff";
export type AuthMode = "provider" | "development";

export interface UserIdentity {
  id: string;
  email: string;
  display_name: string;
  initials: string;
  status: MembershipStatus;
}

export interface Organization {
  id: string;
  name: string;
  kind?: "internal" | "customer" | "partner" | string;
}

export interface WorkspaceContext {
  id: string;
  name: string;
  slug?: string;
  environment: "production" | "staging" | "sandbox" | "development" | string;
  organization: Organization;
  role: UserRole;
  membership_status: MembershipStatus;
  mode: WorkspaceMode;
}

export interface SessionContext {
  user: UserIdentity;
  organization: Organization;
  workspaces: WorkspaceContext[];
  active_workspace_id: string;
  auth_mode: AuthMode;
  expires_at?: string | null;
}

export interface WorkspaceListResponse {
  items: WorkspaceContext[];
}

export interface WorkspaceActivationResponse {
  workspace?: WorkspaceContext;
  active_workspace_id?: string;
}

export interface SessionProblem {
  code: "SESSION_EXPIRED" | "MEMBER_DISABLED" | "ACCESS_DENIED" | "AUTH_UNAVAILABLE";
  message: string;
}

export interface StatusSnapshot {
  id: string;
  vendor_id: string;
  document_id: string;
  as_of: string;
  status: ComplianceStatus;
  failing_requirements: string[];
  computed_by_version: string;
  evidence: StatusEvidence;
}

export interface Check {
  id: string;
  requirement_key: string;
  label: string;
  result: CheckResult;
  reason_code: string;
  message: string;
  observed_value: unknown;
  required_value: unknown;
  created_at: string;
}

export interface StatusEvidence {
  document_filename?: string;
  normalized_fields?: ExtractedFields;
  checks?: Check[];
  review_task_ids?: string[];
}

export interface ExtractedFields {
  named_insured: string | null;
  certificate_holder: string | null;
  gl_occurrence_limit: number | null;
  policy_expiry: string | null;
  additional_insured: boolean | null;
  waiver_of_subrogation: boolean | null;
  [key: string]: unknown;
}

export interface ComplianceDocument {
  id: string;
  vendor_id: string;
  doc_type: string;
  filename: string;
  media_type: string;
  extracted_fields: ExtractedFields;
  created_at: string;
}

export interface Vendor {
  id: string;
  legal_name: string;
  created_at: string;
  latest_status: StatusSnapshot | null;
}

export interface VendorDetail extends Vendor {
  documents: ComplianceDocument[];
  recent_events: AuditEvent[];
}

export interface ReviewTask {
  id: string;
  vendor_id: string;
  vendor_legal_name?: string;
  document_id: string;
  check_id: string;
  requirement_key: string;
  correction_field: string;
  reason_code: string;
  status: "open" | "resolved" | "superseded";
  priority_score?: number;
  priority_band?: "urgent" | "high" | "normal" | string;
  priority_factors?: Record<string, unknown>;
  assigned_to_user_id?: string | null;
  assigned_to_name?: string | null;
  assigned_at?: string | null;
  sla_minutes?: number;
  due_at?: string | null;
  sla_state?: "overdue" | "within_sla" | string;
  escalation_level?: number;
  escalated_at?: string | null;
  escalation_reason?: string | null;
  correction_reason_code?: string | null;
  correction_note?: string | null;
  before_value?: unknown;
  after_value?: unknown;
  provenance?: ReviewProvenance;
  document_filename?: string | null;
  last_touched_at?: string | null;
  updated_at?: string;
  created_at: string;
  resolved_at: string | null;
}

export interface ReviewProvenance {
  document_id: string;
  filename: string;
  page: number;
  line?: number;
  char_start?: number;
  char_end?: number;
  bbox?: { x: number; y: number; width: number; height: number } | null;
  matched_text?: string;
  excerpt?: string;
  locator_kind: string;
  source_quality: string;
}

export interface ReviewTaskEvent {
  id: string;
  event_type: string;
  from_status?: string | null;
  to_status?: string | null;
  actor_id?: string | null;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface ReviewDetail extends ReviewTask {
  events: ReviewTaskEvent[];
}

export interface ReviewQueueResponse {
  items: ReviewTask[];
  count: number;
  limit: number;
  priority_formula: string;
  bulk_cap: number;
}

export type ConnectorKind = "email" | "object_storage" | "notify" | "rest" | "webhook" | "sftp" | "database" | "csv_excel" | "rpa";

export interface ConnectorRecord {
  id: string;
  name: string;
  kind: ConnectorKind;
  status: string;
  config: Record<string, unknown>;
  egress_hosts: string[];
  credential_count: number;
  failure_code?: string | null;
  failure_message?: string | null;
  last_checked_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CredentialRecord {
  id: string;
  connector_id: string;
  label: string;
  secret_type: string;
  ciphertext_present: boolean;
  plaintext_exposed: boolean;
  dek_id: string;
  key_version: string;
  expires_at?: string | null;
  rotated_at: string;
  active: boolean;
  created_at: string;
}

export interface ConnectorTestResponse {
  healthy: boolean;
  connector: ConnectorRecord;
  result?: Record<string, unknown>;
  failure?: { code: string; message: string };
}

export interface McpServerRecord {
  id: string;
  name: string;
  url: string;
  auth_mode: string;
  server_version: string;
  metadata_hash: string;
  allowed_tools: string[];
  workflow_version_ids: string[];
  egress_hosts: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ConnectorCallRecord {
  id: string;
  connector_id?: string | null;
  mcp_server_id?: string | null;
  workflow_version_id?: string | null;
  call_type: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  result_untrusted: boolean;
  status: string;
  failure_code?: string | null;
  approval_required: boolean;
  egress_host?: string | null;
  idempotency_key?: string | null;
  correlation_id: string;
  latency_ms?: number | null;
  created_at: string;
}

export interface CredentialAccessLogRecord {
  id: string;
  credential_id: string;
  actor_id?: string | null;
  action: string;
  purpose: string;
  outcome: string;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  actor_type: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface StatusResponse {
  current: StatusSnapshot;
  history: StatusSnapshot[];
}

export interface VerificationResponse {
  run_id: string;
  status: StatusSnapshot;
  checks: Check[];
  review_tasks: ReviewTask[];
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
  };
}

export type DiscoverySourceType = "sop" | "transcript" | "screen_recording";

export interface DiscoveryStep {
  id?: string;
  title: string;
  description: string;
  system: string;
  minutes_p50: number | null;
  minutes_p90: number | null;
  is_decision: boolean;
}

export interface DiscoveryMetrics {
  volume_per_month: number | null;
  minutes_p50: number | null;
  minutes_p90: number | null;
  fully_loaded_cost_per_hour: number | null;
  error_rate_pct: number | null;
  cost_per_error: number | null;
  rework_rate_pct: number | null;
  cycle_time_hours: number | null;
  headcount_touching: number | null;
  peak_backlog: number | null;
  chase_volume_per_month: number | null;
  lapse_incidents_per_month: number | null;
  audit_prep_hours_per_month: number | null;
}

export interface DiscoveryDraft {
  source_type?: DiscoverySourceType;
  source_name?: string | null;
  generated_at?: string | null;
  steps: DiscoveryStep[];
  exceptions: string[];
  baseline_questions: string[];
}

export interface SignedBaseline {
  id: string;
  process_id: string;
  version: number;
  status: "draft" | "signed" | "superseded";
  signed_by?: {
    id?: string;
    name?: string;
    email?: string;
  } | null;
  signed_at?: string | null;
  frozen_at?: string | null;
  hash?: string | null;
  supersedes_baseline_id?: string | null;
  superseded_by_baseline_id?: string | null;
  metrics: DiscoveryMetrics;
}

export interface OpportunityScore {
  id?: string;
  baseline_id?: string | null;
  current_annual_cost: number;
  automatable_pct: number;
  projected_savings: number;
  confidence: number;
  effort_weeks: number;
  risk_multiplier: number;
  priority_score: number;
  model_cost: number;
  infra_cost: number;
  review_rate_pct: number;
  review_minutes: number;
  inputs: Record<string, number | string | null>;
  formula_version: string;
  computed_at?: string | null;
  provenance?: string | null;
}

export interface DiscoveryRecord {
  process_id: string;
  workspace_id: string;
  name: string;
  department?: string | null;
  owner_user_id?: string | null;
  system_of_record?: string | null;
  trigger: string;
  inputs: string;
  decisions: string;
  exceptions: string;
  approvals: string;
  outputs: string;
  failure_modes: string;
  steps: DiscoveryStep[];
  metrics: DiscoveryMetrics;
  draft?: DiscoveryDraft | null;
  baselines: SignedBaseline[];
  current_baseline?: SignedBaseline | null;
  score?: OpportunityScore | null;
  updated_at?: string | null;
}

export interface DiscoveryResponse {
  items?: DiscoveryRecord[];
  item?: DiscoveryRecord;
  process?: DiscoveryRecord;
  record?: DiscoveryRecord;
  baseline?: SignedBaseline;
  score?: OpportunityScore;
}

export interface DiscoveryDraftResponse {
  process_id?: string | null;
  draft: DiscoveryDraft;
}

export const WORKFLOW_NODE_TYPES = [
  "trigger",
  "fetch",
  "parse",
  "classify",
  "extract",
  "rule",
  "score",
  "llm",
  "tool",
  "approve",
  "notify",
  "halt",
] as const;

export type WorkflowNodeType = (typeof WORKFLOW_NODE_TYPES)[number];
export type WorkflowStatus = "draft" | "published" | "archived" | string;
export type WorkflowVersionStatus = "draft" | "published" | "superseded" | "archived" | string;
export type EvaluationGateStatus = "not_run" | "pending" | "passed" | "failed" | string;

export interface WorkflowThreshold {
  key: string;
  value: number | null;
  label?: string;
  unit?: string;
}

export interface WorkflowPromptReference {
  key: string;
  version: number | null;
}

export interface WorkflowModelConfigReference {
  key: string;
  provider: string;
  version: number | null;
}

export interface WorkflowNode {
  id: string;
  node_key: string;
  type: WorkflowNodeType;
  label: string;
  config: Record<string, unknown>;
}

export interface WorkflowEdge {
  id: string;
  from_node: string;
  to_node: string;
  condition: string | null;
}

export interface WorkflowSpec {
  schema_version: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  thresholds: WorkflowThreshold[];
  prompts: WorkflowPromptReference[];
  model_configs: WorkflowModelConfigReference[];
}

export interface WorkflowValidationIssue {
  code: string;
  path: string;
  message: string;
  severity: "error" | "warning";
  node_key?: string | null;
}

export interface EvaluationGate {
  status: EvaluationGateStatus;
  run_id?: string | null;
  evaluated_at?: string | null;
  failure_reasons: string[];
  metric_deltas?: Record<string, number | string | null>;
}

export interface WorkflowSummary {
  id: string;
  workspace_id: string;
  process_id?: string | null;
  key?: string | null;
  name: string;
  description?: string | null;
  status: WorkflowStatus;
  updated_at?: string | null;
  current_version_id?: string | null;
  current_version?: number | null;
  latest_hash?: string | null;
}

export interface WorkflowVersion {
  id: string;
  workflow_id: string;
  version: number;
  status: WorkflowVersionStatus;
  spec: WorkflowSpec;
  immutable_hash: string | null;
  created_at?: string | null;
  published_at?: string | null;
  published_by?: string | null;
  eval_run_id?: string | null;
  eval_gate: EvaluationGate;
  validation_errors: WorkflowValidationIssue[];
}

export interface WorkflowDetail {
  workflow: WorkflowSummary;
  versions: WorkflowVersion[];
  draft_version?: WorkflowVersion | null;
}

export interface WorkflowListResponse {
  items: WorkflowSummary[];
}

export interface WorkflowResponse {
  item?: WorkflowDetail;
  workflow?: WorkflowDetail;
}

export interface WorkflowVersionResponse {
  item?: WorkflowVersion;
  version?: WorkflowVersion;
}

export interface WorkflowValidationResponse {
  version?: WorkflowVersion;
  validation_errors?: WorkflowValidationIssue[];
  errors?: WorkflowValidationIssue[];
}

export interface WorkflowPublishResponse {
  version?: WorkflowVersion;
  published?: boolean;
  evaluation_gate?: EvaluationGate;
  eval_gate?: EvaluationGate;
  failure_reasons?: string[];
}

export type ExecutionStatus = "queued" | "running" | "waiting_human" | "completed" | "failed" | "dead_letter" | "halted" | "replayed" | string;
export type ExecutionStepStatus = "pending" | "claimed" | "running" | "waiting_human" | "completed" | "failed" | "dead_letter" | "skipped" | string;

export interface RuntimeExecutionStep {
  id: string;
  node_key: string;
  node_type: string;
  sequence: number;
  status: ExecutionStepStatus;
  attempt: number;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  error?: Record<string, unknown> | null;
  provider?: string | null;
  model_ref?: string | null;
  prompt_ref?: string | null;
  prompt_version?: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms?: number | null;
  idempotency_key?: string | null;
  correlation_id: string;
  wait_reason?: string | null;
  compensation?: Record<string, unknown> | null;
  claimed_by?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface RuntimeOutboxEvent {
  id: string;
  event_type: string;
  dedupe_key: string;
  status: string;
  attempts: number;
  correlation_id: string;
  created_at: string;
  delivered_at?: string | null;
}

export interface RuntimeExecutionEvent {
  id: string;
  type: string;
  step_id?: string | null;
  correlation_id: string;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface RuntimeExecution {
  id: string;
  workspace_id: string;
  workflow_id: string;
  workflow_version_id: string;
  workflow_version_hash: string;
  idempotency_key: string;
  correlation_id: string;
  status: ExecutionStatus;
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  error?: Record<string, unknown> | null;
  retry_count: number;
  max_retries: number;
  dry_run: boolean;
  replay_of_id?: string | null;
  created_by: string;
  queued_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  next_attempt_at?: string | null;
  steps: RuntimeExecutionStep[];
  outbox: RuntimeOutboxEvent[];
  external_write_count: number;
  events: RuntimeExecutionEvent[];
}

export interface RuntimeExecutionResponse {
  execution: RuntimeExecution;
  created?: boolean;
  idempotent?: boolean;
  side_effects?: boolean;
  replay_of_id?: string;
  advanced_steps?: string[];
  retried_step_id?: string;
  resumed_step_id?: string;
}

export interface RuntimeExecutionListResponse {
  items: Array<{
    id: string;
    workflow_id: string;
    workflow_version_id: string;
    workflow_version_hash: string;
    status: ExecutionStatus;
    correlation_id: string;
    idempotency_key: string;
    dry_run: boolean;
    created_at: string;
    completed_at?: string | null;
  }>;
}
