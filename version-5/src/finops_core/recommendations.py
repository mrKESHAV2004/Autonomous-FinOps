"""Rule-based recommendation cards shown on the dashboard, built from findings."""

from __future__ import annotations

from collections.abc import Sequence

from finops_core.models import SIGNAL_IDLE, Finding

CRITICAL_WASTE_PCT = 10
HIGH_WASTE_PCT = 5
DAYS_PER_MONTH = 30
FORECAST_DAYS = 7

Recommendation = dict[str, str]


def generate_recommendations(
    findings: Sequence[Finding],
    waste_percentage: float,
    forecast_savings: float,
) -> list[Recommendation]:
    """Return 1–5 recommendation cards, most important first."""
    cards: list[Recommendation | None] = [
        _severity_card(waste_percentage),
        _idle_card(findings),
        _top_service_card(findings),
        _savings_card(forecast_savings),
        _high_confidence_card(findings),
    ]
    return [card for card in cards if card is not None]


def _severity_card(waste_percentage: float) -> Recommendation:
    if waste_percentage > CRITICAL_WASTE_PCT:
        severity, priority, icon = "CRITICAL", "high", "bi-exclamation-triangle"
    elif waste_percentage > HIGH_WASTE_PCT:
        severity, priority, icon = "HIGH", "high", "bi-exclamation-circle"
    else:
        severity, priority, icon = "MODERATE", "medium", "bi-info-circle"
    return {
        "priority": priority,
        "icon": icon,
        "title": f"{severity}: Waste Level Detected",
        "description": f"{waste_percentage:.1f}% of total spend is estimated waste.",
        "action": (
            "Immediate review recommended" if priority == "high" else "Schedule review this week"
        ),
    }


def _idle_card(findings: Sequence[Finding]) -> Recommendation | None:
    idle = [f for f in findings if SIGNAL_IDLE in f.signals]
    if not idle:
        return None
    cost = sum(f.estimated_waste for f in idle)
    return {
        "priority": "high",
        "icon": "bi-power",
        "title": f"{len(idle)} Idle Resource{'s' if len(idle) != 1 else ''}",
        "description": f"Billed ${cost:,.2f} with zero recorded usage.",
        "action": "Confirm with owners, then stop or delete them",
    }


def _top_service_card(findings: Sequence[Finding]) -> Recommendation | None:
    if not findings:
        return None
    by_service: dict[str, float] = {}
    for f in findings:
        by_service[f.service] = by_service.get(f.service, 0.0) + f.estimated_waste
    top_service, top_waste = max(by_service.items(), key=lambda kv: (kv[1], kv[0]))
    return {
        "priority": "high",
        "icon": "bi-funnel",
        "title": f"Focus Area: {top_service}",
        "description": f"Accounts for ${top_waste:,.2f} of estimated waste.",
        "action": f"Start optimization with {top_service} resources",
    }


def _savings_card(forecast_savings: float) -> Recommendation | None:
    if forecast_savings <= 0:
        return None
    monthly = forecast_savings * DAYS_PER_MONTH / FORECAST_DAYS
    return {
        "priority": "high",
        "icon": "bi-cash-coin",
        "title": "Significant Savings Potential",
        "description": f"${forecast_savings:,.0f} in 7 days (${monthly:,.0f} monthly).",
        "action": "Implement recommendations within 48 hours",
    }


def _high_confidence_card(findings: Sequence[Finding]) -> Recommendation | None:
    high = sum(1 for f in findings if f.confidence == "High")
    if high == 0:
        return None
    return {
        "priority": "medium",
        "icon": "bi-shield-check",
        "title": "High Confidence Detections",
        "description": f"{high} resources with strong evidence of waste.",
        "action": "Review high confidence items first",
    }
