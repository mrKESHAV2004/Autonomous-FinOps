"""Run the full analysis for one uploaded file and shape it for the dashboard.

Moved from the body of ``index()`` in ``interface.py``. The fallback ML copy
that lived there is gone; :mod:`finops_core` is the only implementation.
Everything here is plain Python (no Flask), so it is easy to test and to move
into a background worker in Phase 2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from finops_app.plots import generate_plots
from finops_core.detection import OptimizedZombieDetector, confidence_summary
from finops_core.errors import DataValidationError
from finops_core.forecasting import AdvancedForecaster
from finops_core.preprocessing import DataPreprocessor
from finops_core.recommendations import generate_recommendations

logger = logging.getLogger(__name__)

MIN_RECORDS = 10
FORECAST_DAYS = 7
LOOKBACK_DAYS = 14
PREVIEW_ROWS = 10
TOP_WASTE_SERVICES = 5
FALLBACK_INTERVAL = 0.1  # ±10% band when the forecaster returns no interval


@dataclass(frozen=True)
class ForecastOutput:
    daily_costs: pd.Series
    forecast: np.ndarray
    lower: np.ndarray
    upper: np.ndarray


@dataclass(frozen=True)
class SavingsMetrics:
    period_days: int
    forecast_bau: float
    forecast_opt: float
    potential_savings: float
    savings_ratio: float
    avg_daily_cost: float
    daily_waste_avg: float


def load_and_prep_data(filepath: str) -> pd.DataFrame:
    """Return rows with positive cost and engineered features."""
    _, df_analysis = DataPreprocessor().load_and_preprocess(filepath, sample_size=None)
    return df_analysis


def detect_zombies(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Return ``(df_with_scores, zombies, confidence_summary)``."""
    results = OptimizedZombieDetector().detect_anomalies(df)
    zombies = results["zombies"]
    return results["df_with_scores"], zombies, confidence_summary(zombies)


def train_and_forecast(df: pd.DataFrame, forecast_days: int = FORECAST_DAYS) -> ForecastOutput:
    results = AdvancedForecaster(
        lookback_window=LOOKBACK_DAYS, forecast_days=forecast_days
    ).forecast(df)
    daily_costs = df.groupby("UsageDate")["EffectiveCost"].sum().sort_index()
    forecast = np.array(results["forecast"])
    intervals = results["confidence_intervals"]
    if intervals:
        lower, upper = np.array(intervals["lower"]), np.array(intervals["upper"])
    else:
        lower, upper = forecast * (1 - FALLBACK_INTERVAL), forecast * (1 + FALLBACK_INTERVAL)
    return ForecastOutput(daily_costs, forecast, lower, upper)


def compute_savings(forecast_out: ForecastOutput, total_waste: float) -> SavingsMetrics:
    """BAU vs optimised forecast, assuming waste is spread evenly over the period."""
    period_days = len(forecast_out.daily_costs)
    forecast_bau = float(forecast_out.forecast.sum())
    daily_waste_avg = total_waste / period_days if period_days > 0 else 0.0
    forecast_opt = float(np.maximum(forecast_out.forecast - daily_waste_avg, 0).sum())
    potential_savings = forecast_bau - forecast_opt
    return SavingsMetrics(
        period_days=period_days,
        forecast_bau=forecast_bau,
        forecast_opt=forecast_opt,
        potential_savings=potential_savings,
        savings_ratio=(potential_savings / forecast_bau * 100) if forecast_bau > 0 else 0.0,
        avg_daily_cost=float(forecast_out.daily_costs.mean()) if period_days > 0 else 0.0,
        daily_waste_avg=daily_waste_avg,
    )


