"""Fast, deterministic statistical forecast used for every analysis.

Two candidate methods are backtested on the most recent ``horizon`` days and
the one with the lower mean absolute error (MAE) is used:

* ``moving_average_7`` — mean of the last 7 days, flat;
* ``seasonal_weekly`` — each future day = mean of the same weekday over the
  last two weeks (needs >= 14 days).

The band is ±1.96 × the standard deviation of the chosen method's backtest
errors (or of the history when there is too little data to backtest). The
LSTM in :mod:`finops_core.forecasting` is offline-only and is compared
against this baseline in ``finops-train``.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from finops_core.models import ForecastResult

HORIZON_DAYS = 7
WEEK = 7
Z_95 = 1.96

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


METHODS: dict[str, Method] = {
    "moving_average_7": moving_average,
    "seasonal_weekly": seasonal_weekly,
}


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
    """Forecast the next ``horizon`` days of total spend."""
    history = daily.to_numpy(dtype=float)
    if len(history) == 0:
        zeros = tuple(0.0 for _ in range(horizon))
        return ForecastResult("none", (), zeros, zeros, zeros, None)

    errors = backtest(history, horizon)
    maes = {name: float(np.mean(np.abs(err))) for name, err in errors.items()}
    # Ties go to the simpler method (dict order).
    method_name = min(maes, key=maes.__getitem__) if maes else "moving_average_7"
    # A method that ran on the shorter backtest history also runs on the full one.
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
    )


def _round(value: float) -> float:
    return round(float(value), 6)
