"""Discovery, baseline, and opportunity-scoring domain services.

The discovery surface deliberately stays deterministic in this first slice. SOP and
transcript text is treated as untrusted input and converted into an editable draft;
it never publishes a workflow or changes a signed baseline.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    Baseline,
    BaselineMetric,
    OpportunityScore,
    Process,
    ProcessInterview,
    ProcessStep,
    Membership,
    User,
    utc_now,
    new_id,
)
from app.services.audit import append_audit_log, append_data_access_log


FORMULA_VERSION = "opportunity.v1"

REQUIRED_BASELINE_METRICS = (
    "volume_per_month",
    "minutes_p50",
    "minutes_p90",
    "fully_loaded_cost_per_hour",
    "error_rate_pct",
    "cost_per_error",
    "rework_rate_pct",
    "cycle_time_hours",
    "headcount_touching",
    "peak_backlog",
    "chase_volume_per_month",
    "lapse_incidents_per_month",
    "audit_prep_hours_per_month",
)

METRIC_UNITS = {
    "volume_per_month": "instances/month",
    "minutes_p50": "minutes/instance",
    "minutes_p90": "minutes/instance",
    "fully_loaded_cost_per_hour": "currency/hour",
    "error_rate_pct": "percent",
    "cost_per_error": "currency/error",
    "rework_rate_pct": "percent",
    "exception_rate_pct": "percent",
    "cycle_time_hours": "hours/instance",
    "headcount_touching": "people",
    "peak_backlog": "instances",
    "chase_volume_per_month": "instances/month",
    "lapse_incidents_per_month": "incidents/month",
    "audit_prep_hours_per_month": "hours/month",
    "structure_score": "ratio",
    "rule_clarity_score": "ratio",
    "data_availability_score": "ratio",
    "confidence": "ratio",
    "effort_weeks": "weeks",
    "risk_multiplier": "multiplier",
    "review_rate_pct": "percent",
    "review_minutes": "minutes/review",
    "model_cost_annual": "currency/year",
    "infra_cost_annual": "currency/year",
    "model_cost_per_month": "currency/month",
    "infra_cost_per_month": "currency/month",
}

METRIC_ALIASES = {
    "volume": "volume_per_month",
    "volume_monthly": "volume_per_month",
    "monthly_volume": "volume_per_month",
    "p50_minutes": "minutes_p50",
    "minutes_per_instance_p50": "minutes_p50",
    "p90_minutes": "minutes_p90",
    "minutes_per_instance_p90": "minutes_p90",
    "loaded_cost_per_hour": "fully_loaded_cost_per_hour",
    "fully_loaded_hourly_cost": "fully_loaded_cost_per_hour",
    "error_rate": "error_rate_pct",
    "error_rate_percent": "error_rate_pct",
    "rework_rate": "rework_rate_pct",
    "rework_rate_percent": "rework_rate_pct",
    "exception_rate": "exception_rate_pct",
    "exception_rate_percent": "exception_rate_pct",
    "backlog": "peak_backlog",
    "chase_volume": "chase_volume_per_month",
    "lapse_incidents": "lapse_incidents_per_month",
    "lapse_incidents_per_year": "lapse_incidents_per_month",
    "audit_prep_hours": "audit_prep_hours_per_month",
    "model_cost": "model_cost_annual",
    "infra_cost": "infra_cost_annual",
}

_QUESTION_LABELS = {
    "volume_per_month": "How many instances enter this process in a typical month?",
    "minutes_p50": "How many minutes does a typical instance take (p50)?",
    "minutes_p90": "How many minutes does a slow instance take (p90)?",
    "fully_loaded_cost_per_hour": "What is the fully loaded hourly cost for the people doing this work?",
    "error_rate_pct": "What percentage of instances contain an error before rework?",
    "cost_per_error": "What is the loaded cost of one process error?",
    "rework_rate_pct": "What percentage of instances require rework?",
    "cycle_time_hours": "How many hours pass from receipt to completion?",
    "headcount_touching": "How many people touch this process?",
    "peak_backlog": "What is the peak backlog of unfinished instances?",
    "chase_volume_per_month": "How many follow-up or chase actions happen per month?",
    "lapse_incidents_per_month": "How many lapse or expiry incidents happen per month?",
    "audit_prep_hours_per_month": "How many hours per month are spent preparing audit evidence?",
}


def canonical_json(value: Any) -> str:
    """Serialize JSON with stable ordering for signatures and reproducible tests."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_key(key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().casefold()).strip("_")
    return METRIC_ALIASES.get(normalized, normalized)


def _number(value: Any, *, key: str) -> float:
    if isinstance(value, bool):
        raise DomainError("INVALID_METRIC", f"Metric {key} must be numeric", 422)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_METRIC", f"Metric {key} must be numeric", 422) from exc
    if not math.isfinite(number) or number < 0:
        raise DomainError("INVALID_METRIC", f"Metric {key} must be a finite non-negative number", 422)
    if key.endswith("_pct") and number > 100:
        raise DomainError("INVALID_METRIC", f"Metric {key} must be between 0 and 100 percent", 422)
    return number


