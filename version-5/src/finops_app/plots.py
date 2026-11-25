"""Server-side matplotlib charts, returned as base64 PNG strings.

Moved from ``interface.py`` (``generate_plots``). Phase 4 replaces these with
client-side charts fed by a JSON API.
"""

from __future__ import annotations

import base64
import io
from datetime import timedelta
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 - backend must be set first
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finops_core.models import AnalysisResult  # noqa: E402

# Hex equivalents of the Coral tokens in static/css/tokens.css (matplotlib has no OKLCH).
COLORS = {
    "ink": "#1D1614",
    "ink_2": "#312926",
    "muted": "#615955",
    "rule": "#D9D3CF",
    "rule_2": "#C7BFBA",
    "paper_3": "#E8E1DD",
    "cotton": "#FDFBF8",
    "signal": "#BB3D31",
}
CHART_STYLE: dict[str, Any] = {
    "figure.facecolor": COLORS["cotton"],
    "axes.facecolor": COLORS["cotton"],
    "axes.edgecolor": COLORS["rule_2"],
    "axes.labelcolor": COLORS["muted"],
    "axes.titlecolor": COLORS["ink"],
    "axes.titleweight": "semibold",
    "axes.titlelocation": "left",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.color": COLORS["rule"],
    "xtick.color": COLORS["muted"],
    "ytick.color": COLORS["muted"],
    "text.color": COLORS["ink"],
    "legend.frameon": False,
    "font.family": "DejaVu Sans",
}
DPI = 120
TOP_SERVICES = 10
BASE_FONT_SIZE = 12


def generate_plots(result: AnalysisResult) -> dict[str, str]:
    """Return ``{"main_plot": b64, "zombie_analysis": b64?}``."""
    daily = pd.Series(result.daily_costs, index=pd.to_datetime(list(result.daily_dates)))
    fc = result.forecast
    plots: dict[str, str] = {}
    with sns.axes_style("whitegrid"), plt.rc_context(CHART_STYLE):  # type: ignore[arg-type]
        plt.rcParams["font.size"] = BASE_FONT_SIZE  # figure sizes are set per figure
        fig = _forecast_and_confidence_figure(
            daily,
            np.array(fc.values),
            np.array(fc.lower),
            np.array(fc.upper),
            result.total_waste,
            result.confidence_summary(),
        )
        plots["main_plot"] = _to_base64(fig, tight=True)

        service_waste = pd.Series(result.waste_by_service(), dtype=float)
        if len(service_waste) > 0:
            plots["zombie_analysis"] = _to_base64(_service_waste_figure(service_waste), tight=False)
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
        ax1.plot(hist_dates, daily_costs.values, label="Historical spend",
                 color=COLORS["ink"], linewidth=2, marker="o", markersize=3)  # fmt: skip

        if len(forecast) > 0:
            future = [hist_dates[-1] + timedelta(days=i + 1) for i in range(len(forecast))]
            ax1.plot(future, forecast, label="BAU forecast",
                     color=COLORS["muted"], linestyle="--", linewidth=2)  # fmt: skip
            ax1.fill_between(future, forecast_lower, forecast_upper,
                             color=COLORS["paper_3"], label="95% CI")  # fmt: skip
            daily_waste = zombie_savings / max(len(daily_costs), 1)
            ax1.plot(future, np.maximum(forecast - daily_waste, 0), label="Optimized forecast",
                     color=COLORS["signal"], linestyle="-", linewidth=2.5)  # fmt: skip

    ax1.set_title("Daily spend and forecast", fontsize=14)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Daily cost ($)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

    labels, values = list(confidence_summary.keys()), list(confidence_summary.values())
    ax2.bar(labels, values, color=[COLORS["ink"], COLORS["muted"], COLORS["rule_2"]])
    ax2.set_title("Findings by confidence", fontsize=14)
    ax2.set_ylabel("Count")
    ax2.grid(True, alpha=0.3, axis="y")
    for i, value in enumerate(values):
        ax2.text(i, value + 0.5, str(value), ha="center", fontweight="semibold")

    fig.tight_layout()
    return fig


def _service_waste_figure(waste_by_service: pd.Series) -> Figure:
    service_waste = waste_by_service.sort_values(ascending=False).head(TOP_SERVICES)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.invert_yaxis()  # largest at the top
    bar_colors = [COLORS["signal"]] + [COLORS["ink_2"]] * (len(service_waste) - 1)
    bars = ax.barh(range(len(service_waste)), service_waste.to_numpy(), color=bar_colors)

    ax.set_yticks(range(len(service_waste)))
    ax.set_yticklabels(service_waste.index)
    ax.set_xlabel("Estimated waste ($)")
    ax.set_title("Estimated waste by service", fontsize=14)
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
