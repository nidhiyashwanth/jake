from app.services.evaluations import DriftObservation, detect_drift, evaluate_cases, gate_result, metric_deltas


def _case(
    key: str,
    *,
    route: str = "auto",
    expected_route: str = "auto",
    correct: bool | None = True,
    prediction_fields: dict[str, object] | None = None,
    canary: bool = False,
    canary_pass: bool = True,
    correction_required: bool = False,
) -> dict:
    expected = {
        "fields": {"named_insured": "Acme LLC", "expiry": "2099-12-31"},
        "route": expected_route,
        "correct": correct,
        "correction_required": correction_required,
        "canary_pass": canary_pass,
    }
    prediction = {
        "fields": prediction_fields or expected["fields"],
        "route": route,
        "canary_pass": canary_pass,
    }
    return {
        "case_key": key,
        "sender": "sender-a",
        "document_type": "COI",
        "expected": expected,
        "prediction": prediction,
        "canary": canary,
    }


def test_metrics_include_field_precision_recall_and_operational_rates() -> None:
    metrics = evaluate_cases([
        _case("good"),
        _case("review", route="review", expected_route="review"),
        _case("corrected", route="review", expected_route="review", correct=True, prediction_fields={"named_insured": "Wrong", "expiry": "2099-12-31"}, correction_required=True),
        _case("canary", route="halt", expected_route="halt", canary=True),
    ])

    assert metrics["case_count"] == 4
    assert metrics["field_precision"]["named_insured"] == 0.75
    assert metrics["field_recall"]["expiry"] == 1.0
    assert metrics["exact_match_rate"] == 0.75
    assert metrics["straight_through_rate"] == 0.25
    assert metrics["review_rate"] == 0.5
    assert metrics["correction_rate"] == 0.25
    assert metrics["canary_passed"] is True
    assert metrics["by_sender_document_type"]["sender-a|COI"]["case_count"] == 4


def test_gate_blocks_false_auto_canary_and_regression_with_failing_case_ids() -> None:
    baseline = evaluate_cases([_case("good"), _case("review", route="review", expected_route="review")])
    bad_canary = _case("bad-canary", route="auto", expected_route="halt", canary=True, canary_pass=False)
    bad_canary["prediction"]["canary_pass"] = True
    current = evaluate_cases([
        _case("good"),
        _case("false-auto", route="auto", expected_route="review", correct=False),
        bad_canary,
    ])
    passed, failures, failing_cases, deltas = gate_result(current, baseline_metrics=baseline)

    assert passed is False
    assert any("false_auto_rate" in reason for reason in failures)
    assert any("injection" in reason for reason in failures)
    assert "bad-canary" in failing_cases
    assert deltas["false_auto_rate"] > 0
    assert metric_deltas(current, baseline)["exact_match_rate"] == 0


def test_drift_alerts_only_after_group_minimum_and_is_group_specific() -> None:
    observations = [
        *[DriftObservation("sender-a", "COI", True) for _ in range(5)],
        *[DriftObservation("sender-b", "W9", False) for _ in range(5)],
    ]
    snapshot = detect_drift(observations, baseline_correction_rate=0.1, max_delta=0.2, min_samples=5)

    assert snapshot["status"] == "alert"
    assert len(snapshot["alerts"]) == 1
    assert snapshot["alerts"][0]["group"] == "sender-a|COI"
    assert snapshot["metrics"]["sender-b|W9"]["correction_rate"] == 0