def normalize_metrics(raw: dict[str, Any] | list[Any] | None) -> dict[str, dict[str, Any]]:
    """Normalize either a keyed map or a list of metric records.

    The returned shape keeps value, unit, source, and provenance together so the
    scoring response can show exactly where each input came from.
    """

    if raw is None:
        return {}
    entries: Iterable[tuple[str, Any]]
    if isinstance(raw, dict):
        entries = raw.items()
    elif isinstance(raw, list):
        pairs: list[tuple[str, Any]] = []
        for item in raw:
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if not isinstance(item, dict) or not item.get("key"):
                raise DomainError("INVALID_METRIC", "Metric list entries require a key and value", 422)
            pairs.append((str(item["key"]), item))
        entries = pairs
    else:
        raise DomainError("INVALID_METRIC", "metrics must be an object or list", 422)

    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_value in entries:
        key = _normalized_key(raw_key)
        if not key:
            raise DomainError("INVALID_METRIC", "Metric keys cannot be blank", 422)
        if isinstance(raw_value, dict):
            if "value" not in raw_value:
                raise DomainError("INVALID_METRIC", f"Metric {key} requires value", 422)
            value = raw_value["value"]
            unit = raw_value.get("unit") or METRIC_UNITS.get(key, "number")
            source = raw_value.get("source") or "customer_asserted"
            provenance = raw_value.get("provenance") or raw_value.get("provenance_json") or {}
        else:
            value = raw_value
            unit = METRIC_UNITS.get(key, "number")
            source = "customer_asserted"
            provenance = {}
        if not isinstance(provenance, dict):
            raise DomainError("INVALID_METRIC", f"Metric {key} provenance must be an object", 422)
        normalized[key] = {
            "value": _number(value, key=key),
            "unit": str(unit),
            "source": str(source),
            "provenance": provenance,
        }
    return dict(sorted(normalized.items()))


def missing_required_metrics(metrics: dict[str, dict[str, Any]]) -> list[str]:
    return [key for key in REQUIRED_BASELINE_METRICS if key not in metrics]


