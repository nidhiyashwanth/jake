import type { AuthMode, SessionContext, UserRole, WorkspaceContext } from "./types";

export type Capability =
  | "view_review_desk"
  | "operate_review_desk"
  | "view_handoff"
  | "view_audit"
  | "manage_members";

const ROLE_CAPABILITIES: Record<UserRole, Capability[]> = {
  owner: ["view_review_desk", "operate_review_desk", "view_handoff", "view_audit", "manage_members"],
  admin: ["view_review_desk", "operate_review_desk", "view_handoff", "view_audit", "manage_members"],
  builder: ["view_review_desk", "operate_review_desk", "view_audit"],
  operator: ["view_review_desk", "operate_review_desk", "view_handoff"],
  viewer: ["view_review_desk", "view_handoff"],
  auditor: ["view_review_desk", "view_handoff", "view_audit"],
};

export function can(role: UserRole, capability: Capability): boolean {
  return ROLE_CAPABILITIES[role].includes(capability);
}

export function roleLabel(role: UserRole): string {
  return role.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function modeLabel(mode: WorkspaceContext["mode"]): string {
  return mode === "handoff" ? "Handoff" : "Delivery";
}

export function workspaceStorageKey(session: SessionContext): string {
  return `fieldnote.active-workspace:${session.user.id}:${session.organization.id}`;
}

export function readActiveWorkspaceId(session: SessionContext): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(workspaceStorageKey(session));
}

export function persistActiveWorkspaceId(session: SessionContext, workspaceId: string) {
  if (typeof window !== "undefined") window.localStorage.setItem(workspaceStorageKey(session), workspaceId);
}

export function initialsFor(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function isDisabledMember(session: SessionContext, workspace: WorkspaceContext | null): boolean {
  return session.user.status === "disabled" || workspace?.membership_status === "disabled";
}

export function isDevelopmentSession(session: SessionContext, authMode: AuthMode): boolean {
  return authMode === "development" && session.auth_mode === "development";
}
