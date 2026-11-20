"""Server-side matplotlib charts, returned as base64 PNG strings.

Moved from ``interface.py`` (``generate_plots``). Phase 4 replaces these with
client-side charts fed by a JSON API.
"""

from __future__ import annotations

import base64
import io
from datetime import timedelta

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 - backend must be set first
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

COLORS = {
    "primary": "#4F46E5",
    "success": "#10B981",
    "danger": "#EF4444",
    "warning": "#F59E0B",
    "info": "#3B82F6",
    "gray": "#6B7280",
}
DPI = 120
TOP_SERVICES = 10
BASE_FONT_SIZE = 12


def generate_plots(
    daily_costs: pd.Series,
    forecast: np.ndarray,
    forecast_lower: np.ndarray,
    forecast_upper: np.ndarray,
    zombie_savings: float,
    zombies: pd.DataFrame,
    confidence_summary: dict[str, int],
) -> dict[str, str]:
    """Return ``{"main_plot": b64, "zombie_analysis": b64?}``."""
    plots: dict[str, str] = {}
    with sns.axes_style("whitegrid"), plt.rc_context():
        plt.rcParams["font.size"] = BASE_FONT_SIZE  # figure sizes are set per figure
        fig = _forecast_and_confidence_figure(
            daily_costs,
            forecast,
            forecast_lower,
            forecast_upper,
            zombie_savings,
            confidence_summary,
        )
        plots["main_plot"] = _to_base64(fig, tight=True)

        if len(zombies) > 0 and "ServiceCategory" in zombies.columns:
            plots["zombie_analysis"] = _to_base64(_service_waste_figure(zombies), tight=False)
    return plots


def _forecast_and_confidence_figure(
    daily_costs: pd.Series,
    forecast: np.ndarray,
    forecast_lower: np.ndarray,
    forecast_upper: np.ndarray,
    zombie_savings: float,
    confidence_summary: dict[str, int],
) -> Figure:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    if len(daily_costs) > 0:
        hist_dates = pd.to_datetime(daily_costs.index)
        ax1.plot(hist_dates, daily_costs.values, label="Historical Spend",
                 color=COLORS["primary"], linewidth=2.5, marker="o", markersize=4)  # fmt: skip

        if len(forecast) > 0:
            future = [hist_dates[-1] + timedelta(days=i + 1) for i in range(len(forecast))]
            ax1.plot(future, forecast, label="BAU Forecast",
                     color=COLORS["danger"], linestyle="--", linewidth=2)  # fmt: skip
            ax1.fill_between(future, forecast_lower, forecast_upper,
                             color=COLORS["danger"], alpha=0.15, label="95% CI")  # fmt: skip
            daily_waste = zombie_savings / max(len(daily_costs), 1)
            ax1.plot(future, np.maximum(forecast - daily_waste, 0), label="Optimized Forecast",
                     color=COLORS["success"], linestyle="-", linewidth=2.5)  # fmt: skip

    ax1.set_title("Cloud Spend Forecast & Optimization", fontsize=14, fontweight="bold")
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Daily Cost ($)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

    labels, values = list(confidence_summary.keys()), list(confidence_summary.values())
    ax2.bar(labels, values, color=[COLORS["danger"], COLORS["warning"], COLORS["info"]])
    ax2.set_title("Detection Confidence Levels", fontsize=14, fontweight="bold")
    ax2.set_ylabel("Count")
    ax2.grid(True, alpha=0.3, axis="y")
    for i, value in enumerate(values):
        ax2.text(i, value + 0.5, str(value), ha="center", fontweight="bold")

    fig.tight_layout()
    return fig


def _service_waste_figure(zombies: pd.DataFrame) -> Figure:
    service_waste = (
        zombies.groupby("ServiceCategory")["EffectiveCost"]
        .sum()
        .sort_values(ascending=False)
        .head(TOP_SERVICES)
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    bar_colors = plt.cm.coolwarm(np.linspace(0.2, 0.8, len(service_waste)))
    bars = ax.barh(range(len(service_waste)), service_waste.to_numpy(), color=bar_colors)

    ax.set_yticks(range(len(service_waste)))
    ax.set_yticklabels(service_waste.index)
    ax.set_xlabel("Waste Amount ($)")
    ax.set_title("Top Wasteful Service Categories", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3, axis="x")
    for i, (_bar, value) in enumerate(zip(bars, service_waste.to_numpy(), strict=True)):
        ax.text(value + value * 0.01, i, f"${value:,.0f}", va="center", fontsize=10)

    fig.tight_layout()
    return fig


def _to_base64(fig: Figure, *, tight: bool) -> str:
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight" if tight else None)
    finally:
        plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()