def baseline_questions(metrics: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    present = metrics or {}
    return [
        {
            "id": f"question-{key}",
            "key": key,
            "question": question,
            "required": True,
            "answered": key in present,
            "status": "answered" if key in present else "open",
            "editable": True,
        }
        for key, question in _QUESTION_LABELS.items()
    ]


def _clean_line(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()


def build_draft_graph(process: Process, source_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw_lines = [_clean_line(line) for line in source_text.splitlines()]
    lines = [line for line in raw_lines if line]
    if not lines:
        lines = [part.strip() for part in re.split(r"(?<=[.!?])\s+", source_text) if part.strip()]
    if not lines:
        lines = ["Review the captured process description with a workflow owner."]

    nodes: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        lowered = line.casefold()
        node_type = (
            "decision"
            if lowered.startswith(("if ", "when "))
            or any(token in lowered for token in (" if ", " when ", " decide", " approve", " check "))
            else "step"
        )
        nodes.append(
            {
                "id": f"step-{index:03d}",
                "type": node_type,
                "label": line[:240],
                "description": line,
                "human_editable": True,
            }
        )
    edges = [
        {"from": nodes[index - 1]["id"], "to": nodes[index]["id"], "condition": None}
        for index in range(1, len(nodes))
    ]
    graph = {
        "version": 1,
        "status": "draft",
        "publishable": False,
        "trigger": process.trigger_json,
        "nodes": nodes,
        "edges": edges,
        "decisions": process.decisions_json,
        "outputs": process.outputs_json,
    }

    exceptions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in process.exceptions_json:
        description = item if isinstance(item, str) else item.get("description") if isinstance(item, dict) else str(item)
        if description and str(description).casefold() not in seen:
            seen.add(str(description).casefold())
            exceptions.append({"id": f"exception-{len(exceptions) + 1:03d}", "description": str(description), "editable": True})
    exception_pattern = re.compile(r"\b(exception|except|unless|fails?|missing|escalat|manual review|rework|lapse)\b", re.I)
    for line in lines:
        if exception_pattern.search(line) and line.casefold() not in seen:
            seen.add(line.casefold())
            exceptions.append({"id": f"exception-{len(exceptions) + 1:03d}", "description": line, "editable": True})
    return graph, exceptions


def _process_snapshot(process: Process, steps: list[ProcessStep]) -> dict[str, Any]:
    return {
        "id": process.id,
        "name": process.name,
        "department": process.department,
        "owner_user_id": process.owner_user_id,
        "system_of_record": process.system_of_record,
        "trigger": process.trigger_json,
        "inputs": process.inputs_json,
        "decisions": process.decisions_json,
        "exceptions": process.exceptions_json,
        "approvals": process.approvals_json,
        "outputs": process.outputs_json,
        "failure_modes": process.failure_modes_json,
        "steps": [
            {
                "seq": step.seq,
                "description": step.description,
                "system": step.system,
                "minutes_p50": step.minutes_p50,
                "minutes_p90": step.minutes_p90,
                "is_decision": step.is_decision,
            }
            for step in steps
        ],
    }


def baseline_canonical_payload(baseline: Baseline, metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    snapshot = dict(baseline.snapshot_json or {})
    snapshot["baseline_id"] = baseline.id
    snapshot["process_id"] = baseline.process_id
    snapshot["version"] = baseline.version
    snapshot["metrics"] = metrics
    snapshot["supersedes_baseline_id"] = baseline.supersedes_baseline_id
    return snapshot


def _record_not_found_access(db: Session, *, target_type: str, target_id: str) -> None:
    context = db.info.get("request_context")
    if context is None:
        return
    append_audit_log(
        db,
        action="data.access_denied",
        target_type=target_type,
        target_id=target_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"reason": "not_visible_in_active_workspace"},
    )
    db.commit()


def get_process_or_404(db: Session, process_id: str, workspace_id: str) -> Process:
    process = db.scalar(select(Process).where(Process.id == process_id, Process.workspace_id == workspace_id))
    if process is None:
        _record_not_found_access(db, target_type="process", target_id=process_id)
        raise DomainError("PROCESS_NOT_FOUND", f"Process {process_id} was not found", 404)
    return process


def get_interview_or_404(db: Session, interview_id: str, workspace_id: str) -> ProcessInterview:
    interview = db.scalar(
        select(ProcessInterview).where(
            ProcessInterview.id == interview_id,
            ProcessInterview.workspace_id == workspace_id,
        )
    )
    if interview is None:
        _record_not_found_access(db, target_type="process_interview", target_id=interview_id)
        raise DomainError("INTERVIEW_NOT_FOUND", f"Interview {interview_id} was not found", 404)
    return interview


def get_baseline_or_404(db: Session, baseline_id: str, workspace_id: str) -> Baseline:
    baseline = db.scalar(
        select(Baseline).where(Baseline.id == baseline_id, Baseline.workspace_id == workspace_id)
    )
    if baseline is None:
        _record_not_found_access(db, target_type="baseline", target_id=baseline_id)
        raise DomainError("BASELINE_NOT_FOUND", f"Baseline {baseline_id} was not found", 404)
    return baseline


def get_score_or_404(db: Session, score_id: str, workspace_id: str) -> OpportunityScore:
    score = db.scalar(
        select(OpportunityScore).where(
            OpportunityScore.id == score_id,
            OpportunityScore.workspace_id == workspace_id,
        )
    )
    if score is None:
        _record_not_found_access(db, target_type="opportunity_score", target_id=score_id)
        raise DomainError("SCORE_NOT_FOUND", f"Opportunity score {score_id} was not found", 404)
    return score


def active_signed_child(db: Session, baseline_id: str, workspace_id: str) -> Baseline | None:
    return db.scalar(
        select(Baseline)
        .where(
            Baseline.workspace_id == workspace_id,
            Baseline.supersedes_baseline_id == baseline_id,
            Baseline.status == "signed",
        )
        .order_by(Baseline.version.desc())
        .limit(1)
    )


def metric_map(db: Session, baseline: Baseline) -> dict[str, dict[str, Any]]:
    rows = db.scalars(select(BaselineMetric).where(BaselineMetric.baseline_id == baseline.id).order_by(BaselineMetric.key)).all()
    return {
        row.key: {
            "value": float(row.value),
            "unit": row.unit,
            "source": row.source,
            "provenance": row.provenance_json or {},
        }
        for row in rows
    }


def create_process(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    payload: Any,
) -> Process:
    owner_user_id = payload.owner_user_id or actor_id
    owner = db.scalar(select(User).where(User.id == owner_user_id))
    # The explicit membership check below is intentionally separate from the
    # user lookup so a caller cannot assign a process to another workspace.
    owner_membership = db.scalar(
        select(Membership).where(
            Membership.user_id == owner_user_id,
            Membership.workspace_id == workspace_id,
            Membership.status == "active",
        )
    )
    if owner is None or owner_membership is None:
        raise DomainError("PROCESS_OWNER_INVALID", "owner_user_id must be an active member of this workspace", 422)

    process = Process(
        id=new_id(),
        workspace_id=workspace_id,
        name=payload.name,
        department=payload.department,
        owner_user_id=owner_user_id,
        system_of_record=payload.system_of_record,
        trigger_json=payload.trigger,
        inputs_json=list(payload.inputs),
        decisions_json=list(payload.decisions),
        exceptions_json=list(payload.exceptions),
        approvals_json=list(payload.approvals),
        outputs_json=list(payload.outputs),
        failure_modes_json=list(payload.failure_modes),
    )
    db.add(process)
    db.flush()
    for index, step_payload in enumerate(payload.steps, start=1):
        db.add(
            ProcessStep(
                id=new_id(),
                workspace_id=workspace_id,
                process_id=process.id,
                seq=index,
                description=step_payload.description,
                system=step_payload.system,
                minutes_p50=step_payload.minutes_p50,
                minutes_p90=step_payload.minutes_p90,
                is_decision=step_payload.is_decision,
            )
        )
    append_audit_log(
        db,
        action="discovery.process.created",
        target_type="process",
        target_id=process.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"name": process.name, "owner_user_id": process.owner_user_id, "step_count": len(payload.steps)},
    )
    append_audit_log(
        db,
        action="discovery.created",
        target_type="discovery",
        target_id=process.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"name": process.name, "status": "draft"},
    )
    return process


def update_process(db: Session, process: Process, *, workspace_id: str, actor_id: str, payload: Any) -> Process:
    changed: dict[str, Any] = {}
    for field_name, model_name in (
        ("name", "name"),
        ("department", "department"),
        ("owner_user_id", "owner_user_id"),
        ("system_of_record", "system_of_record"),
    ):
        if field_name in payload.model_fields_set:
            value = getattr(payload, field_name)
            if field_name == "owner_user_id":
                membership = db.scalar(
                    select(Membership).where(
                        Membership.user_id == value,
                        Membership.workspace_id == workspace_id,
                        Membership.status == "active",
                    )
                )
                if membership is None:
                    raise DomainError("PROCESS_OWNER_INVALID", "owner_user_id must be an active member of this workspace", 422)
            setattr(process, model_name, value)
            changed[field_name] = value

    json_fields = {
        "trigger": "trigger_json",
        "inputs": "inputs_json",
        "decisions": "decisions_json",
        "exceptions": "exceptions_json",
        "approvals": "approvals_json",
        "outputs": "outputs_json",
        "failure_modes": "failure_modes_json",
    }
    for field_name, model_name in json_fields.items():
        if field_name in payload.model_fields_set:
            value = getattr(payload, field_name)
            setattr(process, model_name, value if field_name == "trigger" else list(value or []))
            changed[field_name] = value

    if "steps" in payload.model_fields_set:
        db.execute(delete(ProcessStep).where(ProcessStep.process_id == process.id, ProcessStep.workspace_id == workspace_id))
        for index, step_payload in enumerate(payload.steps or [], start=1):
            db.add(
                ProcessStep(
                    id=new_id(),
                    workspace_id=workspace_id,
                    process_id=process.id,
                    seq=index,
                    description=step_payload.description,
                    system=step_payload.system,
                    minutes_p50=step_payload.minutes_p50,
                    minutes_p90=step_payload.minutes_p90,
                    is_decision=step_payload.is_decision,
                )
            )
        changed["steps"] = {"count": len(payload.steps or [])}
    if changed:
        append_audit_log(
            db,
            action="discovery.process.updated",
            target_type="process",
            target_id=process.id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            after=changed,
        )
        append_audit_log(
            db,
            action="discovery.draft_updated",
            target_type="discovery",
            target_id=process.id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            after={"fields": sorted(changed)},
        )
    return process


def create_interview(
    db: Session,
    process: Process,
    *,
    workspace_id: str,
    actor_id: str,
    source_type: str,
    source_text: str,
    transcript_ref: str | None,
) -> ProcessInterview:
    graph, exceptions = build_draft_graph(process, source_text)
    interview = ProcessInterview(
        id=new_id(),
        workspace_id=workspace_id,
        process_id=process.id,
        source_type=source_type,
        transcript_ref=transcript_ref,
        source_text=source_text,
        draft_graph=graph,
        exception_list=exceptions,
        baseline_questions=baseline_questions(),
        captured_by=actor_id,
    )
    db.add(interview)
    db.flush()
    append_audit_log(
        db,
        action="discovery.interview.draft_created",
        target_type="process_interview",
        target_id=interview.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"process_id": process.id, "source_type": source_type, "node_count": len(graph["nodes"])},
    )
    append_audit_log(
        db,
        action="discovery.ingested",
        target_type="discovery",
        target_id=process.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"interview_id": interview.id, "source_type": source_type, "human_review_required": True},
    )
    return interview


