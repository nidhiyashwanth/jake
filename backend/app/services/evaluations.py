"""Rights-aware golden evaluation, publish gates, and rolling drift detection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import GoldenCase, GoldenSet, DriftSnapshot, WorkflowEvaluationResult, WorkflowVersion, new_id, utc_now
from app.services.audit import append_audit_log


DEFAULT_GATE: dict[str, float] = {
    "max_false_auto_rate": 0.02,
    "min_exact_match_rate": 0.90,
    "min_macro_field_precision": 0.90,
    "min_macro_field_recall": 0.90,
    "max_correction_rate": 0.15,
    "max_regression_delta": 0.03,
}
DEFAULT_COSTS = {"auto": 0.05, "review": 4.0, "halt": 1.0}
HIGHER_IS_BETTER = frozenset({"exact_match_rate", "macro_field_precision", "macro_field_recall", "straight_through_rate"})
LOWER_IS_BETTER = frozenset({"false_auto_rate", "review_rate", "halt_rate", "cost_per_run", "correction_rate"})
META_FIELDS = frozenset({"route", "correct", "correction_required", "canary_pass", "injection_safe", "cost_usd"})
VALID_RIGHTS = frozenset({"contractual_rights", "manual_review", "synthetic"})
VALID_SOURCE_TYPES = frozenset({"corrected", "manual", "canary", "synthetic"})


@dataclass(frozen=True)
class DriftObservation:
    sender: str
    document_type: str
    corrected: bool


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_gate(gate: Mapping[str, Any] | None = None) -> dict[str, float]:
    values = dict(DEFAULT_GATE)
    if gate:
        for key, value in gate.items():
            if key in values:
                values[key] = float(value)
    if not 0 <= values["max_false_auto_rate"] <= 1:
        raise ValueError("max_false_auto_rate must be between 0 and 1")
    if not 0 <= values["min_exact_match_rate"] <= 1 or not 0 <= values["min_macro_field_precision"] <= 1 or not 0 <= values["min_macro_field_recall"] <= 1:
        raise ValueError("minimum evaluation metrics must be between 0 and 1")
    if not 0 <= values["max_correction_rate"] <= 1 or not 0 <= values["max_regression_delta"] <= 1:
        raise ValueError("evaluation limits must be between 0 and 1")
    return values


def _fields(value: Mapping[str, Any]) -> dict[str, Any]:
    nested = value.get("fields")
    if isinstance(nested, Mapping):
        return dict(nested)
    return {str(key): item for key, item in value.items() if key not in META_FIELDS}


def _route(value: Mapping[str, Any]) -> str:
    route = str(value.get("route", "review")).casefold()
    return route if route in {"auto", "review", "halt"} else "review"


def _correct(value: Mapping[str, Any]) -> bool | None:
    raw = value.get("correct")
    return raw if isinstance(raw, bool) else None


def _case_summary(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(cases)
    if total == 0:
        return {
            "case_count": 0,
            "field_precision": {},
            "field_recall": {},
            "macro_field_precision": None,
            "macro_field_recall": None,
            "exact_match_rate": None,
            "straight_through_rate": 0.0,
            "false_auto_rate": 0.0,
            "review_rate": 0.0,
            "halt_rate": 0.0,
            "correction_rate": 0.0,
            "cost_per_run": 0.0,
        }

    field_names = sorted({field for case in cases for field in (_fields(case.get("expected", {})) | _fields(case.get("prediction", {})))})
    true_positive = {field: 0 for field in field_names}
    false_positive = {field: 0 for field in field_names}
    false_negative = {field: 0 for field in field_names}
    exact = 0
    auto = review = halt = false_auto = corrections = 0
    total_cost = 0.0
    for case in cases:
        expected = case.get("expected", {})
        prediction = case.get("prediction", {})
        expected_fields = _fields(expected)
        predicted_fields = _fields(prediction)
        if all(expected_fields.get(field) == predicted_fields.get(field) for field in field_names):
            exact += 1
        for field in field_names:
            expected_present = expected_fields.get(field) not in (None, "")
            predicted_present = predicted_fields.get(field) not in (None, "")
            if predicted_present and expected_present and predicted_fields.get(field) == expected_fields.get(field):
                true_positive[field] += 1
            elif predicted_present:
                false_positive[field] += 1
            if expected_present and (not predicted_present or predicted_fields.get(field) != expected_fields.get(field)):
                false_negative[field] += 1
        route = _route(prediction)
        auto += int(route == "auto")
        review += int(route == "review")
        halt += int(route == "halt")
        expected_route = str(expected.get("route", "review")).casefold()
        correct = _correct(expected)
        if route == "auto" and (correct is False or (correct is None and expected_route != "auto")):
            false_auto += 1
        corrections += int(bool(expected.get("correction_required", False)))
        raw_cost = prediction.get("cost_usd")
        total_cost += float(raw_cost) if isinstance(raw_cost, (float, int)) and float(raw_cost) >= 0 else DEFAULT_COSTS[route]

    precision: dict[str, float | None] = {}
    recall: dict[str, float | None] = {}
    for field in field_names:
        p_denominator = true_positive[field] + false_positive[field]
        r_denominator = true_positive[field] + false_negative[field]
        precision[field] = true_positive[field] / p_denominator if p_denominator else None
        recall[field] = true_positive[field] / r_denominator if r_denominator else None
    precision_values = [value for value in precision.values() if value is not None]
    recall_values = [value for value in recall.values() if value is not None]
    return {
        "case_count": total,
        "field_precision": precision,
        "field_recall": recall,
        "macro_field_precision": sum(precision_values) / len(precision_values) if precision_values else None,
        "macro_field_recall": sum(recall_values) / len(recall_values) if recall_values else None,
        "exact_match_rate": exact / total,
        "straight_through_rate": auto / total,
        "false_auto_rate": false_auto / total,
        "review_rate": review / total,
        "halt_rate": halt / total,
        "correction_rate": corrections / total,
        "cost_per_run": total_cost / total,
        "auto_count": auto,
        "review_count": review,
        "halt_count": halt,
        "false_auto_count": false_auto,
        "correction_count": corrections,
    }


def evaluate_cases(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute reproducible metrics and breakdowns from stored case snapshots."""

    case_list = list(cases)
    metrics = _case_summary(case_list)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for case in case_list:
        grouped[f"{case.get('sender', 'unknown')}|{case.get('document_type', 'unknown')}"].append(case)
    metrics["by_sender_document_type"] = {key: _case_summary(items) for key, items in sorted(grouped.items())}
    canary_cases = [case for case in case_list if bool(case.get("canary", False))]
    canary_failures: list[str] = []
    for case in canary_cases:
        expected = case.get("expected", {})
        prediction = case.get("prediction", {})
        expected_pass = bool(expected.get("canary_pass", True))
        actual_pass = prediction.get("canary_pass")
        if actual_pass is None:
            actual_pass = prediction.get("injection_safe")
        if actual_pass is None:
            actual_pass = _route(prediction) != "auto" if expected.get("must_not_auto") else True
        if bool(actual_pass) != expected_pass:
            canary_failures.append(str(case.get("case_key", "unknown")))
    metrics["canary_count"] = len(canary_cases)
    metrics["canary_failures"] = canary_failures
    metrics["canary_passed"] = not canary_failures
    return metrics


