"""Rule-based recommendation cards shown on the dashboard.

Moved from ``interface.py`` (``generate_recommendations``) unchanged in logic.
"""

from __future__ import annotations

import pandas as pd

CRITICAL_WASTE_PCT = 10
HIGH_WASTE_PCT = 5
DAYS_PER_MONTH = 30
FORECAST_DAYS = 7

Recommendation = dict[str, str]


def generate_recommendations(
    zombies: pd.DataFrame,
    total_waste: float,
    waste_percentage: float,
    forecast_savings: float,
) -> list[Recommendation]:
    """Return 1–4 recommendation cards, most important first."""
    del total_waste  # kept in the signature for compatibility; not used by any rule
    recommendations = [_severity_card(waste_percentage)]

    top_service = _top_service_card(zombies)
    if top_service:
        recommendations.append(top_service)

    if forecast_savings > 0:
        monthly = forecast_savings * DAYS_PER_MONTH / FORECAST_DAYS
        recommendations.append(
            {
                "priority": "high",
                "icon": "bi-cash-coin",
                "title": "Significant Savings Potential",
                "description": f"${forecast_savings:,.0f} in 7 days (${monthly:,.0f} monthly).",
                "action": "Implement recommendations within 48 hours",
            }
        )

    high_confidence = _high_confidence_card(zombies)
    if high_confidence:
        recommendations.append(high_confidence)
    return recommendations


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
        "description": f"{waste_percentage:.1f}% of total spend is potentially wasteful.",
        "action": (
            "Immediate review recommended" if priority == "high" else "Schedule review this week"
        ),
    }


def _top_service_card(zombies: pd.DataFrame) -> Recommendation | None:
    if len(zombies) == 0 or "ServiceCategory" not in zombies.columns:
        return None
    service_waste = zombies.groupby("ServiceCategory")["EffectiveCost"].sum()
    if len(service_waste) == 0:
        return None
    top_service = service_waste.idxmax()
    return {
        "priority": "high",
        "icon": "bi-funnel",
        "title": f"Focus Area: {top_service}",
        "description": f"Accounts for ${service_waste.max():,.2f} of total waste.",
        "action": f"Start optimization with {top_service} resources",
    }


def _high_confidence_card(zombies: pd.DataFrame) -> Recommendation | None:
    if len(zombies) == 0 or "confidence" not in zombies.columns:
        return None
    high_conf = int((zombies["confidence"] == "High").sum())
    if high_conf == 0:
        return None
    return {
        "priority": "medium",
        "icon": "bi-shield-check",
        "title": "High Confidence Detections",
        "description": f"{high_conf} resources with high confidence of being wasteful.",
        "action": "Review high confidence items first",
    }
