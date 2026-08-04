"""Deterministic, Postgres-backed execution runtime.

The service deliberately keeps orchestration in ordinary code. Provider calls and
connector writes are seams behind a durable step/outbox boundary; a model never
chooses the next node or performs a database write.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import DomainError
from app.models import (
    Execution,
    ExecutionEvent,
    ExecutionStep,
    ExternalWriteReceipt,
    OutboxEvent,
    Workflow,
    WorkflowNode,
    WorkflowVersion,
    new_id,
    utc_now,
)
from app.services.observability import emit_runtime_event, observability_status, redact_untrusted, trace_context
from app.services.value_ledger import ensure_execution_value_events


TERMINAL_EXECUTION_STATES = frozenset({"completed", "dead_letter", "failed", "halted", "replayed"})
TERMINAL_STEP_STATES = frozenset({"completed", "dead_letter", "failed", "skipped"})
CLAIMABLE_STEP_STATES = frozenset({"pending"})


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _short_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()[:2000]


def _config(node: WorkflowNode) -> dict[str, Any]:
    return node.config_json if isinstance(node.config_json, dict) else {}


def _version_or_404(db: Session, workspace_id: str, version_id: str) -> WorkflowVersion:
    version = db.scalar(
        select(WorkflowVersion)
        .options(selectinload(WorkflowVersion.nodes), selectinload(WorkflowVersion.edges))
        .where(WorkflowVersion.id == version_id, WorkflowVersion.workspace_id == workspace_id)
    )
    if version is None:
        raise DomainError("WORKFLOW_VERSION_NOT_FOUND", "The workflow version was not found", 404)
    return version


def _workflow_or_404(db: Session, workspace_id: str, workflow_id: str) -> Workflow:
    workflow = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id))
    if workflow is None:
        raise DomainError("WORKFLOW_NOT_FOUND", "The workflow was not found", 404)
    return workflow


def _event(
    db: Session,
    execution: Execution,
    event_type: str,
    *,
    step: ExecutionStep | None = None,
    payload: dict[str, Any] | None = None,
) -> ExecutionEvent:
    event_id = new_id()
    event_payload = redact_untrusted(payload or {})
    trace = trace_context(execution.correlation_id, event_id)
    if isinstance(event_payload, dict):
        event_payload = {**event_payload, "trace_id": trace["trace_id"], "span_id": trace["span_id"]}
    item = ExecutionEvent(
        id=event_id,
        workspace_id=execution.workspace_id,
        execution_id=execution.id,
        step_id=step.id if step else None,
        event_type=event_type,
        correlation_id=execution.correlation_id,
        payload_json=event_payload,
    )
    db.add(item)
    emit_runtime_event(event_type, correlation_id=execution.correlation_id, span_key=event_id, payload=event_payload)
    return item


def enqueue_outbox(
    db: Session,
    execution: Execution,
    event_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
    *,
    step: ExecutionStep | None = None,
) -> OutboxEvent:
    existing = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.workspace_id == execution.workspace_id,
            OutboxEvent.dedupe_key == dedupe_key,
        )
    )
    if existing is not None:
        return existing
    item = OutboxEvent(
        id=new_id(),
        workspace_id=execution.workspace_id,
        execution_id=execution.id,
        step_id=step.id if step else None,
        event_type=event_type,
        dedupe_key=dedupe_key,
        correlation_id=execution.correlation_id,
        payload_json=payload,
        status="pending",
        attempts=0,
        available_at=utc_now(),
    )
    db.add(item)
    return item


def _ordered_nodes(version: WorkflowVersion) -> list[WorkflowNode]:
    """Return the published graph in deterministic topological execution order.

    Workflow definitions are canonically stored with nodes sorted by key for
    stable hashing. That storage order is not the execution order: published
    edges own sequencing, while node key is only the deterministic tie-breaker
    for independent branches.
    """

    nodes = {node.node_key: node for node in version.nodes}
    outgoing: dict[str, list[str]] = {key: [] for key in nodes}
    indegree: dict[str, int] = {key: 0 for key in nodes}
    for edge in version.edges:
        source = edge.from_node
        target = edge.to_node
        if source not in nodes or target not in nodes:
            continue
        if target not in outgoing[source]:
            outgoing[source].append(target)
            indegree[target] += 1

    ready = sorted(
        (nodes[key] for key, degree in indegree.items() if degree == 0),
        key=lambda node: (node.sort_order, node.node_key),
    )
    ordered: list[WorkflowNode] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for target in sorted(outgoing[node.node_key]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(nodes[target])
                ready.sort(key=lambda item: (item.sort_order, item.node_key))

    # Published workflow validation rejects cycles. Keep a deterministic
    # fallback for defensive handling of legacy rows that predate that gate.
    if len(ordered) != len(nodes):
        return sorted(version.nodes, key=lambda node: (node.sort_order, node.node_key))
    return ordered


def create_execution(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    version_id: str,
    input_json: dict[str, Any],
    idempotency_key: str,
    correlation_id: str | None,
    max_retries: int,
    dry_run: bool = False,
    replay_of_id: str | None = None,
) -> tuple[Execution, bool]:
    version = _version_or_404(db, workspace_id, version_id)
    if version.status != "published" or not version.immutable_hash:
        raise DomainError(
            "WORKFLOW_VERSION_NOT_PUBLISHED",
            "Executions must pin an immutable published workflow version",
            409,
            details={"version_id": version.id, "status": version.status},
        )
    existing = db.scalar(
        select(Execution).where(
            Execution.workspace_id == workspace_id,
            Execution.idempotency_key == idempotency_key,
        )
    )
    input_hash = _hash_json(input_json)
    if existing is not None:
        if existing.workflow_version_id != version.id or _hash_json(existing.input_json) != input_hash:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key is already bound to a different execution request",
                409,
                details={"idempotency_key": idempotency_key},
            )
        return existing, False

    now = utc_now()
    execution = Execution(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_id=version.workflow_id,
        workflow_version_id=version.id,
        workflow_version_hash=version.immutable_hash,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id or f"corr-{uuid4().hex}",
        status="queued",
        input_json=input_json,
        retry_count=0,
        max_retries=max_retries,
        dry_run=dry_run,
        replay_of_id=replay_of_id,
        created_by=actor_id,
        queued_at=now,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(execution)
    db.flush()

    nodes = _ordered_nodes(version)
    if not nodes:
        raise DomainError("WORKFLOW_HAS_NO_NODES", "The published workflow has no executable nodes", 409)
    for sequence, node in enumerate(nodes):
        config = _config(node)
        step_key = None
        if node.node_type == "tool" and bool(config.get("writes_external", config.get("write", False))):
            raw_key = _short_text(config.get("idempotency_key"))
            if raw_key:
                resolved_key = raw_key.replace("{execution_id}", execution.id)
                step_key = resolved_key if resolved_key != raw_key else f"{execution.id}:{raw_key}"
            else:
                step_key = f"{execution.id}:{node.node_key}:{version.immutable_hash}"
        db.add(
            ExecutionStep(
                id=new_id(),
                workspace_id=workspace_id,
                execution_id=execution.id,
                workflow_version_id=version.id,
                node_key=node.node_key,
                node_type=node.node_type,
                sequence=sequence,
                status="pending",
                attempt=0,
                input_json=input_json if sequence == 0 else None,
                provider=_short_text(config.get("provider")) or None,
                model_ref=_short_text(config.get("model_ref", config.get("model_config_key"))) or None,
                prompt_ref=_short_text(config.get("prompt_ref", config.get("prompt_key"))) or None,
                prompt_version=int(config["prompt_version"]) if str(config.get("prompt_version", "")).isdigit() else None,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0,
                idempotency_key=step_key,
                correlation_id=execution.correlation_id,
                available_at=now,
                compensation_json=config.get("compensation") if isinstance(config.get("compensation"), dict) else None,
                created_at=now,
                updated_at=now,
            )
        )
    db.flush()
    enqueue_outbox(
        db,
        execution,
        "execution.created",
        f"execution:{execution.id}:created",
        {
            "execution_id": execution.id,
            "workflow_version_id": version.id,
            "workflow_version_hash": version.immutable_hash,
            "dry_run": dry_run,
        },
    )
    _event(db, execution, "execution.queued", payload={"workflow_version_hash": version.immutable_hash, "dry_run": dry_run})
    return execution, True


def _step_context(db: Session, execution: Execution, step: ExecutionStep) -> dict[str, Any]:
    prior = db.scalars(
        select(ExecutionStep).where(
            ExecutionStep.execution_id == execution.id,
            ExecutionStep.sequence < step.sequence,
        ).order_by(ExecutionStep.sequence)
    ).all()
    return {
        "execution_input": execution.input_json,
        "prior_outputs": {item.node_key: item.output_json for item in prior if item.output_json is not None},
        "correlation_id": execution.correlation_id,
    }


def _claim_next_step(db: Session, execution: Execution, worker_id: str) -> ExecutionStep | None:
    now = utc_now()
    candidates = db.scalars(
        select(ExecutionStep)
        .where(
            ExecutionStep.workspace_id == execution.workspace_id,
            ExecutionStep.execution_id == execution.id,
            ExecutionStep.status.in_(CLAIMABLE_STEP_STATES),
            ExecutionStep.available_at <= now,
        )
        .order_by(ExecutionStep.sequence)
        .with_for_update(skip_locked=True)
    ).all()
    for step in candidates:
        prior_pending = db.scalar(
            select(ExecutionStep.id).where(
                ExecutionStep.execution_id == execution.id,
                ExecutionStep.sequence < step.sequence,
                ExecutionStep.status.not_in(("completed", "skipped")),
            )
        )
        if prior_pending is not None:
            continue
        step.status = "claimed"
        step.claimed_by = worker_id
        step.claimed_at = now
        step.started_at = step.started_at or now
        execution.status = "running"
        execution.started_at = execution.started_at or now
        db.flush()
        return step
    return None


def _node_for_step(db: Session, step: ExecutionStep) -> WorkflowNode:
    node = db.scalar(
        select(WorkflowNode).where(
            WorkflowNode.workflow_version_id == step.workflow_version_id,
            WorkflowNode.node_key == step.node_key,
            WorkflowNode.workspace_id == step.workspace_id,
        )
    )
    if node is None:
        raise DomainError("WORKFLOW_NODE_NOT_FOUND", "The pinned workflow node was not found", 500)
    return node


def _estimate_tokens(value: Any) -> int:
    return max(1, len(_canonical(value)) // 4)


def _external_write(
    db: Session,
    execution: Execution,
    step: ExecutionStep,
    node_config: dict[str, Any],
    output: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    key = step.idempotency_key or f"{execution.id}:{step.node_key}:{execution.workflow_version_hash}"
    connector = _short_text(node_config.get("connector_key", "bounded.connector"), "bounded.connector")
    payload_hash = _hash_json(output)
    existing = db.scalar(
        select(ExternalWriteReceipt).where(
            ExternalWriteReceipt.workspace_id == execution.workspace_id,
            ExternalWriteReceipt.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise DomainError("IDEMPOTENCY_PAYLOAD_CONFLICT", "A connector write key was reused with different content", 409)
        return {**existing.response_json, "duplicate_delivery": True}, True
    response = {
        "connector_key": connector,
        "accepted": True,
        "write_id": f"write-{hashlib.sha256(key.encode()).hexdigest()[:16]}",
        "idempotency_key": key,
        "payload_hash": payload_hash,
        "duplicate_delivery": False,
    }
    db.add(
        ExternalWriteReceipt(
            id=new_id(),
            workspace_id=execution.workspace_id,
            execution_id=execution.id,
            step_id=step.id,
            idempotency_key=key,
            connector_key=connector,
            payload_hash=payload_hash,
            response_json=response,
            created_at=utc_now(),
        )
    )
    return response, False


def _advance_one(db: Session, execution: Execution, worker_id: str) -> ExecutionStep | None:
    step = _claim_next_step(db, execution, worker_id)
    if step is None:
        return None
    node = _node_for_step(db, step)
    config = _config(node)
    started = time.perf_counter()
    context = _step_context(db, execution, step)
    step.input_json = context
    step.attempt += 1
    step.status = "running"
    db.flush()

    fail_until = config.get("fail_until_attempts", 0)
    try:
        fail_count = int(fail_until) if str(fail_until).strip() else 0
    except (TypeError, ValueError):
        fail_count = 0
    if fail_count >= step.attempt:
        error = {"code": "TRANSIENT_PROVIDER_ERROR", "message": "The bounded node provider requested a retry", "attempt": step.attempt}
        step.error_json = error
        if step.attempt > execution.max_retries:
            step.status = "dead_letter"
            execution.status = "dead_letter"
            execution.error_json = error
            execution.completed_at = utc_now()
            _event(db, execution, "execution.dead_letter", step=step, payload=error)
        else:
            delay = min(60, 2 ** max(0, step.attempt - 1))
            step.status = "pending"
            step.available_at = utc_now() + timedelta(seconds=delay)
            execution.retry_count += 1
            execution.next_attempt_at = step.available_at
            _event(db, execution, "step.retry_scheduled", step=step, payload={**error, "delay_seconds": delay})
            enqueue_outbox(
                db,
                execution,
                "execution.retry_scheduled",
                f"execution:{execution.id}:step:{step.id}:attempt:{step.attempt}",
                {"step_id": step.id, "attempt": step.attempt, "available_at": step.available_at.isoformat()},
                step=step,
            )
        step.latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        db.flush()
        return step

    if node.node_type == "approve" or bool(config.get("wait_for_human", config.get("requires_approval", False))):
        step.status = "waiting_human"
        step.wait_reason = _short_text(config.get("reason"), "Human approval is required before continuing")
        execution.status = "waiting_human"
        _event(db, execution, "execution.waiting_human", step=step, payload={"reason": step.wait_reason})
    elif node.node_type == "halt":
        step.status = "completed"
        step.output_json = {"halted": True, "reason": _short_text(config.get("reason"), "Workflow halted")}
        execution.status = "halted"
        execution.output_json = step.output_json
        execution.completed_at = utc_now()
        _event(db, execution, "execution.halted", step=step, payload=step.output_json)
    else:
        output: dict[str, Any] = {
            "node_key": step.node_key,
            "node_type": step.node_type,
            "mode": "dry_run" if execution.dry_run else "bounded_provider",
            "input": context,
        }
        if node.node_type == "llm":
            output["structured_output"] = config.get("output_schema", {})
            output["model_ref"] = step.model_ref
            output["prompt_ref"] = step.prompt_ref
            if isinstance(config.get("citations"), list):
                output["citations"] = redact_untrusted(config["citations"])
        if node.node_type == "rule":
            output["rule_result"] = bool(config.get("result", True))
        if node.node_type == "score":
            output["score"] = float(config.get("score", 1.0))
        if node.node_type == "tool" and bool(config.get("writes_external", config.get("write", False))):
            output["tool_call"] = {
                "tool_key": config.get("tool_key", config.get("connector_key", "bounded.connector")),
                "arguments": redact_untrusted(context),
                "side_effects": not execution.dry_run,
            }
            if execution.dry_run:
                output["external_write"] = "stubbed; no connector write performed"
                output["tool_call"]["response"] = "stubbed; no connector write performed"
            else:
                output["external_write"] = _external_write(db, execution, step, config, output)[0]
                output["tool_call"]["response"] = redact_untrusted(output["external_write"])
                enqueue_outbox(
                    db,
                    execution,
                    "external.write.accepted",
                    f"execution:{execution.id}:step:{step.id}:external-write",
                    {"step_id": step.id, "idempotency_key": step.idempotency_key, "payload_hash": _hash_json(output)},
                    step=step,
                )
        step.output_json = output
        step.input_tokens = _estimate_tokens(context) if node.node_type in {"llm", "extract", "classify"} else 0
        step.output_tokens = _estimate_tokens(output) if node.node_type in {"llm", "extract", "classify"} else 0
        step.cost_usd = round((step.input_tokens + step.output_tokens) * 0.000001, 8)
        step.status = "completed"
        step.completed_at = utc_now()
        _event(
            db,
            execution,
            "step.completed",
            step=step,
            payload={"node_key": step.node_key, "attempt": step.attempt, "cost_usd": step.cost_usd, "dry_run": execution.dry_run},
        )
        enqueue_outbox(
            db,
            execution,
            "execution.step.completed",
            f"execution:{execution.id}:step:{step.id}:completed",
            {"step_id": step.id, "node_key": step.node_key, "attempt": step.attempt, "dry_run": execution.dry_run},
            step=step,
        )

    step.latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    db.flush()
    _reconcile_execution(db, execution)
    return step


def _reconcile_execution(db: Session, execution: Execution) -> None:
    if execution.status in {"waiting_human", "halted", "dead_letter", "failed"}:
        if execution.status in TERMINAL_EXECUTION_STATES:
            ensure_execution_value_events(db, execution)
        return
    steps = db.scalars(select(ExecutionStep).where(ExecutionStep.execution_id == execution.id)).all()
    if steps and all(step.status in {"completed", "skipped"} for step in steps):
        execution.status = "completed"
        execution.completed_at = utc_now()
        execution.output_json = {"steps": {step.node_key: step.output_json for step in steps}}
        _event(db, execution, "execution.completed", payload={"step_count": len(steps), "dry_run": execution.dry_run})
        enqueue_outbox(
            db,
            execution,
            "execution.completed",
            f"execution:{execution.id}:completed",
            {"execution_id": execution.id, "dry_run": execution.dry_run},
        )
    elif any(step.status == "waiting_human" for step in steps):
        execution.status = "waiting_human"
    elif any(step.status == "dead_letter" for step in steps):
        execution.status = "dead_letter"
    else:
        execution.status = "running"
    if execution.status in TERMINAL_EXECUTION_STATES:
        ensure_execution_value_events(db, execution)


def advance_execution(db: Session, execution: Execution, *, worker_id: str, max_steps: int = 1) -> list[ExecutionStep]:
    if execution.status in TERMINAL_EXECUTION_STATES:
        return []
    if execution.status == "waiting_human":
        return []
    steps: list[ExecutionStep] = []
    for _ in range(max_steps):
        step = _advance_one(db, execution, worker_id)
        if step is None:
            break
        steps.append(step)
        if execution.status in TERMINAL_EXECUTION_STATES or execution.status == "waiting_human":
            break
    _reconcile_execution(db, execution)
    return steps


def resume_execution(db: Session, execution: Execution, *, decision: str, output: dict[str, Any], note: str | None) -> ExecutionStep:
    if execution.status != "waiting_human":
        raise DomainError("EXECUTION_NOT_WAITING", "This execution is not waiting for a human decision", 409)
    step = db.scalar(
        select(ExecutionStep).where(
            ExecutionStep.execution_id == execution.id,
            ExecutionStep.status == "waiting_human",
        ).order_by(ExecutionStep.sequence)
    )
    if step is None:
        raise DomainError("WAITING_STEP_NOT_FOUND", "The waiting step could not be found", 409)
    resumed_output = {"decision": decision, **output}
    node = _node_for_step(db, step)
    config = _config(node)
    if step.node_type == "tool" and bool(config.get("writes_external", config.get("write", False))) and not execution.dry_run:
        write_result, _ = _external_write(db, execution, step, config, resumed_output)
        resumed_output["external_write"] = write_result
        enqueue_outbox(
            db,
            execution,
            "external.write.accepted",
            f"execution:{execution.id}:step:{step.id}:external-write",
            {"step_id": step.id, "idempotency_key": step.idempotency_key, "payload_hash": _hash_json(resumed_output)},
            step=step,
        )
    elif step.node_type == "tool" and bool(config.get("writes_external", config.get("write", False))):
        resumed_output["external_write"] = "stubbed; no connector write performed"
    step.status = "completed"
    step.output_json = resumed_output
    step.wait_reason = None
    step.completed_at = utc_now()
    execution.status = "running"
    execution.error_json = None
    _event(db, execution, "human.decision_recorded", step=step, payload={"decision": decision, "note": note})
    enqueue_outbox(
        db,
        execution,
        "execution.human_resumed",
        f"execution:{execution.id}:step:{step.id}:resumed:{step.attempt}",
        {"step_id": step.id, "decision": decision},
        step=step,
    )
    _reconcile_execution(db, execution)
    return step


def retry_execution(db: Session, execution: Execution, *, reason: str, step_id: str | None = None) -> ExecutionStep:
    if execution.status not in {"failed", "dead_letter", "waiting_human"}:
        raise DomainError("EXECUTION_NOT_RETRYABLE", "Only failed, dead-letter, or waiting executions can be retried", 409)
    query = select(ExecutionStep).where(ExecutionStep.execution_id == execution.id)
    if step_id:
        query = query.where(ExecutionStep.id == step_id)
    step = db.scalar(query.where(ExecutionStep.status.in_(("dead_letter", "failed", "waiting_human"))).order_by(ExecutionStep.sequence))
    if step is None:
        raise DomainError("RETRY_STEP_NOT_FOUND", "No retryable step was found", 409)
    step.status = "pending"
    step.available_at = utc_now()
    step.error_json = None
    step.wait_reason = None
    execution.status = "running"
    execution.error_json = None
    execution.completed_at = None
    _event(db, execution, "execution.manual_retry", step=step, payload={"reason": reason})
    enqueue_outbox(
        db,
        execution,
        "execution.manual_retry",
        f"execution:{execution.id}:step:{step.id}:manual-retry:{uuid4().hex}",
        {"step_id": step.id, "reason": reason},
        step=step,
    )
    return step


def replay_execution(
    db: Session,
    original: Execution,
    *,
    actor_id: str,
    idempotency_key: str | None,
    correlation_id: str | None,
    workflow_version_id: str | None = None,
) -> Execution:
    target_version = _version_or_404(db, original.workspace_id, workflow_version_id or original.workflow_version_id)
    if target_version.status != "published" or not target_version.immutable_hash:
        raise DomainError("REPLAY_VERSION_NOT_PUBLISHED", "Safe replay requires a published immutable workflow version", 409)
    if target_version.workflow_id != original.workflow_id:
        raise DomainError("REPLAY_WORKFLOW_MISMATCH", "Safe replay must stay within the original workflow family", 422)
    replay_key = f"replay:{idempotency_key}" if idempotency_key else f"replay:{original.id}:{uuid4().hex}"
    replay, _ = create_execution(
        db,
        workspace_id=original.workspace_id,
        actor_id=actor_id,
        version_id=target_version.id,
        input_json=original.input_json,
        idempotency_key=replay_key,
        correlation_id=correlation_id or f"replay-{uuid4().hex}",
        max_retries=original.max_retries,
        dry_run=True,
        replay_of_id=original.id,
    )
    for _ in range(100):
        before = db.scalar(
            select(func.count(ExecutionStep.id)).where(
                ExecutionStep.execution_id == replay.id,
                ExecutionStep.status == "completed",
            )
        ) or 0
        if replay.status in TERMINAL_EXECUTION_STATES or replay.status == "waiting_human":
            break
        advance_execution(db, replay, worker_id=f"replay-{actor_id}", max_steps=1)
        db.flush()
        after = db.scalar(
            select(func.count(ExecutionStep.id)).where(
                ExecutionStep.execution_id == replay.id,
                ExecutionStep.status == "completed",
            )
        ) or 0
        if after == before and replay.status == "running":
            break
    replay.status = "replayed" if replay.status == "completed" else replay.status
    _event(
        db,
        replay,
        "execution.replay_completed",
        payload={
            "replay_of_id": original.id,
            "side_effects": False,
            "target_workflow_version_id": target_version.id,
            "target_workflow_version_hash": target_version.immutable_hash,
        },
    )
    return replay


def recover_stale_claims(db: Session, *, workspace_id: str, lease_seconds: int = 60) -> int:
    cutoff = utc_now() - timedelta(seconds=lease_seconds)
    steps = db.scalars(
        select(ExecutionStep).where(
            ExecutionStep.workspace_id == workspace_id,
            ExecutionStep.status.in_(("claimed", "running")),
            ExecutionStep.claimed_at < cutoff,
        ).with_for_update(skip_locked=True)
    ).all()
    for step in steps:
        step.status = "pending"
        step.claimed_by = None
        step.claimed_at = None
        step.available_at = utc_now()
        execution = db.get(Execution, step.execution_id)
        if execution and execution.status == "running":
            execution.status = "queued"
        if execution:
            _event(db, execution, "worker.claim_recovered", step=step, payload={"lease_seconds": lease_seconds})
    return len(steps)


def dispatch_outbox(db: Session, *, workspace_id: str, worker_id: str, limit: int = 20) -> list[OutboxEvent]:
    now = utc_now()
    events = db.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.workspace_id == workspace_id,
            OutboxEvent.status == "pending",
            OutboxEvent.available_at <= now,
        )
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for event in events:
        event.status = "claimed"
        event.claimed_by = worker_id
        event.claimed_at = now
        event.attempts += 1
        # The connector boundary is intentionally outside this runtime. The
        # delivered state is a durable handoff, not evidence that a third-party
        # API succeeded.
        event.status = "delivered"
        event.delivered_at = utc_now()
    return events


def execution_payload(db: Session, execution: Execution, *, include_events: bool = True) -> dict[str, Any]:
    steps = db.scalars(
        select(ExecutionStep).where(ExecutionStep.execution_id == execution.id).order_by(ExecutionStep.sequence)
    ).all()
    outbox = db.scalars(
        select(OutboxEvent).where(OutboxEvent.execution_id == execution.id).order_by(OutboxEvent.created_at)
    ).all()
    events = db.scalars(
        select(ExecutionEvent).where(ExecutionEvent.execution_id == execution.id).order_by(ExecutionEvent.occurred_at)
    ).all() if include_events else []
    receipts = db.scalars(
        select(ExternalWriteReceipt).where(ExternalWriteReceipt.execution_id == execution.id)
    ).all()
    execution_trace = trace_context(execution.correlation_id, execution.id)
    return {
        "id": execution.id,
        "workspace_id": execution.workspace_id,
        "workflow_id": execution.workflow_id,
        "workflow_version_id": execution.workflow_version_id,
        "workflow_version_hash": execution.workflow_version_hash,
        "idempotency_key": execution.idempotency_key,
        "correlation_id": execution.correlation_id,
        "status": execution.status,
        "input": redact_untrusted(execution.input_json),
        "output": redact_untrusted(execution.output_json),
        "error": redact_untrusted(execution.error_json),
        "retry_count": execution.retry_count,
        "max_retries": execution.max_retries,
        "dry_run": execution.dry_run,
        "replay_of_id": execution.replay_of_id,
        "created_by": execution.created_by,
        "queued_at": execution.queued_at.isoformat() if execution.queued_at else None,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "next_attempt_at": execution.next_attempt_at.isoformat() if execution.next_attempt_at else None,
        "trace": {**execution_trace, "observability": observability_status()},
        "redaction": {"applied": True, "policy_version": "redaction.v1"},
        "steps": [
            {
                "id": step.id,
                "node_key": step.node_key,
                "node_type": step.node_type,
                "sequence": step.sequence,
                "status": step.status,
                "attempt": step.attempt,
                "input": redact_untrusted(step.input_json),
                "output": redact_untrusted(step.output_json),
                "error": redact_untrusted(step.error_json),
                "provider": step.provider,
                "model_ref": step.model_ref,
                "prompt_ref": step.prompt_ref,
                "prompt_version": step.prompt_version,
                "input_tokens": step.input_tokens,
                "output_tokens": step.output_tokens,
                "cost_usd": step.cost_usd,
                "latency_ms": step.latency_ms,
                "idempotency_key": step.idempotency_key,
                "correlation_id": step.correlation_id,
                "wait_reason": step.wait_reason,
                "compensation": step.compensation_json,
                "trace_id": execution_trace["trace_id"],
                "span_id": trace_context(execution.correlation_id, step.id)["span_id"],
                "citations": redact_untrusted(step.output_json.get("citations", [])) if isinstance(step.output_json, dict) else [],
                "tool_call": redact_untrusted(step.output_json.get("tool_call")) if isinstance(step.output_json, dict) else None,
                "claimed_by": step.claimed_by,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "completed_at": step.completed_at.isoformat() if step.completed_at else None,
            }
            for step in steps
        ],
        "outbox": [
            {
                "id": item.id,
                "event_type": item.event_type,
                "dedupe_key": item.dedupe_key,
                "status": item.status,
                "attempts": item.attempts,
                "correlation_id": item.correlation_id,
                "created_at": item.created_at.isoformat(),
                "delivered_at": item.delivered_at.isoformat() if item.delivered_at else None,
            }
            for item in outbox
        ],
        "external_write_count": len(receipts),
        "events": [
            {
                "id": item.id,
                "type": item.event_type,
                "step_id": item.step_id,
                "correlation_id": item.correlation_id,
                "payload": redact_untrusted(item.payload_json),
                "occurred_at": item.occurred_at.isoformat(),
            }
            for item in events
        ],
    }