def metric_deltas(current: Mapping[str, Any], baseline: Mapping[str, Any] | None) -> dict[str, float]:
    if not baseline:
        return {}
    deltas: dict[str, float] = {}
    for key in sorted(HIGHER_IS_BETTER | LOWER_IS_BETTER):
        current_value = current.get(key)
        baseline_value = baseline.get(key)
        if isinstance(current_value, (int, float)) and isinstance(baseline_value, (int, float)):
            deltas[key] = float(current_value) - float(baseline_value)
    return deltas


def gate_result(
    metrics: Mapping[str, Any],
    *,
    gate: Mapping[str, Any] | None = None,
    baseline_metrics: Mapping[str, Any] | None = None,
) -> tuple[bool, list[str], list[str], dict[str, float]]:
    limits = normalized_gate(gate)
    failures: list[str] = []
    failing_cases = [str(case) for case in metrics.get("canary_failures", [])]
    if float(metrics.get("false_auto_rate") or 0) > limits["max_false_auto_rate"]:
        failures.append(f"false_auto_rate {metrics.get('false_auto_rate'):.4f} exceeds {limits['max_false_auto_rate']:.4f}")
    if metrics.get("exact_match_rate") is not None and float(metrics["exact_match_rate"]) < limits["min_exact_match_rate"]:
        failures.append(f"exact_match_rate {metrics['exact_match_rate']:.4f} is below {limits['min_exact_match_rate']:.4f}")
    if metrics.get("macro_field_precision") is not None and float(metrics["macro_field_precision"]) < limits["min_macro_field_precision"]:
        failures.append(f"macro_field_precision {metrics['macro_field_precision']:.4f} is below {limits['min_macro_field_precision']:.4f}")
    if metrics.get("macro_field_recall") is not None and float(metrics["macro_field_recall"]) < limits["min_macro_field_recall"]:
        failures.append(f"macro_field_recall {metrics['macro_field_recall']:.4f} is below {limits['min_macro_field_recall']:.4f}")
    if float(metrics.get("correction_rate") or 0) > limits["max_correction_rate"]:
        failures.append(f"correction_rate {metrics.get('correction_rate'):.4f} exceeds {limits['max_correction_rate']:.4f}")
    if not bool(metrics.get("canary_passed", True)):
        failures.append("one or more injection canaries failed")
    deltas = metric_deltas(metrics, baseline_metrics)
    for key, delta in deltas.items():
        if key in HIGHER_IS_BETTER and delta < -limits["max_regression_delta"]:
            failures.append(f"{key} regressed by {abs(delta):.4f}, beyond {limits['max_regression_delta']:.4f}")
        if key in LOWER_IS_BETTER and delta > limits["max_regression_delta"]:
            failures.append(f"{key} increased by {delta:.4f}, beyond {limits['max_regression_delta']:.4f}")
    return not failures, failures, failing_cases, deltas


