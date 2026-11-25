from __future__ import annotations

import math

import pandas as pd
import pytest

from finops_core.resources import (
    OUTLIER_Z,
    add_peer_medians,
    find_waste,
    resource_keys,
    summarise_resources,
)


def rows(*items: dict[str, object]) -> pd.DataFrame:
    defaults = {
        "UsageDate": pd.Timestamp("2024-01-01"),
        "ServiceCategory": "Compute",
        "ConsumedUnit": "Hours",
        "RegionId": "us-east-1",
        "SubAccountId": "111",
        "ServiceName": "EC2",
        "UsageMissing": False,
    }
    return pd.DataFrame([{**defaults, **item} for item in items])


def peers(n: int = 6, price: float = 1.0) -> list[dict[str, object]]:
    """n normally-priced resources with slightly varied prices."""
    return [
        {"ResourceId": f"ok-{i}", "EffectiveCost": price * (10 + i * 0.1), "ConsumedQuantity": 10}
        for i in range(n)
    ]


def test_resource_key_prefers_resource_id() -> None:
    df = rows({"ResourceId": "i-1", "EffectiveCost": 1, "ConsumedQuantity": 1})
    assert resource_keys(df).tolist() == ["i-1"]


def test_resource_key_falls_back_to_service_region_account() -> None:
    df = rows({"ResourceId": "  ", "EffectiveCost": 1, "ConsumedQuantity": 1})
    assert resource_keys(df).tolist() == ["svc:EC2|us-east-1|111"]


def test_resource_key_is_per_row_without_any_identifiers() -> None:
    df = pd.DataFrame({"EffectiveCost": [1.0, 2.0], "ConsumedQuantity": [1.0, 1.0]})
    assert resource_keys(df).tolist() == ["row:0", "row:1"]


def test_summary_aggregates_rows_per_resource() -> None:
    df = rows(
        {"ResourceId": "i-1", "EffectiveCost": 2.0, "ConsumedQuantity": 1.0},
        {"ResourceId": "i-1", "EffectiveCost": 3.0, "ConsumedQuantity": 4.0,
         "UsageDate": pd.Timestamp("2024-01-02")},
    )  # fmt: skip
    summary = summarise_resources(df).set_index("resource_key")

    assert summary.loc["i-1", "total_cost"] == 5.0
    assert summary.loc["i-1", "total_usage"] == 5.0
    assert summary.loc["i-1", "days_active"] == 2
    assert summary.loc["i-1", "cost_per_unit"] == 1.0


def test_idle_resource_is_high_confidence_full_waste() -> None:
    df = rows(*peers(), {"ResourceId": "idle", "EffectiveCost": 40.0, "ConsumedQuantity": 0.0})

    (finding,) = find_waste(df, period_days=10)

    assert finding.resource_key == "idle"
    assert finding.signals == ("idle",)
    assert finding.confidence == "High"
    assert finding.estimated_waste == 40.0
    assert finding.estimated_monthly_waste == pytest.approx(120.0)
    assert "zero usage" in finding.reasons[0]


def test_missing_usage_is_not_treated_as_idle() -> None:
    df = rows(
        *peers(),
        {"ResourceId": "unknown", "EffectiveCost": 40.0, "ConsumedQuantity": 0.0,
         "UsageMissing": True},
    )  # fmt: skip
    assert find_waste(df, period_days=10) == ()


def test_overpriced_resource_waste_is_cost_above_peer_median() -> None:
    expensive = {"ResourceId": "pricey", "EffectiveCost": 200.0, "ConsumedQuantity": 10}
    df = rows(*peers(), expensive)

    (finding,) = find_waste(df, period_days=30)

    median_price = summarise_resources(df)["cost_per_unit"].median()
    assert finding.signals == ("overpriced",)
    assert finding.confidence == "Medium"
    assert finding.estimated_waste == pytest.approx(200.0 - 10 * median_price, rel=1e-6)
    assert "similar Compute resources" in finding.reasons[0]


def test_overpriced_and_ml_flag_is_high_confidence() -> None:
    df = rows(*peers(), {"ResourceId": "pricey", "EffectiveCost": 200.0, "ConsumedQuantity": 10})
    (finding,) = find_waste(df, period_days=30, ml_scores={"pricey": 0.97})
    assert finding.signals == ("overpriced", "ml_outlier")
    assert finding.confidence == "High"


def test_ml_flag_alone_is_low_confidence() -> None:
    df = rows(*peers(), {"ResourceId": "odd", "EffectiveCost": 15.0, "ConsumedQuantity": 10})
    (finding,) = find_waste(df, period_days=30, ml_scores={"odd": 0.9})
    assert finding.signals == ("ml_outlier",)
    assert finding.confidence == "Low"


def test_no_peers_means_no_overpriced_signal() -> None:
    df = rows(
        {"ResourceId": "a", "EffectiveCost": 1.0, "ConsumedQuantity": 1},
        {"ResourceId": "b", "EffectiveCost": 100.0, "ConsumedQuantity": 1},
    )
    assert find_waste(df, period_days=10) == ()


def test_wide_natural_price_range_is_not_flagged_wholesale() -> None:
    # Prices spread over two orders of magnitude: 3x the median is normal here.
    spread = [
        {"ResourceId": f"r{i}", "EffectiveCost": float(p), "ConsumedQuantity": 1}
        for i, p in enumerate([1, 2, 4, 8, 16, 32, 64, 128])
    ]
    assert find_waste(rows(*spread), period_days=10) == ()


def test_peer_z_is_infinite_when_all_peers_share_one_price() -> None:
    same_price = [
        {"ResourceId": f"p{i}", "EffectiveCost": 10.0, "ConsumedQuantity": 10} for i in range(4)
    ]
    df = rows(*same_price, {"ResourceId": "x", "EffectiveCost": 50.0, "ConsumedQuantity": 10})

    z = add_peer_medians(summarise_resources(df)).set_index("resource_key")["peer_z"]

    assert math.isinf(z["x"]) and z["x"] > OUTLIER_Z
    assert z["p0"] == 0.0
    (finding,) = find_waste(df, period_days=10)
    assert finding.resource_key == "x" and finding.signals == ("overpriced",)


def test_findings_sorted_by_waste() -> None:
    df = rows(
        *peers(),
        {"ResourceId": "small", "EffectiveCost": 5.0, "ConsumedQuantity": 0.0},
        {"ResourceId": "big", "EffectiveCost": 50.0, "ConsumedQuantity": 0.0},
    )
    assert [f.resource_key for f in find_waste(df, period_days=10)] == ["big", "small"]
