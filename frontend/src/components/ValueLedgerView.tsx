"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiRequestError, api } from "@/lib/api";
import type { SessionContext, ValueDrilldownResponse, ValueEventRecord, ValueRollup, WorkspaceContext } from "@/lib/types";

interface ValueLedgerViewProps {
  session: SessionContext;
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
}

function errorText(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : "The value ledger could not be loaded.";
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
}

function number(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function canExport(role: WorkspaceContext["role"]): boolean {
  return role === "owner" || role === "admin" || role === "auditor";
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function ValueLedgerView({ session, workspace, onAuthFailure }: ValueLedgerViewProps) {
  const [rollup, setRollup] = useState<ValueRollup | null>(null);
  const [events, setEvents] = useState<ValueEventRecord[]>([]);
  const [drilldown, setDrilldown] = useState<ValueDrilldownResponse | null>(null);
  const [metric, setMetric] = useState("net_dollars");
  const [implementationCost, setImplementationCost] = useState("0");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cost = Math.max(0, Number(implementationCost) || 0);
      const [nextRollup, nextEvents] = await Promise.all([
        api.getValueRollup({ implementationCostUsd: cost }),
        api.listValueEvents({ limit: 12 }),
      ]);
      setRollup(nextRollup);
      setEvents(nextEvents.items);
    } catch (loadError) {
      if (loadError instanceof ApiRequestError && loadError.status === 401) onAuthFailure(loadError);
      else setError(errorText(loadError));
    } finally {
      setLoading(false);
    }
  }, [implementationCost, onAuthFailure, workspace.id]);

  useEffect(() => { void load(); }, [load]);

  async function openDrilldown(nextMetric: string) {
    setMetric(nextMetric);
    setBusy(`drilldown:${nextMetric}`);
    setError(null);
    try {
      setDrilldown(await api.getValueDrilldown(nextMetric));
    } catch (loadError) {
      setError(errorText(loadError));
    } finally {
      setBusy(null);
    }
  }

  async function exportPack(format: "csv" | "pdf") {
    if (!canExport(workspace.role)) return;
    setBusy(`export:${format}`);
    setError(null);
    try {
      const cost = Math.max(0, Number(implementationCost) || 0);
      const blob = format === "csv" ? await api.exportValueCsv({ implementationCostUsd: cost }) : await api.exportValuePdf({ implementationCostUsd: cost });
      download(blob, `value-realization.${format}`);
      setNotice(`${format.toUpperCase()} value pack exported with the current reconciliation evidence.`);
    } catch (exportError) {
      setError(errorText(exportError));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <section className="value-surface"><div className="panel-empty"><span>...</span><strong>Loading value evidence</strong><p>Reading immutable events, signed baseline references, and reconciliation status.</p></div></section>;
  }

  const reconciliation = rollup?.reconciliation;
  const value = rollup?.value;
  const volume = rollup?.volume;
  return (
    <section className="value-surface">
      <header className="value-hero">
        <div>
          <p className="eyebrow">L-01 / value realization</p>
          <h2>Show the work behind the savings.</h2>
          <p>Every number stays tied to an execution, an immutable workflow version, a signed baseline when available, and the method that produced it.</p>
        </div>
        <div className="value-hero-meta"><strong>{number(volume?.ingested, 0)}</strong><span>units traced</span><b>/</b><strong>{number(value?.hours_saved, 1)}</strong><span>hours saved</span></div>
      </header>

      {error && <div className="alert alert--error" role="alert"><strong>Ledger boundary.</strong> {error}</div>}
      {notice && <div className="alert alert--success" role="status"><strong>Exported.</strong> {notice}</div>}

      <section className="value-toolbar panel">
        <div><p className="eyebrow">Evidence scope</p><h3>Price the readout only when the inputs are known.</h3><p className="value-copy">Implementation cost is optional. It changes ROI and payback; it never changes the underlying event totals.</p></div>
        <label>Implementation cost (USD)<input aria-label="Implementation cost in USD" inputMode="decimal" value={implementationCost} onChange={(event) => setImplementationCost(event.target.value)} onBlur={() => void load()} /></label>
        <div className="value-actions"><button className="button button--primary" type="button" onClick={() => void load()} disabled={loading || Boolean(busy)}>Refresh evidence</button><button className="button" type="button" onClick={() => void exportPack("csv")} disabled={!canExport(workspace.role) || Boolean(busy)}>Export CSV</button><button className="button" type="button" onClick={() => void exportPack("pdf")} disabled={!canExport(workspace.role) || Boolean(busy)}>Export PDF</button></div>
      </section>

      <section className="value-metric-grid" aria-label="Value summary">
        <button className="value-metric value-metric--linked" type="button" onClick={() => void openDrilldown("volume")}><small>Volume processed</small><strong>{number(volume?.ingested, 0)}</strong><span>{number(volume?.straight_through_rate_pct, 1)}% straight-through</span></button>
        <button className="value-metric value-metric--linked" type="button" onClick={() => void openDrilldown("hours_saved")}><small>Hours saved</small><strong>{number(value?.hours_saved, 1)}</strong><span>baseline-rate evidence</span></button>
        <button className="value-metric value-metric--linked" type="button" onClick={() => void openDrilldown("net_dollars")}><small>Net dollars</small><strong>{money(value?.net_dollars_usd)}</strong><span>{money(value?.gross_benefits_usd)} gross benefit</span></button>
        <div className="value-metric"><small>Cost / completed unit</small><strong>{money(value?.cost_per_completed_unit_usd)}</strong><span>{money(value?.costs_usd)} measured costs</span></div>
        <div className="value-metric"><small>ROI</small><strong>{value?.roi_pct === null || value?.roi_pct === undefined ? "Unpriced" : `${number(value.roi_pct, 1)}%`}</strong><span>{value?.payback_date ? `Payback ${value.payback_date}` : "Add implementation cost to model payback"}</span></div>
        <button className="value-metric value-metric--linked" type="button" onClick={() => void openDrilldown("cycle_time")}><small>Cycle time reduction</small><strong>{number(rollup?.cycle_time.reduction_hours, 1)}h</strong><span>baseline {number(rollup?.cycle_time.baseline_hours, 1)}h</span></button>
      </section>

      <section className="value-grid">
        <article className="panel value-reconciliation"><div className="panel-heading"><div><p className="eyebrow">01 / Reconciliation</p><h3>Nothing disappears between intake and outcome.</h3></div><span className={reconciliation?.reconciles ? "value-status value-status--ok" : "value-status value-status--bad"}>{reconciliation?.reconciles ? "PASS" : "CHECK"}</span></div><div className="value-reconcile-grid"><div><small>Ingested</small><strong>{number(reconciliation?.ingested, 0)}</strong></div><div><small>Auto</small><strong>{number(reconciliation?.auto, 0)}</strong></div><div><small>Reviewed</small><strong>{number(reconciliation?.reviewed, 0)}</strong></div><div><small>Halted</small><strong>{number(reconciliation?.halted, 0)}</strong></div></div><p className="value-boundary">Delta {number(reconciliation?.delta, 4)} · orphan events {number(reconciliation?.orphan_events, 0)} · formula {rollup?.formula_version}</p></article>
        <article className="panel"><div className="panel-heading"><div><p className="eyebrow">02 / Adoption</p><h3>Who is using the system?</h3></div></div>{rollup?.adoption.length ? <div className="value-adoption-list">{rollup.adoption.map((item) => <div className="value-adoption-row" key={`${item.actor_id}:${item.department}`}><div><strong>{item.actor_id}</strong><small>{item.department}</small></div><b>{number(item.units, 0)} units</b></div>)}</div> : <div className="panel-empty panel-empty--compact"><span>⌁</span><p>Adoption appears after real executions are recorded.</p></div>}</article>
      </section>

      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">03 / Event evidence</p><h3>Recent immutable events</h3></div><span className="panel-note">{events.length} shown · {rollup?.event_count} total</span></div>{events.length ? <div className="value-event-list">{events.map((event) => <div className="value-event-row" key={event.id}><div><strong>{event.kind.replaceAll("_", " ")}</strong><small>{event.method} · {event.confidence} confidence · {new Date(event.computed_at).toLocaleString("en-IN")}</small></div><span className={event.dollar_value < 0 ? "value-number value-number--cost" : "value-number"}>{event.dollar_value ? money(event.dollar_value) : `${number(event.quantity, 2)} ${event.unit}`}</span><code>{event.execution_id || event.review_task_id || event.source_artifact_id}</code></div>)}</div> : <div className="panel-empty panel-empty--compact"><span>⌁</span><strong>No value events yet.</strong><p>Run a real execution or resolve a review correction; the ledger will not invent activity.</p></div>}</section>

      {drilldown && <section className="panel value-drilldown"><div className="panel-heading"><div><p className="eyebrow">04 / Drill-down · {metric}</p><h3>Source records for this number.</h3></div><button className="button" type="button" onClick={() => setDrilldown(null)}>Close</button></div>{busy === `drilldown:${metric}` ? <p className="value-copy">Loading linked records…</p> : drilldown.items.length ? <div className="value-event-list">{drilldown.items.map((event) => <div className="value-event-row" key={event.id}><div><strong>{event.kind.replaceAll("_", " ")}</strong><small>{event.links.execution || event.links.review || event.links.event}</small></div><span className={event.dollar_value < 0 ? "value-number value-number--cost" : "value-number"}>{money(event.dollar_value)}</span><code>{event.baseline_hash || "no signed baseline hash"}</code></div>)}</div> : <div className="panel-empty panel-empty--compact"><span>⌁</span><p>No source events match this metric.</p></div>}</section>}

      <footer className="value-footer"><span>Signed baseline: {rollup?.baseline.hash ? `${rollup.baseline.hash.slice(0, 16)}…` : "not attached"}</span><span>Read-only evidence surface · {session.user.email}</span></footer>
    </section>
  );
}