def detect_drift(
    observations: Iterable[DriftObservation],
    *,
    baseline_correction_rate: float,
    max_delta: float = 0.10,
    min_samples: int = 5,
) -> dict[str, Any]:
    if not 0 <= baseline_correction_rate <= 1 or not 0 <= max_delta <= 1:
        raise ValueError("drift baseline and max_delta must be between 0 and 1")
    grouped: dict[str, list[DriftObservation]] = defaultdict(list)
    for observation in observations:
        grouped[f"{observation.sender}|{observation.document_type}"].append(observation)
    metrics: dict[str, Any] = {}
    alerts: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items()):
        corrected = sum(1 for item in items if item.corrected)
        rate = corrected / len(items)
        delta = rate - baseline_correction_rate
        metrics[key] = {"sample_count": len(items), "correction_count": corrected, "correction_rate": rate, "delta": delta}
        if len(items) >= min_samples and delta > max_delta:
            alerts.append({"group": key, "sample_count": len(items), "correction_rate": rate, "delta": delta, "reason": "rolling_correction_rate_drift"})
    return {"status": "alert" if alerts else "ok", "metrics": metrics, "alerts": alerts, "baseline_correction_rate": baseline_correction_rate, "max_delta": max_delta, "min_samples": min_samples}


def golden_set_payload(db: Session, golden_set: GoldenSet, *, include_cases: bool = True) -> dict[str, Any]:
    cases = db.scalars(
        select(GoldenCase)
        .where(GoldenCase.golden_set_id == golden_set.id, GoldenCase.workspace_id == golden_set.workspace_id)
        .order_by(GoldenCase.case_key)
    ).all()
    payload: dict[str, Any] = {
        "id": golden_set.id,
        "workflow_id": golden_set.workflow_id,
        "workflow_version_id": golden_set.workflow_version_id,
        "name": golden_set.name,
        "version": golden_set.version,
        "status": golden_set.status,
        "source_policy": golden_set.source_policy_json,
        "gate": golden_set.gate_json,
        "canonical_hash": golden_set.canonical_hash,
        "case_count": len(cases),
        "created_by": golden_set.created_by,
        "created_at": golden_set.created_at.isoformat(),
    }
    if include_cases:
        payload["cases"] = [
            {
                "id": case.id,
                "case_key": case.case_key,
                "source_type": case.source_type,
                "rights_status": case.rights_status,
                "rights_basis": case.rights_basis,
                "sender": case.sender,
                "document_type": case.document_type,
                "input": case.input_json,
                "expected": case.expected_json,
                "prediction": case.prediction_json,
                "canary": case.canary,
                "created_at": case.created_at.isoformat(),
            }
            for case in cases
        ]
    return payload


