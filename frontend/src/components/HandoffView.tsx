"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiRequestError } from "@/lib/api";
import type { ReviewTask, UserRole, Vendor, WorkspaceContext } from "@/lib/types";
import { can, modeLabel, roleLabel } from "@/lib/tenancy";

interface HandoffViewProps {
  workspace: WorkspaceContext;
  onAuthFailure: (error: ApiRequestError) => void;
  onOpenReviewDesk: () => void;
}

function messageFor(error: unknown): string {
  if (error instanceof ApiRequestError) return `${error.message} (${error.code})`;
  if (error instanceof Error) return error.message;
  return "The handoff queue could not be loaded.";
}

function taskLabel(task: ReviewTask): string {
  return task.correction_field.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function HandoffView({ workspace, onAuthFailure, onOpenReviewDesk }: HandoffViewProps) {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [reviews, setReviews] = useState<ReviewTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const workspaceIdRef = useRef(workspace.id);

  const loadQueue = useCallback(async (requestedWorkspaceId: string) => {
    setLoading(true);
    setError(null);
    try {
      const [vendorResponse, reviewResponse] = await Promise.all([api.listVendors(), api.getReviews()]);
      if (workspaceIdRef.current !== requestedWorkspaceId) return;
      setVendors(vendorResponse.items);
      setReviews(reviewResponse.items.filter((review) => review.status === "open"));
    } catch (loadError) {
      if (workspaceIdRef.current !== requestedWorkspaceId) return;
      if (loadError instanceof ApiRequestError && [401, 403].includes(loadError.status)) {
        onAuthFailure(loadError);
      } else {
        setError(messageFor(loadError));
      }
    } finally {
      if (workspaceIdRef.current === requestedWorkspaceId) setLoading(false);
    }
  }, [onAuthFailure]);

  useEffect(() => {
    workspaceIdRef.current = workspace.id;
    setVendors([]);
    setReviews([]);
    setLoading(true);
    void loadQueue(workspace.id);
  }, [loadQueue, workspace.id]);

  const vendorNames = new Map(vendors.map((vendor) => [vendor.id, vendor.legal_name]));
  const canOperate = can(workspace.role, "operate_review_desk");

  return (
    <div className="handoff-surface">
      <section className="handoff-hero">
        <div>
          <p className="eyebrow">{modeLabel(workspace.mode)} / field path</p>
          <h2>Make the next decision easy to hand off.</h2>
          <p>This view keeps the customer or field operator on the smallest useful path: see the open exception, understand the evidence, then return a correction to the proof trail.</p>
        </div>
        <div className="handoff-hero-meta">
          <span className="handoff-mode-mark">{workspace.mode === "handoff" ? "HO" : "DE"}</span>
          <span><strong>{workspace.mode === "handoff" ? "Customer operated" : "Team operated"}</strong><small>{roleLabel(workspace.role)} access</small></span>
        </div>
      </section>

      <div className="handoff-grid">
        <section className="panel handoff-queue-panel" aria-labelledby="handoff-queue-title">
          <div className="panel-heading">
            <div><p className="eyebrow">01 / Open work</p><h3 id="handoff-queue-title">Correction queue</h3></div>
            <span className="count-badge count-badge--dark">{loading ? "--" : reviews.length.toString().padStart(2, "0")}</span>
          </div>
          {loading ? (
            <div className="handoff-loading" aria-label="Loading handoff queue"><span /><span /><span /></div>
          ) : error ? (
            <div className="handoff-error" role="alert"><strong>Queue unavailable.</strong><p>{error}</p><button className="button button--quiet" onClick={() => void loadQueue(workspace.id)} type="button">Try again</button></div>
          ) : reviews.length === 0 ? (
            <div className="panel-empty handoff-empty"><span aria-hidden="true">+</span><p>No open correction tasks in this workspace. A verification exception will appear here when the desk needs a human decision.</p></div>
          ) : (
            <div className="handoff-task-list">
              {reviews.map((review, index) => (
                <article className="handoff-task" key={review.id}>
                  <span className="handoff-task-number">{String(index + 1).padStart(2, "0")}</span>
                  <div className="handoff-task-copy">
                    <div className="handoff-task-kicker"><span>{review.reason_code}</span><span>{taskLabel(review)}</span></div>
                    <h4>{review.vendor_legal_name || vendorNames.get(review.vendor_id) || "Vendor record"}</h4>
                    <p>Confirm the observed {taskLabel(review).toLowerCase()} and send the correction back through the review desk.</p>
                  </div>
                  <button className="button button--quiet" onClick={onOpenReviewDesk} type="button">Open desk <span aria-hidden="true">-&gt;</span></button>
                </article>
              ))}
            </div>
          )}
        </section>

        <aside className="handoff-guide" aria-label="Operator guide">
          <section className="panel guide-panel">
            <p className="eyebrow">02 / Working agreement</p>
            <h3>One decision, one proof.</h3>
            <ol className="guide-list">
              <li><span>01</span><div><strong>Open the desk</strong><small>Start from the vendor and the exact exception.</small></div></li>
              <li><span>02</span><div><strong>Correct the observed field</strong><small>Use the source document, not an assumption.</small></div></li>
              <li><span>03</span><div><strong>Re-check</strong><small>The new result and reason enter the ledger together.</small></div></li>
            </ol>
          </section>
          <section className="handoff-scope-card">
            <div className="scope-card-top"><span className="live-dot" /><span>Workspace boundary</span></div>
            <strong>{workspace.name}</strong>
            <p>Queue data is requested with this workspace context. Switching context clears the desk selection before the next request begins.</p>
            {!canOperate && <span className="scope-readonly">Read-only role · corrections require an operator</span>}
          </section>
        </aside>
      </div>
    </div>
  );
}

export function surfaceRoleAllowed(role: UserRole): boolean {
  return can(role, "view_handoff");
}
