"""Typed, immutable results produced by the analysis engine.

These are what the web app, the CLI and (later) the database consume. They
serialise cleanly with :func:`dataclasses.asdict`.
"""

from __future__ import annotations

from dataclasses import dataclass

ANALYSIS_VERSION = "phase1-resource-v1"
CONFIDENCE_LEVELS = ("High", "Medium", "Low")

# Signal names used in Finding.signals
SIGNAL_IDLE = "idle"
SIGNAL_OVERPRICED = "overpriced"
SIGNAL_ML_OUTLIER = "ml_outlier"
SIGNAL_UNATTACHED_EBS = "unattached_ebs"
SIGNAL_IDLE_ELB = "idle_elb"
SIGNAL_STOPPED_INSTANCE = "stopped_instance"
SIGNAL_OLD_SNAPSHOT = "old_snapshot"
SIGNAL_IDLE_IP = "idle_ip"

RULE_SIGNALS = (
    SIGNAL_UNATTACHED_EBS,
    SIGNAL_IDLE_ELB,
    SIGNAL_STOPPED_INSTANCE,
    SIGNAL_OLD_SNAPSHOT,
    SIGNAL_IDLE_IP,
)


@dataclass(frozen=True)
class Finding:
    """One resource that is probably wasting money, with the evidence."""

    resource_key: str
    resource_id: str | None
    resource_name: str | None
    service: str
    region: str | None
    account: str | None
    unit: str | None
    total_cost: float
    total_usage: float
    days_active: int
    estimated_waste: float
    estimated_monthly_waste: float
    confidence: str
    signals: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def label(self) -> str:
        """Human-friendly name for tables."""
        if self.resource_name or self.resource_id:
            return str(self.resource_name or self.resource_id)
        if self.resource_key.startswith("row:"):
            return f"{self.service} line item #{self.resource_key[4:]}"
        return self.resource_key.removeprefix("svc:").replace("|", " · ")


@dataclass(frozen=True)
class ForecastResult:
    """Daily spend forecast with an uncertainty band."""

    method: str
    dates: tuple[str, ...]
    values: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    backtest_mae: float | None
    backtest_mape: float | None = None
    fallback_reason: str | None = None

    @property
    def total(self) -> float:
        return float(sum(self.values))


@dataclass(frozen=True)
class AnalysisResult:
    """Everything one analysis run produces (no presentation formatting)."""

    analysis_version: str
    records: int
    resources: int
    period_start: str | None
    period_end: str | None
    period_days: int
    total_spend: float
    daily_dates: tuple[str, ...]
    daily_costs: tuple[float, ...]
    findings: tuple[Finding, ...]
    forecast: ForecastResult

    @property
    def total_waste(self) -> float:
        return float(sum(f.estimated_waste for f in self.findings))

    @property
    def waste_percentage(self) -> float:
        return self.total_waste / self.total_spend * 100 if self.total_spend > 0 else 0.0

    def confidence_summary(self) -> dict[str, int]:
        summary = dict.fromkeys(CONFIDENCE_LEVELS, 0)
        for finding in self.findings:
            summary[finding.confidence] += 1
        return summary

    def waste_by_service(self) -> dict[str, float]:
        """Estimated waste per service, largest first."""
        totals: dict[str, float] = {}
        for finding in self.findings:
            totals[finding.service] = totals.get(finding.service, 0.0) + finding.estimated_waste
        return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))
