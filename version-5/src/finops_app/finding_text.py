"""Words for a finding: what each signal means and what to do about it."""

from __future__ import annotations

from collections.abc import Sequence

from finops_core.models import SIGNAL_IDLE, SIGNAL_ML_OUTLIER, SIGNAL_OVERPRICED

SIGNAL_NAMES = {
    SIGNAL_IDLE: "Idle",
    SIGNAL_OVERPRICED: "Overpriced",
    SIGNAL_ML_OUTLIER: "Unusual pattern",
}
SIGNAL_MEANINGS = {
    SIGNAL_IDLE: "Billed on days with zero recorded usage.",
    SIGNAL_OVERPRICED: (
        "Pays at least 3× what similar resources pay per unit, and is a statistical "
        "outlier among them."
    ),
    SIGNAL_ML_OUTLIER: (
        "The anomaly model rates its cost-to-usage pattern as unusual. On its own this "
        "is weak evidence."
    ),
}
ACTIONS = {
    SIGNAL_IDLE: (
        "Stop or delete it. If it may be needed again, snapshot or export it first, " "then delete."
    ),
    SIGNAL_OVERPRICED: (
        "Right-size it or move it to a cheaper tier, region or pricing plan "
        "(reserved capacity or a savings plan) that matches its peers."
    ),
    SIGNAL_ML_OUTLIER: (
        "Check with its owner whether this usage is expected. If it is, mark it as a "
        "false positive so it stops showing up."
    ),
}


def signal_name(signal: str) -> str:
    return SIGNAL_NAMES.get(signal, signal.replace("_", " ").capitalize())


def recommended_action(signals: Sequence[str]) -> str:
    """The action for the strongest signal present."""
    for signal in (SIGNAL_IDLE, SIGNAL_OVERPRICED, SIGNAL_ML_OUTLIER):
        if signal in signals:
            return ACTIONS[signal]
    return "Review this resource's usage with its owner."


def explained_signals(signals: Sequence[str]) -> list[tuple[str, str]]:
    return [(signal_name(s), SIGNAL_MEANINGS.get(s, "")) for s in signals]
