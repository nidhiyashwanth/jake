"use client";

import { ChangeEvent, FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE_URL, api, ApiRequestError, AUTH_MODE, DEV_AUTH_ENABLED, setActiveWorkspaceContext } from "@/lib/api";
import AppHandoffView from "@/components/HandoffView";
import DiscoveryView from "@/components/DiscoveryView";
import WorkflowStudio from "@/components/WorkflowStudio";
import ExecutionRuntime from "@/components/ExecutionRuntime";
import ConnectorsView from "@/components/ConnectorsView";
import ComplianceView from "@/components/ComplianceView";
import ConfidenceView from "@/components/ConfidenceView";
import ReviewQueuePanel from "@/components/ReviewQueuePanel";
import { AppSidebar, AuthorizationDenied, MemberDisabled, SURFACE_ITEMS, WorkspaceHeader } from "@/components/WorkspaceChrome";
import type { SurfaceKey } from "@/components/WorkspaceChrome";
import { can, isDisabledMember, persistActiveWorkspaceId, readActiveWorkspaceId, roleLabel } from "@/lib/tenancy";
import type {
  AuditEvent,
  Check,
  ComplianceDocument,
  ExtractedFields,
  ReviewTask,
  SessionContext,
  StatusResponse,
  StatusSnapshot,
  Vendor,
  VendorDetail,
  WorkspaceContext,
  WorkspaceMode,
} from "@/lib/types";

const fieldDefinitions: Array<{ key: keyof ExtractedFields; label: string; hint: string }> = [
  { key: "named_insured", label: "Named insured", hint: "Must match the vendor legal name" },
  { key: "certificate_holder", label: "Certificate holder", hint: "Seeded contracting entity" },
  { key: "gl_occurrence_limit", label: "GL occurrence limit", hint: "Minimum $2,000,000" },
  { key: "policy_expiry", label: "Policy expiry", hint: "Must be valid today" },
  { key: "additional_insured", label: "Additional insured", hint: "Endorsement present" },
  { key: "waiver_of_subrogation", label: "Waiver of subrogation", hint: "Endorsement present" },
];

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not found";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return `$${value.toLocaleString("en-US")}`;
  return String(value);
}

function editableValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function friendlyEventName(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Try that action again.";
}

function statusClass(status: StatusSnapshot | null): string {
  if (!status) return "status-pill status-pill--quiet";
  return status.status === "compliant" ? "status-pill status-pill--good" : "status-pill status-pill--warn";
}

function statusText(status: StatusSnapshot | null): string {
  if (!status) return "Awaiting verification";
  return status.status === "compliant" ? "Compliant" : "Needs review";
}

type AuthState = "loading" | "signed_out" | "expired" | "disabled" | "denied" | "failed" | "ready";

interface ReviewDeskProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  activeSurface: SurfaceKey;
  contextError: string | null;
  contextBusy: boolean;
  modeBusy: boolean;
  onNavigate: (surface: SurfaceKey) => void;
  onWorkspaceSelect: (workspace: WorkspaceContext) => void;
  onModeChange: (mode: WorkspaceMode) => void;
  onSignOut: () => void;
  onSessionExpired: (error: ApiRequestError) => void;
}

function LoadingBoundary() {
  return <main className="boundary-screen"><div className="boundary-loading"><div className="loader-ring" /><p>Checking workspace access...</p></div></main>;
}

function LoginBoundary({
  state,
  message,
  email,
  signingIn,
  onEmailChange,
  onDevelopmentSignIn,
  onProviderSignIn,
}: {
  state: Exclude<AuthState, "loading" | "ready">;
  message: string | null;
  email: string;
  signingIn: boolean;
  onEmailChange: (value: string) => void;
  onDevelopmentSignIn: (event: FormEvent<HTMLFormElement>) => void;
  onProviderSignIn: () => void;
}) {
  const isBlocked = state === "disabled";
  const isExpired = state === "expired";
  return (
    <main className="boundary-screen">
      <section className={`boundary-card ${isBlocked ? "boundary-card--blocked" : ""}`}>
        <div className="boundary-brand"><div className="brand-mark" aria-hidden="true"><span /><span /><span /></div><strong>Fieldnote</strong></div>
        <p className="eyebrow">{isBlocked ? "Membership disabled" : isExpired ? "Session ended" : "Identity boundary"}</p>
        <h1>{isBlocked ? "This account cannot enter the workspace." : "Keep the workspace boundary intact."}</h1>
        <p>{message || (isExpired ? "Your session expired or was revoked. Sign in again to reload an authorized workspace context." : "Choose the identity path configured for this environment before any workspace data is requested.")}</p>
        {isBlocked ? (
          <div className="boundary-note"><span className="boundary-mark">!</span><span>Ask an organization owner to restore this membership. No workspace data has been loaded.</span></div>
        ) : (
          <>
            {AUTH_MODE === "provider" && <button className="boundary-provider-button" onClick={onProviderSignIn} type="button">Continue with identity provider <span aria-hidden="true">-&gt;</span></button>}
            {DEV_AUTH_ENABLED && (
              <form className="dev-auth-form" onSubmit={onDevelopmentSignIn}>
                <div className="dev-auth-label"><span>Local development path</span><span className="auth-mode-chip auth-mode-chip--dev">Not production auth</span></div>
                <label htmlFor="dev-email">Email for local operator identity</label>
                <div className="dev-auth-input-row"><input autoComplete="email" id="dev-email" onChange={(event) => onEmailChange(event.target.value)} placeholder="operator@example.com" required type="email" value={email} /><button className="button button--primary" disabled={signingIn} type="submit">{signingIn ? "Starting..." : "Start local session"}</button></div>
                <p>Development mode calls the real API health endpoint first. The session is stored only for this browser tab and is never a production credential.</p>
              </form>
            )}
            {!DEV_AUTH_ENABLED && AUTH_MODE !== "provider" && <div className="boundary-note"><span className="boundary-mark">i</span><span>Authentication is not configured for this build. Set the provider boundary before continuing.</span></div>}
          </>
        )}
      </section>
    </main>
  );
}

