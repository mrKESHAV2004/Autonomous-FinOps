from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from finops_core.detection import (
    MAX_CONTAMINATION,
    MIN_CONTAMINATION,
    OptimizedZombieDetector,
    confidence_summary,
    estimate_contamination,
)
from finops_core.preprocessing import DataPreprocessor


def _analysed(path: Path) -> pd.DataFrame:
    _, df = DataPreprocessor().load_and_preprocess(str(path))
    return df


@pytest.fixture
def analysed(make_billing_csv: Callable[..., Path]) -> pd.DataFrame:
    return _analysed(make_billing_csv(days=20, rows_per_day=30))


def test_flags_some_but_not_most_rows(analysed: pd.DataFrame) -> None:
    result = OptimizedZombieDetector().detect_anomalies(analysed)

    share = result["zombie_count"] / len(analysed)
    assert 0 < share < 0.3
    assert set(result["zombies"]["confidence"]) <= {"High", "Medium", "Low"}
    assert result["total_waste"] == pytest.approx(result["zombies"]["EffectiveCost"].sum())
    assert "anomaly_probability" in result["df_with_scores"].columns


def test_detection_is_deterministic(analysed: pd.DataFrame) -> None:
    first = OptimizedZombieDetector().detect_anomalies(analysed.copy())
    second = OptimizedZombieDetector().detect_anomalies(analysed.copy())

    pd.testing.assert_index_equal(first["zombies"].index, second["zombies"].index)


IDLE_ROWS = [
    {"UsageDate": "2024-01-05", "ServiceCategory": "Compute",
     "EffectiveCost": 25_000.0 + i, "ConsumedQuantity": 0.01}
    for i in range(3)
]  # fmt: skip


def test_flags_injected_expensive_idle_rows(make_billing_csv: Callable[..., Path]) -> None:
    df = _analysed(make_billing_csv(days=20, rows_per_day=30, extra_rows=IDLE_ROWS))

    zombies = OptimizedZombieDetector().detect_anomalies(df)["zombies"]

    assert (zombies["EffectiveCost"] >= 25_000).sum() == 3


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known version-4 bug kept for result parity in Phase 0: anomaly_probability is "
        "inverted (IsolationForest.decision_function is LOWER for more anomalous rows, "
        "but _decision_to_probability maps higher scores to higher probability), so the "
        "most extreme zombies get Low confidence. Fix in Phase 1 and drop this marker."
    ),
)
def test_most_extreme_zombies_get_high_confidence(make_billing_csv: Callable[..., Path]) -> None:
    df = _analysed(make_billing_csv(days=20, rows_per_day=30, extra_rows=IDLE_ROWS))

    zombies = OptimizedZombieDetector().detect_anomalies(df)["zombies"]

    assert set(zombies.loc[zombies["EffectiveCost"] >= 25_000, "confidence"]) <= {"High", "Medium"}


def test_falls_back_to_two_features_when_few_available() -> None:
    df = pd.DataFrame({"LogCost": [1.0, 2.0], "LogUsage": [1.0, 1.0]})
    assert OptimizedZombieDetector()._select_best_features(df) == ["LogCost", "LogUsage"]


def test_selects_at_most_fifteen_features(analysed: pd.DataFrame) -> None:
    assert len(OptimizedZombieDetector()._select_best_features(analysed)) <= 15


def test_small_datasets_use_size_based_contamination() -> None:
    assert estimate_contamination(pd.Series([1.0] * 10)) == MAX_CONTAMINATION
    assert estimate_contamination(pd.Series([1.0] * 100)) == MAX_CONTAMINATION  # 50/100 capped
    # >100 rows: still floored at the size-based value when the cost tail is flat
    assert estimate_contamination(pd.Series([1.0] * 101)) == MAX_CONTAMINATION
    # 1000 rows: size-based base is 50/1000 = 0.05
    assert estimate_contamination(pd.Series([1.0] * 1000)) == pytest.approx(0.05)


def test_large_datasets_stay_within_bounds() -> None:
    value = estimate_contamination(pd.Series(range(1, 5001), dtype=float))
    assert MIN_CONTAMINATION <= value <= MAX_CONTAMINATION


def test_confidence_summary_has_all_levels() -> None:
    zombies = pd.DataFrame({"confidence": ["High", "High", "Low"]})
    assert confidence_summary(zombies) == {"High": 2, "Medium": 0, "Low": 1}
    assert confidence_summary(pd.DataFrame()) == {"High": 0, "Medium": 0, "Low": 0}
