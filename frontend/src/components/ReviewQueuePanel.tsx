"use client";

import { useEffect, useMemo, useState } from "react";

import type { ReviewTask } from "@/lib/types";

interface ReviewQueuePanelProps {
  items: ReviewTask[];
  loading: boolean;
  selectedId: string | null;
  canOperate: boolean;
  currentUserId: string;
  error: string | null;
  onRefresh: () => void;
  onSelect: (task: ReviewTask) => void;
  onBulkAssign: (taskIds: string[]) => Promise<void>;
  onBulkEscalate: (taskIds: string[]) => Promise<void>;
}

function formatAge(value: string): string {
  const created = new Date(value).valueOf();
  if (Number.isNaN(created)) return "age unavailable";
  const minutes = Math.max(0, Math.round((Date.now() - created) / 60000));
  if (minutes < 60) return `${minutes}m old`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m old`;
}

function taskLabel(task: ReviewTask): string {
  return task.correction_field.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function ReviewQueuePanel({
  items,
  loading,
  selectedId,
  canOperate,
  currentUserId,
  error,
  onRefresh,
  onSelect,
  onBulkAssign,
  onBulkEscalate,
}: ReviewQueuePanelProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const allSelected = items.length > 0 && items.every((item) => selectedSet.has(item.id));

  useEffect(() => {
    function handleHelpShortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const editing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT" || target?.isContentEditable;
      if (editing || event.key !== "?") return;
      event.preventDefault();
      setShowHelp((value) => !value);
    }
    window.addEventListener("keydown", handleHelpShortcut);
    return () => window.removeEventListener("keydown", handleHelpShortcut);
  }, []);

  function toggle(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleAll() {
    setSelectedIds(allSelected ? [] : items.map((item) => item.id));
  }

  async function runBulk(action: "assign" | "escalate") {
    if (!selectedIds.length || !canOperate) return;
    setBusyAction(action);
    try {
      if (action === "assign") await onBulkAssign(selectedIds);
      else await onBulkEscalate(selectedIds);
      setSelectedIds([]);
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section className="review-queue-panel panel" aria-labelledby="review-queue-title">
      <div className="review-queue-header">
        <div>
          <p className="eyebrow">V-01 / Operator queue</p>
          <h2 id="review-queue-title">Review desk</h2>
          <p className="review-queue-subtitle">Prioritized exceptions with a source locator, owner, and clock.</p>
        </div>
        <div className="review-queue-header-actions">
          <span className="review-queue-formula">review.priority.v1</span>
          <button aria-label="Review desk keyboard help" className="button button--quiet" onClick={() => setShowHelp((value) => !value)} type="button">?</button>
          <button className="button button--quiet" disabled={loading} onClick={onRefresh} type="button">{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
      </div>
      {showHelp && <div className="review-keyboard-help" role="note"><strong>Keyboard</strong><span><kbd>Tab</kbd> move through queue</span><span><kbd>Enter</kbd> open selected task</span><span><kbd>E</kbd> focus correction</span><span><kbd>R</kbd> refresh queue</span><span><kbd>?</kbd> toggle this help</span></div>}
      {error && <div className="review-queue-error" role="alert">{error}</div>}
      <div className="review-queue-toolbar">
        <label className="review-select-all"><input aria-label="Select all visible review tasks" checked={allSelected} onChange={toggleAll} type="checkbox" /><span>Select visible</span></label>
        <span className="review-queue-count">{loading ? "Loading queue…" : `${items.length} open ${items.length === 1 ? "task" : "tasks"}`}</span>
        {selectedIds.length > 0 && <div className="review-bulk-actions"><span>{selectedIds.length} selected</span><button className="button button--quiet" disabled={!canOperate || busyAction !== null} onClick={() => void runBulk("assign")} type="button">{busyAction === "assign" ? "Assigning…" : "Assign to me"}</button><button className="button button--quiet" disabled={!canOperate || busyAction !== null} onClick={() => void runBulk("escalate")} type="button">{busyAction === "escalate" ? "Escalating…" : "Escalate"}</button></div>}
      </div>
      {loading ? (
        <div aria-label="Loading review queue" className="review-queue-loading"><span /><span /><span /></div>
      ) : items.length === 0 ? (
        <div className="review-queue-empty"><strong>No open review tasks.</strong><span>Verification exceptions will appear here with their evidence and SLA clock.</span></div>
      ) : (
        <div className="review-queue-list" role="list">
          {items.map((task, index) => (
            <div className={`review-queue-row ${selectedId === task.id ? "review-queue-row--selected" : ""}`} key={task.id} role="listitem">
              <input aria-label={`Select review task ${task.id}`} checked={selectedSet.has(task.id)} onChange={() => toggle(task.id)} type="checkbox" />
              <button className="review-queue-row-main" onClick={() => onSelect(task)} onKeyDown={(event) => { if (event.key === "Enter") onSelect(task); }} type="button">
                <span className={`review-priority review-priority--${task.priority_band || "normal"}`}>{String(task.priority_band || "normal")}</span>
                <span className="review-queue-order">{String(index + 1).padStart(2, "0")}</span>
                <span className="review-queue-row-copy"><strong>{task.vendor_legal_name || "Vendor record"}</strong><span>{taskLabel(task)} · {task.reason_code}</span><small>{task.document_filename || "Source document"} · {formatAge(task.created_at)}</small></span>
                <span className={`review-sla review-sla--${task.sla_state === "overdue" ? "overdue" : "ok"}`}>{task.sla_state === "overdue" ? "Overdue" : `${task.sla_minutes || 60}m SLA`}</span>
                <span className="review-queue-arrow" aria-hidden="true">→</span>
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="review-queue-footer"><span>Workspace scoped · {currentUserId ? "operator identity active" : "operator identity unavailable"}</span><span>Bulk cap: 25 tasks</span></div>
    </section>
  );
}