def update_interview(
    db: Session,
    interview: ProcessInterview,
    *,
    workspace_id: str,
    actor_id: str,
    payload: Any,
) -> ProcessInterview:
    changed: dict[str, Any] = {}
    for field_name in ("source_text", "draft_graph", "exception_list", "baseline_questions"):
        if field_name in payload.model_fields_set:
            setattr(interview, field_name, getattr(payload, field_name))
            changed[field_name] = {"updated": True}
    append_audit_log(
        db,
        action="discovery.interview.draft_updated",
        target_type="process_interview",
        target_id=interview.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after=changed,
    )
    return interview


def create_baseline(
    db: Session,
    process: Process,
    *,
    workspace_id: str,
    actor_id: str,
    raw_metrics: dict[str, Any] | list[Any],
    notes: str | None,
    supersedes_baseline_id: str | None,
) -> Baseline:
    metrics = normalize_metrics(raw_metrics)
    if supersedes_baseline_id:
        prior = get_baseline_or_404(db, supersedes_baseline_id, workspace_id)
        if prior.process_id != process.id or prior.status != "signed":
            raise DomainError("BASELINE_SUPERSESSION_INVALID", "Only a signed baseline for this process can be superseded", 422)
    current_version = db.scalar(select(func.max(Baseline.version)).where(Baseline.process_id == process.id)) or 0
    steps = db.scalars(
        select(ProcessStep).where(ProcessStep.process_id == process.id, ProcessStep.workspace_id == workspace_id).order_by(ProcessStep.seq)
    ).all()
    baseline = Baseline(
        id=new_id(),
        workspace_id=workspace_id,
        process_id=process.id,
        version=int(current_version) + 1,
        status="draft",
        snapshot_json={
            "process": _process_snapshot(process, steps),
            "metrics": metrics,
            "notes": notes,
        },
        notes=notes,
        created_by=actor_id,
        supersedes_baseline_id=supersedes_baseline_id,
    )
    db.add(baseline)
    db.flush()
    for key, metric in metrics.items():
        db.add(
            BaselineMetric(
                id=new_id(),
                workspace_id=workspace_id,
                baseline_id=baseline.id,
                key=key,
                value=metric["value"],
                unit=metric["unit"],
                source=metric["source"],
                provenance_json=metric["provenance"],
            )
        )
    db.flush()
    append_audit_log(
        db,
        action="discovery.baseline.created",
        target_type="baseline",
        target_id=baseline.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"process_id": process.id, "version": baseline.version, "status": baseline.status, "metric_count": len(metrics)},
    )
    append_audit_log(
        db,
        action="baseline.created",
        target_type="baseline",
        target_id=baseline.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"process_id": process.id, "version": baseline.version, "status": baseline.status},
    )
    return baseline


