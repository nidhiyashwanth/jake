"use client";

import { ReactNode, useEffect, useRef, useState } from "react";

import type { AuthMode, SessionContext, UserRole, WorkspaceContext, WorkspaceMode } from "@/lib/types";
import { can, modeLabel, roleLabel } from "@/lib/tenancy";

export type SurfaceKey = "review" | "compliance" | "confidence" | "evaluations" | "handoff" | "workflows" | "discovery" | "runtime" | "connections" | "ledger" | "members";

interface SurfaceItem {
  key: SurfaceKey;
  title: string;
  kicker: string;
  icon: string;
  allowedRoles: UserRole[];
  live?: boolean;
}
export const SURFACE_ITEMS: SurfaceItem[] = [
  { key: "review", title: "Review desk", kicker: "F01 / live", icon: "01", allowedRoles: ["owner", "admin", "builder", "operator", "viewer", "auditor"], live: true },
  { key: "compliance", title: "Compliance policy", kicker: "P-01 / live", icon: "02", allowedRoles: ["owner", "admin", "builder", "operator", "viewer", "auditor"], live: true },
  { key: "confidence", title: "Confidence lab", kicker: "Q-01 / live", icon: "03", allowedRoles: ["owner", "admin", "builder", "operator", "viewer", "auditor"], live: true },
  { key: "evaluations", title: "Evaluation control", kicker: "E-01 / live", icon: "04", allowedRoles: ["owner", "admin", "builder", "operator", "viewer", "auditor"], live: true },
  { key: "handoff", title: "Field handoff", kicker: "T-01 / live", icon: "05", allowedRoles: ["owner", "admin", "operator", "viewer", "auditor"], live: true },
  { key: "workflows", title: "Workflows", kicker: "W-01 / active", icon: "06", allowedRoles: ["owner", "admin", "builder", "operator", "viewer"], live: true },
  { key: "discovery", title: "Discovery studio", kicker: "D-01 / active", icon: "07", allowedRoles: ["owner", "admin", "builder", "operator", "viewer", "auditor"], live: true },
  { key: "runtime", title: "Execution runtime", kicker: "R-01 / active", icon: "08", allowedRoles: ["owner", "admin", "builder", "operator", "viewer", "auditor"], live: true },
  { key: "connections", title: "Connections", kicker: "C-01 / live", icon: "09", allowedRoles: ["owner", "admin", "builder", "operator", "viewer", "auditor"], live: true },
  { key: "ledger", title: "Audit ledger", kicker: "G-01 / next", icon: "10", allowedRoles: ["owner", "admin", "auditor"] },
  { key: "members", title: "Org & members", kicker: "T-01 / next", icon: "11", allowedRoles: ["owner", "admin"] },
];

interface WorkspaceSwitcherProps {
  session: SessionContext;
  activeWorkspace: WorkspaceContext;
  onSelect: (workspace: WorkspaceContext) => void;
  busy?: boolean;
}

export function WorkspaceSwitcher({ session, activeWorkspace, onSelect, busy = false }: WorkspaceSwitcherProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const grouped = session.workspaces.reduce<Record<string, WorkspaceContext[]>>((groups, workspace) => {
    const organizationName = workspace.organization.name || session.organization.name;
    groups[organizationName] = [...(groups[organizationName] ?? []), workspace];
    return groups;
  }, {});

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className="workspace-switcher" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        className="workspace-switcher-trigger"
        disabled={busy}
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="workspace-switcher-mark" aria-hidden="true">{activeWorkspace.name.slice(0, 1).toUpperCase()}</span>
        <span className="workspace-switcher-copy">
          <small>Active workspace</small>
          <strong>{activeWorkspace.name}</strong>
          <em>{activeWorkspace.organization.name}</em>
        </span>
        <span className="workspace-switcher-chevron" aria-hidden="true">{open ? "-" : "+"}</span>
      </button>
      {open && (
        <div className="workspace-menu" role="menu" aria-label="Choose workspace">
          {Object.entries(grouped).map(([organizationName, workspaces]) => (
            <div className="workspace-menu-group" key={organizationName}>
              <p>{organizationName}</p>
              {workspaces.map((workspace) => {
                const selected = workspace.id === activeWorkspace.id;
                const disabled = workspace.membership_status !== "active";
                return (
                  <button
                    aria-current={selected ? "true" : undefined}
                    className={`workspace-menu-item ${selected ? "workspace-menu-item--active" : ""}`}
                    disabled={disabled || busy}
                    key={workspace.id}
                    onClick={() => {
                      setOpen(false);
                      onSelect(workspace);
                    }}
                    role="menuitem"
                    type="button"
                  >
                    <span>
                      <strong>{workspace.name}</strong>
                      <small>{workspace.environment} / {roleLabel(workspace.role)}</small>
                    </span>
                    {selected && <span className="workspace-menu-check" aria-label="Active">*</span>}
                    {disabled && <span className="workspace-menu-disabled">Disabled</span>}
                  </button>
                );
              })}
            </div>
          ))}
          {session.workspaces.length === 0 && <p className="workspace-menu-empty">No active workspaces are assigned to this session.</p>}
        </div>
      )}
    </div>
  );
}

interface NavigationRailProps {
  role: UserRole;
  activeSurface: SurfaceKey;
  onNavigate: (surface: SurfaceKey) => void;
}

