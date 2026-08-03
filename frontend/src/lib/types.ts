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
  created_at: string;
  resolved_at: string | null;
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
