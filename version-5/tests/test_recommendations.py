from __future__ import annotations

import pytest

from factories import finding
from finops_core.recommendations import generate_recommendations

FINDINGS = (
    finding(resource_key="a", service="Compute", estimated_waste=100.0, confidence="High"),
    finding(resource_key="b", service="Compute", estimated_waste=50.0, confidence="Low"),
    finding(resource_key="c", service="Storage", estimated_waste=20.0, confidence="High"),
)


@pytest.mark.parametrize(
    ("waste_pct", "title", "priority"),
    [
        (12.0, "CRITICAL: Waste Level Detected", "high"),
        (7.0, "HIGH: Waste Level Detected", "high"),
        (5.0, "MODERATE: Waste Level Detected", "medium"),
    ],
)
def test_severity_thresholds(waste_pct: float, title: str, priority: str) -> None:
    first = generate_recommendations((), waste_pct, 0)[0]
    assert first["title"] == title
    assert first["priority"] == priority


def test_cards_in_priority_order() -> None:
    recs = generate_recommendations(FINDINGS, 12.0, forecast_savings=70.0)

    assert [r["title"] for r in recs] == [
        "CRITICAL: Waste Level Detected",
        "Focus Area: Compute",
        "Significant Savings Potential",
        "High Confidence Detections",
    ]
    assert recs[1]["description"] == "Accounts for $150.00 of estimated waste."
    assert recs[2]["description"] == "$70 in 7 days ($300 monthly)."
    assert recs[3]["description"] == "2 resources with strong evidence of waste."


def test_idle_card_when_idle_resources_found() -> None:
    idle = (finding(signals=("idle",), estimated_waste=40.0, confidence="High"),)
    titles = [r["title"] for r in generate_recommendations(idle, 1.0, 0)]
    assert "1 Idle Resource" in titles


def test_only_severity_card_without_findings_or_savings() -> None:
    assert len(generate_recommendations((), 0, 0)) == 1


def test_no_high_confidence_card_when_none_are_high() -> None:
    low = tuple(finding(resource_key=k, confidence="Low") for k in "xy")
    titles = [r["title"] for r in generate_recommendations(low, 1, 0)]
    assert "High Confidence Detections" not in titles
