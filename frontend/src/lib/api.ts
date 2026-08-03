import type {
  AuthMode,
  ApiErrorBody,
  AuditEvent,
  ReviewTask,
  SessionContext,
  StatusResponse,
  Vendor,
  VendorDetail,
  VerificationResponse,
  WorkspaceActivationResponse,
  WorkspaceContext,
  WorkspaceListResponse,
} from "./types";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const AUTH_MODE: AuthMode = process.env.NEXT_PUBLIC_AUTH_MODE === "provider" ? "provider" : "development";
const DEV_AUTH_ENABLED = process.env.NODE_ENV !== "production" && AUTH_MODE === "development";
const DEVELOPMENT_SESSION_KEY = "fieldnote.development-session.v1";
let activeWorkspaceId: string | null = null;

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
    const value = JSON.parse(stored) as SessionContext;
    if (!value?.user?.id || !Array.isArray(value.workspaces) || value.auth_mode !== "development") return null;
    return value;
  } catch {
    window.sessionStorage.removeItem(DEVELOPMENT_SESSION_KEY);
    return null;
  }
}

function storeDevelopmentSession(session: SessionContext) {
  if (typeof window !== "undefined") window.sessionStorage.setItem(DEVELOPMENT_SESSION_KEY, JSON.stringify(session));
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
    const session = await request<SessionContext>("/api/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({ email: normalizedEmail }),
    });
    const normalizedSession = { ...session, auth_mode: "development" as const };
    storeDevelopmentSession(normalizedSession);
    return normalizedSession;
  } catch (error) {
    if (!(error instanceof ApiRequestError) || ![404, 405].includes(error.status)) throw error;
    // The F01 API predates T-01. A local session is allowed only after a real
    // health check and only in a non-production development build.
    await request<{ status: string; database: string }>("/api/health");
    const session = localDevelopmentSession(normalizedEmail);
    storeDevelopmentSession(session);
    return session;
  }
}

async function signOut() {
  try {
    await request<void>("/api/auth/logout", { method: "POST" });
  } catch (error) {
    if (!(error instanceof ApiRequestError) || ![404, 405].includes(error.status)) throw error;
  } finally {
    if (typeof window !== "undefined") window.sessionStorage.removeItem(DEVELOPMENT_SESSION_KEY);
    activeWorkspaceId = null;
  }
}

export const api = {
  health: () => request<{ status: string; database: string }>("/api/health"),
  getSession: () => request<SessionContext>("/api/auth/session"),
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
  updateReview: (reviewId: string, value: unknown, field: string) =>
    request<VerificationResponse>(`/api/reviews/${reviewId}`, {
      method: "PATCH",
      body: JSON.stringify({ value, field }),
    }),
};

function setActiveWorkspaceContext(workspaceId: string | null) {
  activeWorkspaceId = workspaceId;
}

export { API_BASE_URL, AUTH_MODE, DEV_AUTH_ENABLED, setActiveWorkspaceContext };