def update_baseline(
    db: Session,
    baseline: Baseline,
    *,
    workspace_id: str,
    actor_id: str,
    raw_metrics: dict[str, Any] | list[Any] | None,
    notes: str | None,
    fields_set: set[str],
) -> Baseline:
    if baseline.status != "draft":
        raise DomainError("BASELINE_IMMUTABLE", "Only an unsigned draft baseline can be edited", 409)
    changed: dict[str, Any] = {}
    if "metrics" in fields_set:
        metrics = normalize_metrics(raw_metrics)
        db.execute(delete(BaselineMetric).where(BaselineMetric.baseline_id == baseline.id, BaselineMetric.workspace_id == workspace_id))
        for key, metric in metrics.items():
            db.add(
                BaselineMetric(
                    id=new_id(),
                    workspace_id=workspace_id,
                    baseline_id=baseline.id,
                    key=key,
                    value=metric["value"],
                    unit=metric["unit"],
                    source=metric["source"],
                    provenance_json=metric["provenance"],
                )
            )
        baseline.snapshot_json = {**(baseline.snapshot_json or {}), "metrics": metrics}
        changed["metric_count"] = len(metrics)
    if "notes" in fields_set:
        baseline.notes = notes
        baseline.snapshot_json = {**(baseline.snapshot_json or {}), "notes": notes}
        changed["notes_updated"] = True
    db.flush()
    append_audit_log(
        db,
        action="discovery.baseline.updated",
        target_type="baseline",
        target_id=baseline.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after=changed,
    )
    return baseline


