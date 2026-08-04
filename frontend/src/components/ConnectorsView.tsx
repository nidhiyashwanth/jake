"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { ApiRequestError, api } from "@/lib/api";
import type { ConnectorCallRecord, ConnectorKind, ConnectorRecord, CredentialAccessLogRecord, McpServerRecord, SessionContext, WorkspaceContext } from "@/lib/types";

interface ConnectorsViewProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

const connectorKinds: ConnectorKind[] = ["email", "object_storage", "notify", "rest", "webhook", "sftp", "database", "csv_excel", "rpa"];

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : "The connector request failed. Retry from the server boundary.";
}

function formatDate(value?: string | null): string {
  if (!value) return "Not yet";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function statusClass(status: string): string {
  return status === "healthy" || status === "active" ? "connection-status connection-status--good" : status === "unhealthy" ? "connection-status connection-status--warn" : "connection-status";
}

export default function ConnectorsView({ session, workspace, onAuthFailure }: ConnectorsViewProps) {
  const [connectors, setConnectors] = useState<ConnectorRecord[]>([]);
  const [servers, setServers] = useState<McpServerRecord[]>([]);
  const [calls, setCalls] = useState<ConnectorCallRecord[]>([]);
  const [accessLog, setAccessLog] = useState<CredentialAccessLogRecord[]>([]);
  const [selectedConnectorId, setSelectedConnectorId] = useState("");
  const [selectedServerId, setSelectedServerId] = useState("");
  const [kind, setKind] = useState<ConnectorKind>("email");
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("sandbox://sandbox.local");
  const [credentialLabel, setCredentialLabel] = useState("Primary connector credential");
  const [credentialSecret, setCredentialSecret] = useState("");
  const [mcpName, setMcpName] = useState("");
  const [mcpTool, setMcpTool] = useState("search_single_contact");
  const [mcpScope, setMcpScope] = useState("");
  const [mcpCallArgs, setMcpCallArgs] = useState('{"query":"sandbox"}');
  const [valueAtRisk, setValueAtRisk] = useState("0");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const canManage = workspace.role === "owner" || workspace.role === "admin";
  const canReadAudit = canManage || workspace.role === "auditor";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [connectorResponse, serverResponse, callResponse, accessResponse] = await Promise.all([
        api.listConnectors(),
        api.listMcpServers(),
        api.listMcpCalls(),
        canReadAudit ? api.listCredentialAccessLog() : Promise.resolve({ items: [], count: 0 }),
      ]);
      setConnectors(connectorResponse.items);
      setServers(serverResponse.items);
      setCalls(callResponse.items);
      setAccessLog(accessResponse.items);
      setSelectedConnectorId((current) => current && connectorResponse.items.some((item) => item.id === current) ? current : connectorResponse.items[0]?.id ?? "");
      setSelectedServerId((current) => current && serverResponse.items.some((item) => item.id === current) ? current : serverResponse.items[0]?.id ?? "");
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) onAuthFailure(loadError);
      else setError(errorText(loadError));
    } finally {
      setLoading(false);
    }
  }, [canReadAudit, onAuthFailure]);

  useEffect(() => { void load(); }, [load, workspace.id]);

  async function handleCreateConnector(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || !name.trim()) return;
    setBusy("connector");
    setError(null);
    try {
      await api.createConnector({ name: name.trim(), kind, config: { endpoint: endpoint.trim() }, egress_hosts: [new URL(endpoint.trim()).hostname] });
      setName("");
      await load();
      setNotice("Connector configuration saved without accepting a raw secret.");
    } catch (createError) {
      setError(errorText(createError));
    } finally {
      setBusy(null);
    }
  }

  async function handleTestConnector() {
    if (!selectedConnectorId) return;
    setBusy("test");
    setError(null);
    try {
      const response = await api.testConnector(selectedConnectorId);
      setTestResult(response.healthy ? "Sandbox health check passed. No credential material was returned." : `Health check failed safely: ${response.failure?.code || "CONNECTOR_FAILED"}.`);
      await load();
    } catch (testError) {
      setError(errorText(testError));
    } finally {
      setBusy(null);
    }
  }

  async function handleSaveCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || !selectedConnectorId || !credentialSecret) return;
    setBusy("credential");
    setError(null);
    try {
      await api.createCredential(selectedConnectorId, { label: credentialLabel, secret: credentialSecret, secret_type: "oauth_refresh_token" });
      setCredentialSecret("");
      await load();
      setNotice("Credential encrypted in the workspace vault. Plaintext is never returned or logged.");
    } catch (credentialError) {
      setError(errorText(credentialError));
    } finally {
      setBusy(null);
    }
  }

  async function handleCreateServer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || !mcpName.trim() || !mcpTool.trim()) return;
    setBusy("server");
    setError(null);
    try {
      await api.createMcpServer({
        name: mcpName.trim(),
        url: "sandbox://mcp.local",
        server_version: "sandbox-1",
        metadata: { value_at_risk_limit: 100, tools: [{ name: mcpTool.trim(), read_only: true, description: "Untrusted sandbox tool metadata." }] },
        allowed_tools: [mcpTool.trim()],
        workflow_version_ids: mcpScope.trim() ? [mcpScope.trim()] : [],
        egress_hosts: ["mcp.local"],
      });
      setMcpName("");
      await load();
      setNotice("MCP server metadata pinned with an explicit tool and workflow allow-list.");
    } catch (serverError) {
      setError(errorText(serverError));
    } finally {
      setBusy(null);
    }
  }

  async function handleCallTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedServerId) return;
    setBusy("call");
    setError(null);
    try {
      const args = JSON.parse(mcpCallArgs) as Record<string, unknown>;
      const response = await api.callMcpTool(selectedServerId, { tool_name: mcpTool, arguments: args, workflow_version_id: mcpScope.trim() || undefined, value_at_risk: Number(valueAtRisk) || 0, approved, idempotency_key: `ui-${Date.now().toString(36)}` });
      setNotice(response.approval_required ? "The gateway recorded an approval-required call without executing it." : "MCP call completed through the sandbox gateway; output remains untrusted.");
      await load();
    } catch (callError) {
      setError(errorText(callError));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="connections-surface">
      <div className="connections-hero">
        <div><p className="eyebrow">C-01 / secure integrations</p><h1>Connect the work, keep the boundary.</h1><p>Workspace-scoped connectors, pinned MCP tools, and an envelope vault. Provider output is untrusted data; secrets never appear in this surface.</p></div>
        <div className="connections-hero-meta"><span className="live-dot" />{session.user.display_name}<span>·</span>{workspace.name}<span>·</span>{canManage ? "Administrator controls" : "Read-only inspection"}</div>
      </div>

      {error && <div className="alert alert--error" role="alert"><strong>Connector action paused.</strong> {error}<button onClick={() => setError(null)} type="button">Dismiss</button></div>}
      {notice && <div className="alert alert--success" role="status"><span>✓</span> {notice}<button onClick={() => setNotice(null)} type="button">Dismiss</button></div>}

      <div className="connections-grid">
        <section className="panel connections-panel">
          <div className="panel-heading"><div><p className="eyebrow">01 / Providers</p><h2>Connector registry</h2></div><span className="count-badge count-badge--dark">{connectors.length.toString().padStart(2, "0")}</span></div>
          {loading ? <div className="panel-empty"><span>◌</span><p>Loading workspace connectors…</p></div> : connectors.length === 0 ? <div className="panel-empty"><span>+</span><p>No connectors yet. Start with a sandbox adapter; production providers stay behind the same interface.</p></div> : <div className="connection-list">{connectors.map((connector) => <button className={`connection-row ${selectedConnectorId === connector.id ? "connection-row--active" : ""}`} key={connector.id} onClick={() => setSelectedConnectorId(connector.id)} type="button"><span className={statusClass(connector.status)}>{connector.status}</span><span><strong>{connector.name}</strong><small>{connector.kind} · {connector.credential_count} vault credential{connector.credential_count === 1 ? "" : "s"}</small></span><span className="row-arrow">→</span></button>)}</div>}
          <form className="connection-form" onSubmit={handleCreateConnector}>
            <label>New connector name<input disabled={!canManage} onChange={(event) => setName(event.target.value)} placeholder="Compliance inbox" value={name} /></label>
            <div className="connection-form-row"><label>Adapter<select disabled={!canManage} onChange={(event) => setKind(event.target.value as ConnectorKind)} value={kind}>{connectorKinds.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>Sandbox endpoint<input disabled={!canManage} onChange={(event) => setEndpoint(event.target.value)} value={endpoint} /></label></div>
            <button className="button button--primary" disabled={!canManage || busy !== null || !name.trim()} type="submit">{busy === "connector" ? "Saving…" : "Add connector"}</button>
          </form>
        </section>

        <section className="panel connections-panel">
          <div className="panel-heading"><div><p className="eyebrow">02 / Vault</p><h2>Credential boundary</h2></div><span className="panel-note">AES-GCM envelope</span></div>
          <p className="connections-copy">The API accepts a secret only at this boundary. It stores ciphertext under a per-workspace DEK wrapped by the deployment KMS seam, and exposes only key metadata afterward.</p>
          <form className="connection-form" onSubmit={handleSaveCredential}>
            <label>Target connector<select disabled={!canManage || !connectors.length} onChange={(event) => setSelectedConnectorId(event.target.value)} value={selectedConnectorId}>{connectors.length === 0 ? <option value="">Create a connector first</option> : connectors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label>Credential label<input disabled={!canManage} onChange={(event) => setCredentialLabel(event.target.value)} value={credentialLabel} /></label>
            <label>OAuth refresh secret<input autoComplete="new-password" disabled={!canManage} onChange={(event) => setCredentialSecret(event.target.value)} placeholder="Entered once; never rendered again" type="password" value={credentialSecret} /></label>
            <button className="button button--dark" disabled={!canManage || busy !== null || !selectedConnectorId || !credentialSecret} type="submit">{busy === "credential" ? "Encrypting…" : "Store encrypted credential"}</button>
          </form>
          {selectedConnectorId && <button className="button button--quiet connection-test-button" disabled={busy !== null} onClick={() => void handleTestConnector()} type="button">{busy === "test" ? "Testing…" : "Test selected connector"}</button>}
          {testResult && <div className="connection-result" role="status">{testResult}</div>}
        </section>

        <section className="panel connections-panel">
          <div className="panel-heading"><div><p className="eyebrow">03 / MCP gateway</p><h2>Pinned tool servers</h2></div><span className="panel-note">allow-list first</span></div>
          {servers.length === 0 ? <div className="panel-empty"><span>◌</span><p>No pinned MCP server metadata. Add a sandbox server to exercise the gateway contract.</p></div> : <div className="connection-list">{servers.map((server) => <button className={`connection-row ${selectedServerId === server.id ? "connection-row--active" : ""}`} key={server.id} onClick={() => { setSelectedServerId(server.id); setMcpTool(server.allowed_tools[0] || mcpTool); }} type="button"><span className={statusClass(server.status)}>{server.status}</span><span><strong>{server.name}</strong><small>v{server.server_version} · {server.allowed_tools.join(", ")}</small></span><span className="row-arrow">→</span></button>)}</div>}
          <form className="connection-form" onSubmit={handleCreateServer}>
            <label>Server name<input disabled={!canManage} onChange={(event) => setMcpName(event.target.value)} placeholder="Sandbox MCP" value={mcpName} /></label>
            <div className="connection-form-row"><label>Allowed tool<input disabled={!canManage} onChange={(event) => setMcpTool(event.target.value)} value={mcpTool} /></label><label>Workflow version scope<input disabled={!canManage} onChange={(event) => setMcpScope(event.target.value)} placeholder="Required for scoped calls" value={mcpScope} /></label></div>
            <button className="button button--primary" disabled={!canManage || busy !== null || !mcpName.trim() || !mcpTool.trim()} type="submit">{busy === "server" ? "Pinning…" : "Pin MCP server"}</button>
          </form>
        </section>

        <section className="panel connections-panel">
          <div className="panel-heading"><div><p className="eyebrow">04 / Call boundary</p><h2>Sandbox invocation</h2></div><span className="panel-note">untrusted output</span></div>
          <form className="connection-form" onSubmit={handleCallTool}>
            <label>Server<select disabled={!servers.length} onChange={(event) => setSelectedServerId(event.target.value)} value={selectedServerId}>{servers.length === 0 ? <option value="">Pin a server first</option> : servers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <div className="connection-form-row"><label>Value at risk<input min="0" onChange={(event) => setValueAtRisk(event.target.value)} type="number" value={valueAtRisk} /><small>Above the pinned limit, approval is required.</small></label><label className="connection-check"><input checked={approved} onChange={(event) => setApproved(event.target.checked)} type="checkbox" /> Approval recorded</label></div>
            <label>Arguments<textarea onChange={(event) => setMcpCallArgs(event.target.value)} value={mcpCallArgs} /></label>
            <button className="button button--dark" disabled={busy !== null || !selectedServerId} type="submit">{busy === "call" ? "Calling…" : "Call allow-listed tool"}</button>
          </form>
          {calls.length > 0 && <div className="call-list">{calls.slice(0, 5).map((call) => <div className="call-row" key={call.id}><span className={statusClass(call.status)}>{call.status}</span><div><strong>{call.tool_name}</strong><small>{call.result_untrusted ? "Untrusted result" : "Result"} · {formatDate(call.created_at)}</small></div><code>{call.failure_code || call.correlation_id}</code></div>)}</div>}
        </section>
      </div>

      {canReadAudit && <section className="panel credential-audit-panel"><div className="panel-heading"><div><p className="eyebrow">05 / Auditor view</p><h2>Credential access log</h2></div><span className="panel-note">No secret values</span></div>{accessLog.length === 0 ? <div className="panel-empty panel-empty--wide"><span>◌</span><p>No credential access events in this workspace.</p></div> : <div className="audit-table">{accessLog.slice(0, 12).map((event) => <div className="audit-table-row" key={event.id}><strong>{event.action}</strong><span>{event.purpose}</span><span>{event.outcome}</span><small>{formatDate(event.created_at)}</small></div>)}</div>}</section>}
    </section>
  );
}
