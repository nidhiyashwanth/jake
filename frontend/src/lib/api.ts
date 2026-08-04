import type {
  AuthMode,
  ApiErrorBody,
  AuditEvent,
  ConnectorCallRecord,
  ConnectorKind,
  ConnectorRecord,
  ConnectorTestResponse,
  CredentialAccessLogRecord,
  CredentialRecord,
  DiscoveryDraft,
  DiscoveryDraftResponse,
  DiscoveryRecord,
  DiscoveryResponse,
  DiscoverySourceType,
  ReviewTask,
  SessionContext,
  StatusResponse,
  Vendor,
  VendorDetail,
  VerificationResponse,
  WorkspaceActivationResponse,
  WorkspaceContext,
  WorkspaceListResponse,
  WorkflowDetail,
  WorkflowListResponse,
  WorkflowPublishResponse,
  WorkflowResponse,
  WorkflowSpec,
  WorkflowValidationResponse,
  WorkflowVersion,
  WorkflowVersionResponse,
  RuntimeExecution,
  RuntimeExecutionListResponse,
  RuntimeExecutionResponse,
  McpServerRecord,
  ChaseRecord,
  ComplianceDocumentTypeRecord,
  ComplianceRuleRecord,
  ConfidenceAssessmentRecord,
  ConfidenceAuditRecord,
  ConfidenceSimulationResult,
  ConfidenceThresholdSetRecord,
  DriftSnapshotRecord,
  GoldenEvaluationResponse,
  GoldenSetRecord,
  ReasonCodeRecord,
  RequirementSetRecord,
} from "./types";
import { normalizeWorkflowDetail, normalizeWorkflowList, normalizeWorkflowVersion, serializeWorkflowSpec } from "./workflow-contract";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const AUTH_MODE: AuthMode = process.env.NEXT_PUBLIC_AUTH_MODE === "provider" ? "provider" : "development";
const DEV_AUTH_ENABLED = AUTH_MODE === "development" && process.env.NEXT_PUBLIC_ALLOW_DEVELOPMENT_AUTH === "true";
const DEVELOPMENT_SESSION_KEY = "fieldnote.development-session.v1";
let activeWorkspaceId: string | null = null;
let activeSessionToken: string | null = null;

interface DevelopmentLoginResponse {
  access_token?: string;
  token?: string;
  session?: { id?: string; expires_at?: string };
  user?: { id?: string; email?: string; name?: string };
  workspace?: { id?: string; name?: string };
  role?: WorkspaceContext["role"];
}

interface StoredSessionEnvelope {
  session: SessionContext;
  access_token: string;
}

export class ApiRequestError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(activeSessionToken ? { Authorization: `Bearer ${activeSessionToken}` } : {}),
        ...(activeWorkspaceId ? { "X-Workspace-ID": activeWorkspaceId } : {}),
        ...options?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiRequestError("The API could not be reached. Start the local Compose stack and try again.", "API_UNREACHABLE", 0);
  }

  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // Keep the stable local error below when the API did not return JSON.
    }
    throw new ApiRequestError(
      body.error?.message || `Request failed with status ${response.status}`,
      body.error?.code || "API_REQUEST_FAILED",
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestBlob(path: string, options?: RequestInit): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        ...(activeSessionToken ? { Authorization: `Bearer ${activeSessionToken}` } : {}),
        ...(activeWorkspaceId ? { "X-Workspace-ID": activeWorkspaceId } : {}),
        ...options?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiRequestError("The API could not be reached. Start the local Compose stack and try again.", "API_UNREACHABLE", 0);
  }

  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // Preserve the stable local error when the API did not return JSON.
    }
    throw new ApiRequestError(
      body.error?.message || `Request failed with status ${response.status}`,
      body.error?.code || "API_REQUEST_FAILED",
      response.status,
    );
  }
  return response.blob();
}

