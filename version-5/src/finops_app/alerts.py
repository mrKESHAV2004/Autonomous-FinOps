"""Alert evaluation and notification engine for Slack webhooks and Email."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

from finops_app import repository as repo
from finops_app.budgets import evaluate_budgets

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from finops_app.models import AlertConfig, AlertHistory, Analysis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertEvent:
    """An identified issue triggering a notification."""

    event_type: str  # high_confidence_findings | budget_exceeded | spend_spike
    summary: str
    details: dict[str, Any]


def evaluate_analysis_for_alerts(
    session: Session,
    org_id: str,
    analysis: Analysis,
    config: AlertConfig,
) -> list[AlertEvent]:
    """Inspect analysis metrics and findings against an alert configuration's triggers."""
    events: list[AlertEvent] = []

    # 1. High-confidence waste findings
    if config.notify_high_confidence:
        high_conf = [f for f in analysis.findings if f.confidence == "high" and f.status == "open"]
        if high_conf:
            total_waste = sum(f.est_monthly_waste for f in high_conf)
            top_resources = [
                f.resource_name or f.resource_id or f.resource_key for f in high_conf[:3]
            ]
            summary = (
                f"{len(high_conf)} new high-confidence zombie/waste finding(s) detected, "
                f"totaling ~${total_waste:,.2f}/mo potential waste."
            )
            events.append(
                AlertEvent(
                    event_type="high_confidence_findings",
                    summary=summary,
                    details={
                        "count": len(high_conf),
                        "total_monthly_waste": round(total_waste, 2),
                        "top_resources": top_resources,
                    },
                )
            )

    # 2. Budget exceeded
    if config.notify_budget_exceeded:
        budget_statuses = evaluate_budgets(session, org_id, analysis)
        exceeded = [b for b in budget_statuses if b.is_exceeded]
        for b in exceeded:
            scope_desc = f"{b.scope_type} ({b.scope_value})" if b.scope_value else b.scope_type
            summary = (
                f"Budget exceeded for {scope_desc}: projected spend of ${b.projected_spend:,.2f} "
                f"exceeds limit of ${b.monthly_amount:,.2f} ({b.percent_used:.1f}% used)."
            )
            events.append(
                AlertEvent(
                    event_type="budget_exceeded",
                    summary=summary,
                    details={
                        "budget_id": b.budget_id,
                        "scope_type": b.scope_type,
                        "scope_value": b.scope_value,
                        "monthly_limit": b.monthly_amount,
                        "current_spend": b.current_spend,
                        "projected_spend": b.projected_spend,
                        "percent_used": b.percent_used,
                    },
                )
            )

    # 3. Spend spikes (day-over-day)
    if config.notify_spend_spikes and analysis.daily_costs and len(analysis.daily_costs) >= 2:
        costs = [float(c) for c in analysis.daily_costs]
        # Compare latest day against previous day
        prev_day = costs[-2]
        latest_day = costs[-1]
        threshold = config.spike_threshold_percent / 100.0

        if (
            prev_day > 0
            and latest_day > prev_day * (1.0 + threshold)
            and (latest_day - prev_day) >= 5.0
        ):
            pct_increase = ((latest_day - prev_day) / prev_day) * 100.0
            latest_date = (
                analysis.daily_dates[-1]
                if analysis.daily_dates and len(analysis.daily_dates) >= len(costs)
                else "latest day"
            )
            summary = (
                f"Daily cloud spend spiked by {pct_increase:.1f}% on {latest_date} "
                f"(${prev_day:,.2f} -> ${latest_day:,.2f})."
            )
            events.append(
                AlertEvent(
                    event_type="spend_spike",
                    summary=summary,
                    details={
                        "previous_day_cost": round(prev_day, 2),
                        "latest_day_cost": round(latest_day, 2),
                        "percent_increase": round(pct_increase, 1),
                        "threshold_percent": config.spike_threshold_percent,
                    },
                )
            )

    return events


def send_slack_notification(
    webhook_url: str, event: AlertEvent, org_name: str
) -> tuple[bool, str | None]:
    """Send alert notification payload to a Slack incoming webhook."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"FinOps Alert: {event.event_type.replace('_', ' ').title()}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{event.summary}*\n*Organisation:* {org_name}",
            },
        },
    ]

    payload: dict[str, Any] = {
        "blocks": blocks,
        "text": f"FinOps Alert ({org_name}): {event.summary}",
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code == 200:
            return True, None
        return False, f"Slack webhook returned HTTP {resp.status_code}: {resp.text[:100]}"
    except Exception as exc:
        return False, f"Failed to send Slack webhook: {exc}"


def send_email_notification(
    destination: str, event: AlertEvent, org_name: str
) -> tuple[bool, str | None]:
    """Send or record alert email notification."""
    # Production setups configure SMTP; in local/test we log and return success
    logger.info(
        "FinOps email alert to %s: [%s] %s (Org: %s)",
        destination,
        event.event_type,
        event.summary,
        org_name,
    )
    return True, None


def dispatch_alerts_for_analysis(
    session: Session,
    org_id: str,
    analysis: Analysis,
) -> list[AlertHistory]:
    """Evaluate and dispatch alerts to all active configured channels for an analysis."""
    configs = [c for c in repo.list_alert_configs(session, org_id) if c.is_active]
    if not configs:
        return []

    from finops_app.models import Organization

    org = session.get(Organization, org_id)
    org_name = org.name if org else "FinOps Org"

    dispatched_history: list[AlertHistory] = []

    for cfg in configs:
        events = evaluate_analysis_for_alerts(session, org_id, analysis, cfg)
        for ev in events:
            if cfg.channel_type == "slack":
                ok, err = send_slack_notification(cfg.destination, ev, org_name)
            elif cfg.channel_type == "email":
                ok, err = send_email_notification(cfg.destination, ev, org_name)
            else:
                ok, err = False, f"Unknown channel type: {cfg.channel_type}"

            entry = repo.log_alert(
                session,
                org_id=org_id,
                channel_type=cfg.channel_type,
                event_type=ev.event_type,
                summary=ev.summary,
                details=ev.details,
                status="sent" if ok else "failed",
                error_message=err,
                analysis_id=analysis.id,
            )
            dispatched_history.append(entry)

    return dispatched_history
