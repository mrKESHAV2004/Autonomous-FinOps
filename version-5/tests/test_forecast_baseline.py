from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finops_core.forecast_baseline import (
    backtest,
    daily_series,
    forecast_daily,
    moving_average,
    seasonal_weekly,
)


def series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_daily_series_fills_missing_days_with_zero() -> None:
    df = pd.DataFrame(
        {
            "UsageDate": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-03"]),
            "EffectiveCost": [1.0, 2.0, 5.0],
        }
    )
    daily = daily_series(df)
    assert daily.tolist() == [3.0, 0.0, 5.0]
    assert daily.index[1] == pd.Timestamp("2024-01-02")


def test_daily_series_empty() -> None:
    assert daily_series(pd.DataFrame({"UsageDate": [], "EffectiveCost": []})).empty


def test_moving_average_uses_last_week() -> None:
    out = moving_average(np.array([100.0] * 3 + [10.0] * 7), 3)
    assert out is not None
    assert out.tolist() == [10.0, 10.0, 10.0]


def test_seasonal_needs_two_weeks() -> None:
    assert seasonal_weekly(np.ones(13), 7) is None
    week = [1.0, 2, 3, 4, 5, 6, 7]
    out = seasonal_weekly(np.array(week * 2), 7)
    assert out is not None
    assert out.tolist() == week


def test_picks_seasonal_for_weekly_pattern() -> None:
    weekly = [10.0, 10, 10, 10, 10, 50, 50] * 5
    fc = forecast_daily(series(weekly))

    assert fc.method == "seasonal_weekly"
    assert fc.backtest_mae == pytest.approx(0.0)
    assert list(fc.values) == weekly[:7]
    assert fc.lower == fc.values == fc.upper  # zero backtest error -> zero band


def test_picks_moving_average_for_flat_noise() -> None:
    rng = np.random.default_rng(0)
    fc = forecast_daily(series(list(100 + rng.normal(0, 1, 28))))
    assert fc.method in {"moving_average_7", "seasonal_weekly"}
    assert all(lo <= v <= hi for lo, v, hi in zip(fc.lower, fc.values, fc.upper, strict=True))


def test_short_history_has_no_backtest() -> None:
    fc = forecast_daily(series([5.0, 7.0, 9.0]))
    assert fc.method == "moving_average_7"
    assert fc.backtest_mae is None
    assert fc.values == (7.0,) * 7
    assert fc.dates[0] == "2024-01-04"


def test_lower_band_never_negative() -> None:
    fc = forecast_daily(series([0.0, 100.0] * 10))
    assert min(fc.lower) >= 0


def test_empty_history() -> None:
    fc = forecast_daily(pd.Series(dtype=float))
    assert fc.method == "none"
    assert fc.total == 0.0


def test_backtest_skips_methods_that_cannot_run() -> None:
    assert set(backtest(np.ones(10), 7)) == {"moving_average_7"}
    assert backtest(np.ones(7), 7) == {}
