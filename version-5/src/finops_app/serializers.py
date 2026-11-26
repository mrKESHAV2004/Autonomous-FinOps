"""Plain-dict views of stored rows, shared by the JSON API and the pages."""

from __future__ import annotations

from typing import Any

from finops_app.analysis import compute_savings
from finops_app.finding_text import explained_signals, recommended_action
from finops_app.models import Analysis, Finding, FindingEvent
from finops_app.repository import load_result
from finops_app.triage import STATUS_LABELS


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def finding_label(f: Finding) -> str:
    if f.resource_name or f.resource_id:
        return str(f.resource_name or f.resource_id)
    if f.resource_key.startswith("row:"):
        return f"{f.service} line item #{f.resource_key[4:]}"
    return f.resource_key.removeprefix("svc:").replace("|", " · ")


def finding_dict(f: Finding) -> dict[str, Any]:
    return {
        "id": f.id,
        "analysis_id": f.analysis_id,
        "label": finding_label(f),
        "resource_key": f.resource_key,
        "resource_id": f.resource_id,
        "resource_name": f.resource_name,
        "service": f.service,
        "region": f.region,
        "account": f.account,
        "unit": f.unit,
        "total_cost": f.total_cost,
        "total_usage": f.total_usage,
        "days_active": f.days_active,
        "estimated_waste": f.est_waste,
        "estimated_monthly_waste": f.est_monthly_waste,
        "confidence": f.confidence,
        "signals": list(f.signals),
        "reasons": list(f.reasons),
        "status": f.status,
        "status_label": STATUS_LABELS.get(f.status, f.status),
        "snoozed_until": _iso(f.snoozed_until),
        "status_changed_at": _iso(f.status_changed_at),
    }


def finding_detail_dict(f: Finding, events: list[FindingEvent]) -> dict[str, Any]:
    return {
        **finding_dict(f),
        "recommended_action": recommended_action(f.signals),
        "signal_explanations": [
            {"name": name, "meaning": meaning} for name, meaning in explained_signals(f.signals)
        ],
        "history": [event_dict(e) for e in events],
    }


def event_dict(e: FindingEvent) -> dict[str, Any]:
    return {
        "from_status": e.from_status,
        "to_status": e.to_status,
        "note": e.note,
        "snoozed_until": _iso(e.snoozed_until),
        "by": e.user.email if e.user is not None else None,
        "at": _iso(e.created_at),
    }


def analysis_dict(a: Analysis) -> dict[str, Any]:
    return {
        "id": a.id,
        "filename": a.dataset.original_filename,
        "rows": a.dataset.row_count,
        "status": a.status,
        "error": a.error_message if a.status == "failed" else None,
        "created_at": _iso(a.created_at),
        "finished_at": _iso(a.finished_at),
        "total_spend": a.total_spend,
        "total_waste": a.total_waste,
    }


def series_dict(a: Analysis) -> dict[str, Any]:
    """Daily spend, the forecast with its band, and the forecast after fixes."""
    result = load_result(a)
    savings = compute_savings(result)
    fc = result.forecast
    return {
        "daily": {"dates": list(result.daily_dates), "costs": list(result.daily_costs)},
        "forecast": {
            "method": fc.method,
            "dates": list(fc.dates),
            "values": list(fc.values),
            "lower": list(fc.lower),
            "upper": list(fc.upper),
            "optimised": [max(v - savings.daily_waste_avg, 0.0) for v in fc.values],
            "backtest_mae": fc.backtest_mae,
        },
    }
