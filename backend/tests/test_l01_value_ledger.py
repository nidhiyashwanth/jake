from datetime import date

import pytest

from app.errors import DomainError
from app.services.value_ledger import append_value_event, calculate_value_rollup, event_projection


def test_value_rollup_reconciles_outcomes_and_prices_roi() -> None:
    rows = [
        {"id": "u1", "kind": "unit_processed", "quantity": 1, "dollar_value": 0, "metadata": {"outcome": "auto", "actor_id": "a", "department": "ops"}},
        {"id": "u2", "kind": "unit_processed", "quantity": 1, "dollar_value": 0, "metadata": {"outcome": "reviewed", "actor_id": "b", "department": "ops"}},
        {"id": "u3", "kind": "unit_processed", "quantity": 1, "dollar_value": 0, "metadata": {"outcome": "halted", "actor_id": "c", "department": "risk"}},
        {"id": "benefit", "kind": "time_saved", "quantity": 0.5, "dollar_value": 50, "metadata": {}},
        {"id": "cost", "kind": "model_cost", "quantity": 2, "dollar_value": -2, "metadata": {}},
    ]

    result = calculate_value_rollup(
        rows,
        baseline_metrics={"cycle_time_hours": 12},
        baseline_id="baseline-1",
        baseline_hash="hash-1",
        implementation_cost_usd=24,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )

    assert result["reconciliation"] == {
        "ingested": 3.0,
        "auto": 1.0,
        "reviewed": 1.0,
        "halted": 1.0,
        "delta": 0.0,
        "reconciles": True,
        "orphan_events": 0,
    }
    assert result["value"]["net_dollars_usd"] == 48.0
    assert result["value"]["roi_pct"] == 2400.0
    assert result["value"]["payback_days"] == 15.0
    assert result["baseline"] == {"id": "baseline-1", "hash": "hash-1", "metrics": {"cycle_time_hours": 12}}
    assert result["adoption"][0]["actor_id"] == "a"


def test_value_rollup_exposes_reconciliation_failure_and_orphans() -> None:
    result = calculate_value_rollup(
        [
            {"id": "u1", "kind": "unit_processed", "quantity": 1, "dollar_value": 0, "metadata": {"outcome": "auto"}},
            {"id": "u2", "kind": "unit_processed", "quantity": 1, "dollar_value": 0, "metadata": {"outcome": "unknown"}, "orphan": True},
        ]
    )
    assert result["reconciliation"]["reconciles"] is False
    assert result["reconciliation"]["delta"] == 1.0
    assert result["reconciliation"]["orphan_events"] == 1


def test_event_projection_keeps_drilldown_links_and_redacts_secret_keys() -> None:
    item = event_projection(
        {
            "id": "event-1",
            "execution_id": "execution-1",
            "review_task_id": None,
            "kind": "model_cost",
            "quantity": 1,
            "dollar_value": -1,
            "metadata": {"api_key": "secret", "outcome": "auto"},
        }
    )
    assert item["links"]["execution"] == "/api/runtime/executions/execution-1"
    assert item["metadata"]["api_key"] == "[REDACTED]"


def test_append_value_event_rejects_unbounded_or_unknown_values_before_db_access() -> None:
    with pytest.raises(DomainError):
        append_value_event(
            None,  # type: ignore[arg-type]
            workspace_id="workspace",
            event_key="event",
            source_artifact_type="test",
            source_artifact_id="artifact",
            kind="not-a-kind",
            quantity=1,
            unit="unit",
            dollar_value=0,
            method="measured_ab",
            confidence="high",
        )