def create_golden_set(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    workflow_version: WorkflowVersion,
    name: str,
    version: int | None,
    status: str,
    source_policy: Mapping[str, Any],
    gate: Mapping[str, Any],
    cases: list[Mapping[str, Any]],
) -> GoldenSet:
    if not cases:
        raise DomainError("GOLDEN_SET_EMPTY", "A golden set must contain at least one case", 422)
    limits = normalized_gate(gate)
    normalized_cases: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    rights_counts: dict[str, int] = defaultdict(int)
    for raw in cases:
        case_key = str(raw.get("case_key", "")).strip()
        source_type = str(raw.get("source_type", "")).strip()
        rights_status = str(raw.get("rights_status", "")).strip()
        rights_basis = " ".join(str(raw.get("rights_basis", "")).split())
        if not case_key or case_key in seen_keys:
            raise DomainError("GOLDEN_CASE_KEY_INVALID", "Golden case keys must be present and unique", 422)
        if source_type not in VALID_SOURCE_TYPES:
            raise DomainError("GOLDEN_CASE_SOURCE_INVALID", f"Unsupported golden case source type: {source_type}", 422)
        if rights_status not in VALID_RIGHTS or not rights_basis:
            raise DomainError("GOLDEN_CASE_RIGHTS_REQUIRED", "Every golden case requires explicit rights_status and rights_basis", 422)
        seen_keys.add(case_key)
        rights_counts[rights_status] += 1
        normalized_cases.append(
            {
                "case_key": case_key,
                "source_type": source_type,
                "rights_status": rights_status,
                "rights_basis": rights_basis,
                "sender": str(raw.get("sender") or "unknown"),
                "document_type": str(raw.get("document_type") or "unknown"),
                "input": dict(raw.get("input") or {}),
                "expected": dict(raw.get("expected") or {}),
                "prediction": dict(raw.get("prediction") or {}),
                "canary": bool(raw.get("canary", source_type == "canary")),
            }
        )
    latest_version = db.scalar(
        select(func.max(GoldenSet.version)).where(
            GoldenSet.workspace_id == workspace_id,
            GoldenSet.workflow_version_id == workflow_version.id,
            GoldenSet.name == name,
        )
    ) or 0
    chosen_version = version or latest_version + 1
    if chosen_version <= latest_version:
        raise DomainError("GOLDEN_SET_VERSION_CONFLICT", "Golden-set versions must increase monotonically", 409)
    source_policy_payload = {**dict(source_policy), "rights_counts": dict(sorted(rights_counts.items()))}
    canonical_payload = {"workflow_version_id": workflow_version.id, "name": name, "version": chosen_version, "source_policy": source_policy_payload, "gate": limits, "cases": normalized_cases}
    golden_set = GoldenSet(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_id=workflow_version.workflow_id,
        workflow_version_id=workflow_version.id,
        name=name,
        version=chosen_version,
        status=status,
        source_policy_json=source_policy_payload,
        gate_json=limits,
        canonical_hash=canonical_hash(canonical_payload),
        created_by=actor_id,
        created_at=utc_now(),
    )
    db.add(golden_set)
    db.flush()
    for item in normalized_cases:
        db.add(
            GoldenCase(
                id=new_id(),
                workspace_id=workspace_id,
                golden_set_id=golden_set.id,
                case_key=item["case_key"],
                source_type=item["source_type"],
                rights_status=item["rights_status"],
                rights_basis=item["rights_basis"],
                sender=item["sender"],
                document_type=item["document_type"],
                input_json=item["input"],
                expected_json=item["expected"],
                prediction_json=item["prediction"],
                canary=item["canary"],
                created_at=utc_now(),
            )
        )
    db.flush()
    return golden_set


def get_golden_set_or_404(db: Session, golden_set_id: str, workspace_id: str) -> GoldenSet:
    golden_set = db.scalar(select(GoldenSet).where(GoldenSet.id == golden_set_id, GoldenSet.workspace_id == workspace_id))
    if golden_set is None:
        raise DomainError("GOLDEN_SET_NOT_FOUND", f"Golden set {golden_set_id} was not found", 404)
    return golden_set


