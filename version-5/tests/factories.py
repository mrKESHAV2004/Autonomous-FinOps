"""Small builders for core result objects used across tests."""

from __future__ import annotations

from typing import Any

from finops_core.models import ANALYSIS_VERSION, AnalysisResult, Finding, ForecastResult


def finding(**overrides: Any) -> Finding:
    values: dict[str, Any] = {
        "resource_key": "i-1",
        "resource_id": "i-1",
        "resource_name": None,
        "service": "Compute",
        "region": "us-east-1",
        "account": "123",
        "unit": "Hours",
        "total_cost": 100.0,
        "total_usage": 10.0,
        "days_active": 5,
        "estimated_waste": 50.0,
        "estimated_monthly_waste": 300.0,
        "confidence": "Medium",
        "signals": ("overpriced",),
        "reasons": ("Pays a lot",),
    }
    values.update(overrides)
    return Finding(**values)


def forecast(values: tuple[float, ...] = (100.0,) * 7) -> ForecastResult:
    dates = tuple(f"2024-02-{i + 1:02d}" for i in range(len(values)))
    return ForecastResult(
        method="moving_average_7",
        dates=dates,
        values=values,
        lower=tuple(v * 0.9 for v in values),
        upper=tuple(v * 1.1 for v in values),
        backtest_mae=5.0,
    )


def result(
    findings: tuple[Finding, ...] = (),
    period_days: int = 10,
    total_spend: float = 1_000.0,
    forecast_values: tuple[float, ...] = (100.0,) * 7,
) -> AnalysisResult:
    dates = tuple(f"2024-01-{i + 1:02d}" for i in range(period_days))
    return AnalysisResult(
        analysis_version=ANALYSIS_VERSION,
        records=50,
        resources=10,
        period_start=dates[0] if dates else None,
        period_end=dates[-1] if dates else None,
        period_days=period_days,
        total_spend=total_spend,
        daily_dates=dates,
        daily_costs=tuple(total_spend / period_days for _ in dates) if period_days else (),
        findings=findings,
        forecast=forecast(forecast_values),
    )