def sign_baseline(
    db: Session,
    baseline: Baseline,
    *,
    workspace_id: str,
    actor_id: str,
    signature_note: str | None,
) -> Baseline:
    if baseline.status != "draft":
        raise DomainError("BASELINE_IMMUTABLE", "A signed baseline cannot be signed or changed again", 409)
    metrics = metric_map(db, baseline)
    missing = missing_required_metrics(metrics)
    if missing:
        raise DomainError(
            "BASELINE_INCOMPLETE",
            "Baseline is missing required metrics: " + ", ".join(missing),
            422,
        )
    if baseline.supersedes_baseline_id:
        prior = get_baseline_or_404(db, baseline.supersedes_baseline_id, workspace_id)
        if prior.process_id != baseline.process_id or prior.status != "signed":
            raise DomainError("BASELINE_SUPERSESSION_INVALID", "The superseded baseline must be signed", 422)
    baseline.snapshot_json = {**(baseline.snapshot_json or {}), "metrics": metrics}
    baseline.status = "signed"
    baseline.signed_by = actor_id
    baseline.signed_at = utc_now()
    baseline.canonical_hash = canonical_hash(baseline_canonical_payload(baseline, metrics))
    db.flush()
    append_audit_log(
        db,
        action="discovery.baseline.signed",
        target_type="baseline",
        target_id=baseline.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={
            "process_id": baseline.process_id,
            "version": baseline.version,
            "canonical_hash": baseline.canonical_hash,
            "signed_at": baseline.signed_at.isoformat() if baseline.signed_at else None,
            "supersedes_baseline_id": baseline.supersedes_baseline_id,
            "signature_note": signature_note,
        },
    )
    append_audit_log(
        db,
        action="baseline.signed",
        target_type="baseline",
        target_id=baseline.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"version": baseline.version, "canonical_hash": baseline.canonical_hash},
    )
    if baseline.supersedes_baseline_id:
        append_audit_log(
            db,
            action="baseline.superseded",
            target_type="baseline",
            target_id=baseline.supersedes_baseline_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            after={"superseded_by_baseline_id": baseline.id, "version": baseline.version},
        )
    return baseline


def _percent_fraction(value: float, key: str) -> float:
    if value > 1:
        return value / 100
    return value