function SurfaceFrame({
  session,
  workspace,
  activeSurface,
  contextError,
  contextBusy,
  modeBusy,
  onNavigate,
  onWorkspaceSelect,
  onModeChange,
  onSignOut,
  children,
}: {
  session: SessionContext;
  workspace: WorkspaceContext;
  activeSurface: SurfaceKey;
  contextError: string | null;
  contextBusy: boolean;
  modeBusy: boolean;
  onNavigate: (surface: SurfaceKey) => void;
  onWorkspaceSelect: (workspace: WorkspaceContext) => void;
  onModeChange: (mode: WorkspaceMode) => void;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const item = SURFACE_ITEMS.find((surface) => surface.key === activeSurface);
  return (
    <main className="app-shell">
      <AppSidebar activeSurface={activeSurface} activeWorkspace={workspace} busy={modeBusy || contextBusy} onNavigate={onNavigate} onWorkspaceSelect={onWorkspaceSelect} session={session} />
      <section className="workspace">
        <WorkspaceHeader authMode={session.auth_mode} eyebrow={item?.kicker || "Workspace surface"} modeBusy={modeBusy} onModeChange={onModeChange} onSignOut={onSignOut} session={session} title={item?.title || "Workspace"} workspace={workspace} />
        {contextError && <div className="alert alert--error" role="alert"><strong>Context not changed.</strong> {contextError}</div>}
        {children}
      </section>
    </main>
  );
}

function FutureSurface({ surface, workspace }: { surface: SurfaceKey; workspace: WorkspaceContext }) {
  const item = SURFACE_ITEMS.find((candidate) => candidate.key === surface);
  return (
    <section className="future-surface">
      <div className="future-surface-index">{item?.icon || "--"}</div>
      <p className="eyebrow">{item?.kicker || "Planned surface"}</p>
      <h2>{item?.title || "Workspace surface"} is staged next.</h2>
      <p>The navigation contract is ready for <strong>{workspace.name}</strong>, but this workstream only owns the T-01 tenancy boundary and the existing F01 review path. No pretend records are rendered here.</p>
      <span className="future-surface-note">This route will be enabled when its package Definition of Done passes.</span>
    </section>
  );
}

export default function HomePage() {
  const [authState, setAuthState] = useState<AuthState>("loading");
  const [session, setSession] = useState<SessionContext | null>(null);
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceContext | null>(null);
  const [activeSurface, setActiveSurface] = useState<SurfaceKey>("review");
  const [authMessage, setAuthMessage] = useState<string | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);
  const [contextBusy, setContextBusy] = useState(false);
  const [modeBusy, setModeBusy] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const [devEmail, setDevEmail] = useState("");

  const hydrateSession = useCallback((nextSession: SessionContext) => {
    const persistedId = readActiveWorkspaceId(nextSession);
    const nextWorkspace = nextSession.workspaces.find((workspace) => workspace.id === persistedId)
      || nextSession.workspaces.find((workspace) => workspace.id === nextSession.active_workspace_id)
      || nextSession.workspaces.find((workspace) => workspace.membership_status === "active")
      || null;
    setSession(nextSession);
    if (isDisabledMember(nextSession, nextWorkspace)) {
      setActiveWorkspace(nextWorkspace);
      setActiveWorkspaceContext(null);
      setAuthState("disabled");
      setAuthMessage(`${nextSession.user.email} is disabled for this workspace.`);
      return;
    }
    if (!nextWorkspace) {
      setActiveWorkspace(null);
      setActiveWorkspaceContext(null);
      setAuthState("denied");
      setAuthMessage("This identity has no active workspace membership.");
      return;
    }
    setActiveWorkspace(nextWorkspace);
    setActiveWorkspaceContext(nextWorkspace.id);
    persistActiveWorkspaceId(nextSession, nextWorkspace.id);
    setAuthMessage(null);
    setContextError(null);
    setAuthState("ready");
  }, []);

  const handleSessionExpired = useCallback((error: ApiRequestError) => {
    setActiveWorkspaceContext(null);
    setSession(null);
    setActiveWorkspace(null);
    setAuthState("expired");
    setAuthMessage(error.message || "Your session is no longer authorized.");
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const liveSession = await api.getSession();
        if (!cancelled) hydrateSession(liveSession);
        return;
      } catch (sessionError) {
        const stored = api.getStoredDevelopmentSession();
        if (!cancelled && stored && DEV_AUTH_ENABLED) {
          try {
            await api.health();
            if (!cancelled) hydrateSession(stored);
            return;
          } catch {
            // Fall through to the sign-in boundary when the local runtime is down.
          }
        }
        if (cancelled) return;
        if (sessionError instanceof ApiRequestError && sessionError.status === 403) {
          setAuthState(sessionError.code === "MEMBER_DISABLED" ? "disabled" : "denied");
          setAuthMessage(sessionError.message);
        } else if (DEV_AUTH_ENABLED && sessionError instanceof ApiRequestError && [401, 404].includes(sessionError.status)) {
          setAuthState("signed_out");
          setAuthMessage("No active provider session was found. The explicitly labelled local development path is available below.");
        } else {
          setAuthState("failed");
          setAuthMessage(errorMessage(sessionError));
        }
      }
    })();
    return () => { cancelled = true; };
  }, [hydrateSession]);

  async function handleDevelopmentSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSigningIn(true);
    setAuthMessage(null);
    try {
      const nextSession = await api.startDevelopmentSession(devEmail);
      hydrateSession(nextSession);
    } catch (signInError) {
      setAuthMessage(errorMessage(signInError));
    } finally {
      setSigningIn(false);
    }
  }

  function handleProviderSignIn() {
    if (typeof window === "undefined") return;
    const returnTo = encodeURIComponent(window.location.href);
    window.location.assign(`${API_BASE_URL}/api/auth/login?return_to=${returnTo}`);
  }

  async function handleSignOut() {
    try {
      await api.signOut();
    } catch (signOutError) {
      setContextError(errorMessage(signOutError));
    }
    setActiveWorkspaceContext(null);
    setSession(null);
    setActiveWorkspace(null);
    setAuthState("signed_out");
    setAuthMessage("You signed out. Workspace data has been cleared from this client session.");
  }

  async function handleWorkspaceSelect(nextWorkspace: WorkspaceContext) {
    if (!session || !activeWorkspace || nextWorkspace.id === activeWorkspace.id) return;
    if (nextWorkspace.membership_status !== "active") {
      setContextError("That membership is disabled and cannot become the active workspace.");
      return;
    }
    setContextBusy(true);
    setContextError(null);
    try {
      let resolvedWorkspace = nextWorkspace;
      try {
        const response = await api.activateWorkspace(nextWorkspace.id);
        if ("workspace" in response && response.workspace) resolvedWorkspace = response.workspace;
        else if ("id" in response) resolvedWorkspace = response;
      } catch (activationError) {
        if (session.auth_mode !== "development" || !(activationError instanceof ApiRequestError) || ![404, 405].includes(activationError.status)) throw activationError;
      }
      const nextSession = { ...session, active_workspace_id: resolvedWorkspace.id, workspaces: session.workspaces.map((workspace) => workspace.id === resolvedWorkspace.id ? resolvedWorkspace : workspace) };
      setSession(nextSession);
      setActiveWorkspace(resolvedWorkspace);
      setActiveWorkspaceContext(resolvedWorkspace.id);
      persistActiveWorkspaceId(nextSession, resolvedWorkspace.id);
      setActiveSurface("review");
    } catch (activationError) {
      if (activationError instanceof ApiRequestError && activationError.status === 401) handleSessionExpired(activationError);
      else setContextError(errorMessage(activationError));
    } finally {
      setContextBusy(false);
    }
  }

  async function handleModeChange(nextMode: WorkspaceMode) {
    if (!session || !activeWorkspace || activeWorkspace.mode === nextMode) return;
    setModeBusy(true);
    setContextError(null);
    try {
      let resolvedWorkspace = { ...activeWorkspace, mode: nextMode };
      try {
        const response = await api.updateWorkspaceMode(activeWorkspace.id, nextMode);
        if ("workspace" in response && response.workspace) resolvedWorkspace = response.workspace;
        else if ("id" in response) resolvedWorkspace = response;
      } catch (modeError) {
        if (session.auth_mode !== "development" || !(modeError instanceof ApiRequestError) || ![404, 405].includes(modeError.status)) throw modeError;
      }
      const nextSession = { ...session, workspaces: session.workspaces.map((workspace) => workspace.id === resolvedWorkspace.id ? resolvedWorkspace : workspace) };
      setSession(nextSession);
      setActiveWorkspace(resolvedWorkspace);
      setActiveWorkspaceContext(resolvedWorkspace.id);
      persistActiveWorkspaceId(nextSession, resolvedWorkspace.id);
      if (nextMode === "handoff") setActiveSurface("handoff");
    } catch (modeError) {
      if (modeError instanceof ApiRequestError && modeError.status === 401) handleSessionExpired(modeError);
      else setContextError(errorMessage(modeError));
    } finally {
      setModeBusy(false);
    }
  }

  function handleNavigate(surface: SurfaceKey) {
    setContextError(null);
    setActiveSurface(surface);
  }

  if (authState === "loading") return <LoadingBoundary />;
  if (authState !== "ready" || !session || !activeWorkspace) {
    if (authState === "disabled" && session) return <MemberDisabled email={session.user.email} />;
    return <LoginBoundary email={devEmail} message={authMessage} onDevelopmentSignIn={handleDevelopmentSignIn} onEmailChange={setDevEmail} onProviderSignIn={handleProviderSignIn} signingIn={signingIn} state={authState === "ready" ? "failed" : authState} />;
  }

  const activeAllowed = SURFACE_ITEMS.find((item) => item.key === activeSurface)?.allowedRoles.includes(activeWorkspace.role) ?? false;
  const surface = !activeAllowed ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <AuthorizationDenied role={activeWorkspace.role} />
    </SurfaceFrame>
  ) : activeSurface === "review" ? (
    <ReviewDesk activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSessionExpired={handleSessionExpired} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace} />
  ) : activeSurface === "handoff" ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <AppHandoffView onAuthFailure={handleSessionExpired} onOpenReviewDesk={() => setActiveSurface("review")} workspace={activeWorkspace} />
    </SurfaceFrame>
  ) : activeSurface === "discovery" ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <DiscoveryView onAuthFailure={handleSessionExpired} session={session} workspace={activeWorkspace} />
    </SurfaceFrame>
  ) : activeSurface === "workflows" ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <WorkflowStudio onAuthFailure={handleSessionExpired} session={session} workspace={activeWorkspace} />
    </SurfaceFrame>
  ) : activeSurface === "runtime" ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <ExecutionRuntime onAuthFailure={handleSessionExpired} session={session} workspace={activeWorkspace} />
    </SurfaceFrame>
  ) : activeSurface === "connections" ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <ConnectorsView onAuthFailure={handleSessionExpired} session={session} workspace={activeWorkspace} />
    </SurfaceFrame>
  ) : activeSurface === "compliance" ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <ComplianceView onAuthFailure={handleSessionExpired} session={session} workspace={activeWorkspace} />
    </SurfaceFrame>
  ) : activeSurface === "confidence" ? (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <ConfidenceView onAuthFailure={handleSessionExpired} session={session} workspace={activeWorkspace} />
    </SurfaceFrame>
  ) : (
    <SurfaceFrame activeSurface={activeSurface} contextBusy={contextBusy} contextError={contextError} modeBusy={modeBusy} onModeChange={handleModeChange} onNavigate={handleNavigate} onSignOut={handleSignOut} onWorkspaceSelect={handleWorkspaceSelect} session={session} workspace={activeWorkspace}>
      <FutureSurface surface={activeSurface} workspace={activeWorkspace} />
    </SurfaceFrame>
  );

  return surface;
}

