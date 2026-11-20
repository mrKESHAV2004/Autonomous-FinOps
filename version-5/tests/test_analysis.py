from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from finops_app import analysis
from finops_app.analysis import ForecastOutput, compute_savings, run_analysis
from finops_core.errors import DataValidationError


def _forecast(days: int, values: list[float]) -> ForecastOutput:
    daily = pd.Series([100.0] * days, index=pd.date_range("2024-01-01", periods=days))
    arr = np.array(values)
    return ForecastOutput(daily, arr, arr * 0.9, arr * 1.1)


def test_savings_spread_waste_evenly_over_period() -> None:
    s = compute_savings(_forecast(10, [100.0] * 7), total_waste=50.0)

    assert s.period_days == 10
    assert s.daily_waste_avg == pytest.approx(5.0)
    assert s.forecast_bau == pytest.approx(700.0)
    assert s.forecast_opt == pytest.approx(665.0)
    assert s.potential_savings == pytest.approx(35.0)
    assert s.savings_ratio == pytest.approx(5.0)
    assert s.avg_daily_cost == pytest.approx(100.0)


def test_optimised_forecast_never_negative() -> None:
    s = compute_savings(_forecast(1, [10.0, 0.0]), total_waste=1_000.0)
    assert s.forecast_opt == 0.0
    assert s.potential_savings == pytest.approx(10.0)


def test_savings_with_no_history() -> None:
    s = compute_savings(
        ForecastOutput(pd.Series(dtype=float), np.zeros(7), np.zeros(7), np.zeros(7)), 5.0
    )
    assert s.period_days == 0
    assert s.daily_waste_avg == 0.0
    assert s.savings_ratio == 0.0
    assert s.avg_daily_cost == 0.0


def test_run_analysis_short_history_uses_average_forecast(
    make_billing_csv: Callable[..., Path],
) -> None:
    results = run_analysis(str(make_billing_csv(days=10, rows_per_day=15)))

    assert results["period_days"] == 10
    assert results["total_records"] == 150
    assert results["insight_headline"] == "AI-Powered Cloud Waste Analysis Complete"
    assert set(results["confidence_summary"]) == {"High", "Medium", "Low"}
    assert "main_plot" in results["plots"]
    assert results["zombies_preview"].startswith("<table")
    assert results["total_spend"].startswith("$")


def test_run_analysis_rejects_too_few_rows(make_billing_csv: Callable[..., Path]) -> None:
    with pytest.raises(DataValidationError, match="at least 10"):
        run_analysis(str(make_billing_csv(days=1, rows_per_day=5)))


def test_preview_html_escapes_service_names() -> None:
    zombies = pd.DataFrame(
        {
            "UsageDate": ["2024-01-01"],
            "ServiceCategory": ["<script>alert(1)</script>"],
            "EffectiveCost": [5.0],
            "confidence": ["High"],
        }
    )
    assert "<script>" not in analysis._zombies_preview_html(zombies)
    assert "<script>" not in analysis._waste_distribution_html(zombies)


def test_empty_zombies_render_friendly_messages() -> None:
    assert "No zombie resources detected" in analysis._zombies_preview_html(pd.DataFrame())
    assert "No category data" in analysis._waste_distribution_html(pd.DataFrame())