def calculate_score(
    db: Session,
    baseline: Baseline,
    *,
    workspace_id: str,
    actor_id: str,
    request_inputs: Any,
) -> OpportunityScore:
    if baseline.status != "signed":
        raise DomainError("BASELINE_NOT_SIGNED", "Opportunity scoring requires a signed baseline", 409)
    metrics = metric_map(db, baseline)
    missing = missing_required_metrics(metrics)
    if missing:
        raise DomainError("BASELINE_INCOMPLETE", "Baseline is missing required metrics: " + ", ".join(missing), 422)

    provided = request_inputs.model_dump(exclude_none=True)
    nested_inputs = provided.pop("inputs", None)
    if isinstance(nested_inputs, dict):
        provided = {**nested_inputs, **provided}
    provided.pop("formula_version", None)
    user_provenance = provided.pop("input_provenance", {}) or {}
    aliases = {
        "structure_score": ("structure_score",),
        "rule_clarity_score": ("rule_clarity_score",),
        "data_availability_score": ("data_availability_score",),
        "exception_rate": ("exception_rate", "exception_rate_pct", "rework_rate_pct"),
        "confidence": ("confidence",),
        "effort_weeks": ("effort_weeks",),
        "risk_multiplier": ("risk_multiplier",),
        "review_rate": ("review_rate", "review_rate_pct"),
        "review_minutes": ("review_minutes",),
        "model_cost_annual": ("model_cost_annual", "model_cost"),
        "infra_cost_annual": ("infra_cost_annual", "infra_cost"),
    }
    defaults = {
        "structure_score": 0.70,
        "rule_clarity_score": 0.70,
        "data_availability_score": 0.70,
        "confidence": 0.75,
        "effort_weeks": 4.0,
        "risk_multiplier": 1.0,
        "review_minutes": float(metrics["minutes_p50"]["value"]),
        "model_cost_annual": 0.0,
        "infra_cost_annual": 0.0,
    }
    resolved: dict[str, float] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for key, candidate_keys in aliases.items():
        request_key = next((candidate for candidate in candidate_keys if candidate in provided), None)
        metric_key = next((candidate for candidate in candidate_keys if candidate in metrics), None)
        if request_key is not None:
            value = _number(provided[request_key], key=key)
            source = "score_request"
            source_key = request_key
        elif metric_key is not None:
            value = float(metrics[metric_key]["value"])
            if key in {"exception_rate", "review_rate"}:
                value = _percent_fraction(value, metric_key)
            source = "baseline_metric"
            source_key = metric_key
        elif key == "exception_rate":
            value = 0.10
            source = "default"
            source_key = None
        elif key == "review_rate":
            value = -1.0
            source = "derived"
            source_key = None
        else:
            value = defaults[key]
            source = "default"
            source_key = None
        resolved[key] = value
        provenance[key] = {
            "source": source,
            "metric_key": source_key,
            "user_provenance": user_provenance.get(key),
        }

    annual_volume = float(metrics["volume_per_month"]["value"]) * 12
    p50_minutes = float(metrics["minutes_p50"]["value"])
    loaded_rate = float(metrics["fully_loaded_cost_per_hour"]["value"])
    error_rate = _percent_fraction(float(metrics["error_rate_pct"]["value"]), "error_rate_pct")
    cost_per_error = float(metrics["cost_per_error"]["value"])
    labor_cost = annual_volume * p50_minutes / 60 * loaded_rate
    error_cost = annual_volume * error_rate * cost_per_error
    current_annual_cost = labor_cost + error_cost

    structure_component = resolved["structure_score"] * 0.30
    rule_component = resolved["rule_clarity_score"] * 0.30
    data_component = resolved["data_availability_score"] * 0.25
    exception_component = (1 - min(max(resolved["exception_rate"], 0), 1)) * 0.15
    if "automatable_pct" in provided:
        automatable_pct = _percent_fraction(_number(provided["automatable_pct"], key="automatable_pct"), "automatable_pct")
        automatable_pct = min(max(automatable_pct, 0), 1)
        provenance["automatable_pct"] = {
            "source": "score_request",
            "metric_key": "automatable_pct",
            "user_provenance": user_provenance.get("automatable_pct"),
        }
    else:
        automatable_pct = min(max(structure_component + rule_component + data_component + exception_component, 0), 1)
        provenance["automatable_pct"] = {
            "source": "derived",
            "metric_key": None,
            "user_provenance": None,
        }
    resolved["automatable_pct"] = automatable_pct
    if resolved["review_rate"] < 0:
        resolved["review_rate"] = max(0.0, 1 - automatable_pct)
        provenance["review_rate"] = {"source": "derived", "metric_key": None, "user_provenance": None}
    review_cost = annual_volume * resolved["review_rate"] * resolved["review_minutes"] / 60 * loaded_rate
    gross_savings = current_annual_cost * automatable_pct
    projected_savings = gross_savings - resolved["model_cost_annual"] - resolved["infra_cost_annual"] - review_cost
    priority_denominator = resolved["effort_weeks"] * resolved["risk_multiplier"]
    priority_score = projected_savings * resolved["confidence"] / priority_denominator

    inputs = {
        **resolved,
        "volume_per_month": float(metrics["volume_per_month"]["value"]),
        "minutes_p50": p50_minutes,
        "fully_loaded_cost_per_hour": loaded_rate,
        "error_rate_pct": float(metrics["error_rate_pct"]["value"]),
        "cost_per_error": cost_per_error,
    }
    breakdown = {
        "annual_volume": annual_volume,
        "current_annual_cost": current_annual_cost,
        "annual_cost_components": {"labor": labor_cost, "errors": error_cost},
        "automatable_components": {
            "structure": structure_component,
            "rule_clarity": rule_component,
            "data_availability": data_component,
            "exception_handling": exception_component,
        },
        "savings_components": {
            "gross_savings": gross_savings,
            "model_cost": resolved["model_cost_annual"],
            "infra_cost": resolved["infra_cost_annual"],
            "review_cost": review_cost,
        },
        "priority_components": {
            "numerator": projected_savings * resolved["confidence"],
            "denominator": priority_denominator,
        },
    }
    score = OpportunityScore(
        id=new_id(),
        workspace_id=workspace_id,
        process_id=baseline.process_id,
        baseline_id=baseline.id,
        formula_version=FORMULA_VERSION,
        annual_cost=current_annual_cost,
        projected_savings=projected_savings,
        automatable_pct=automatable_pct,
        confidence=resolved["confidence"],
        effort_weeks=resolved["effort_weeks"],
        risk_multiplier=resolved["risk_multiplier"],
        priority_score=priority_score,
        inputs_json=inputs,
        component_breakdown_json=breakdown,
        input_provenance_json=provenance,
    )
    db.add(score)
    db.flush()
    append_audit_log(
        db,
        action="discovery.opportunity_scored",
        target_type="opportunity_score",
        target_id=score.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={
            "process_id": baseline.process_id,
            "baseline_id": baseline.id,
            "formula_version": FORMULA_VERSION,
            "annual_cost": current_annual_cost,
            "projected_savings": projected_savings,
            "priority_score": priority_score,
        },
    )
    append_audit_log(
        db,
        action="opportunity_score.computed",
        target_type="opportunity_score",
        target_id=score.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"baseline_id": baseline.id, "formula_version": FORMULA_VERSION},
    )
    return score


