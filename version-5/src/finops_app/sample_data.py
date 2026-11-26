"""A small, realistic FOCUS-style billing file for first-time users.

30 days of 24 resources; a few are idle (billed with zero usage) and a few
pay far more per unit than their peers, so the sample has findings to triage.
"""

from __future__ import annotations

import csv
import io
import random
from datetime import date, timedelta

SERVICES = ("Compute", "Storage", "Database", "Network")
REGIONS = ("us-east-1", "eu-west-1", "ap-south-1")
ACCOUNTS = ("prod-001", "dev-002")
RESOURCES = 24
DAYS = 30
IDLE = {3, 11, 19}
OVERPRICED = {6, 14, 22}
HEADER = (
    "UsageDate", "ServiceCategory", "EffectiveCost", "ConsumedQuantity",
    "ResourceId", "RegionId", "SubAccountId",
)  # fmt: skip


def sample_csv() -> str:
    # Seeded so the sample is the same every time; not used for anything secret.
    rng = random.Random(42)  # noqa: S311  # nosec B311
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADER)
    start = date(2024, 1, 1)
    for day in range(DAYS):
        for i in range(RESOURCES):
            usage = round(rng.uniform(40, 120), 2)
            cost = round(usage * rng.uniform(0.9, 1.1) * (1 + i % 4) / 4, 2)
            if i in IDLE:
                usage = 0.0
            if i in OVERPRICED:
                cost, usage = round(cost * 8, 2), round(usage * 0.4, 2)
            writer.writerow(
                (
                    (start + timedelta(days=day)).isoformat(),
                    SERVICES[i % len(SERVICES)],
                    cost,
                    usage,
                    f"res-{i:03d}",
                    REGIONS[i % len(REGIONS)],
                    ACCOUNTS[i % len(ACCOUNTS)],
                )
            )
    return out.getvalue()