function ReviewDesk({ session, workspace, activeSurface, contextError, contextBusy, modeBusy, onNavigate, onWorkspaceSelect, onModeChange, onSignOut, onSessionExpired }: ReviewDeskProps) {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [selectedVendorId, setSelectedVendorId] = useState<string | null>(null);
  const [selectedVendor, setSelectedVendor] = useState<VendorDetail | null>(null);
  const [statusData, setStatusData] = useState<StatusResponse | null>(null);
  const [ledger, setLedger] = useState<AuditEvent[]>([]);
  const [reviews, setReviews] = useState<ReviewTask[]>([]);
  const [reviewQueue, setReviewQueue] = useState<ReviewTask[]>([]);
  const [reviewQueueLoading, setReviewQueueLoading] = useState(true);
  const [reviewQueueError, setReviewQueueError] = useState<string | null>(null);
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [verifyingDocumentId, setVerifyingDocumentId] = useState<string | null>(null);
  const [savingReviewId, setSavingReviewId] = useState<string | null>(null);
  const [newVendorName, setNewVendorName] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [reviewValues, setReviewValues] = useState<Record<string, string>>({});
  const [reviewReasonCodes, setReviewReasonCodes] = useState<Record<string, string>>({});
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const workspaceIdRef = useRef(workspace.id);
  const canOperate = can(workspace.role, "operate_review_desk");

  const currentStatus = statusData?.current ?? selectedVendor?.latest_status ?? null;
  const currentDocument: ComplianceDocument | null = selectedVendor?.documents[0] ?? null;
  const normalizedFields = currentStatus?.evidence.normalized_fields ?? currentDocument?.extracted_fields ?? null;
  const currentChecks = currentStatus?.evidence.checks ?? [];
  const checksByKey = useMemo(() => new Map(currentChecks.map((check) => [check.requirement_key, check])), [currentChecks]);
  const vendorReviews = reviews.filter((review) => review.vendor_id === selectedVendorId && review.status === "open");

  async function refreshVendors() {
    const response = await api.listVendors();
    if (workspaceIdRef.current !== workspace.id) return;
    setVendors(response.items);
    setSelectedVendorId((currentId) => currentId && response.items.some((vendor) => vendor.id === currentId) ? currentId : response.items[0]?.id ?? null);
  }

  async function refreshDetails(vendorId: string) {
    const requestedWorkspaceId = workspace.id;
    setDetailLoading(true);
    try {
      const [detail, ledgerResponse, reviewResponse] = await Promise.all([
        api.getVendor(vendorId),
        api.getLedger(vendorId),
        api.getReviews(),
      ]);
      let nextStatus: StatusResponse | null = null;
      try {
        nextStatus = await api.getStatus(vendorId);
      } catch (statusError) {
        if (!(statusError instanceof ApiRequestError) || statusError.status !== 404) throw statusError;
      }
      if (workspaceIdRef.current !== requestedWorkspaceId) return;
      setSelectedVendor(detail);
      setStatusData(nextStatus);
      setLedger(ledgerResponse.items);
      setReviews(reviewResponse.items);
      setReviewValues({});
      setReviewReasonCodes({});
      setReviewNotes({});
    } finally {
      if (workspaceIdRef.current === requestedWorkspaceId) setDetailLoading(false);
    }
  }

  async function refreshReviewQueue() {
    const requestedWorkspaceId = workspace.id;
    setReviewQueueLoading(true);
    setReviewQueueError(null);
    try {
      const response = await api.getReviewQueue("open", 50);
      if (workspaceIdRef.current !== requestedWorkspaceId) return;
      setReviewQueue(response.items);
    } catch (queueLoadError) {
      if (workspaceIdRef.current === requestedWorkspaceId) setReviewQueueError(errorMessage(queueLoadError));
    } finally {
      if (workspaceIdRef.current === requestedWorkspaceId) setReviewQueueLoading(false);
    }
  }

  async function refreshAll(vendorId: string | null = selectedVendorId) {
    setError(null);
    try {
      await refreshVendors();
      await refreshReviewQueue();
      if (vendorId) await refreshDetails(vendorId);
    } catch (refreshError) {
      reportError(refreshError);
    }
  }

  useEffect(() => {
    workspaceIdRef.current = workspace.id;
    setVendors([]);
    setSelectedVendorId(null);
    setSelectedVendor(null);
    setStatusData(null);
    setLedger([]);
    setReviews([]);
    setReviewQueue([]);
    setSelectedReviewId(null);
    setReviewQueueError(null);
    setReviewValues({});
    setSelectedFile(null);
    setError(null);
    setNotice(null);
    setDetailLoading(false);
    setInitialLoading(true);
    void (async () => {
      try {
        await Promise.all([refreshVendors(), refreshReviewQueue()]);
      } catch (loadError) {
        reportError(loadError);
      } finally {
        if (workspaceIdRef.current === workspace.id) setInitialLoading(false);
      }
    })();
  }, [workspace.id]);

  useEffect(() => {
    function handleDeskShortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const editing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT" || target?.isContentEditable;
      if (editing) return;
      if (event.key.toLowerCase() === "r") {
        event.preventDefault();
        void refreshReviewQueue();
      }
      if (event.key.toLowerCase() === "e") {
        event.preventDefault();
        document.querySelector<HTMLInputElement>("input[aria-label^='Correction for']")?.focus();
      }
    }
    window.addEventListener("keydown", handleDeskShortcut);
    return () => window.removeEventListener("keydown", handleDeskShortcut);
  }, [workspace.id]);

  useEffect(() => {
    if (!selectedVendorId) {
      setSelectedVendor(null);
      setStatusData(null);
      setLedger([]);
      setReviews([]);
      return;
    }
    void refreshDetails(selectedVendorId).catch((loadError) => reportError(loadError));
  }, [selectedVendorId, workspace.id]);

  function reportError(operationError: unknown) {
    if (operationError instanceof ApiRequestError && operationError.status === 401) {
      onSessionExpired(operationError);
      return;
    }
    setError(errorMessage(operationError));
  }

  async function handleCreateVendor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canOperate) {
      setError("Your role can view this desk but cannot create or change vendor records.");
      return;
    }
    const legalName = newVendorName.trim();
    if (!legalName) return;
    setCreating(true);
    setError(null);
    try {
      const vendor = await api.createVendor(legalName);
      setNewVendorName("");
      await refreshVendors();
      setSelectedVendorId(vendor.id);
      setNotice(`${vendor.legal_name} is ready for its first COI.`);
    } catch (createError) {
      reportError(createError);
    } finally {
      setCreating(false);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFile(event.target.files?.[0] ?? null);
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canOperate) {
      setError("Your role can view this desk but cannot upload documents.");
      return;
    }
    if (!selectedVendorId || !selectedFile) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadDocument(selectedVendorId, selectedFile);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refreshAll(selectedVendorId);
      setNotice("COI uploaded. The extracted fields are ready for verification.");
    } catch (uploadError) {
      reportError(uploadError);
    } finally {
      setUploading(false);
    }
  }

  async function handleVerify(documentId: string) {
    if (!canOperate) {
      setError("Your role can view this desk but cannot run verification.");
      return;
    }
    setVerifyingDocumentId(documentId);
    setError(null);
    try {
      const result = await api.verifyDocument(documentId);
      await refreshAll(selectedVendorId);
      setNotice(result.status.status === "compliant" ? "Verification passed. Proof is recorded." : "Verification needs a human review.");
    } catch (verifyError) {
      reportError(verifyError);
    } finally {
      setVerifyingDocumentId(null);
    }
  }

  async function handleReviewSave(review: ReviewTask) {
    if (!canOperate) {
      setError("Your role can view this desk but cannot resolve review tasks.");
      return;
    }
    const fieldValue = reviewValues[review.id] ?? editableValue(normalizedFields?.[review.correction_field]);
    if (!fieldValue.trim()) return;
    setSavingReviewId(review.id);
    setError(null);
    try {
      const reasonCode = reviewReasonCodes[review.id] || "SOURCE_TEXT_CORRECTION";
      const note = reviewNotes[review.id] || "Confirmed against the source evidence.";
      const result = await api.updateReview(review.id, fieldValue, review.correction_field, reasonCode, note);
      await refreshAll(selectedVendorId);
      setNotice(result.status.status === "compliant" ? "Correction accepted. Vendor is now compliant." : "Correction saved. Another requirement still needs review.");
    } catch (reviewError) {
      reportError(reviewError);
    } finally {
      setSavingReviewId(null);
    }
  }

  function handleQueueSelect(task: ReviewTask) {
    setSelectedReviewId(task.id);
    setSelectedVendorId(task.vendor_id);
    setNotice(null);
  }

  async function handleBulkAssign(taskIds: string[]) {
    try {
      await api.bulkReviewAction({ review_ids: taskIds, action: "assign", assignee_user_id: session.user.id });
      await refreshReviewQueue();
      setNotice(`${taskIds.length} review task${taskIds.length === 1 ? "" : "s"} assigned to you.`);
    } catch (bulkError) {
      reportError(bulkError);
      throw bulkError;
    }
  }

  async function handleBulkEscalate(taskIds: string[]) {
    try {
      await api.bulkReviewAction({ review_ids: taskIds, action: "escalate", reason: "Operator requested supervisor review." });
      await refreshReviewQueue();
      setNotice(`${taskIds.length} review task${taskIds.length === 1 ? "" : "s"} escalated.`);
    } catch (bulkError) {
      reportError(bulkError);
      throw bulkError;
    }
  }

  const selectedName = selectedVendor?.legal_name ?? "Select a vendor";

  return (
    <main className="app-shell">
      <AppSidebar activeSurface={activeSurface} activeWorkspace={workspace} busy={modeBusy || contextBusy} onNavigate={onNavigate} onWorkspaceSelect={onWorkspaceSelect} session={session}>
        <div className="sidebar-meta">
          <span className="live-dot" />
          <span>F01 · local workspace</span>
        </div>

        <div className="sidebar-section-heading">
          <span>Vendors</span>
          <span className="count-badge">{vendors.length.toString().padStart(2, "0")}</span>
        </div>

        <div className="vendor-list" aria-label="Vendors">
          {initialLoading ? (
            <div className="skeleton-list" aria-label="Loading vendors"><span /><span /><span /></div>
          ) : vendors.length === 0 ? (
            <p className="sidebar-empty">No vendors yet. Add the first one below.</p>
          ) : (
            vendors.map((vendor) => (
              <button
                className={`vendor-row ${vendor.id === selectedVendorId ? "vendor-row--active" : ""}`}
                key={vendor.id}
                onClick={() => { setNotice(null); setSelectedVendorId(vendor.id); }}
                type="button"
              >
                <span className={`vendor-status-dot ${vendor.latest_status?.status === "compliant" ? "vendor-status-dot--good" : vendor.latest_status ? "vendor-status-dot--warn" : ""}`} />
                <span className="vendor-row-copy">
                  <strong>{vendor.legal_name}</strong>
                  <small>{vendor.latest_status ? statusText(vendor.latest_status) : "No verification yet"}</small>
                </span>
                <span className="row-arrow" aria-hidden="true">↗</span>
              </button>
            ))
          )}
        </div>

        <form className="new-vendor-form" onSubmit={handleCreateVendor}>
          <label htmlFor="new-vendor">Add vendor {canOperate ? "" : "(read-only)"}</label>
          <div className="input-with-action">
            <input
              disabled={!canOperate}
              id="new-vendor"
              onChange={(event) => setNewVendorName(event.target.value)}
              placeholder="Legal name"
              value={newVendorName}
            />
            <button aria-label="Add vendor" disabled={!canOperate || creating || !newVendorName.trim()} type="submit">+</button>
          </div>
          <p>{canOperate ? "Use the legal name printed on the certificate." : "Ask an operator to add vendor records."}</p>
        </form>

        <div className="sidebar-footer review-sidebar-footer">
          <div className="footer-rule" />
          <p>Every decision keeps its source, reason, and timestamp.</p>
          <span>rules.v1 · append-only ledger</span>
        </div>
      </AppSidebar>

      <section className="workspace">
        <WorkspaceHeader authMode={session.auth_mode} eyebrow="F01 / vendor proof" modeBusy={modeBusy} onModeChange={onModeChange} onSignOut={onSignOut} session={session} title="Verification, with a paper trail." workspace={workspace} />

        {contextError && <div className="alert alert--error" role="alert"><strong>Context not changed.</strong> {contextError}</div>}
        {!canOperate && <div className="read-only-banner" role="status"><strong>Read-only view.</strong> Your {roleLabel(workspace.role)} role can inspect proof and history but cannot change vendor records.</div>}
        {error && <div className="alert alert--error" role="alert"><strong>Action paused.</strong> {error}<button onClick={() => setError(null)} type="button">Dismiss</button></div>}
        {notice && <div className="alert alert--success" role="status"><span>✓</span> {notice}<button onClick={() => setNotice(null)} type="button">Dismiss</button></div>}

        <ReviewQueuePanel canOperate={canOperate} currentUserId={session.user.id} error={reviewQueueError} items={reviewQueue} loading={reviewQueueLoading} onBulkAssign={handleBulkAssign} onBulkEscalate={handleBulkEscalate} onRefresh={() => void refreshReviewQueue()} onSelect={handleQueueSelect} selectedId={selectedReviewId} />

        {!initialLoading && vendors.length === 0 ? (
          <section className="empty-state">
            <div className="empty-illustration" aria-hidden="true"><span>+</span><i /><i /><i /></div>
            <p className="eyebrow">Start with one vendor</p>
            <h2>Make the first certificate legible.</h2>
            <p>Add a legal vendor name in the left rail, then upload a text-readable COI. The desk will show what it saw and why each rule passed or failed.</p>
          </section>
        ) : detailLoading && !selectedVendor ? (
          <section className="loading-state"><div className="loader-ring" /><p>Opening {selectedName}…</p></section>
        ) : selectedVendor ? (
          <div className="content-stack">
            <section className="vendor-heading">
              <div>
                <div className="breadcrumb"><span>Vendors</span><b>/</b><span>{selectedVendor.legal_name}</span></div>
                <h2>{selectedVendor.legal_name}</h2>
                <p>One view for observed evidence, exceptions, and the decision made on the day.</p>
              </div>
              <div className={statusClass(currentStatus)}><span className="status-dot" />{statusText(currentStatus)}</div>
            </section>

            <section className="overview-grid">
              <div className="metric-card metric-card--accent">
                <span className="card-kicker">Current decision</span>
                <strong>{currentStatus ? statusText(currentStatus) : "Not verified"}</strong>
                <small>{currentStatus ? `${currentStatus.failing_requirements.length} open exception${currentStatus.failing_requirements.length === 1 ? "" : "s"}` : "Upload and run the seeded rules"}</small>
              </div>
              <div className="metric-card">
                <span className="card-kicker">Last snapshot</span>
                <strong>{currentStatus ? formatDate(currentStatus.as_of) : "—"}</strong>
                <small>{currentStatus ? `Version ${currentStatus.computed_by_version}` : "No point-in-time record yet"}</small>
              </div>
              <div className="metric-card">
                <span className="card-kicker">Documents</span>
                <strong>{selectedVendor.documents.length.toString().padStart(2, "0")}</strong>
                <small>{selectedVendor.documents.length ? "COI evidence on file" : "Waiting for intake"}</small>
              </div>
            </section>

            <section className={`panel intake-panel ${!canOperate ? "intake-panel--readonly" : ""}`}>
              <div className="panel-heading">
                <div><p className="eyebrow">01 / Intake</p><h3>Bring the certificate into the light.</h3></div>
                <span className="panel-note">Text-readable PDF or TXT · 10 MB max</span>
              </div>
              <form className="upload-bar" onSubmit={handleUpload}>
                <label className={`file-picker ${selectedFile ? "file-picker--selected" : ""} ${!canOperate ? "file-picker--disabled" : ""}`} htmlFor="coi-file">
                  <span className="upload-glyph" aria-hidden="true">↑</span>
                  <span><strong>{selectedFile ? selectedFile.name : "Choose a COI"}</strong><small>{selectedFile ? `${Math.ceil(selectedFile.size / 1024)} KB ready to send` : "Drop a file or browse from this device"}</small></span>
                  <input accept=".pdf,.txt,application/pdf,text/plain" disabled={!canOperate} id="coi-file" onChange={handleFileChange} ref={fileInputRef} type="file" />
                </label>
                <button className="button button--primary" disabled={!selectedFile || uploading} type="submit">{uploading ? "Reading…" : "Upload COI"}<span aria-hidden="true">↗</span></button>
              </form>
              {selectedVendor.documents.length > 0 && <div className="document-list">{selectedVendor.documents.map((document) => <DocumentRow canOperate={canOperate} document={document} isVerifying={verifyingDocumentId === document.id} onVerify={handleVerify} key={document.id} />)}</div>}
            </section>

            <div className="two-column-grid">
              <section className="panel observations-panel">
                <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">02 / What we saw</p><h3>Normalized fields</h3></div><span className="tiny-label">{currentStatus ? "from latest snapshot" : "from latest document"}</span></div>
                {normalizedFields ? <div className="field-table">{fieldDefinitions.map((field) => { const check = checksByKey.get(fieldKeyToRequirement(field.key)); return <div className="field-row" key={field.key}><div><span className="field-label">{field.label}</span><small>{field.hint}</small></div><strong className={normalizedFields[field.key] === null ? "value-missing" : ""}>{formatValue(normalizedFields[field.key])}</strong><span className={`mini-check ${check?.result === "pass" ? "mini-check--pass" : check ? "mini-check--fail" : "mini-check--quiet"}`}>{check?.result === "pass" ? "PASS" : check ? "CHECK" : "—"}</span></div>; })}</div> : <div className="panel-empty"><span>◎</span><p>Upload a COI to see extracted fields here.</p></div>}
              </section>

              <section className={`panel review-panel ${!canOperate ? "review-panel--readonly" : ""}`}>
                <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">03 / Human review</p><h3>Exceptions to resolve</h3></div><span className="count-badge count-badge--dark">{vendorReviews.length.toString().padStart(2, "0")}</span></div>
                {vendorReviews.length === 0 ? <div className="review-empty"><span className="review-empty-mark">{currentStatus?.status === "compliant" ? "✓" : "·"}</span><p>{currentStatus?.status === "compliant" ? "No exceptions. This vendor has a clean decision." : "Verification creates focused correction tasks here."}</p></div> : <div className="review-list">{vendorReviews.map((review) => <ReviewCard fieldValue={reviewValues[review.id] ?? editableValue(normalizedFields?.[review.correction_field])} isSaving={savingReviewId === review.id} note={reviewNotes[review.id] ?? ""} onChange={(value) => setReviewValues((previous) => ({ ...previous, [review.id]: value }))} onNoteChange={(value) => setReviewNotes((previous) => ({ ...previous, [review.id]: value }))} onReasonChange={(value) => setReviewReasonCodes((previous) => ({ ...previous, [review.id]: value }))} onSave={() => void handleReviewSave(review)} reasonCode={reviewReasonCodes[review.id] ?? "SOURCE_TEXT_CORRECTION"} review={review} key={review.id} />)}</div>}
              </section>
            </div>

            <section className="panel requirements-panel">
              <div className="panel-heading"><div><p className="eyebrow">04 / Rule ledger</p><h3>Every requirement gets a reason.</h3></div><span className="panel-note">Deterministic checks · {currentStatus?.computed_by_version ?? "rules.v1"}</span></div>
              {currentChecks.length === 0 ? <div className="panel-empty panel-empty--wide"><span>◌</span><p>Verify the latest document to populate the requirement matrix.</p></div> : <div className="requirements-table"><div className="requirements-head"><span>Requirement</span><span>Observed</span><span>Expected</span><span>Decision</span></div>{currentChecks.map((check) => <RequirementRow check={check} key={check.id} />)}</div>}
            </section>

            <div className="two-column-grid two-column-grid--bottom">
              <section className="panel history-panel">
                <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">05 / Point in time</p><h3>Status history</h3></div><span className="tiny-label">Append-only</span></div>
                {statusData?.history.length ? <div className="history-list">{statusData.history.map((snapshot, index) => <div className="history-row" key={snapshot.id}><span className={`history-marker ${snapshot.status === "compliant" ? "history-marker--good" : ""}`} /> <div><strong>{statusText(snapshot)}</strong><small>{formatDate(snapshot.as_of)} · {snapshot.failing_requirements.length} exception{snapshot.failing_requirements.length === 1 ? "" : "s"}</small></div><span className="history-index">{String(statusData.history.length - index).padStart(2, "0")}</span></div>)}</div> : <div className="panel-empty"><span>◷</span><p>Each verification decision will become a snapshot.</p></div>}
              </section>
              <section className="panel ledger-panel">
                <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">06 / Evidence trail</p><h3>Audit ledger</h3></div><span className="tiny-label">{ledger.length} events</span></div>
                {ledger.length ? <div className="ledger-list">{ledger.slice(0, 6).map((event) => <div className="ledger-row" key={event.id}><span className="ledger-icon" aria-hidden="true">↳</span><div><strong>{friendlyEventName(event.event_type)}</strong><small>{event.actor_type} · {formatDate(event.occurred_at)}</small></div></div>)}</div> : <div className="panel-empty"><span>⌁</span><p>Uploads, decisions, and corrections will appear here.</p></div>}
              </section>
            </div>
          </div>
        ) : (
          <section className="loading-state"><div className="loader-ring" /><p>Preparing the review desk…</p></section>
        )}
      </section>
    </main>
  );
}

