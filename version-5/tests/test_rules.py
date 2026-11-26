from __future__ import annotations

import pandas as pd

from finops_core.models import (
    SIGNAL_IDLE,
    SIGNAL_IDLE_ELB,
    SIGNAL_IDLE_IP,
    SIGNAL_OLD_SNAPSHOT,
    SIGNAL_STOPPED_INSTANCE,
    SIGNAL_UNATTACHED_EBS,
)
from finops_core.resources import find_waste
from finops_core.rules import detect_rule_signals


def test_detect_unattached_ebs() -> None:
    row = {
        "resource_id": "vol-0123456789abcdef0",
        "resource_name": "backup-volume",
        "service": "Storage",
        "total_cost": 45.0,
        "total_usage": 0.0,
        "days_active": 30,
    }
    signals = detect_rule_signals(row)
    assert len(signals) == 1
    assert signals[0][0] == SIGNAL_UNATTACHED_EBS
    assert "Unattached EBS volume" in signals[0][1]


def test_detect_idle_elb() -> None:
    row = {
        "resource_id": "app/my-alb/50dc6c495c0c9188",
        "resource_name": "staging-loadbalancer",
        "service": "Network",
        "total_cost": 22.5,
        "total_usage": 0.0,
        "days_active": 30,
    }
    signals = detect_rule_signals(row)
    assert len(signals) == 1
    assert signals[0][0] == SIGNAL_IDLE_ELB
    assert "Idle load balancer" in signals[0][1]


def test_detect_stopped_instance() -> None:
    row = {
        "resource_id": "i-0987654321fedcba0",
        "resource_name": "worker-stopped",
        "service": "Compute",
        "total_cost": 35.0,
        "total_usage": 0.0,
        "days_active": 15,
    }
    signals = detect_rule_signals(row)
    assert len(signals) == 1
    assert signals[0][0] == SIGNAL_STOPPED_INSTANCE
    assert "Stopped compute instance" in signals[0][1]


def test_detect_old_snapshot() -> None:
    row = {
        "resource_id": "snap-01122334455667788",
        "resource_name": "archive-snap-2023",
        "service": "Storage",
        "total_cost": 15.0,
        "total_usage": 100.0,
        "days_active": 120,
    }
    signals = detect_rule_signals(row)
    assert len(signals) == 1
    assert signals[0][0] == SIGNAL_OLD_SNAPSHOT
    assert "Aged snapshot" in signals[0][1]


def test_detect_idle_ip() -> None:
    row = {
        "resource_id": "eipalloc-01234567",
        "resource_name": "unused-elastic-ip",
        "service": "Network",
        "total_cost": 7.30,
        "total_usage": 0.0,
        "days_active": 30,
    }
    signals = detect_rule_signals(row)
    assert len(signals) == 1
    assert signals[0][0] == SIGNAL_IDLE_IP
    assert "Unattached public IP" in signals[0][1]


def test_find_waste_integrates_rule_signals() -> None:
    df = pd.DataFrame(
        [
            {
                "UsageDate": "2024-01-01",
                "ServiceCategory": "Storage",
                "ResourceId": "vol-001a2b3c4d",
                "EffectiveCost": 50.0,
                "ConsumedQuantity": 0.0,
            },
            {
                "UsageDate": "2024-01-02",
                "ServiceCategory": "Storage",
                "ResourceId": "vol-001a2b3c4d",
                "EffectiveCost": 50.0,
                "ConsumedQuantity": 0.0,
            },
        ]
    )
    findings = find_waste(df, period_days=2)
    assert len(findings) == 1
    f = findings[0]
    assert f.confidence == "High"
    assert SIGNAL_IDLE in f.signals
    assert SIGNAL_UNATTACHED_EBS in f.signals
    assert f.estimated_waste == 100.0