function localDevelopmentSession(email: string): SessionContext {
  const normalizedEmail = email.trim().toLowerCase();
  const localName = normalizedEmail.split("@")[0]?.replace(/[._-]+/g, " ").trim() || "Local operator";
  const displayName = localName.replace(/\b\w/g, (letter) => letter.toUpperCase());
  const initials = displayName
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const organization = {
    id: "local-development-organization",
    name: "Local Fieldnote Lab",
    kind: "internal" as const,
  };
  const workspace: WorkspaceContext = {
    id: "local-development-workspace",
    name: "Local operations",
    environment: "development",
    organization,
    role: "owner",
    membership_status: "active",
    mode: "delivery",
  };

  return {
    user: {
      id: `local-user:${normalizedEmail}`,
      email: normalizedEmail,
      display_name: displayName,
      initials: initials || "LO",
      status: "active",
    },
    organization,
    workspaces: [workspace],
    active_workspace_id: workspace.id,
    auth_mode: "development",
    expires_at: null,
  };
}

function readStoredDevelopmentSession(): SessionContext | null {
  if (typeof window === "undefined") return null;
  const stored = window.sessionStorage.getItem(DEVELOPMENT_SESSION_KEY);
  if (!stored) return null;
  try {
    const value = JSON.parse(stored) as StoredSessionEnvelope | SessionContext;
    if ("session" in value && value.session && value.access_token) {
      activeSessionToken = value.access_token;
      return value.session;
    }
    if ("user" in value && value.user?.id && Array.isArray(value.workspaces) && value.auth_mode === "development") {
      return value;
    }
    return null;
  } catch {
    window.sessionStorage.removeItem(DEVELOPMENT_SESSION_KEY);
    return null;
  }
}

function storeDevelopmentSession(session: SessionContext, token: string) {
  activeSessionToken = token;
  if (typeof window !== "undefined") {
    const envelope: StoredSessionEnvelope = { session, access_token: token };
    window.sessionStorage.setItem(DEVELOPMENT_SESSION_KEY, JSON.stringify(envelope));
  }
}

function fallbackSessionFromLogin(email: string, response: DevelopmentLoginResponse): SessionContext {
  const normalizedEmail = email.trim().toLowerCase();
  const organization = {
    id: "development-organization",
    name: "Local Fieldnote Lab",
    kind: "internal" as const,
  };
  const workspace: WorkspaceContext = {
    id: response.workspace?.id || "development-workspace",
    name: response.workspace?.name || "Local operations",
    environment: "development",
    organization,
    role: response.role || "owner",
    membership_status: "active",
    mode: "delivery",
  };
  const displayName = response.user?.name || normalizedEmail.split("@")[0] || "Local operator";
  return {
    user: {
      id: response.user?.id || `local-user:${normalizedEmail}`,
      email: response.user?.email || normalizedEmail,
      display_name: displayName,
      initials: displayName.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase(),
      status: "active",
    },
    organization,
    workspaces: [workspace],
    active_workspace_id: workspace.id,
    auth_mode: "development",
    expires_at: response.session?.expires_at || null,
  };
}

async function startDevelopmentSession(email: string): Promise<SessionContext> {
  if (!DEV_AUTH_ENABLED) {
    throw new ApiRequestError("Local development authentication is disabled for this build.", "DEV_AUTH_DISABLED", 403);
  }
  const normalizedEmail = email.trim().toLowerCase();
  if (!normalizedEmail || !normalizedEmail.includes("@")) {
    throw new ApiRequestError("Enter an email address to start the local session.", "INVALID_DEV_EMAIL", 400);
  }

  try {
    const localName = normalizedEmail.split("@")[0]?.replace(/[._-]+/g, " ").trim() || "Local operator";
    const loginResponse = await request<DevelopmentLoginResponse>("/api/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({
        email: normalizedEmail,
        name: localName,
        organization_name: "Local Fieldnote Lab",
        workspace_name: `Local operations - ${localName}`,
      }),
    });
    const token = loginResponse.access_token || loginResponse.token;
    if (!token) throw new ApiRequestError("The development auth boundary did not return a bearer session.", "AUTH_SESSION_MISSING", 502);
    activeSessionToken = token;
    let normalizedSession: SessionContext;
    try {
      normalizedSession = { ...(await request<SessionContext>("/api/auth/session")), auth_mode: "development" as const };
    } catch (sessionError) {
      if (!(sessionError instanceof ApiRequestError) || ![404, 405].includes(sessionError.status)) throw sessionError;
      normalizedSession = fallbackSessionFromLogin(normalizedEmail, loginResponse);
    }
    storeDevelopmentSession(normalizedSession, token);
    return normalizedSession;
  } catch (error) {
    if (!(error instanceof ApiRequestError) || ![404, 405].includes(error.status)) throw error;
    // The F01 API predates T-01. A local session is allowed only after a real
    // health check and only in a non-production development build.
    await request<{ status: string; database: string }>("/api/health");
    const session = localDevelopmentSession(normalizedEmail);
    storeDevelopmentSession(session, "local-development-fallback");
    return session;
  }
}

