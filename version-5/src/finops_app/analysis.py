"""Shape a core :class:`AnalysisResult` into the dict ``dashboard.html`` renders.

All analysis happens in :func:`finops_core.pipeline.analyze`; this module only
adds savings maths, charts, recommendation cards and HTML tables. No Flask
imports, so it can move into a background worker in Phase 2.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from finops_app.plots import generate_plots
from finops_core.models import AnalysisResult, Finding
from finops_core.pipeline import analyze
from finops_core.recommendations import generate_recommendations

PREVIEW_ROWS = 10
TOP_WASTE_SERVICES = 5
FORECAST_METHOD_LABELS = {
    "moving_average_7": "7-day moving average",
    "seasonal_weekly": "weekly seasonal pattern",
    "none": "no history",
}


@dataclass(frozen=True)
class SavingsMetrics:
    forecast_bau: float
    forecast_opt: float
    potential_savings: float
    savings_ratio: float
    avg_daily_cost: float
    daily_waste_avg: float


def compute_savings(result: AnalysisResult) -> SavingsMetrics:
    """BAU vs optimised forecast, assuming waste is spread evenly over the period."""
    days = result.period_days
    forecast_bau = result.forecast.total
    daily_waste = result.total_waste / days if days > 0 else 0.0
    forecast_opt = float(sum(max(v - daily_waste, 0.0) for v in result.forecast.values))
    savings = forecast_bau - forecast_opt
    return SavingsMetrics(
        forecast_bau=forecast_bau,
        forecast_opt=forecast_opt,
        potential_savings=savings,
        savings_ratio=(savings / forecast_bau * 100) if forecast_bau > 0 else 0.0,
        avg_daily_cost=result.total_spend / days if days > 0 else 0.0,
        daily_waste_avg=daily_waste,
    )


def run_analysis(filepath: str) -> dict[str, Any]:
    """Analyse one file and return the ``results`` dict for dashboard.html.

    Raises :class:`~finops_core.errors.DataValidationError` (user-safe message)
    when the data cannot be analysed.
    """
    return build_dashboard(analyze(filepath))


def build_dashboard(result: AnalysisResult) -> dict[str, Any]:
    s = compute_savings(result)
    recommendations = generate_recommendations(
        result.findings, result.waste_percentage, s.potential_savings
    )
    fc = result.forecast
    method = FORECAST_METHOD_LABELS.get(fc.method, fc.method)
    accuracy = f" (last-week error ±${fc.backtest_mae:,.2f}/day)" if fc.backtest_mae else ""
    return {
        "total_spend": f"${result.total_spend:,.2f}",
        "zombie_waste": f"${result.total_waste:,.2f}",
        "zombie_count": f"{len(result.findings):,}",
        "forecast_bau": f"${s.forecast_bau:,.2f}",
        "forecast_opt": f"${s.forecast_opt:,.2f}",
        "savings": f"${s.potential_savings:,.2f}",
        "zombie_pct_of_total": f"{result.waste_percentage:.1f}%",
        "savings_pct_vs_bau": f"{s.savings_ratio:.1f}%",
        "avg_daily_cost": f"${s.avg_daily_cost:,.2f}",
        "avg_daily_zombie": f"${s.daily_waste_avg:,.2f}",
        "period_days": result.period_days,
        "total_records": result.records,
        "insight_headline": "Cloud Waste Analysis Complete",
        "insight_detail": [
            f"Analyzed {result.records:,} billable records for {result.resources:,} resources "
            f"over {result.period_days} days",
            f"Found {len(result.findings):,} resources with likely waste "
            f"(${result.total_waste:,.2f}, {result.waste_percentage:.1f}% of spend)",
            f"Forecast uses a {method}{accuracy}",
        ],
        "plots": generate_plots(result),
        "recommendations": recommendations,
        "waste_distribution": _waste_distribution_html(result),
        "confidence_summary": result.confidence_summary(),
        "zombies_preview": _findings_html(result.findings),
        "analysis_version": result.analysis_version,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _findings_html(findings: tuple[Finding, ...]) -> str:
    if not findings:
        return (
            '<div class="alert alert-success text-center">'
            '<i class="bi bi-check-circle me-2"></i>'
            "No wasteful resources detected. Your cloud spend appears to be efficient."
            "</div>"
        )
    header = "".join(
        f"<th>{h}</th>"
        for h in ("Resource", "Service", "Region", "Est. waste", "Per month", "Confidence", "Why")
    )
    rows = "".join(_finding_row(f) for f in findings[:PREVIEW_ROWS])
    return (
        '<table class="table table-striped table-hover align-middle">'
        f"<thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>"
    )


def _finding_row(f: Finding) -> str:
    cells = (
        f.label,
        f.service,
        f.region or "—",
        f"${f.estimated_waste:,.2f}",
        f"${f.estimated_monthly_waste:,.2f}",
        f.confidence,
        "; ".join(f.reasons),
    )
    return "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in cells) + "</tr>"


def _waste_distribution_html(result: AnalysisResult) -> str:
    by_service = list(result.waste_by_service().items())[:TOP_WASTE_SERVICES]
    if not by_service:
        return "<p class='text-muted'>No category data available</p>"
    rows = "".join(
        f"<tr><th>{html.escape(service)}</th><td>${waste:,.2f}</td></tr>"
        for service, waste in by_service
    )
    return f'<table class="table table-sm table-hover"><tbody>{rows}</tbody></table>'
