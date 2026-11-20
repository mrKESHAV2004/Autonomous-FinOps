from __future__ import annotations

import pandas as pd
import pytest

from finops_core.recommendations import generate_recommendations

ZOMBIES = pd.DataFrame(
    {
        "ServiceCategory": ["Compute", "Compute", "Storage"],
        "EffectiveCost": [100.0, 50.0, 20.0],
        "confidence": ["High", "Low", "High"],
    }
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
    first = generate_recommendations(pd.DataFrame(), 0, waste_pct, 0)[0]
    assert first["title"] == title
    assert first["priority"] == priority


def test_all_four_cards_when_everything_applies() -> None:
    recs = generate_recommendations(ZOMBIES, 170.0, 12.0, forecast_savings=70.0)

    titles = [r["title"] for r in recs]
    assert titles == [
        "CRITICAL: Waste Level Detected",
        "Focus Area: Compute",
        "Significant Savings Potential",
        "High Confidence Detections",
    ]
    assert recs[1]["description"] == "Accounts for $150.00 of total waste."
    assert recs[2]["description"] == "$70 in 7 days ($300 monthly)."
    assert recs[3]["description"] == "2 resources with high confidence of being wasteful."


def test_only_severity_card_without_zombies_or_savings() -> None:
    assert len(generate_recommendations(pd.DataFrame(), 0, 0, 0)) == 1


def test_no_high_confidence_card_when_none_are_high() -> None:
    low = ZOMBIES.assign(confidence="Low")
    titles = [r["title"] for r in generate_recommendations(low, 1, 1, 0)]
    assert "High Confidence Detections" not in titles