export function NavigationRail({ role, activeSurface, onNavigate }: NavigationRailProps) {
  return (
    <nav className="sidebar-nav" aria-label="Product navigation">
      <p className="sidebar-nav-label">Operate</p>
      {SURFACE_ITEMS.map((item) => {
        const allowed = item.allowedRoles.includes(role);
        const active = item.key === activeSurface;
        return (
          <button
            aria-current={active ? "page" : undefined}
            aria-disabled={!allowed}
            className={`nav-item ${active ? "nav-item--active" : ""} ${!allowed ? "nav-item--locked" : ""}`}
            key={item.key}
            onClick={() => onNavigate(item.key)}
            type="button"
          >
            <span className="nav-item-index" aria-hidden="true">{item.icon}</span>
            <span className="nav-item-copy">
              <strong>{item.title}</strong>
              <small>{item.kicker}</small>
            </span>
            <span className="nav-item-state" aria-hidden="true">{!allowed ? "LOCK" : item.live ? "" : "SOON"}</span>
          </button>
        );
      })}
    </nav>
  );
}

interface AppSidebarProps {
  session: SessionContext;
  activeWorkspace: WorkspaceContext;
  activeSurface: SurfaceKey;
  onNavigate: (surface: SurfaceKey) => void;
  onWorkspaceSelect: (workspace: WorkspaceContext) => void;
  children?: ReactNode;
  busy?: boolean;
}

export function AppSidebar({ session, activeWorkspace, activeSurface, onNavigate, onWorkspaceSelect, children, busy }: AppSidebarProps) {
  return (
    <aside className="sidebar">
      <div className="chrome-top">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><span /><span /><span /></div>
          <div>
            <p className="eyebrow">Fieldnote</p>
            <p className="brand-title">Operations control</p>
          </div>
        </div>
        <div className={`auth-mode-chip ${session.auth_mode === "development" ? "auth-mode-chip--dev" : ""}`}>
          <span className="live-dot" />
          {session.auth_mode === "development" ? "Local dev auth" : "Provider session"}
        </div>
        <WorkspaceSwitcher activeWorkspace={activeWorkspace} busy={busy} onSelect={onWorkspaceSelect} session={session} />
        <NavigationRail activeSurface={activeSurface} onNavigate={onNavigate} role={activeWorkspace.role} />
      </div>
      {children}
      <div className="sidebar-footer">
        <div className="footer-rule" />
        <p>{activeWorkspace.mode === "handoff" ? "Customer operators own the next decision in this workspace." : "Your team operates this workspace for the customer."}</p>
        <span>{modeLabel(activeWorkspace.mode)} mode · {roleLabel(activeWorkspace.role)} access</span>
      </div>
    </aside>
  );
}

interface WorkspaceHeaderProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  authMode: AuthMode;
  eyebrow: string;
  title: string;
  modeBusy?: boolean;
  onModeChange: (mode: WorkspaceMode) => void;
  onSignOut: () => void;
}

export function WorkspaceHeader({ session, workspace, authMode, eyebrow, title, modeBusy = false, onModeChange, onSignOut }: WorkspaceHeaderProps) {
  const canChangeMode = can(workspace.role, "manage_members") || workspace.role === "operator";
  return (
    <header className="topbar product-topbar">
      <div className="topbar-heading">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <div className="context-trail"><span>{workspace.organization.name}</span><b>/</b><span>{workspace.name}</span><b>/</b><span>{workspace.environment}</span></div>
      </div>
      <div className="topbar-right">
        <div className="mode-control" aria-label="Workspace operating mode" role="group">
          <span>Mode</span>
          {(["delivery", "handoff"] as const).map((mode) => (
            <button
              aria-pressed={workspace.mode === mode}
              className={workspace.mode === mode ? "mode-option mode-option--active" : "mode-option"}
              disabled={!canChangeMode || modeBusy}
              key={mode}
              onClick={() => onModeChange(mode)}
              type="button"
            >
              {modeLabel(mode)}
            </button>
          ))}
        </div>
        <div className="api-indicator"><span className="live-dot" /> API connected</div>
        <div className="profile-chip">
          <div className="avatar" aria-hidden="true">{session.user.initials}</div>
          <div><strong>{session.user.display_name}</strong><small>{roleLabel(workspace.role)} · {authMode === "development" ? "local" : "managed"}</small></div>
        </div>
        <button className="signout-button" onClick={onSignOut} type="button">Sign out</button>
      </div>
    </header>
  );
}

export function AuthorizationDenied({ role, title = "This surface is outside your role" }: { role: UserRole; title?: string }) {
  return (
    <section className="access-state access-state--denied" role="alert">
      <span className="access-state-mark" aria-hidden="true">!</span>
      <p className="eyebrow">403 / authorization boundary</p>
      <h2>{title}</h2>
      <p>Your current role is <strong>{roleLabel(role)}</strong>. Ask a workspace owner or admin to grant the capability required for this surface. The client has not loaded data for this denied context.</p>
    </section>
  );
}

export function MemberDisabled({ email }: { email: string }) {
  return (
    <main className="boundary-screen">
      <section className="boundary-card boundary-card--blocked" role="alert">
        <span className="boundary-mark">!</span>
        <p className="eyebrow">Membership disabled</p>
        <h1>This account cannot enter the workspace.</h1>
        <p><strong>{email}</strong> is disabled. Ask an organization owner to restore access. Existing workspace data remains isolated from this session.</p>
      </section>
    </main>
  );
}
