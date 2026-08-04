"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { ApiRequestError, api } from "@/lib/api";
import type {
  AuditPackRecord,
  GovernanceArtifactRecord,
  GovernanceIncidentRecord,
  GovernanceModelRecord,
  GovernanceSummary,
  LegalHoldRecord,
  ModelChangeRecord,
  RetentionPolicyRecord,
  RetentionRunRecord,
  SessionContext,
  WorkspaceContext,
} from "@/lib/types";

interface GovernanceViewProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message + " (" + error.code + ")";
  return error instanceof Error ? error.message : "The governance control plane could not be loaded.";
}

function dateText(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function canManage(role: WorkspaceContext["role"]): boolean {
  return role === "owner" || role === "admin";
}

function canExport(role: WorkspaceContext["role"]): boolean {
  return canManage(role) || role === "auditor";
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function Metric({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return <div className="governance-metric"><small>{label}</small><strong>{value}</strong><span>{detail}</span></div>;
}

export default function GovernanceView({ session, workspace, onAuthFailure }: GovernanceViewProps) {
  const [summary, setSummary] = useState<GovernanceSummary | null>(null);
  const [artifacts, setArtifacts] = useState<GovernanceArtifactRecord[]>([]);
  const [policies, setPolicies] = useState<RetentionPolicyRecord[]>([]);
  const [holds, setHolds] = useState<LegalHoldRecord[]>([]);
  const [incidents, setIncidents] = useState<GovernanceIncidentRecord[]>([]);
  const [models, setModels] = useState<GovernanceModelRecord[]>([]);
  const [changes, setChanges] = useState<ModelChangeRecord[]>([]);
  const [packs, setPacks] = useState<AuditPackRecord[]>([]);
  const [retentionRun, setRetentionRun] = useState<RetentionRunRecord | null>(null);
  const [incidentSummary, setIncidentSummary] = useState("");
  const [incidentSeverity, setIncidentSeverity] = useState<"low" | "medium" | "high" | "critical">("medium");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextSummary, nextArtifacts, nextPolicies, nextHolds, nextIncidents, nextModels, nextPacks] = await Promise.all([
        api.getGovernanceSummary(),
        api.listGovernanceArtifacts(),
        api.listRetentionPolicies(),
        api.listLegalHolds(),
        api.listGovernanceIncidents(),
        api.listModelRegistry(),
        api.listAuditPacks(),
      ]);
      setSummary(nextSummary);
      setArtifacts(nextArtifacts.items);
      setPolicies(nextPolicies.items);
      setHolds(nextHolds.items);
      setIncidents(nextIncidents.items);
      setModels(nextModels.items);
      setChanges(nextModels.changes);
      setPacks(nextPacks.items);
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) onAuthFailure(loadError);
      else setError(errorText(loadError));
    } finally {
      setLoading(false);
    }
  }, [onAuthFailure, workspace.id]);

  useEffect(() => { void load(); }, [load]);

  async function runDryCheck() {
    setBusy("retention");
    setError(null);
    try {
      const run = await api.runRetention({ dry_run: true });
      setRetentionRun(run);
      setNotice("Retention dry-run scanned " + run.scanned_count + " artifact" + (run.scanned_count === 1 ? "" : "s") + " and found " + run.eligible_count + " eligible source" + (run.eligible_count === 1 ? "" : "s") + ".");
      await load();
    } catch (actionError) {
      setError(errorText(actionError));
    } finally {
      setBusy(null);
    }
  }

  async function generateAuditPack() {
    if (!canExport(workspace.role)) return;
    setBusy("pack");
    setError(null);
    try {
      const pack = await api.createAuditPack();
      setNotice("Audit pack generated with SHA-256 " + pack.sha256.slice(0, 16) + "…");
      await load();
    } catch (actionError) {
      setError(errorText(actionError));
    } finally {
      setBusy(null);
    }
  }

  async function downloadAuditPack() {
    if (!canExport(workspace.role) || !packs[0]) return;
    setBusy("download");
    setError(null);
    try {
      const blob = await api.downloadAuditPack(packs[0].id);
      download(blob, "audit-pack-" + packs[0].id + ".json");
      setNotice("Redacted audit pack downloaded. The export is recorded in the audit ledger.");
    } catch (actionError) {
      setError(errorText(actionError));
    } finally {
      setBusy(null);
    }
  }

  async function createIncident(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage(workspace.role) || !incidentSummary.trim()) return;
    setBusy("incident");
    setError(null);
    try {
      await api.createGovernanceIncident({ severity: incidentSeverity, summary: incidentSummary.trim(), customer_notification_status: "pending" });
      setIncidentSummary("");
      setNotice("Incident opened with a customer-notification checkpoint.");
      await load();
    } catch (actionError) {
      setError(errorText(actionError));
    } finally {
      setBusy(null);
    }
  }

  async function resolveIncident(incident: GovernanceIncidentRecord) {
    if (!canManage(workspace.role)) return;
    setBusy("resolve:" + incident.id);
    setError(null);
    try {
      await api.updateGovernanceIncident(incident.id, { status: "resolved" });
      setNotice("Incident marked resolved with a timestamped lifecycle event.");
      await load();
    } catch (actionError) {
      setError(errorText(actionError));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <section className="governance-surface"><div className="panel-empty"><span>...</span><strong>Loading governance evidence</strong><p>Reading access logs, privacy state, retention controls, incidents, and model history.</p></div></section>;
  }

  return (
    <section className="governance-surface">
      <header className="governance-hero">
        <div>
          <p className="eyebrow">G-01 / governance and privacy</p>
          <h2>Make every decision inspectable.</h2>
          <p>PII classification, source-retention controls, incident history, model change evidence, and dated audit packs live on the same workspace boundary as the product data.</p>
        </div>
        <div className="governance-hero-meta"><strong>{summary?.policy_version || "pii.v1"}</strong><span>control policy</span><b>/</b><strong>{summary?.audit_log_count ?? 0}</strong><span>audit events</span></div>
      </header>

      {error && <div className="alert alert--error" role="alert"><strong>Governance boundary.</strong> {error}</div>}
      {notice && <div className="alert alert--success" role="status"><strong>Recorded.</strong> {notice}</div>}

      <section className="governance-toolbar panel">
        <div><p className="eyebrow">Control room</p><h3>Evidence stays attributable and reversible.</h3><p className="governance-copy">Retention execution deletes source content only after policy due date and skips artifacts under an active legal hold. Derived fields, hashes, and audit evidence remain.</p></div>
        <div className="governance-actions"><button className="button button--primary" disabled={Boolean(busy)} onClick={() => void load()} type="button">Refresh controls</button><button className="button" disabled={Boolean(busy)} onClick={() => void runDryCheck()} type="button">Run retention dry-run</button><button className="button" disabled={!canExport(workspace.role) || Boolean(busy)} onClick={() => void generateAuditPack()} type="button">Generate audit pack</button><button className="button" disabled={!canExport(workspace.role) || !packs[0] || Boolean(busy)} onClick={() => void downloadAuditPack()} type="button">Download latest pack</button></div>
      </section>

      <section className="governance-metric-grid" aria-label="Governance summary">
        <Metric detail="classified source and derived records" label="Artifacts" value={summary?.artifact_count ?? 0} />
        <Metric detail="field paths flagged, values excluded from exports" label="PII detected" value={summary?.pii_detected_count ?? 0} />
        <Metric detail="active preservation controls" label="Legal holds" value={summary?.active_legal_hold_count ?? 0} />
        <Metric detail="unresolved customer-visible records" label="Open incidents" value={summary?.open_incident_count ?? 0} />
        <Metric detail="provider/model configurations" label="Registered models" value={summary?.model_count ?? 0} />
        <Metric detail="read, change, approval, and export trail" label="Access evidence" value={(summary?.data_access_log_count ?? 0) + (summary?.credential_access_log_count ?? 0)} />
      </section>

      <section className="governance-grid">
        <article className="panel"><div className="panel-heading"><div><p className="eyebrow">01 / Privacy ledger</p><h3>Artifacts and source state</h3></div><span className="panel-note">{artifacts.length} records</span></div>{artifacts.length ? <div className="governance-table">{artifacts.slice(0, 12).map((artifact) => <div className="governance-row" key={artifact.id}><div><strong>{artifact.artifact_type}</strong><small>{artifact.artifact_id} · {artifact.classification}</small></div><span className={"governance-pill governance-pill--" + artifact.pii_status}>{artifact.pii_status}</span><span>{artifact.source_deleted_at ? "Source deleted" : artifact.retention_until ? "Due " + dateText(artifact.retention_until) : "No policy due date"}</span></div>)}</div> : <div className="panel-empty panel-empty--compact"><span>◌</span><strong>No governed artifacts yet.</strong><p>Upload a source document and its PII classification will appear here without exposing raw values.</p></div>}</article>
        <article className="panel"><div className="panel-heading"><div><p className="eyebrow">02 / Retention</p><h3>Policy and preservation state</h3></div><span className="panel-note">{policies.length} versions</span></div>{policies.length ? <div className="governance-table">{policies.slice(0, 8).map((policy) => <div className="governance-row" key={policy.id}><div><strong>{policy.artifact_type}</strong><small>v{policy.version} · {policy.action}</small></div><span>{policy.retention_days} days</span><span className={policy.active ? "governance-state governance-state--active" : "governance-state"}>{policy.active ? "Active" : "Inactive"}</span></div>)}</div> : <div className="panel-empty panel-empty--compact"><span>◌</span><strong>No retention policy configured.</strong><p>Owners and admins can add a workspace policy before scheduling source deletion.</p></div>}{retentionRun && <p className="governance-boundary">Last dry-run: {retentionRun.eligible_count} eligible · {retentionRun.held_count} held · {retentionRun.scanned_count} scanned · active holds {holds.filter((hold) => hold.status === "active").length}.</p>}</article>
      </section>

      <section className="governance-grid">
        <article className="panel"><div className="panel-heading"><div><p className="eyebrow">03 / Incidents</p><h3>Own the failure narrative.</h3></div><span className="panel-note">{incidents.length} total</span></div>{canManage(workspace.role) && <form className="governance-incident-form" onSubmit={createIncident}><input aria-label="Incident summary" maxLength={10000} onChange={(event) => setIncidentSummary(event.target.value)} placeholder="What happened?" value={incidentSummary} /><select aria-label="Incident severity" onChange={(event) => setIncidentSeverity(event.target.value as typeof incidentSeverity)} value={incidentSeverity}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select><button className="button button--dark" disabled={Boolean(busy) || !incidentSummary.trim()} type="submit">Open incident</button></form>}{incidents.length ? <div className="governance-table">{incidents.slice(0, 10).map((incident) => <div className="governance-row governance-row--incident" key={incident.id}><div><strong>{incident.summary}</strong><small>{incident.severity} · {dateText(incident.detected_at)} · notify {incident.customer_notification_status}</small></div><span className={"governance-pill governance-pill--" + incident.status}>{incident.status}</span>{canManage(workspace.role) && incident.status !== "resolved" && <button className="button button--small" disabled={Boolean(busy)} onClick={() => void resolveIncident(incident)} type="button">Resolve</button>}</div>)}</div> : <div className="panel-empty panel-empty--compact"><span>✓</span><strong>No incidents recorded.</strong><p>That is a state to preserve, not a reason to hide the workflow.</p></div>}</article>
        <article className="panel"><div className="panel-heading"><div><p className="eyebrow">04 / Model registry</p><h3>Know what changed.</h3></div><span className="panel-note">{changes.length} changes</span></div>{models.length ? <div className="governance-table">{models.slice(0, 10).map((model) => <div className="governance-row" key={model.id}><div><strong>{model.key} v{model.version}</strong><small>{model.provider} / {model.model_id}</small></div><span className="governance-state governance-state--active">{model.training_policy}</span><span>{model.opt_in_reference || "No opt-in required"}</span></div>)}</div> : <div className="panel-empty panel-empty--compact"><span>◌</span><strong>No model configurations registered.</strong><p>Model changes appear here without storing prompt bodies or credentials in the registry.</p></div>}</article>
      </section>

      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">05 / Dated audit pack</p><h3>One redacted bundle for review.</h3></div><span className="panel-note">{packs.length} generated</span></div>{packs.length ? <div className="governance-pack-list">{packs.slice(0, 6).map((pack) => <div className="governance-pack-row" key={pack.id}><div><strong>{dateText(pack.generated_at)}</strong><small>{pack.schema_version} · {pack.redaction_policy_version}</small></div><code>{pack.sha256}</code><button className="button button--small" disabled={!canExport(workspace.role) || Boolean(busy)} onClick={() => void downloadAuditPack()} type="button">Download latest</button></div>)}</div> : <div className="panel-empty panel-empty--compact"><span>□</span><strong>No audit pack generated.</strong><p>Generate one when you need a dated view of production workflows, model changes, oversight, metrics, incidents, retention, and access evidence.</p></div>}</section>

      <footer className="governance-footer"><span>PII policy {summary?.policy_version || "pii.v1"} · append-only access evidence</span><span>Workspace {workspace.name} · {session.user.email}</span></footer>
    </section>
  );
}