def run_analysis(filepath: str) -> dict[str, Any]:
    """Full pipeline for one file; returns the ``results`` dict for dashboard.html.

    Raises :class:`DataValidationError` with a user-safe message when the data
    cannot be analysed.
    """
    df = load_and_prep_data(filepath)
    if len(df) < MIN_RECORDS:
        raise DataValidationError(
            f"Insufficient data. Need at least {MIN_RECORDS} records with positive costs."
        )

    df, zombies, conf_summary = detect_zombies(df)
    total_waste = float(zombies["EffectiveCost"].sum()) if len(zombies) > 0 else 0.0
    total_spend = float(df["EffectiveCost"].sum())
    waste_percentage = (total_waste / total_spend * 100) if total_spend > 0 else 0.0

    forecast_out = train_and_forecast(df)
    savings = compute_savings(forecast_out, total_waste)
    plots = generate_plots(
        forecast_out.daily_costs, forecast_out.forecast, forecast_out.lower, forecast_out.upper,
        total_waste, zombies, conf_summary,
    )  # fmt: skip
    recommendations = generate_recommendations(
        zombies, total_waste, waste_percentage, savings.potential_savings
    )
    logger.info(
        "Analysis complete",
        extra={
            "records": len(df),
            "zombies": len(zombies),
            "waste_pct": round(waste_percentage, 2),
        },
    )
    return _format_results(
        df, zombies, conf_summary, total_spend, total_waste, waste_percentage, savings,
        plots, recommendations,
    )  # fmt: skip


def _format_results(
    df: pd.DataFrame,
    zombies: pd.DataFrame,
    conf_summary: dict[str, int],
    total_spend: float,
    total_waste: float,
    waste_percentage: float,
    s: SavingsMetrics,
    plots: dict[str, str],
    recommendations: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "total_spend": f"${total_spend:,.2f}",
        "zombie_waste": f"${total_waste:,.2f}",
        "zombie_count": f"{len(zombies):,}",
        "forecast_bau": f"${s.forecast_bau:,.2f}",
        "forecast_opt": f"${s.forecast_opt:,.2f}",
        "savings": f"${s.potential_savings:,.2f}",
        "zombie_pct_of_total": f"{waste_percentage:.1f}%",
        "savings_pct_vs_bau": f"{s.savings_ratio:.1f}%",
        "avg_daily_cost": f"${s.avg_daily_cost:,.2f}",
        "avg_daily_zombie": f"${s.daily_waste_avg:,.2f}",
        "period_days": s.period_days,
        "total_records": len(df),
        "insight_headline": "AI-Powered Cloud Waste Analysis Complete",
        "insight_detail": [
            f"Analyzed {len(df):,} records spanning {s.period_days} days",
            f"Detected {len(zombies):,} potential zombie resources",
            f"Identified ${s.potential_savings:,.0f} in 7-day savings opportunity",
        ],
        "plots": plots,
        "recommendations": recommendations,
        "waste_distribution": _waste_distribution_html(zombies),
        "confidence_summary": conf_summary,
        "zombies_preview": _zombies_preview_html(zombies),
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _zombies_preview_html(zombies: pd.DataFrame) -> str:
    if len(zombies) == 0:
        return (
            '<div class="alert alert-success text-center">'
            '<i class="bi bi-check-circle me-2"></i>'
            "No zombie resources detected! Your cloud spend appears to be efficient."
            "</div>"
        )
    cols = ["UsageDate", "ServiceCategory", "EffectiveCost"]
    if "confidence" in zombies.columns:
        cols.append("confidence")
    preview = zombies[[c for c in cols if c in zombies.columns]].head(PREVIEW_ROWS).copy()
    preview["EffectiveCost"] = preview["EffectiveCost"].apply(lambda x: f"${x:,.2f}")
    return str(
        preview.to_html(
            classes="table table-striped table-hover align-middle", index=False, escape=True
        )
    )


def _waste_distribution_html(zombies: pd.DataFrame) -> str:
    empty = "<p class='text-muted'>No category data available</p>"
    if len(zombies) == 0 or "ServiceCategory" not in zombies.columns:
        return empty
    waste = zombies.groupby("ServiceCategory")["EffectiveCost"].sum().nlargest(TOP_WASTE_SERVICES)
    if len(waste) == 0:
        return empty
    return str(
        waste.to_frame().to_html(
            classes="table table-sm table-hover",
            float_format="${:,.2f}".format,
            header=False,
            escape=True,
        )
    )
