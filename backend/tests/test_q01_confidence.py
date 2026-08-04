import pytest

from app.services.confidence import (
    MIN_SAMPLE_RATE,
    ConfidenceSignals,
    ThresholdValues,
    _stable_sample,
    compute_confidence,
    simulate,
)


def _thresholds(**overrides: float) -> ThresholdValues:
    values = {
        "auto_threshold": 0.85,
        "review_threshold": 0.65,
        "halt_threshold": 0.45,
        "value_at_risk_limit": 10_000,
        "sample_rate": 0.02,
    }
    values.update(overrides)
    return ThresholdValues(**values)


def _signals(**overrides: float | bool) -> ConfidenceSignals:
    values: dict[str, float | bool] = {
        "extraction_consistency": 0.95,
        "validation_severity": 0.02,
        "matching_score": 0.96,
        "novelty_score": 0.05,
        "sender_history_score": 0.92,
        "value_at_risk": 500,
    }
    values.update(overrides)
    return ConfidenceSignals(**values)


def test_confidence_formula_uses_all_six_observable_signals_and_routes_auto() -> None:
    decision = compute_confidence(_signals(), _thresholds())

    assert set(decision.components) == {
        "extraction_consistency",
        "validation_quality",
        "matching_score",
        "novelty_quality",
        "sender_history_score",
        "value_at_risk_score",
    }
    assert 0 <= decision.confidence <= 1
    assert decision.route == "auto"
    assert decision.evidence["formula_version"] == "confidence.v1"
    assert decision.evidence["model_confidence_used"] is False


def test_risk_and_severity_force_review_or_halt_even_when_extraction_is_strong() -> None:
    high_risk = compute_confidence(_signals(value_at_risk=25_000), _thresholds())
    low_quality = compute_confidence(
        _signals(validation_severity=1.0, novelty_score=1.0, matching_score=0.1),
        _thresholds(),
    )

    assert high_risk.route == "review"
    assert high_risk.route_band == "value_at_risk_review"
    assert low_quality.route == "halt"


def test_required_halt_is_a_deterministic_override() -> None:
    decision = compute_confidence(_signals(required_halt=True), _thresholds())

    assert decision.route == "halt"
    assert decision.route_band == "forced_halt"


def test_simulator_reconciles_and_reports_false_auto_cost() -> None:
    cases = [_signals(value_at_risk=500), _signals(matching_score=0.3), _signals(required_halt=True)]
    results = simulate(
        cases,
        [False, True, True],
        [("conservative", _thresholds(auto_threshold=0.95)), ("default", _thresholds())],
    )

    assert len(results) == 2
    for result in results:
        assert result["auto_count"] + result["review_count"] + result["halt_count"] == result["total"]
        assert result["reconciles"] is True
        assert result["estimated_cost_usd"] >= 0
    assert results[1]["false_auto_count"] == 1
    assert results[1]["estimated_error"] == 1.0


def test_sample_rate_has_a_hard_two_percent_floor_and_is_retry_stable() -> None:
    assert _stable_sample("same-assessment", 1.0) is True
    assert _stable_sample("same-assessment", MIN_SAMPLE_RATE) == _stable_sample("same-assessment", MIN_SAMPLE_RATE)
    with pytest.raises(ValueError):
        _stable_sample("too-low", 0.019)


def test_confidence_threshold_order_is_invariant() -> None:
    with pytest.raises(ValueError):
        ThresholdValues(
            auto_threshold=0.5,
            review_threshold=0.7,
            halt_threshold=0.4,
            value_at_risk_limit=100,
        ).validate()