async function getSession() {
  const stored = readStoredDevelopmentSession();
  if (stored && activeSessionToken) {
    const liveSession = await request<SessionContext>("/api/auth/session");
    const normalizedSession = { ...liveSession, auth_mode: "development" as const };
    storeDevelopmentSession(normalizedSession, activeSessionToken);
    return normalizedSession;
  }
  return request<SessionContext>("/api/auth/session");
}

async function signOut() {
  try {
    await request<void>("/api/auth/logout", { method: "POST" });
  } catch (error) {
    if (!(error instanceof ApiRequestError) || ![404, 405].includes(error.status)) throw error;
  } finally {
    if (typeof window !== "undefined") window.sessionStorage.removeItem(DEVELOPMENT_SESSION_KEY);
    activeWorkspaceId = null;
    activeSessionToken = null;
  }
}

export const api = {
  health: () => request<{ status: string; database: string }>("/api/health"),
  getSession,
  getStoredDevelopmentSession: () => readStoredDevelopmentSession(),
  startDevelopmentSession,
  signOut,
  listWorkspaces: () => request<WorkspaceListResponse>("/api/workspaces"),
  activateWorkspace: (workspaceId: string) =>
    request<WorkspaceActivationResponse | WorkspaceContext>(`/api/workspaces/${workspaceId}/activate`, { method: "POST" }),
  updateWorkspaceMode: (workspaceId: string, mode: "delivery" | "handoff") =>
    request<WorkspaceActivationResponse | WorkspaceContext>(`/api/workspaces/${workspaceId}/mode`, {
      method: "PATCH",
      body: JSON.stringify({ mode }),
    }),
  listVendors: () => request<{ items: Vendor[] }>("/api/vendors"),
  listComplianceDocumentTypes: () => request<{ items: ComplianceDocumentTypeRecord[]; count: number }>("/api/compliance/document-types"),
  listComplianceRules: () => request<{ items: ComplianceRuleRecord[]; count: number }>("/api/compliance/rule-library"),
  listReasonCodes: () => request<{ items: ReasonCodeRecord[]; count: number; taxonomy_version: string }>("/api/compliance/reason-codes"),
  listRequirementSets: () => request<{ items: RequirementSetRecord[]; count: number }>("/api/compliance/requirement-sets"),
  createRequirementSet: (payload: { name: string; version: number; status?: "draft" | "active"; project_id?: string | null }) =>
    request<{ requirement_set: RequirementSetRecord }>("/api/compliance/requirement-sets", { method: "POST", body: JSON.stringify(payload) }),
  listConfidenceThresholdSets: () => request<{ items: ConfidenceThresholdSetRecord[] }>("/api/confidence/threshold-sets"),
  createConfidenceThresholdSet: (payload: {
    workflow_version_id?: string | null;
    version?: number;
    status?: "draft" | "active";
    auto_threshold: number;
    review_threshold: number;
    halt_threshold: number;
    value_at_risk_limit: number;
    sample_rate: number;
    cost_auto_usd?: number;
    cost_review_usd?: number;
    cost_halt_usd?: number;
    reason?: string | null;
  }) => request<{ threshold_set: ConfidenceThresholdSetRecord }>("/api/confidence/threshold-sets", { method: "POST", body: JSON.stringify(payload) }),
  assessConfidence: (payload: {
    assessment_key: string;
    workflow_version_id?: string | null;
    extraction_consistency: number;
    validation_severity: number;
    matching_score: number;
    novelty_score: number;
    sender_history_score: number;
    value_at_risk: number;
    required_halt?: boolean;
    model_confidence?: number;
    evidence?: Record<string, unknown>;
  }) => request<{ assessment: ConfidenceAssessmentRecord; audit: ConfidenceAuditRecord | null; idempotent_replay: boolean }>("/api/confidence/assess", { method: "POST", body: JSON.stringify(payload) }),
  simulateConfidence: (payload: {
    cases: Array<{
      case_key: string;
      extraction_consistency: number;
      validation_severity: number;
      matching_score: number;
      novelty_score: number;
      sender_history_score: number;
      value_at_risk: number;
      required_halt?: boolean;
      known_correct?: boolean | null;
    }>;
    thresholds: Array<{
      label: string;
      auto_threshold: number;
      review_threshold: number;
      halt_threshold: number;
      value_at_risk_limit: number;
    }>;
  }) => request<{ formula_version: string; case_count: number; results: ConfidenceSimulationResult[] }>("/api/confidence/simulate", { method: "POST", body: JSON.stringify(payload) }),
  listConfidenceAudits: () => request<{ items: ConfidenceAuditRecord[] }>("/api/confidence/audits"),
  completeConfidenceAudit: (auditId: string, actualCorrect: boolean, outcomeSummary?: string) =>
    request<{ audit: ConfidenceAuditRecord; thresholds: ConfidenceThresholdSetRecord[] }>(`/api/confidence/audits/${auditId}/outcome`, { method: "POST", body: JSON.stringify({ actual_correct: actualCorrect, outcome_summary: outcomeSummary }) }),
  listGoldenSets: () => request<{ items: GoldenSetRecord[] }>("/api/evaluations/golden-sets"),
  createGoldenSet: (payload: {
    workflow_version_id: string;
    name: string;
    status?: "draft" | "active";
    source_policy?: Record<string, unknown>;
    gate?: Record<string, number>;
    cases: Array<{
      case_key: string;
      source_type: "corrected" | "manual" | "canary" | "synthetic";
      rights_status: "contractual_rights" | "manual_review" | "synthetic";
      rights_basis: string;
      sender: string;
      document_type: string;
      input: Record<string, unknown>;
      expected: Record<string, unknown>;
      prediction: Record<string, unknown>;
      canary?: boolean;
    }>;
  }) => request<{ golden_set: GoldenSetRecord }>("/api/evaluations/golden-sets", { method: "POST", body: JSON.stringify(payload) }),
  runGoldenEvaluation: (versionId: string, goldenSetId: string, baselineEvaluationId?: string | null) =>
    request<GoldenEvaluationResponse>(`/api/workflow-versions/${versionId}/evaluations/golden`, { method: "POST", body: JSON.stringify({ golden_set_id: goldenSetId, baseline_evaluation_id: baselineEvaluationId || undefined }) }),
  listEvaluationDrift: () => request<{ items: DriftSnapshotRecord[] }>("/api/evaluations/drift"),
  recordEvaluationDrift: (payload: {
    workflow_version_id: string;
    window_key: string;
    baseline_correction_rate: number;
    max_delta: number;
    min_samples: number;
    observations: Array<{ sender: string; document_type: string; corrected: boolean }>;
  }) => request<{ snapshot: DriftSnapshotRecord; alerted: boolean }>("/api/evaluations/drift", { method: "POST", body: JSON.stringify(payload) }),
  getVendor: (vendorId: string) => request<VendorDetail>(`/api/vendors/${vendorId}`),
  createVendor: (legalName: string) =>
    request<Vendor>("/api/vendors", { method: "POST", body: JSON.stringify({ legal_name: legalName }) }),
  uploadDocument: (vendorId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("doc_type", "COI");
    return request<import("./types").ComplianceDocument>(`/api/vendors/${vendorId}/documents`, {
      method: "POST",
      body: formData,
    });
  },
  verifyDocument: (documentId: string) =>
    request<VerificationResponse>(`/api/documents/${documentId}/verify`, { method: "POST" }),
  getStatus: (vendorId: string) => request<StatusResponse>(`/api/vendors/${vendorId}/status`),
  getLedger: (vendorId: string) => request<{ items: AuditEvent[] }>(`/api/vendors/${vendorId}/ledger`),
  getReviews: () => request<{ items: ReviewTask[] }>("/api/reviews"),
  getReviewQueue: (status = "open", limit = 50) => request<import("./types").ReviewQueueResponse>(`/api/reviews/queue?status=${encodeURIComponent(status)}&limit=${limit}`),
  getReviewDetail: (reviewId: string) => request<{ review: import("./types").ReviewDetail }>(`/api/reviews/${reviewId}`),
  assignReview: (reviewId: string, assigneeUserId?: string | null) =>
    request<{ review: ReviewTask }>(`/api/reviews/${reviewId}/assign`, { method: "POST", body: JSON.stringify({ assignee_user_id: assigneeUserId ?? null }) }),
  escalateReview: (reviewId: string, reason: string, level?: number) =>
    request<{ review: ReviewTask }>(`/api/reviews/${reviewId}/escalate`, { method: "POST", body: JSON.stringify({ reason, level }) }),
  bulkReviewAction: (payload: { review_ids: string[]; action: "assign" | "unassign" | "escalate"; assignee_user_id?: string | null; reason?: string }) =>
    request<{ action: string; updated: number; review_ids: string[] }>("/api/reviews/bulk", { method: "POST", body: JSON.stringify(payload) }),
  listConnectors: () => request<{ items: ConnectorRecord[]; count: number }>("/api/connectors"),
  createConnector: (payload: { name: string; kind: ConnectorKind; config?: Record<string, unknown>; egress_hosts?: string[] }) =>
    request<{ connector: ConnectorRecord }>("/api/connectors", { method: "POST", body: JSON.stringify(payload) }),
  testConnector: (connectorId: string, target?: string) =>
    request<ConnectorTestResponse>(`/api/connectors/${connectorId}/test`, { method: "POST", body: JSON.stringify({ target }) }),
  verifyWebhook: (connectorId: string, payload: { body: string; timestamp: number; signature: string }) =>
    request<{ verified: boolean; failure_code?: string | null; body_sha256: string }>(`/api/connectors/${connectorId}/webhook/verify`, { method: "POST", body: JSON.stringify(payload) }),
  createCredential: (connectorId: string, payload: { label: string; secret: string; secret_type?: string }) =>
    request<{ credential: CredentialRecord }>(`/api/connectors/${connectorId}/credentials`, { method: "POST", body: JSON.stringify(payload) }),
  rotateCredential: (connectorId: string, credentialId: string, secret: string) =>
    request<{ credential: CredentialRecord }>(`/api/connectors/${connectorId}/credentials/${credentialId}/rotate`, { method: "POST", body: JSON.stringify({ secret }) }),
  listCredentialAccessLog: () => request<{ items: CredentialAccessLogRecord[]; count: number }>("/api/credentials/access-log"),
  listMcpServers: () => request<{ items: McpServerRecord[]; count: number }>("/api/mcp/servers"),
  createMcpServer: (payload: { name: string; url: string; auth_mode?: string; server_version: string; metadata: Record<string, unknown>; allowed_tools?: string[]; workflow_version_ids?: string[]; egress_hosts?: string[] }) =>
    request<{ server: McpServerRecord }>("/api/mcp/servers", { method: "POST", body: JSON.stringify(payload) }),
  callMcpTool: (serverId: string, payload: { tool_name: string; arguments?: Record<string, unknown>; workflow_version_id?: string; value_at_risk?: number; approved?: boolean; approval_note?: string; idempotency_key?: string }) =>
    request<{ call: ConnectorCallRecord; idempotent: boolean; approved?: boolean; approval_required?: boolean }>(`/api/mcp/servers/${serverId}/tools/call`, { method: "POST", body: JSON.stringify(payload) }),
  listMcpCalls: () => request<{ items: ConnectorCallRecord[]; count: number }>("/api/mcp/calls"),
  listChases: (vendorId: string) => request<{ items: ChaseRecord[]; count: number }>(`/api/vendors/${vendorId}/chases`),
  createChase: (vendorId: string, payload: { requirement_id?: string | null; customer_sender_connector_id: string; expected_doc_type: string; max_attempts?: number; max_messages_per_week?: number; touch_schedule_days?: number[] }) =>
    request<{ chase: ChaseRecord }>(`/api/vendors/${vendorId}/chases`, { method: "POST", body: JSON.stringify(payload) }),
  sendChaseTouch: (chaseId: string, body: string, approved: boolean) =>
    request<{ chase: ChaseRecord }>(`/api/chases/${chaseId}/touch`, { method: "POST", body: JSON.stringify({ body, approved }) }),
  receiveChaseReply: (chaseId: string, body: string, attachmentDocumentId?: string | null) =>
    request<{ chase: ChaseRecord }>(`/api/chases/${chaseId}/reply`, { method: "POST", body: JSON.stringify({ body, attachment_document_id: attachmentDocumentId || null }) }),
  updateReview: (reviewId: string, value: unknown, field: string, reasonCode: string, note?: string) =>
    request<VerificationResponse>(`/api/reviews/${reviewId}`, {
      method: "PATCH",
      body: JSON.stringify({ value, field, reason_code: reasonCode, note }),
    }),
  getDiscovery: () => request<DiscoveryResponse>("/api/discoveries"),
  saveDiscovery: (payload: Record<string, unknown>, processId?: string | null) =>
    request<DiscoveryResponse>(processId ? `/api/discoveries/${processId}` : "/api/discoveries", {
      method: processId ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    }),
  ingestDiscoverySource: (processId: string, payload: { source_type: DiscoverySourceType; source_name?: string; content: string }) =>
    (() => {
      const formData = new FormData();
      formData.append("source_type", payload.source_type === "screen_recording" ? "screen_recording_narration" : payload.source_type);
      if (payload.source_name) formData.append("source_name", payload.source_name);
      formData.append("content", payload.content);
      return request<{ ingestion_id?: string; draft?: DiscoveryDraft }>(`/api/discoveries/${processId}/ingestions`, {
        method: "POST",
        body: formData,
      });
    })(),
  getDiscoveryDraft: (processId: string) => request<DiscoveryDraftResponse>(`/api/discoveries/${processId}/draft`),
  updateDiscoveryDraft: (processId: string, payload: Record<string, unknown>) =>
    request<DiscoveryDraftResponse>(`/api/discoveries/${processId}/draft`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  answerDiscoveryQuestion: (processId: string, questionId: string, answer: string) =>
    request<DiscoveryResponse>(`/api/discoveries/${processId}/questions/${questionId}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  addDiscoveryException: (processId: string, value: string) =>
    request<DiscoveryResponse>(`/api/discoveries/${processId}/exceptions`, {
      method: "POST",
      body: JSON.stringify({ value }),
    }),
  listDiscoveryBaselines: (processId: string) => request<DiscoveryResponse>(`/api/discoveries/${processId}/baselines`),
  createDiscoveryBaseline: (processId: string, payload: Record<string, unknown>) =>
    request<DiscoveryResponse>(`/api/discoveries/${processId}/baselines`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  signDiscoveryBaseline: (processId: string, baselineId: string, payload: Record<string, unknown>) =>
    request<DiscoveryResponse>(`/api/discoveries/${processId}/baselines/${baselineId}/sign`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  exportDiscoveryBaseline: (processId: string, baselineId: string) =>
    requestBlob(`/api/discoveries/${processId}/baselines/${baselineId}/export`),
  computeDiscoveryScore: (processId: string, baselineId: string, payload: Record<string, unknown>) =>
    request<DiscoveryResponse>(`/api/discoveries/${processId}/baselines/${baselineId}/scores`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getOpportunityScore: (scoreId: string) => request<DiscoveryResponse>(`/api/opportunity-scores/${scoreId}`),
  listWorkflows: async (): Promise<WorkflowListResponse> => normalizeWorkflowList(await request<unknown>("/api/workflows")),
  getWorkflow: async (workflowId: string): Promise<WorkflowDetail> => normalizeWorkflowDetail(await request<WorkflowResponse>(`/api/workflows/${workflowId}`)),
  createWorkflow: async (payload: { key: string; name: string; description?: string | null; process_id?: string | null }): Promise<WorkflowDetail> =>
    normalizeWorkflowDetail(await request<WorkflowResponse>("/api/workflows", { method: "POST", body: JSON.stringify(payload) })),
  updateWorkflow: async (workflowId: string, payload: { key?: string; name?: string; description?: string | null; process_id?: string | null }): Promise<WorkflowDetail> =>
    normalizeWorkflowDetail(await request<WorkflowResponse>(`/api/workflows/${workflowId}`, { method: "PATCH", body: JSON.stringify(payload) })),
  createWorkflowVersion: async (workflowId: string, spec: WorkflowSpec, sourceVersionId?: string | null): Promise<WorkflowVersion> =>
    normalizeWorkflowVersion(
      await request<WorkflowVersionResponse>(`/api/workflows/${workflowId}/versions`, {
        method: "POST",
        body: JSON.stringify({ ...serializeWorkflowSpec(spec), source_version_id: sourceVersionId || undefined }),
      }),
      workflowId,
    ),
  updateWorkflowVersion: async (workflowId: string, versionId: string, spec: WorkflowSpec): Promise<WorkflowVersion> =>
    normalizeWorkflowVersion(
      await request<WorkflowVersionResponse>(`/api/workflow-versions/${versionId}`, {
        method: "PATCH",
        body: JSON.stringify(serializeWorkflowSpec(spec)),
      }),
      workflowId,
    ),
  validateWorkflowVersion: (workflowId: string, versionId: string) =>
    request<WorkflowValidationResponse>(`/api/workflow-versions/${versionId}/validate`, { method: "POST" }),
  evaluateWorkflowVersion: (workflowId: string, versionId: string) =>
    request<WorkflowVersionResponse>(`/api/workflow-versions/${versionId}/evaluation-runs`, { method: "POST", body: JSON.stringify({ suite_key: "w01.synthetic.baseline" }) }),
  publishWorkflowVersion: (workflowId: string, versionId: string) =>
    request<WorkflowPublishResponse>(`/api/workflow-versions/${versionId}/publish`, { method: "POST" }),
  listExecutions: (status?: string) =>
    request<RuntimeExecutionListResponse>(`/api/runtime/executions${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  getExecution: async (executionId: string): Promise<RuntimeExecution> =>
    (await request<RuntimeExecutionResponse>(`/api/runtime/executions/${executionId}`)).execution,
  createExecution: async (payload: { workflow_version_id: string; input: Record<string, unknown>; idempotency_key: string; correlation_id?: string; max_retries?: number }) =>
    request<RuntimeExecutionResponse>("/api/runtime/executions", { method: "POST", body: JSON.stringify(payload) }),
  advanceExecution: async (executionId: string, maxSteps = 1) =>
    request<RuntimeExecutionResponse>(`/api/runtime/executions/${executionId}/advance`, { method: "POST", body: JSON.stringify({ max_steps: maxSteps }) }),
  retryExecution: async (executionId: string, reason: string, stepId?: string) =>
    request<RuntimeExecutionResponse>(`/api/runtime/executions/${executionId}/retry`, { method: "POST", body: JSON.stringify({ reason, step_id: stepId }) }),
  resumeExecution: async (executionId: string, decision: string, output: Record<string, unknown> = {}, note?: string) =>
    request<RuntimeExecutionResponse>(`/api/runtime/executions/${executionId}/resume`, { method: "POST", body: JSON.stringify({ decision, output, note }) }),
  replayExecution: async (executionId: string, idempotencyKey?: string) =>
    request<RuntimeExecutionResponse>(`/api/runtime/executions/${executionId}/replay`, { method: "POST", body: JSON.stringify({ idempotency_key: idempotencyKey }) }),
  recoverRuntimeWorker: () => request<{ recovered: number; lease_seconds: number }>("/api/runtime/workers/recover", { method: "POST" }),
  dispatchRuntimeOutbox: (limit = 20) => request<{ dispatched: number; event_ids: string[] }>("/api/runtime/outbox/dispatch", { method: "POST", body: JSON.stringify({ limit }) }),
};

function setActiveWorkspaceContext(workspaceId: string | null) {
  activeWorkspaceId = workspaceId;
}

export { API_BASE_URL, AUTH_MODE, DEV_AUTH_ENABLED, setActiveWorkspaceContext };
