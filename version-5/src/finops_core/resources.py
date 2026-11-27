"""Resource-level waste detection.

Rows are grouped into resources (``ResourceId``, or service + region + account
when there is no id). Each resource is then checked against explicit signals:

* **idle** — billed, with usage recorded as zero on every row
  (waste = the full cost);
* **overpriced** — cost per unit at least ``OVERPRICE_RATIO``× the median of
  similar resources (same service category and usage unit, at least
  ``MIN_PEERS`` of them) *and* a robust outlier among them (modified z-score
  of log price >= ``OUTLIER_Z``), so naturally wide price ranges are not
  flagged wholesale (waste = cost above the peer median);
* **ml_outlier** — at least one of its rows was flagged High confidence by the
  row-level Isolation Forest ensemble (supporting evidence; waste = cost above
  the peer median, if any).

Confidence: High = idle, or overpriced *and* ml_outlier; Medium = overpriced;
Low = ml_outlier only. A resource with no estimated waste is not reported.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from typing import Any

import numpy as np
import pandas as pd

from finops_core.models import (
    SIGNAL_IDLE,
    SIGNAL_ML_OUTLIER,
    SIGNAL_OLD_SNAPSHOT,
    SIGNAL_OVERPRICED,
    Finding,
)
from finops_core.rules import detect_rule_signals

OVERPRICE_RATIO = 3.0
OUTLIER_Z = 3.5  # Iglewicz & Hoaglin's recommended modified z-score cut-off
MAD_SCALE = 0.6745  # makes MAD-based z comparable to a normal z-score
MIN_PEERS = 3
MIN_REPORTED_WASTE = 0.01
DAYS_PER_MONTH = 30
FALLBACK_KEY_COLUMNS = ("ServiceName", "RegionId", "SubAccountId")
ROW_KEY_PREFIX = "row:"
UNKNOWN_SERVICE = "Unknown"


def resource_keys(df: pd.DataFrame) -> pd.Series:
    """Stable key per row.

    The ResourceId; else ``svc:<service>|<region>|<account>``; else, when the
    file has no resource or account columns at all, each line item is its own
    resource (``row:<n>``) so it can still be compared with its service peers.
    """
    fallback_cols = [c for c in FALLBACK_KEY_COLUMNS if c in df.columns]
    if fallback_cols:
        joined = df[fallback_cols].astype("string").fillna("-").agg("|".join, axis=1)
        fallback = "svc:" + joined
    else:
        fallback = pd.Series([f"{ROW_KEY_PREFIX}{i}" for i in range(len(df))], index=df.index)
    fallback = fallback.astype("string")

    if "ResourceId" not in df.columns:
        return fallback
    ids = _blank_to_na(df["ResourceId"])
    return ids.fillna(fallback)


def summarise_resources(df: pd.DataFrame) -> pd.DataFrame:
    """One row per resource with cost, usage and descriptive columns."""
    usage_missing = (
        df["UsageMissing"] if "UsageMissing" in df.columns else pd.Series(False, index=df.index)
    )
    work = pd.DataFrame(
        {
            "resource_key": resource_keys(df),
            "cost": df["EffectiveCost"].astype(float),
            "usage": df["ConsumedQuantity"].where(~usage_missing, 0.0).astype(float),
            "usage_missing": usage_missing.astype(bool),
            "day": df["UsageDate"] if "UsageDate" in df.columns else 0,
            "service": _text_column(df, "ServiceCategory").fillna(UNKNOWN_SERVICE),
            "resource_id": _text_column(df, "ResourceId"),
            "resource_name": _text_column(df, "ResourceName"),
            "region": _text_column(df, "RegionId"),
            "account": _text_column(df, "SubAccountId"),
            "unit": _text_column(df, "ConsumedUnit"),
        }
    )
    first = "first"  # first non-null value in each group
    summary = work.groupby("resource_key", sort=True).agg(
        total_cost=("cost", "sum"),
        total_usage=("usage", "sum"),
        any_usage_missing=("usage_missing", "any"),
        days_active=("day", "nunique"),
        service=("service", first),
        resource_id=("resource_id", first),
        resource_name=("resource_name", first),
        region=("region", first),
        account=("account", first),
        unit=("unit", first),
    )
    summary["cost_per_unit"] = np.where(
        summary["total_usage"] > 0, summary["total_cost"] / summary["total_usage"], np.nan
    )
    return summary.reset_index()


def add_peer_medians(summary: pd.DataFrame) -> pd.DataFrame:
    """Add peer statistics for cost-per-unit within the same service + unit.

    ``peer_median`` / ``peer_count`` and ``peer_z``: the modified z-score
    (Iglewicz & Hoaglin) of log cost-per-unit, using the median absolute
    deviation. ``inf`` when all peers share one price and this one is higher.
    """
    groups = [summary["service"], summary["unit"].fillna("")]
    priced = summary["cost_per_unit"]
    log_price = np.log(priced)
    log_median = log_price.groupby(groups).transform("median")
    mad = (log_price - log_median).abs().groupby(groups).transform("median")
    deviation = log_price - log_median
    peer_z = np.where(
        mad > 0,
        MAD_SCALE * deviation / mad.where(mad > 0, 1.0),
        np.where(deviation > 0, np.inf, 0.0),
    )
    return summary.assign(
        peer_median=priced.groupby(groups).transform("median"),
        peer_count=priced.groupby(groups).transform("count"),
        peer_z=peer_z,
    )


def find_waste(
    df: pd.DataFrame,
    period_days: int,
    ml_scores: Mapping[str, float] | None = None,
) -> tuple[Finding, ...]:
    """Return findings sorted by estimated waste (largest first).

    ``ml_scores`` maps resource_key -> highest row anomaly probability for
    resources the row-level ensemble flagged with High confidence.
    """
    scores = dict(ml_scores or {})
    summary = add_peer_medians(summarise_resources(df))
    months = max(period_days, 1) / DAYS_PER_MONTH
    findings = [
        finding
        for row in summary.to_dict("records")
        if (finding := _evaluate(row, scores.get(row["resource_key"]), months)) is not None
    ]
    return tuple(sorted(findings, key=lambda f: (-f.estimated_waste, f.resource_key)))


def _evaluate(row: Mapping[Hashable, Any], ml_score: float | None, months: float) -> Finding | None:
    cost, usage = float(row["total_cost"]), float(row["total_usage"])
    unit = row["unit"] or "unit"
    idle = usage == 0 and not row["any_usage_missing"] and cost > 0
    has_peers = row["peer_count"] >= MIN_PEERS and pd.notna(row["cost_per_unit"])
    ratio = row["cost_per_unit"] / row["peer_median"] if has_peers and row["peer_median"] else 0
    overpriced = bool(has_peers and ratio >= OVERPRICE_RATIO and row["peer_z"] >= OUTLIER_Z)

    signals: list[str] = []
    reasons: list[str] = []
    if idle:
        signals.append(SIGNAL_IDLE)
        reasons.append(f"Billed ${cost:,.2f} over {row['days_active']} day(s) with zero usage")

    rule_results = detect_rule_signals(row)
    has_rules = len(rule_results) > 0
    snapshot_only = has_rules and all(s[0] == SIGNAL_OLD_SNAPSHOT for s in rule_results) and not idle
    for r_sig, r_rsn in rule_results:
        signals.append(r_sig)
        reasons.append(r_rsn)

    if overpriced:
        signals.append(SIGNAL_OVERPRICED)
        reasons.append(
            f"Pays ${row['cost_per_unit']:,.4f} per {unit}, {ratio:.1f}× the median of "
            f"{int(row['peer_count'])} similar {row['service']} resources"
        )
    if ml_score is not None:
        signals.append(SIGNAL_ML_OUTLIER)
        reasons.append(f"Unusual cost/usage pattern (anomaly score {ml_score:.2f})")
    if not signals:
        return None

    if idle or (has_rules and not snapshot_only):
        waste = cost
    elif snapshot_only:
        waste = round(cost * 0.75, 6)
    elif has_peers:
        waste = max(cost - usage * float(row["peer_median"]), 0.0)
    else:
        waste = 0.0
    if waste < MIN_REPORTED_WASTE:
        return None

    return Finding(
        resource_key=str(row["resource_key"]),
        resource_id=_or_none(row["resource_id"]),
        resource_name=_or_none(row["resource_name"]),
        service=str(row["service"]),
        region=_or_none(row["region"]),
        account=_or_none(row["account"]),
        unit=_or_none(row["unit"]),
        total_cost=round(cost, 6),
        total_usage=round(usage, 6),
        days_active=int(row["days_active"]),
        estimated_waste=round(waste, 6),
        estimated_monthly_waste=round(waste / months, 6),
        confidence=_confidence(
            idle, overpriced, ml_score is not None, has_rules, snapshot_only=snapshot_only
        ),
        signals=tuple(signals),
        reasons=tuple(reasons),
    )


def _confidence(
    idle: bool,
    overpriced: bool,
    ml_flagged: bool,
    has_rules: bool = False,
    snapshot_only: bool = False,
) -> str:
    if (has_rules and not snapshot_only) or idle or (overpriced and ml_flagged):
        return "High"
    if overpriced or (has_rules and snapshot_only):
        return "Medium"
    return "Low"


def _text_column(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return _blank_to_na(df[name])


def _blank_to_na(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return text.mask(text == "")


def _or_none(value: Any) -> str | None:
    return None if value is None or pd.isna(value) else str(value)