def run_golden_evaluation(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    workflow_version: WorkflowVersion,
    golden_set: GoldenSet,
    baseline_evaluation_id: str | None,
) -> WorkflowEvaluationResult:
    if golden_set.workflow_id != workflow_version.workflow_id:
        raise DomainError("GOLDEN_SET_WORKFLOW_MISMATCH", "The golden set belongs to a different workflow", 422)
    if golden_set.status != "active":
        raise DomainError("GOLDEN_SET_NOT_ACTIVE", "Only an active golden set can run a release evaluation", 409)
    cases = db.scalars(
        select(GoldenCase).where(GoldenCase.golden_set_id == golden_set.id, GoldenCase.workspace_id == workspace_id).order_by(GoldenCase.case_key)
    ).all()
    snapshots = [
        {"case_key": case.case_key, "sender": case.sender, "document_type": case.document_type, "expected": case.expected_json, "prediction": case.prediction_json, "canary": case.canary}
        for case in cases
    ]
    metrics = evaluate_cases(snapshots)
    baseline = None
    baseline_result = None
    if baseline_evaluation_id:
        baseline_result = db.scalar(
            select(WorkflowEvaluationResult).where(
                WorkflowEvaluationResult.id == baseline_evaluation_id,
                WorkflowEvaluationResult.workspace_id == workspace_id,
            )
        )
        if baseline_result is None:
            raise DomainError("EVALUATION_BASELINE_NOT_FOUND", "The requested baseline evaluation was not found", 404)
        baseline = baseline_result.metrics_json
    passed, failures, failing_cases, deltas = gate_result(metrics, gate=golden_set.gate_json, baseline_metrics=baseline)
    result = WorkflowEvaluationResult(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_version_id=workflow_version.id,
        definition_hash=workflow_version.definition_hash,
        passed=passed,
        metrics_json={"evaluation_type": "golden.e01", "golden_set_id": golden_set.id, **metrics},
        failure_reasons_json=failures,
        evaluator="server.golden.e01",
        evaluation_type="golden.e01",
        golden_set_id=golden_set.id,
        baseline_evaluation_id=baseline_result.id if baseline_result else None,
        metric_deltas_json=deltas,
        failing_cases_json=failing_cases,
        created_by=actor_id,
        evaluated_at=utc_now(),
    )
    db.add(result)
    db.flush()
    append_audit_log(
        db,
        action="evaluation.golden_completed",
        target_type="workflow_version",
        target_id=workflow_version.id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        after={"evaluation_id": result.id, "golden_set_id": golden_set.id, "passed": passed, "failure_reasons": failures, "metric_deltas": deltas},
    )
    return result


def drift_payload(snapshot: DriftSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "workflow_version_id": snapshot.workflow_version_id,
        "window_key": snapshot.window_key,
        "status": snapshot.status,
        "baseline_correction_rate": snapshot.baseline_correction_rate,
        "max_delta": snapshot.max_delta,
        "metrics": snapshot.metrics_json,
        "alerts": snapshot.alerts_json,
        "created_by": snapshot.created_by,
        "created_at": snapshot.created_at.isoformat(),
    }


def record_drift_snapshot(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    workflow_version_id: str,
    window_key: str,
    observations: Iterable[DriftObservation],
    baseline_correction_rate: float,
    max_delta: float,
    min_samples: int,
) -> DriftSnapshot:
    detection = detect_drift(observations, baseline_correction_rate=baseline_correction_rate, max_delta=max_delta, min_samples=min_samples)
    snapshot = DriftSnapshot(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_version_id=workflow_version_id,
        window_key=window_key,
        status=detection["status"],
        baseline_correction_rate=baseline_correction_rate,
        max_delta=max_delta,
        metrics_json={**detection["metrics"], "min_samples": min_samples},
        alerts_json=detection["alerts"],
        created_by=actor_id,
        created_at=utc_now(),
    )
    db.add(snapshot)
    db.flush()
    if snapshot.status == "alert":
        append_audit_log(
            db,
            action="evaluation.drift.alert",
            target_type="drift_snapshot",
            target_id=snapshot.id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            after={"workflow_version_id": workflow_version_id, "window_key": window_key, "alerts": snapshot.alerts_json},
        )
    return snapshot


def list_golden_sets(db: Session, workspace_id: str) -> list[GoldenSet]:
    return db.scalars(select(GoldenSet).where(GoldenSet.workspace_id == workspace_id).order_by(desc(GoldenSet.created_at))).all()


def list_drift_snapshots(db: Session, workspace_id: str) -> list[DriftSnapshot]:
    return db.scalars(select(DriftSnapshot).where(DriftSnapshot.workspace_id == workspace_id).order_by(desc(DriftSnapshot.created_at))).all()
