export type ComplianceStatus = "compliant" | "needs_review";
export type CheckResult = "pass" | "fail" | "uncertain";

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