def process_payload(db: Session, process: Process, *, workspace_id: str, actor_id: str | None = None) -> dict[str, Any]:
    steps = db.scalars(
        select(ProcessStep).where(ProcessStep.process_id == process.id, ProcessStep.workspace_id == workspace_id).order_by(ProcessStep.seq)
    ).all()
    interviews = db.scalars(
        select(ProcessInterview)
        .where(ProcessInterview.process_id == process.id, ProcessInterview.workspace_id == workspace_id)
        .order_by(ProcessInterview.captured_at.desc())
    ).all()
    baselines = db.scalars(
        select(Baseline).where(Baseline.process_id == process.id, Baseline.workspace_id == workspace_id).order_by(Baseline.version.desc())
    ).all()
    scores = db.scalars(
        select(OpportunityScore)
        .where(OpportunityScore.process_id == process.id, OpportunityScore.workspace_id == workspace_id)
        .order_by(OpportunityScore.computed_at.desc())
    ).all()
    if actor_id:
        append_data_access_log(
            db,
            workspace_id=workspace_id,
            actor_id=actor_id,
            artifact_id=process.id,
            resource_type="process_discovery",
            purpose="process_detail",
        )
    return {
        "id": process.id,
        "process_id": process.id,
        "workspace_id": process.workspace_id,
        "status": "draft",
        "draft_status": "draft",
        "human_review_required": True,
        "publish_allowed": False,
        "name": process.name,
        "department": process.department,
        "owner_user_id": process.owner_user_id,
        "system_of_record": process.system_of_record,
        "trigger": process.trigger_json,
        "inputs": process.inputs_json,
        "steps": [
            {
                "id": step.id,
                "seq": step.seq,
                "description": step.description,
                "system": step.system,
                "minutes_p50": step.minutes_p50,
                "minutes_p90": step.minutes_p90,
                "is_decision": step.is_decision,
            }
            for step in steps
        ],
        "decisions": process.decisions_json,
        "exceptions": process.exceptions_json,
        "approvals": process.approvals_json,
        "outputs": process.outputs_json,
        "failure_modes": process.failure_modes_json,
        "created_at": process.created_at.isoformat(),
        "updated_at": process.updated_at.isoformat(),
        "interviews": [interview_payload(item) for item in interviews],
        "baselines": [baseline_payload(db, item, workspace_id=workspace_id) for item in baselines],
        "opportunity_scores": [score_payload(item) for item in scores],
        "draft": interview_payload(interviews[0])["draft"] if interviews else None,
        "current_baseline": baseline_payload(db, baselines[0], workspace_id=workspace_id) if baselines else None,
        "score": score_payload(scores[0]) if scores else None,
    }


def interview_payload(interview: ProcessInterview) -> dict[str, Any]:
    return {
        "id": interview.id,
        "process_id": interview.process_id,
        "source_type": interview.source_type,
        "transcript_ref": interview.transcript_ref,
        "draft_graph": interview.draft_graph,
        "draft": {
            "source_type": interview.source_type,
            "source_name": interview.transcript_ref,
            "generated_at": interview.captured_at.isoformat(),
            "steps": interview.draft_graph.get("nodes", []),
            "exceptions": interview.exception_list,
            "baseline_questions": interview.baseline_questions,
        },
        "status": "draft",
        "draft_status": "draft",
        "human_review_required": True,
        "publish_allowed": False,
        "exception_list": interview.exception_list,
        "baseline_questions": interview.baseline_questions,
        "human_editable": True,
        "publishable": False,
        "captured_by": interview.captured_by,
        "captured_at": interview.captured_at.isoformat(),
        "updated_at": interview.updated_at.isoformat(),
    }


def baseline_payload(db: Session, baseline: Baseline, *, workspace_id: str) -> dict[str, Any]:
    metrics = metric_map(db, baseline)
    superseded_by = active_signed_child(db, baseline.id, workspace_id)
    signed_by: dict[str, Any] | None = None
    if baseline.signed_by:
        signer = db.get(User, baseline.signed_by)
        if signer:
            signed_by = {"id": signer.id, "email": signer.email, "name": signer.name}
    return {
        "id": baseline.id,
        "process_id": baseline.process_id,
        "version": baseline.version,
        "status": "superseded" if superseded_by else baseline.status,
        "raw_status": baseline.status,
        "snapshot": baseline.snapshot_json,
        "notes": baseline.notes,
        "metrics": metrics,
        "signed_by": signed_by,
        "signed_at": baseline.signed_at.isoformat() if baseline.signed_at else None,
        "canonical_hash": baseline.canonical_hash,
        "hash": baseline.canonical_hash,
        "supersedes_baseline_id": baseline.supersedes_baseline_id,
        "superseded_by_baseline_id": superseded_by.id if superseded_by else None,
        "created_by": baseline.created_by,
        "created_at": baseline.created_at.isoformat(),
        "immutable": baseline.status == "signed",
    }


def score_payload(score: OpportunityScore) -> dict[str, Any]:
    return {
        "id": score.id,
        "process_id": score.process_id,
        "baseline_id": score.baseline_id,
        "formula_version": score.formula_version,
        "annual_cost": score.annual_cost,
        "current_annual_cost": score.annual_cost,
        "projected_savings": score.projected_savings,
        "automatable_pct": score.automatable_pct,
        "confidence": score.confidence,
        "effort_weeks": score.effort_weeks,
        "risk_multiplier": score.risk_multiplier,
        "priority_score": score.priority_score,
        "inputs": score.inputs_json,
        "input_provenance": score.input_provenance_json,
        "component_breakdown": score.component_breakdown_json,
        "computed_at": score.computed_at.isoformat(),
    }


def export_baseline(db: Session, baseline: Baseline, *, workspace_id: str) -> dict[str, Any]:
    payload = baseline_payload(db, baseline, workspace_id=workspace_id)
    payload["export_format"] = "ledger.baseline.v1"
    payload["exported_at"] = datetime.now(timezone.utc).isoformat()
    return payload