function fieldKeyToRequirement(key: keyof ExtractedFields): string {
  const mapping: Record<string, string> = {
    named_insured: "named_insured_match",
    certificate_holder: "certificate_holder_match",
    gl_occurrence_limit: "gl_occurrence_minimum",
    policy_expiry: "policy_not_expired",
    additional_insured: "additional_insured_present",
    waiver_of_subrogation: "waiver_of_subrogation_present",
  };
  return mapping[key as string];
}

function DocumentRow({ document, isVerifying, onVerify, canOperate }: { document: ComplianceDocument; isVerifying: boolean; onVerify: (documentId: string) => void; canOperate: boolean }) {
  return <div className="document-row"><div className="document-icon">COI</div><div className="document-copy"><strong>{document.filename}</strong><small>Uploaded {formatDate(document.created_at)} · {document.media_type || "text document"}</small></div><button className="button button--quiet" disabled={isVerifying} onClick={() => onVerify(document.id)} type="button">{isVerifying ? "Checking…" : "Verify"}<span aria-hidden="true">→</span></button></div>;
}

function highlightedSource(excerpt: string, matchedText: string | undefined): ReactNode {
  if (!matchedText) return excerpt;
  const start = excerpt.toLocaleLowerCase().indexOf(matchedText.toLocaleLowerCase());
  if (start < 0) return excerpt;
  const end = start + matchedText.length;
  return <>{excerpt.slice(0, start)}<mark>{excerpt.slice(start, end)}</mark>{excerpt.slice(end)}</>;
}

