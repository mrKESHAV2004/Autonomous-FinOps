from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from factories import finding, result
from finops_app.analysis import build_dashboard, compute_savings, run_analysis
from finops_core.errors import DataValidationError


def test_savings_spread_waste_evenly_over_period() -> None:
    r = result(findings=(finding(estimated_waste=50.0),), period_days=10, total_spend=1_000.0)

    s = compute_savings(r)

    assert s.daily_waste_avg == pytest.approx(5.0)
    assert s.forecast_bau == pytest.approx(700.0)
    assert s.forecast_opt == pytest.approx(665.0)
    assert s.potential_savings == pytest.approx(35.0)
    assert s.savings_ratio == pytest.approx(5.0)
    assert s.avg_daily_cost == pytest.approx(100.0)


def test_optimised_forecast_never_negative() -> None:
    r = result(
        findings=(finding(estimated_waste=1_000.0),), period_days=1, forecast_values=(10.0, 0.0)
    )
    s = compute_savings(r)
    assert s.forecast_opt == 0.0
    assert s.potential_savings == pytest.approx(10.0)


def test_savings_with_no_history() -> None:
    s = compute_savings(result(period_days=0, forecast_values=(0.0,) * 7))
    assert s.daily_waste_avg == 0.0
    assert s.savings_ratio == 0.0
    assert s.avg_daily_cost == 0.0


def test_dashboard_lists_findings_with_reasons() -> None:
    f = finding(resource_name="db-prod", estimated_waste=12.5, reasons=("Pays 5× peers",))
    data = build_dashboard(result(findings=(f,)))

    assert data["zombie_count"] == "1"
    assert data["zombie_waste"] == "$12.50"
    assert "db-prod" in data["zombies_preview"]
    assert "Pays 5× peers" in data["zombies_preview"]
    assert "Compute" in data["waste_distribution"]
    assert set(data["plots"]) == {"main_plot", "zombie_analysis"}
    assert data["analysis_version"].startswith("phase1")


def test_dashboard_escapes_resource_text() -> None:
    f = finding(resource_name="<script>alert(1)</script>", service="<b>svc</b>")
    data = build_dashboard(result(findings=(f,)))
    assert "<script>" not in data["zombies_preview"]
    assert "<b>svc</b>" not in data["waste_distribution"]


def test_empty_findings_render_friendly_messages() -> None:
    data = build_dashboard(result())
    assert "No wasteful resources detected" in data["zombies_preview"]
    assert "No category data" in data["waste_distribution"]
    assert set(data["plots"]) == {"main_plot"}


def test_run_analysis_end_to_end(make_billing_csv: Callable[..., Path]) -> None:
    data = run_analysis(str(make_billing_csv(days=10, rows_per_day=15)))

    assert data["period_days"] == 10
    assert data["total_records"] == 150
    assert set(data["confidence_summary"]) == {"High", "Medium", "Low"}
    assert data["total_spend"].startswith("$")


def test_run_analysis_rejects_too_few_rows(make_billing_csv: Callable[..., Path]) -> None:
    with pytest.raises(DataValidationError, match="at least 10"):
        run_analysis(str(make_billing_csv(days=1, rows_per_day=5)))
