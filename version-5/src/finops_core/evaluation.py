"""Model quality evaluation: Precision@k, confusion matrix, and waste realization.

Evaluates waste detection precision using human triage feedback:
* ``fixed`` or ``acknowledged`` -> confirmed true positive (label = 1)
* ``false_positive`` -> rejected (label = 0)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from finops_core.models import Finding


@dataclass(frozen=True)
class LabelledFinding:
    finding: Finding
    label: int  # 1 for confirmed waste (fixed/acknowledged), 0 for false_positive


def precision_at_k(items: Sequence[LabelledFinding], k: int) -> float:
    """Fraction of true waste in the top ``k`` highest-waste findings."""
    if not items or k <= 0:
        return 0.0
    sorted_items = sorted(
        items,
        key=lambda item: (-item.finding.estimated_waste, item.finding.resource_key),
    )
    top_k = sorted_items[:k]
    if not top_k:
        return 0.0
    positives = sum(item.label for item in top_k)
    return float(round(positives / len(top_k), 4))


def evaluate_ranking(
    items: Sequence[LabelledFinding],
    cutoffs: tuple[int, ...] = (5, 10, 20),
) -> dict[str, float]:
    """Calculate Precision@k across multiple cutoffs."""
    return {f"precision@{k}": precision_at_k(items, k) for k in cutoffs}


def confusion_metrics(items: Sequence[LabelledFinding]) -> dict[str, Any]:
    """Summary of True Positives, False Positives, and overall Precision."""
    total = len(items)
    if total == 0:
        return {
            "total_evaluated": 0,
            "true_positives": 0,
            "false_positives": 0,
            "precision": 0.0,
            "false_positive_rate": 0.0,
        }
    tp = sum(1 for item in items if item.label == 1)
    fp = sum(1 for item in items if item.label == 0)
    precision = round(tp / total, 4) if total > 0 else 0.0
    fpr = round(fp / total, 4) if total > 0 else 0.0
    return {
        "total_evaluated": total,
        "true_positives": tp,
        "false_positives": fp,
        "precision": precision,
        "false_positive_rate": fpr,
    }


def waste_realization(items: Sequence[LabelledFinding]) -> dict[str, float]:
    """Financial impact: predicted waste vs. confirmed and rejected waste."""
    total_waste = sum(item.finding.estimated_waste for item in items)
    confirmed_waste = sum(item.finding.estimated_waste for item in items if item.label == 1)
    rejected_waste = sum(item.finding.estimated_waste for item in items if item.label == 0)
    realization_rate = round(confirmed_waste / total_waste * 100.0, 2) if total_waste > 0 else 0.0
    return {
        "total_flagged_waste": round(total_waste, 2),
        "confirmed_real_waste": round(confirmed_waste, 2),
        "rejected_false_waste": round(rejected_waste, 2),
        "waste_realization_rate_pct": realization_rate,
    }
