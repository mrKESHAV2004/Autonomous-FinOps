"""Words for a finding: what each signal means and what to do about it."""

from __future__ import annotations

from collections.abc import Sequence

from finops_core.models import (
    SIGNAL_IDLE,
    SIGNAL_IDLE_ELB,
    SIGNAL_IDLE_IP,
    SIGNAL_ML_OUTLIER,
    SIGNAL_OLD_SNAPSHOT,
    SIGNAL_OVERPRICED,
    SIGNAL_STOPPED_INSTANCE,
    SIGNAL_UNATTACHED_EBS,
)

SIGNAL_NAMES = {
    SIGNAL_IDLE: "Idle",
    SIGNAL_OVERPRICED: "Overpriced",
    SIGNAL_ML_OUTLIER: "Unusual pattern",
    SIGNAL_UNATTACHED_EBS: "Unattached EBS",
    SIGNAL_IDLE_ELB: "Idle load balancer",
    SIGNAL_STOPPED_INSTANCE: "Stopped instance",
    SIGNAL_OLD_SNAPSHOT: "Aged snapshot",
    SIGNAL_IDLE_IP: "Unattached Elastic IP",
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
    SIGNAL_UNATTACHED_EBS: (
        "Billed for block storage volume capacity while completely disconnected or idle with 0 IOPS."
    ),
    SIGNAL_IDLE_ELB: (
        "Billed hourly availability fees with zero processed bytes or active client requests."
    ),
    SIGNAL_STOPPED_INSTANCE: (
        "Stopped virtual machine incurring persistent storage and allocated IP charges with zero compute usage."
    ),
    SIGNAL_OLD_SNAPSHOT: (
        "Storage snapshot older than 90 days accumulating ongoing storage costs."
    ),
    SIGNAL_IDLE_IP: (
        "Public IPv4 address allocated to account but unattached to any running instance, incurring idle hourly charges."
    ),
}
ACTIONS = {
    SIGNAL_UNATTACHED_EBS: (
        "Snapshot the volume for archival if needed, then delete the unattached volume."
    ),
    SIGNAL_IDLE_ELB: (
        "Verify whether target groups have active instances. If obsolete, delete the load balancer."
    ),
    SIGNAL_STOPPED_INSTANCE: (
        "Terminate the instance if decommissioned, or downsize attached EBS volumes."
    ),
    SIGNAL_OLD_SNAPSHOT: (
        "Review retention policy and delete legacy snapshots or move to cold archive storage."
    ),
    SIGNAL_IDLE_IP: (
        "Release the unassociated Elastic IP back to the pool to stop recurring charges."
    ),
    SIGNAL_IDLE: (
        "Stop or delete it. If it may be needed again, snapshot or export it first, then delete."
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
    priority = (
        SIGNAL_UNATTACHED_EBS,
        SIGNAL_IDLE_ELB,
        SIGNAL_STOPPED_INSTANCE,
        SIGNAL_OLD_SNAPSHOT,
        SIGNAL_IDLE_IP,
        SIGNAL_IDLE,
        SIGNAL_OVERPRICED,
        SIGNAL_ML_OUTLIER,
    )
    for signal in priority:
        if signal in signals and signal in ACTIONS:
            return ACTIONS[signal]
    return "Review this resource's usage with its owner."


def explained_signals(signals: Sequence[str]) -> list[tuple[str, str]]:
    return [(signal_name(s), SIGNAL_MEANINGS.get(s, "")) for s in signals]