function ReviewCard({ review, fieldValue, isSaving, note, onChange, onNoteChange, onReasonChange, onSave, reasonCode }: { review: ReviewTask; fieldValue: string; isSaving: boolean; note: string; onChange: (value: string) => void; onNoteChange: (value: string) => void; onReasonChange: (value: string) => void; onSave: () => void; reasonCode: string }) {
  const provenance = review.provenance;
  return <div className="review-card"><div className="review-card-top"><span className="review-flag">{review.reason_code}</span><span className="review-field">{review.correction_field.replaceAll("_", " ")}</span></div><strong>Confirm the observed value</strong><p>This correction is written to the document record and triggers a new verification snapshot.</p>{provenance && <details className="review-provenance" open><summary>Source locator</summary><div><strong>{provenance.filename}</strong><span>Page {provenance.page}{provenance.line ? ` · line ${provenance.line}` : ""}{provenance.char_start !== undefined ? ` · characters ${provenance.char_start}–${provenance.char_end ?? provenance.char_start}` : ""}</span><blockquote>{highlightedSource(provenance.excerpt || provenance.matched_text || "Source excerpt unavailable.", provenance.matched_text)}</blockquote><small>{provenance.bbox ? "Bounding box recorded." : "Text locator recorded; visual bounding box unavailable for this source."}</small></div></details>}<div className="review-input-row"><input aria-label={`Correction for ${review.correction_field}`} onChange={(event) => onChange(event.target.value)} value={fieldValue} /><button className="button button--dark" disabled={isSaving || !fieldValue.trim()} onClick={onSave} type="button">{isSaving ? "Saving…" : "Re-check"}</button></div><div className="review-correction-meta"><label>Reason code<select aria-label={`Reason code for ${review.correction_field}`} onChange={(event) => onReasonChange(event.target.value)} value={reasonCode}><option value="SOURCE_TEXT_CORRECTION">Source text correction</option><option value="VENDOR_CORRECTION">Vendor correction</option><option value="RULE_OVERRIDE">Rule override</option></select></label><label>Correction note<textarea aria-label={`Correction note for ${review.correction_field}`} onChange={(event) => onNoteChange(event.target.value)} placeholder="Why is this value correct?" value={note} /></label></div></div>;
}

function RequirementRow({ check }: { check: Check }) {
  return <div className="requirements-row"><div><strong>{check.label}</strong><small>{check.reason_code}</small></div><span>{formatValue(check.observed_value)}</span><span>{formatValue(check.required_value)}</span><span className={`decision decision--${check.result}`}><i />{check.result === "pass" ? "Pass" : "Review"}</span></div>;
}
