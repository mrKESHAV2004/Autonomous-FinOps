from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from finops_app import create_app, triage
from finops_app.config import Config
from web_helpers import csrf_token, signup, upload


@pytest.fixture
def analysis_id(client: FlaskClient, make_billing_csv: Callable[..., Path]) -> str:
    url = upload(client, make_billing_csv(days=14, rows_per_day=30, anomaly_rate=0.15).read_bytes())
    return url.rsplit("/", 1)[1]


def _data(resp) -> object:  # type: ignore[no-untyped-def]
    body = resp.get_json()
    assert body["success"] is True and body["error"] is None, body
    return body["data"]


def test_api_needs_sign_in(anon_client: FlaskClient) -> None:
    resp = anon_client.get("/api/v1/analyses")
    assert resp.status_code == 401
    assert resp.get_json() == {"success": False, "data": None, "error": "Sign in first."}


def test_list_and_summary(client: FlaskClient, analysis_id: str) -> None:
    (listed,) = _data(client.get("/api/v1/analyses"))
    assert listed["id"] == analysis_id and listed["status"] == "succeeded"

    summary = _data(client.get(f"/api/v1/analyses/{analysis_id}"))
    assert summary["findings"] > 0
    assert set(summary["by_status"]) == {
        "open",
        "acknowledged",
        "fixed",
        "snoozed",
        "false_positive",
    }
    assert summary["by_status"]["open"]["count"] == summary["findings"]
    assert sum(summary["confidence"].values()) == summary["findings"]
    assert summary["waste_by_service"]


def test_series(client: FlaskClient, analysis_id: str) -> None:
    s = _data(client.get(f"/api/v1/analyses/{analysis_id}/series"))
    assert len(s["daily"]["dates"]) == 14 == len(s["daily"]["costs"])
    fc = s["forecast"]
    assert len(fc["values"]) == len(fc["lower"]) == len(fc["upper"]) == len(fc["optimised"]) == 7
    assert all(o <= v for o, v in zip(fc["optimised"], fc["values"], strict=True))


def test_findings_filter_sort_and_page(client: FlaskClient, analysis_id: str) -> None:
    resp = client.get(f"/api/v1/analyses/{analysis_id}/findings?per_page=25")
    body = resp.get_json()
    rows, meta = body["data"], body["meta"]
    assert meta["page"] == 1 and meta["per_page"] == 25 and meta["total"] >= len(rows)
    wastes = [r["estimated_waste"] for r in rows]
    assert wastes == sorted(wastes, reverse=True)

    service = rows[0]["service"]
    filtered = _data(client.get(f"/api/v1/analyses/{analysis_id}/findings?service={service}"))
    assert filtered and all(r["service"] == service for r in filtered)

    beyond = client.get(f"/api/v1/analyses/{analysis_id}/findings?page=999").get_json()
    assert beyond["meta"]["page"] == beyond["meta"]["pages"]  # clamped to the last page
    junk = client.get(f"/api/v1/analyses/{analysis_id}/findings?per_page=7&sort=drop&page=x")
    assert junk.get_json()["meta"]["per_page"] == 25


def test_search_treats_wildcards_literally(client: FlaskClient, analysis_id: str) -> None:
    assert _data(client.get(f"/api/v1/analyses/{analysis_id}/findings?q=%25")) == []
    assert _data(client.get(f"/api/v1/analyses/{analysis_id}/findings?q=_")) == []


def test_finding_detail_and_status_change(client: FlaskClient, analysis_id: str) -> None:
    first = _data(client.get(f"/api/v1/analyses/{analysis_id}/findings"))[0]
    in_30_days = (triage.today() + timedelta(days=30)).isoformat()
    detail = _data(client.get(f"/api/v1/findings/{first['id']}"))
    assert detail["recommended_action"] and detail["history"] == []

    changed = _data(
        client.post(
            f"/api/v1/findings/{first['id']}/status",
            json={"status": "snoozed", "note": "after the migration", "snoozed_until": in_30_days},
        )
    )
    assert changed["status"] == "snoozed" and changed["snoozed_until"] == in_30_days
    assert changed["history"][0]["by"] == "owner@acme.example.com"


