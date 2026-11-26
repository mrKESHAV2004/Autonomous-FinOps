from __future__ import annotations

from unittest.mock import patch

from flask.testing import FlaskClient

from finops_app.connectors.base import ConnectorVerificationResult


def test_connectors_page_renders(client: FlaskClient) -> None:
    resp = client.get("/connectors")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Cloud Connectors" in html
    assert "Connect AWS" in html
    assert "External ID:" in html


def test_add_and_verify_and_delete_aws_connection(client: FlaskClient) -> None:
    # 1. Add AWS Connection
    resp = client.post(
        "/connectors/aws",
        data={
            "name": "Production AWS",
            "role_arn": "arn:aws:iam::123456789012:role/FinOpsRole",
            "s3_bucket": "prod-cur-bucket",
            "s3_prefix": "cur/",
            "region": "us-east-1",
            "external_id": "test-ext-id",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Production AWS" in html
    assert "prod-cur-bucket" in html

    # Extract connection ID from API to test verify and delete
    api_resp = client.get("/api/v1/connectors")
    assert api_resp.status_code == 200
    conns = api_resp.get_json()["data"]
    assert len(conns) == 1
    conn_id = conns[0]["id"]

    # 2. Verify connection
    with patch("finops_app.connectors.sync.AwsConnector.verify") as mock_verify:
        mock_verify.return_value = ConnectorVerificationResult(
            success=True, message="Connected successfully to S3 bucket"
        )
        verify_resp = client.post(f"/connectors/{conn_id}/verify", follow_redirects=True)
        assert verify_resp.status_code == 200
        assert "Connected successfully" in verify_resp.get_data(as_text=True)

    # 3. Delete connection
    del_resp = client.post(f"/connectors/{conn_id}/delete", follow_redirects=True)
    assert del_resp.status_code == 200
    assert "deleted" in del_resp.get_data(as_text=True)

    # Verify deleted from API
    api_resp_after = client.get("/api/v1/connectors")
    assert len(api_resp_after.get_json()["data"]) == 0


def test_budgets_page_and_crud(client: FlaskClient) -> None:
    # 1. View page
    resp = client.get("/budgets")
    assert resp.status_code == 200
    assert "Budgets" in resp.get_data(as_text=True)

    # 2. Add total budget
    post_resp = client.post(
        "/budgets",
        data={
            "scope_type": "total",
            "scope_value": "",
            "monthly_amount": "5000.00",
        },
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    html = post_resp.get_data(as_text=True)
    assert "Total Monthly Spend" in html
    assert "5,000.00" in html

    # 3. Check via API
    api_resp = client.get("/api/v1/budgets")
    assert api_resp.status_code == 200
    budgets = api_resp.get_json()["data"]
    assert len(budgets) == 1
    assert budgets[0]["monthly_amount"] == 5000.0
    budget_id = budgets[0]["id"]

    # 4. Delete budget
    del_resp = client.post(f"/budgets/{budget_id}/delete", follow_redirects=True)
    assert del_resp.status_code == 200
    assert "Budget deleted" in del_resp.get_data(as_text=True)


def test_alerts_page_and_crud(client: FlaskClient) -> None:
    # 1. View alerts page
    resp = client.get("/alerts")
    assert resp.status_code == 200
    assert "Alerts & Notifications" in resp.get_data(as_text=True)

    # 2. Add Slack webhook alert
    post_resp = client.post(
        "/alerts",
        data={
            "channel_type": "slack",
            "destination": "https://hooks.slack.com/services/test/123",
            "notify_high_confidence": "y",
            "notify_budget_exceeded": "y",
            "notify_spend_spikes": "y",
            "spike_threshold_percent": "25.0",
        },
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert "Alert channel configured successfully" in post_resp.get_data(as_text=True)

    # 3. Check via API
    api_resp = client.get("/api/v1/alerts")
    assert api_resp.status_code == 200
    configs = api_resp.get_json()["data"]["configs"]
    assert len(configs) == 1
    config_id = configs[0]["id"]

    # 4. Send test notification
    with patch("finops_app.alerts_views.send_slack_notification", return_value=(True, None)):
        test_resp = client.post(f"/alerts/{config_id}/test", follow_redirects=True)
        assert test_resp.status_code == 200
        assert "Test notification sent successfully" in test_resp.get_data(as_text=True)

    # 5. Delete alert config
    del_resp = client.post(f"/alerts/{config_id}/delete", follow_redirects=True)
    assert del_resp.status_code == 200
    assert "Alert configuration deleted" in del_resp.get_data(as_text=True)


def test_api_phase5_endpoints(client: FlaskClient) -> None:
    # Test JSON API creation
    conn_resp = client.post(
        "/api/v1/connectors/aws",
        json={
            "name": "API AWS",
            "role_arn": "arn:aws:iam::123:role/FinOps",
            "s3_bucket": "api-cur-bucket",
        },
    )
    assert conn_resp.status_code == 201
    conn_id = conn_resp.get_json()["data"]["id"]

    # Test API list
    list_conns = client.get("/api/v1/connectors")
    assert list_conns.status_code == 200
    assert any(c["id"] == conn_id for c in list_conns.get_json()["data"])

    # Test Budget API
    budget_resp = client.post(
        "/api/v1/budgets",
        json={"scope_type": "total", "monthly_amount": 10000.0},
    )
    assert budget_resp.status_code == 201

    # Test Alert API
    alert_resp = client.post(
        "/api/v1/alerts",
        json={"channel_type": "email", "destination": "ops@example.com"},
    )
    assert alert_resp.status_code == 201
