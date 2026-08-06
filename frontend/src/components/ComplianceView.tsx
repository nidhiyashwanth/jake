"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiRequestError, api } from "@/lib/api";
import type {
  ChaseRecord,
  ComplianceDocumentTypeRecord,
  ComplianceRuleRecord,
  ConnectorRecord,
  ReasonCodeRecord,
  RequirementSetRecord,
  SessionContext,
  Vendor,
  WorkspaceContext,
} from "@/lib/types";

interface ComplianceViewProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : "The compliance request failed. Retry from the API boundary.";
}

function dateText(value?: string | null): string {
  if (!value) return "Not scheduled";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function isManager(role: WorkspaceContext["role"]): boolean {
  return role === "owner" || role === "admin" || role === "builder";
}

function canChase(role: WorkspaceContext["role"]): boolean {
  return role === "owner" || role === "admin" || role === "operator";
}

export default function ComplianceView({ session, workspace, onAuthFailure }: ComplianceViewProps) {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [connectors, setConnectors] = useState<ConnectorRecord[]>([]);
  const [documentTypes, setDocumentTypes] = useState<ComplianceDocumentTypeRecord[]>([]);
  const [rules, setRules] = useState<ComplianceRuleRecord[]>([]);
  const [reasonCodes, setReasonCodes] = useState<ReasonCodeRecord[]>([]);
  const [requirementSets, setRequirementSets] = useState<RequirementSetRecord[]>([]);
  const [selectedVendorId, setSelectedVendorId] = useState("");
  const [selectedSetId, setSelectedSetId] = useState("");
  const [chases, setChases] = useState<ChaseRecord[]>([]);
  const [newSetName, setNewSetName] = useState("Wedge Compliance v1");
  const [newSetVersion, setNewSetVersion] = useState("1");
  const [chaseDocType, setChaseDocType] = useState("ACORD_855");
  const [chaseRequirementId, setChaseRequirementId] = useState("");
  const [senderConnectorId, setSenderConnectorId] = useState("");
  const [touchBodies, setTouchBodies] = useState<Record<string, string>>({});
  const [approved, setApproved] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const manager = isManager(workspace.role);
  const chaseOperator = canChase(workspace.role);

  const activeSet = useMemo(
    () => requirementSets.find((item) => item.id === selectedSetId) || requirementSets.find((item) => item.status === "active") || null,
    [requirementSets, selectedSetId],
  );
  const emailConnectors = useMemo(() => connectors.filter((connector) => connector.kind === "email"), [connectors]);
  const selectedRequirements = useMemo(
    () => activeSet?.requirements.filter((requirement) => requirement.doc_type === chaseDocType) || [],
    [activeSet, chaseDocType],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [vendorResponse, connectorResponse, typeResponse, ruleResponse, reasonResponse, setResponse] = await Promise.all([
        api.listVendors(),
        api.listConnectors(),
        api.listComplianceDocumentTypes(),
        api.listComplianceRules(),
        api.listReasonCodes(),
        api.listRequirementSets(),
      ]);
      setVendors(vendorResponse.items);
      setConnectors(connectorResponse.items);
      setDocumentTypes(typeResponse.items);
      setRules(ruleResponse.items);
      setReasonCodes(reasonResponse.items);
      setRequirementSets(setResponse.items);
      setSelectedVendorId((current) => current && vendorResponse.items.some((item) => item.id === current) ? current : vendorResponse.items[0]?.id || "");
      setSelectedSetId((current) => current && setResponse.items.some((item) => item.id === current) ? current : setResponse.items.find((item) => item.status === "active")?.id || setResponse.items[0]?.id || "");
      setSenderConnectorId((current) => current && connectorResponse.items.some((item) => item.id === current) ? current : connectorResponse.items.find((item) => item.kind === "email")?.id || "");
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) onAuthFailure(loadError);
      else setError(errorText(loadError));
    } finally {
      setLoading(false);
    }
  }, [onAuthFailure]);

  const loadChases = useCallback(async () => {
    if (!selectedVendorId) {
      setChases([]);
      return;
    }
    try {
      const response = await api.listChases(selectedVendorId);
      setChases(response.items);
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) onAuthFailure(loadError);
      else setError(errorText(loadError));
    }
  }, [onAuthFailure, selectedVendorId]);

  useEffect(() => { void load(); }, [load, workspace.id]);
  useEffect(() => { void loadChases(); }, [loadChases]);

  useEffect(() => {
    const first = selectedRequirements[0]?.id || "";
    setChaseRequirementId((current) => current && selectedRequirements.some((item) => item.id === current) ? current : first);
  }, [selectedRequirements]);

  async function createSet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manager || !newSetName.trim()) return;
    setBusy("set");
    setError(null);
    try {
      await api.createRequirementSet({ name: newSetName.trim(), version: Number(newSetVersion) || 1, status: "active" });
      await load();
      setNotice("Published a new immutable requirement-set version with the seeded rule and reason-code library.");
    } catch (createError) { setError(errorText(createError)); } finally { setBusy(null); }
  }

  async function createChase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!chaseOperator || !selectedVendorId || !senderConnectorId || !chaseDocType) return;
    setBusy("chase");
    setError(null);
    try {
      await api.createChase(selectedVendorId, { requirement_id: chaseRequirementId || null, customer_sender_connector_id: senderConnectorId, expected_doc_type: chaseDocType, max_attempts: 4, max_messages_per_week: 3, touch_schedule_days: [0, 3, 7, 14] });
      await loadChases();
      setNotice("Chase thread created. The sender remains customer-owned and the workflow cannot negotiate coverage or approval.");
    } catch (createError) { setError(errorText(createError)); } finally { setBusy(null); }
  }

  async function sendTouch(chase: ChaseRecord) {
    const body = touchBodies[chase.id] || `Please send the requested ${chase.expected_doc_type} document for the open compliance requirement.`;
    setBusy(`touch-${chase.id}`);
    setError(null);
    try {
      await api.sendChaseTouch(chase.id, body, approved[chase.id] === true);
      await loadChases();
      setNotice("Sandbox touch recorded with a body hash only. No approval or coverage decision was sent.");
    } catch (sendError) { setError(errorText(sendError)); } finally { setBusy(null); }
  }

  if (loading) return <section className="compliance-surface"><div className="panel-empty"><span>…</span><strong>Loading policy boundary</strong><p>Reading live taxonomy, versioned rules, and chase state for this workspace.</p></div></section>;

  return (
    <section className="compliance-surface">
      <header className="compliance-hero">
        <div>
          <p className="eyebrow">P-01 / live policy boundary</p>
          <h2>Verify the whole vendor file, not just the certificate.</h2>
          <p>Versioned requirements, explainable exceptions, historical document supersession, and a bounded chase desk are all scoped to <strong>{workspace.name}</strong>.</p>
        </div>
        <div className="compliance-hero-meta"><strong>{rules.length}</strong><span>deterministic rules</span><b>·</b><strong>{documentTypes.length}</strong><span>document types</span></div>
      </header>

      {error && <div className="alert alert--error" role="alert"><strong>Boundary error.</strong> {error}</div>}
      {notice && <div className="alert alert--success" role="status"><strong>Recorded.</strong> {notice}</div>}

      <div className="compliance-grid">
        <section className="panel compliance-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Policy versions</p><h3>Requirement sets</h3></div><span className="panel-note">No code edit required</span></div>
          {manager && <form className="compliance-create-form" onSubmit={createSet}>
            <label>New version<input onChange={(event) => setNewSetName(event.target.value)} placeholder="Wedge Compliance v1" value={newSetName} /></label>
            <label>Version<input min="1" onChange={(event) => setNewSetVersion(event.target.value)} type="number" value={newSetVersion} /></label>
            <button className="button button--dark" disabled={busy === "set"} type="submit">{busy === "set" ? "Publishing…" : "Publish rules"}</button>
          </form>}
          <div className="compliance-set-list">
            {requirementSets.length === 0 ? <div className="panel-empty"><span>+</span><strong>No requirement set yet.</strong><p>Publish the wedge template to activate deterministic policy checks.</p></div> : requirementSets.map((item) => <button className={`compliance-set-row ${item.id === activeSet?.id ? "compliance-set-row--active" : ""}`} key={item.id} onClick={() => setSelectedSetId(item.id)} type="button"><span className="compliance-set-mark">v{item.version}</span><span><strong>{item.name}</strong><small>{item.status} · {item.requirements.length} rules</small></span><b>{item.id === activeSet?.id ? "Active" : "Inspect"}</b></button>)}
          </div>
        </section>

        <section className="panel compliance-panel">
          <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Explainable exceptions</p><h3>Rule library</h3></div><span className="panel-note">{reasonCodes.length} reason codes</span></div>
          <div className="compliance-rule-list">{rules.map((rule) => <article className="compliance-rule" key={rule.key}><div><strong>{rule.key}</strong><small>{rule.doc_type} · {rule.reason_code}</small></div><p>{rule.statement}</p></article>)}</div>
        </section>
      </div>

      <section className="panel compliance-panel">
        <div className="panel-heading panel-heading--compact"><div><p className="eyebrow">Customer-owned outreach</p><h3>Bounded chase threads</h3></div><span className="panel-note">CC owner on escalation · weekly cap enforced</span></div>
        <form className="compliance-chase-form" onSubmit={createChase}>
          <label>Vendor<select disabled={!chaseOperator} onChange={(event) => setSelectedVendorId(event.target.value)} value={selectedVendorId}><option value="">Choose a vendor</option>{vendors.map((vendor) => <option key={vendor.id} value={vendor.id}>{vendor.legal_name}</option>)}</select></label>
          <label>Document<select disabled={!chaseOperator} onChange={(event) => setChaseDocType(event.target.value)} value={chaseDocType}>{documentTypes.map((type) => <option key={type.key} value={type.key}>{type.label}</option>)}</select></label>
          <label>Requirement<select disabled={!chaseOperator || selectedRequirements.length === 0} onChange={(event) => setChaseRequirementId(event.target.value)} value={chaseRequirementId}><option value="">No specific rule</option>{selectedRequirements.map((requirement) => <option key={requirement.id} value={requirement.id}>{requirement.key}</option>)}</select></label>
          <label>Sender<select disabled={!chaseOperator} onChange={(event) => setSenderConnectorId(event.target.value)} value={senderConnectorId}><option value="">Choose customer sender</option>{emailConnectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.name} · {connector.status}</option>)}</select></label>
          <button className="button button--primary" disabled={!chaseOperator || busy === "chase" || !selectedVendorId || !senderConnectorId} type="submit">{busy === "chase" ? "Opening…" : "Open chase"}</button>
        </form>
        <div className="compliance-chase-list">
          {chases.length === 0 ? <div className="panel-empty"><span>↗</span><strong>No chase threads for this vendor.</strong><p>Open a bounded request only when a specific document requirement needs follow-up.</p></div> : chases.map((chase) => <article className="compliance-chase-card" key={chase.id}><div className="compliance-chase-card-top"><div><strong>{chase.expected_doc_type}</strong><small>{chase.status} · {chase.attempts}/{chase.max_attempts} touches · next {dateText(chase.next_action_at)}</small></div><span className={`compliance-status compliance-status--${chase.status === "compliant_and_verified" ? "good" : chase.status === "escalated" ? "warn" : "quiet"}`}>{chase.status.replaceAll("_", " ")}</span></div><p>Every send uses the customer-owned connector. Messages never state approval or negotiate coverage.</p>{chase.status !== "compliant_and_verified" && chase.status !== "closed" && chaseOperator && <div className="compliance-touch-controls"><input aria-label={`Chase message for ${chase.expected_doc_type}`} onChange={(event) => setTouchBodies((current) => ({ ...current, [chase.id]: event.target.value }))} placeholder={`Request the ${chase.expected_doc_type} document`} value={touchBodies[chase.id] || ""} /><label className="compliance-approval"><input checked={approved[chase.id] === true} onChange={(event) => setApproved((current) => ({ ...current, [chase.id]: event.target.checked }))} type="checkbox" /> I approve this sandbox send</label><button className="button button--quiet" disabled={busy === `touch-${chase.id}`} onClick={() => void sendTouch(chase)} type="button">{busy === `touch-${chase.id}` ? "Sending…" : "Send sandbox touch"}</button></div>}<div className="compliance-event-list">{chase.events.map((event) => <div className="compliance-event" key={event.id}><span>{event.event_type}</span><p>{event.summary}</p><small>{dateText(event.occurred_at)}</small></div>)}</div></article>)}
        </div>
      </section>

      <footer className="compliance-footer"><span>Workspace scoped · {session.user.email}</span><span>Document bodies and chase bodies stay behind their evidence boundaries.</span></footer>
    </section>
  );
}