def test_status_change_validation(client: FlaskClient, analysis_id: str) -> None:
    fid = _data(client.get(f"/api/v1/analyses/{analysis_id}/findings"))[0]["id"]
    url = f"/api/v1/findings/{fid}/status"
    assert client.post(url, data="nope", content_type="text/plain").status_code == 400
    assert client.post(url, json={"status": 3}).status_code == 400
    assert client.post(url, json={"status": "snoozed", "snoozed_until": "soon"}).status_code == 400
    bad = client.post(url, json={"status": "open"})
    assert bad.status_code == 422
    assert bad.get_json()["error"] == "This finding is already open."


def test_unfinished_analysis_is_409(client: FlaskClient) -> None:
    url = upload(client, b"UsageDate,EffectiveCost,ConsumedQuantity\n2024-01-01,5,1\n")
    aid = url.rsplit("/", 1)[1]
    assert _data(client.get(f"/api/v1/analyses/{aid}"))["status"] == "failed"
    resp = client.get(f"/api/v1/analyses/{aid}/findings")
    assert resp.status_code == 409
    assert resp.get_json()["success"] is False


def test_api_is_tenant_scoped(app: Flask, analysis_id: str, client: FlaskClient) -> None:
    other = app.test_client()
    signup(other, "eve@example.com", "Eve Org")
    fid = _data(client.get(f"/api/v1/analyses/{analysis_id}/findings"))[0]["id"]
    for path in (
        f"/api/v1/analyses/{analysis_id}",
        f"/api/v1/analyses/{analysis_id}/series",
        f"/api/v1/analyses/{analysis_id}/findings",
        f"/api/v1/findings/{fid}",
    ):
        resp = other.get(path)
        assert resp.status_code == 404, path
        assert resp.get_json()["success"] is False
    assert other.post(f"/api/v1/findings/{fid}/status", json={"status": "fixed"}).status_code == 404
    assert _data(other.get("/api/v1/analyses")) == []


def test_viewers_cannot_change_status(app: Flask, client: FlaskClient, analysis_id: str) -> None:
    viewer = app.test_client()
    signup(viewer, "viewer@example.com", "Viewer home")
    client.post("/members", data={"email": "viewer@example.com", "role": "viewer"})
    orgs = viewer.get("/analyses").get_data(as_text=True)
    marker = orgs.index(">Acme ")
    start = orgs.rfind('name="org_id" value="', 0, marker) + len('name="org_id" value="')
    viewer.post("/org/switch", data={"org_id": orgs[start:].split('"', 1)[0]})
    fid = _data(viewer.get(f"/api/v1/analyses/{analysis_id}/findings"))[0]["id"]
    resp = viewer.post(f"/api/v1/findings/{fid}/status", json={"status": "fixed"})
    assert resp.status_code == 403 and resp.get_json()["success"] is False


def test_api_posts_need_the_csrf_header(
    config: Config, make_billing_csv: Callable[..., Path]
) -> None:
    app = create_app(replace(config, csrf=True))
    c = app.test_client()
    token = csrf_token(c.get("/signup").get_data(as_text=True))
    c.post(
        "/signup",
        data={
            "csrf_token": token,
            "email": "a@example.com",
            "password": "correct horse battery staple",
            "org_name": "A",
        },
    )
    page = c.get("/upload").get_data(as_text=True)
    resp = c.post(
        "/upload",
        data={
            "csrf_token": csrf_token(page),
            "file": (
                make_billing_csv(days=14, rows_per_day=30, anomaly_rate=0.15).open("rb"),
                "b.csv",
            ),
        },
        content_type="multipart/form-data",
    )
    aid = resp.headers["Location"].rsplit("/", 1)[1]
    fid = c.get(f"/api/v1/analyses/{aid}/findings").get_json()["data"][0]["id"]
    url = f"/api/v1/findings/{fid}/status"
    assert c.post(url, json={"status": "fixed"}).status_code == 400
    ok = c.post(url, json={"status": "fixed"}, headers={"X-CSRFToken": csrf_token(page)})
    assert ok.status_code == 200
