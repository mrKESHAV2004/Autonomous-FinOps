from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from finops_app import repository as repo
from finops_app.alerts import (
    AlertEvent,
    dispatch_alerts_for_analysis,
    evaluate_analysis_for_alerts,
    send_slack_notification,
)
from finops_app.budgets import evaluate_budget
from finops_app.db import Database, upgrade
from finops_app.models import (
    AlertConfig,
    Analysis,
    Budget,
    Dataset,
    Finding,
    Organization,
)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    upgrade(url)
    database = Database(url)
    yield database
    database.dispose()


def test_evaluate_budget_total() -> None:
    budget = Budget(
        id="b1",
        org_id="org1",
        scope_type="total",
        scope_value=None,
        monthly_amount=1000.0,
    )
    analysis = Analysis(
        id="a1",
        org_id="org1",
        total_spend=800.0,
        period_days=20,
    )
    # total_spend=800 over 20 days -> 40/day * 30 = 1200 projected -> exceeds 1000
    status = evaluate_budget(budget, analysis)
    assert status.scope_type == "total"
    assert status.current_spend == 800.0
    assert status.projected_spend == 1200.0
    assert status.percent_used == 80.0
    assert status.is_exceeded is True


def test_evaluate_budget_service() -> None:
    budget = Budget(
        id="b2",
        org_id="org1",
        scope_type="service",
        scope_value="AmazonEC2",
        monthly_amount=500.0,
    )
    f1 = Finding(
        id="f1",
        org_id="org1",
        analysis_id="a1",
        rank=1,
        resource_key="ec2-1",
        service="AmazonEC2",
        total_cost=200.0,
        total_usage=100.0,
        days_active=30,
        est_waste=50.0,
        est_monthly_waste=50.0,
        confidence="high",
        signals=[],
        reasons=[],
    )
    f2 = Finding(
        id="f2",
        org_id="org1",
        analysis_id="a1",
        rank=2,
        resource_key="s3-1",
        service="AmazonS3",
        total_cost=300.0,
        total_usage=100.0,
        days_active=30,
        est_waste=100.0,
        est_monthly_waste=100.0,
        confidence="high",
        signals=[],
        reasons=[],
    )
    analysis = Analysis(
        id="a1",
        org_id="org1",
        total_spend=1000.0,
        period_days=30,
    )
    analysis.findings = [f1, f2]
    status = evaluate_budget(budget, analysis)
    assert status.current_spend == 200.0
    assert status.projected_spend == 200.0
    assert status.percent_used == 40.0
    assert status.is_exceeded is False


def test_alert_evaluation_triggers(db: Database) -> None:
    with db.session() as session:
        org = Organization(slug="alert-org", name="Alert Org")
        session.add(org)
        session.flush()

        ds = Dataset(
            org_id=org.id,
            original_filename="test.csv",
            storage_key="test-key-1",
            size_bytes=100,
            row_count=10,
        )
        session.add(ds)
        session.flush()

        analysis = Analysis(
            org_id=org.id,
            dataset_id=ds.id,
            total_spend=5000.0,
            period_days=30,
            daily_dates=["2026-11-20", "2026-11-21", "2026-11-22"],
            daily_costs=[100.0, 110.0, 250.0],  # 250 vs 110 is > 100% spike
        )
        session.add(analysis)
        session.flush()

        finding = Finding(
            org_id=org.id,
            analysis_id=analysis.id,
            rank=1,
            resource_key="zombie-inst",
            resource_id="i-12345",
            service="AmazonEC2",
            total_cost=500.0,
            total_usage=0.0,
            days_active=30,
            est_waste=500.0,
            est_monthly_waste=500.0,
            confidence="high",
            status="open",
            signals=["idle"],
            reasons=["Zero usage recorded"],
        )
        session.add(finding)
        analysis.findings = [finding]

        # Budget of $2000 vs $5000 spend
        repo.upsert_budget(session, org.id, "total", None, 2000.0)

        cfg = AlertConfig(
            org_id=org.id,
            channel_type="slack",
            destination="https://hooks.slack.com/services/test",
            notify_high_confidence=True,
            notify_budget_exceeded=True,
            notify_spend_spikes=True,
            spike_threshold_percent=20.0,
        )

        events = evaluate_analysis_for_alerts(session, org.id, analysis, cfg)
        event_types = [e.event_type for e in events]

        assert "high_confidence_findings" in event_types
        assert "budget_exceeded" in event_types
        assert "spend_spike" in event_types


def test_send_slack_notification() -> None:
    event = AlertEvent(
        event_type="high_confidence_findings",
        summary="3 high confidence waste findings",
        details={"count": 3},
    )
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok, err = send_slack_notification("https://hooks.slack.com/test", event, "Acme Corp")
        assert ok is True
        assert err is None
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert "Acme Corp" in call_kwargs["json"]["text"]


def test_dispatch_alerts_for_analysis(db: Database) -> None:
    with db.session() as session:
        org = Organization(slug="dispatch-org", name="Dispatch Org")
        session.add(org)
        session.flush()

        ds = Dataset(
            org_id=org.id,
            original_filename="test2.csv",
            storage_key="test-key-2",
            size_bytes=100,
            row_count=10,
        )
        session.add(ds)
        session.flush()

        analysis = Analysis(
            org_id=org.id,
            dataset_id=ds.id,
            total_spend=1500.0,
            period_days=30,
        )
        session.add(analysis)
        session.flush()

        finding = Finding(
            org_id=org.id,
            analysis_id=analysis.id,
            rank=1,
            resource_key="res-test",
            service="AmazonS3",
            total_cost=300.0,
            total_usage=0.0,
            days_active=30,
            est_waste=300.0,
            est_monthly_waste=300.0,
            confidence="high",
            status="open",
            signals=["idle"],
            reasons=["Unused bucket"],
        )
        session.add(finding)
        analysis.findings = [finding]

        repo.save_alert_config(
            session,
            org.id,
            channel_type="email",
            destination="finops-alerts@example.com",
            notify_high_confidence=True,
        )
        session.flush()

        dispatched = dispatch_alerts_for_analysis(session, org.id, analysis)
        assert len(dispatched) == 1
        assert dispatched[0].status == "sent"
        assert dispatched[0].channel_type == "email"
        assert dispatched[0].event_type == "high_confidence_findings"

        history = repo.list_alert_history(session, org.id)
        assert len(history) == 1
        assert "high_confidence_findings" in history[0].event_type
