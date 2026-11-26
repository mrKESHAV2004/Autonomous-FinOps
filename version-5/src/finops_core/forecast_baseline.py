"""Fast, deterministic statistical forecast used for every analysis.

Candidate methods are backtested on the most recent ``horizon`` days:
* ``moving_average_7`` — mean of the last 7 days, flat;
* ``seasonal_weekly`` — each future day = mean of the same weekday over the
  last two weeks (needs >= 14 days);
* ``naive_yesterday`` — flat spend matching the previous day.

Auto-fallback: if a candidate model has higher MAPE than the naive/moving-average
baseline or exhibits divergence (MAPE > 50%), it automatically falls back
to the simpler moving-average baseline with an explanation.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from finops_core.models import ForecastResult

HORIZON_DAYS = 7
WEEK = 7
Z_95 = 1.96
MAX_ALLOWED_MAPE = 50.0

Method = Callable[[np.ndarray, int], np.ndarray | None]


def daily_series(df: pd.DataFrame) -> pd.Series:
    """Total cost per calendar day; days with no rows count as zero spend."""
    if len(df) == 0:
        return pd.Series(dtype=float)
    daily = df.groupby(pd.to_datetime(df["UsageDate"]).dt.normalize())["EffectiveCost"].sum()
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    return daily.reindex(full_range, fill_value=0.0).astype(float)


def moving_average(history: np.ndarray, horizon: int) -> np.ndarray | None:
    if len(history) == 0:
        return None
    return np.full(horizon, float(history[-WEEK:].mean()))


def seasonal_weekly(history: np.ndarray, horizon: int) -> np.ndarray | None:
    if len(history) < 2 * WEEK:
        return None
    last_two_weeks = history[-2 * WEEK :].reshape(2, WEEK)
    weekday_means = last_two_weeks.mean(axis=0)
    return np.array([weekday_means[h % WEEK] for h in range(horizon)])


def naive_yesterday(history: np.ndarray, horizon: int) -> np.ndarray | None:
    if len(history) == 0:
        return None
    return np.full(horizon, float(history[-1]))


METHODS: dict[str, Method] = {
    "moving_average_7": moving_average,
    "seasonal_weekly": seasonal_weekly,
    "naive_yesterday": naive_yesterday,
}


def calculate_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Percentage Error (MAPE). Omits elements where actual == 0."""
    mask = actual > 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100.0)


def backtest(history: np.ndarray, horizon: int) -> dict[str, np.ndarray]:
    """Errors (actual - predicted) per method on the last ``horizon`` days."""
    if len(history) <= horizon:
        return {}
    train, actual = history[:-horizon], history[-horizon:]
    errors = {}
    for name, method in METHODS.items():
        predicted = method(train, horizon)
        if predicted is not None:
            errors[name] = actual - predicted
    return errors


def forecast_daily(daily: pd.Series, horizon: int = HORIZON_DAYS) -> ForecastResult:
    """Forecast the next ``horizon`` days of total spend with backtesting and auto-fallback."""
    history = daily.to_numpy(dtype=float)
    if len(history) == 0:
        zeros = tuple(0.0 for _ in range(horizon))
        return ForecastResult("none", (), zeros, zeros, zeros, None, None, None)

    errors = backtest(history, horizon)
    maes = {name: float(np.mean(np.abs(err))) for name, err in errors.items()}
    actual_holdout = history[-horizon:] if len(history) > horizon else np.array([])
    mapes: dict[str, float] = {}
    if len(actual_holdout) == horizon:
        train = history[:-horizon]
        for name, method in METHODS.items():
            pred = method(train, horizon)
            if pred is not None:
                mapes[name] = calculate_mape(actual_holdout, pred)

    # Initial selection: method with lowest MAE (ties broken by moving_average_7)
    method_name = min(maes, key=maes.__getitem__) if maes else "moving_average_7"
    fallback_reason: str | None = None

    # Auto-fallback checks:
    # If seasonal_weekly was picked but its MAPE is higher than moving_average_7,
    # or exceeds the divergence threshold (50%), fall back to moving_average_7.
    if method_name == "seasonal_weekly" and "moving_average_7" in mapes:
        seasonal_mape = mapes.get("seasonal_weekly", 0.0)
        baseline_mape = mapes.get("moving_average_7", 0.0)
        if seasonal_mape > MAX_ALLOWED_MAPE:
            method_name = "moving_average_7"
            fallback_reason = (
                f"Seasonal weekly MAPE ({seasonal_mape:.1f}%) exceeded tolerance threshold "
                f"({MAX_ALLOWED_MAPE:.0f}%); fell back to moving average baseline."
            )
        elif seasonal_mape > baseline_mape:
            method_name = "moving_average_7"
            fallback_reason = (
                f"Seasonal weekly MAPE ({seasonal_mape:.1f}%) worse than baseline MAPE "
                f"({baseline_mape:.1f}%); fell back to moving average."
            )

    raw = METHODS[method_name](history, horizon)
    values = np.maximum(np.asarray(raw if raw is not None else np.zeros(horizon)), 0.0)

    spread = float(np.std(errors[method_name])) if method_name in errors else float(np.std(history))
    margin = Z_95 * spread
    last_day = pd.Timestamp(daily.index.max())
    dates = tuple((last_day + pd.Timedelta(days=i + 1)).date().isoformat() for i in range(horizon))
    return ForecastResult(
        method=method_name,
        dates=dates,
        values=tuple(_round(v) for v in values),
        lower=tuple(_round(max(v - margin, 0.0)) for v in values),
        upper=tuple(_round(v + margin) for v in values),
        backtest_mae=_round(maes[method_name]) if method_name in maes else None,
        backtest_mape=_round(mapes[method_name]) if method_name in mapes else None,
        fallback_reason=fallback_reason,
    )


def _round(value: float) -> float:
    return round(float(value), 6)
