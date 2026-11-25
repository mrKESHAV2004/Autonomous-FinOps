"""Input contract for billing data (FOCUS-style CSV).

Required: a cost column and a usage-quantity column (common aliases accepted).
Optional: a date column and resource/service descriptors. Missing optional
columns degrade gracefully (e.g. resources fall back to service-level keys).
"""

from __future__ import annotations

import pandas as pd

from finops_core.errors import DataValidationError

# canonical name -> accepted aliases, in priority order
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "EffectiveCost": ("EffectiveCost", "Cost", "UnblendedCost", "BilledCost", "Amount"),
    "ConsumedQuantity": ("ConsumedQuantity", "UsageQuantity", "UsageAmount", "PricingQuantity"),
}
REQUIRED_COLUMNS = tuple(COLUMN_ALIASES)
DATE_COLUMNS = ("ChargePeriodStart", "UsageDateTime", "BillingPeriodStart", "UsageDate")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with canonical column names; raise if required ones are missing."""
    renames: dict[str, str] = {}
    missing: list[str] = []
    for canonical, aliases in COLUMN_ALIASES.items():
        if canonical in df.columns:
            continue
        found = next((a for a in aliases if a in df.columns), None)
        if found is None:
            missing.append(canonical)
        else:
            renames[found] = canonical
    if missing:
        accepted = "; ".join(f"{c}: {', '.join(COLUMN_ALIASES[c])}" for c in missing)
        raise DataValidationError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Expected FOCUS-style billing data (accepted names — {accepted})."
        )
    return df.rename(columns=renames)
