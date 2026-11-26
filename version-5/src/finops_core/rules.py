"""Rule-based zombie resource and architectural waste detectors.

Applies deterministic, highly explainable domain rules to resources:
1. Unattached / idle EBS Volumes (SIGNAL_UNATTACHED_EBS)
2. Idle Elastic / Application Load Balancers (SIGNAL_IDLE_ELB)
3. Stopped Compute Instances with ongoing charges (SIGNAL_STOPPED_INSTANCE)
4. Aged / abandoned Storage Snapshots (SIGNAL_OLD_SNAPSHOT)
5. Unassociated / idle Elastic IP Addresses (SIGNAL_IDLE_IP)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finops_core.models import (
    SIGNAL_IDLE_ELB,
    SIGNAL_IDLE_IP,
    SIGNAL_OLD_SNAPSHOT,
    SIGNAL_STOPPED_INSTANCE,
    SIGNAL_UNATTACHED_EBS,
)

SNAPSHOT_RETENTION_THRESHOLD_DAYS = 90


def detect_rule_signals(row: Mapping[Any, Any]) -> list[tuple[str, str]]:
    """Evaluate domain rules against one resource summary row.

    Returns a list of (signal_name, reason_explanation) tuples.
    """
    signals: list[tuple[str, str]] = []

    res_id = str(row.get("resource_id") or "").lower()
    res_name = str(row.get("resource_name") or "").lower()
    res_key = str(row.get("resource_key") or "").lower()
    service = str(row.get("service") or "").lower()
    total_cost = float(row.get("total_cost", 0.0))
    total_usage = float(row.get("total_usage", 0.0))
    days_active = int(row.get("days_active", 1))

    text_target = f"{res_id} {res_name} {res_key} {service}"

    has_valid_zero_usage = total_usage == 0 and not bool(row.get("any_usage_missing", False))

    # 1. Unattached EBS Volume (vol- prefix or volume/ebs in storage with zero usage)
    is_ebs = (
        res_id.startswith("vol-")
        or "vol-" in text_target
        or ("ebs" in text_target and "volume" in text_target)
        or (service in ("storage", "ebs") and "volume" in text_target)
    )
    if is_ebs and total_cost > 0 and has_valid_zero_usage:
        signals.append(
            (
                SIGNAL_UNATTACHED_EBS,
                f"Unattached EBS volume: billed ${total_cost:,.2f} over {days_active} day(s) "
                f"with zero read/write IOPS or usage",
            )
        )

    # 2. Idle Load Balancer (app/, net/, lb-, elb in network with zero usage or traffic)
    is_elb = (
        res_id.startswith("arn:aws:elasticloadbalancing")
        or res_id.startswith("app/")
        or res_id.startswith("net/")
        or "loadbalancer" in text_target
        or "elb" in text_target
        or (service in ("network", "networking") and "balancer" in text_target)
    )
    if is_elb and total_cost > 0 and has_valid_zero_usage:
        signals.append(
            (
                SIGNAL_IDLE_ELB,
                f"Idle load balancer: billed ${total_cost:,.2f} over {days_active} day(s) "
                f"with zero processed bytes or active request traffic",
            )
        )

    # 3. Stopped Compute Instance (i- prefix, vm-, instance in compute with zero usage but positive cost)
    is_compute = (
        res_id.startswith("i-")
        or res_id.startswith("vm-")
        or "instance" in text_target
        or "virtualmachine" in text_target
        or "virtual machine" in text_target
    )
    if is_compute and not is_ebs and total_cost > 0 and has_valid_zero_usage:
        signals.append(
            (
                SIGNAL_STOPPED_INSTANCE,
                f"Stopped compute instance: billed ${total_cost:,.2f} in persistent allocation "
                f"and attached storage with zero CPU hours utilized",
            )
        )

    # 4. Aged Snapshot (snap- prefix or snapshot in storage, active >= 90 days)
    is_snapshot = res_id.startswith("snap-") or "snapshot" in text_target
    if is_snapshot and total_cost > 0 and days_active >= SNAPSHOT_RETENTION_THRESHOLD_DAYS:
        signals.append(
            (
                SIGNAL_OLD_SNAPSHOT,
                f"Aged snapshot: active for {days_active} day(s) (>= {SNAPSHOT_RETENTION_THRESHOLD_DAYS}d limit) "
                f"accumulating ${total_cost:,.2f} in storage charges",
            )
        )

    # 5. Idle Elastic IP (eipalloc-, eip, ip- in network with zero usage)
    is_eip = (
        res_id.startswith("eipalloc-")
        or "elasticip" in text_target
        or ("publicipv4" in text_target and "idle" in text_target)
        or ("eip" in text_target and service in ("network", "vpc"))
    )
    if is_eip and not is_compute and total_cost > 0 and has_valid_zero_usage:
        signals.append(
            (
                SIGNAL_IDLE_IP,
                f"Unattached public IP address: billed ${total_cost:,.2f} for idle allocation",
            )
        )

    return signals
