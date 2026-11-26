from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from finops_app import tasks, triage
from finops_app.findings_views import csv_cell
from web_helpers import signup, upload


@pytest.fixture
def analysis_url(client: FlaskClient, make_billing_csv: Callable[..., Path]) -> str:
    return upload(
        client, make_billing_csv(days=14, rows_per_day=30, anomaly_rate=0.15).read_bytes()
    )


def _findings(client: FlaskClient, analysis_url: str) -> list[dict]:  # type: ignore[type-arg]
    aid = analysis_url.rsplit("/", 1)[1]
    data: list[dict] = client.get(f"/api/v1/analyses/{aid}/findings?per_page=100").get_json()["data"]  # type: ignore[type-arg]
    return data


def test_overview_shows_triage_and_top_findings(client: FlaskClient, analysis_url: str) -> None:
    body = client.get(analysis_url).get_data(as_text=True)
    assert "Triage" in body and "Biggest open findings" in body
    assert 'aria-current="page">Overview' in body
    assert "Show the numbers" in body  # the chart's data table
    first = _findings(client, analysis_url)[0]
    assert f"/findings/{first['id']}" in body


def test_findings_page_filters_and_links(client: FlaskClient, analysis_url: str) -> None:
    rows = _findings(client, analysis_url)
    service = rows[0]["service"]
    body = client.get(f"{analysis_url}/findings?service={service}").get_data(as_text=True)
    expected = sum(1 for r in rows if r["service"] == service)
    assert f"{expected:,} finding" in body
    assert "Clear filters" in body
    assert f"findings.csv?service={service}" in body


def _many_idle_resources(n: int = 40, days: int = 10) -> bytes:
    lines = ["UsageDate,ServiceCategory,ResourceId,EffectiveCost,ConsumedQuantity"]
    for d in range(1, days + 1):
        for i in range(n):
            lines.append(f"2024-01-{d:02d},Compute,idle-{i},{10 + i},0")
            lines.append(f"2024-01-{d:02d},Compute,busy-{i},{10 + i},{50 + i}")
    return "\n".join(lines).encode()


def test_findings_page_pages(client: FlaskClient) -> None:
    url = upload(client, _many_idle_resources())
    total = len(_findings(client, url))
    assert total > 25, "fixture must produce more than one page"
    body = client.get(f"{url}/findings").get_data(as_text=True)
    assert 'rel="next"' in body and "page=2" in body
    second = client.get(f"{url}/findings?page=2").get_data(as_text=True)
    assert 'rel="prev"' in second and "Page 2 of" in second


def test_csv_export_matches_filters(client: FlaskClient, analysis_url: str) -> None:
    rows = _findings(client, analysis_url)
    resp = client.get(f"{analysis_url}/findings.csv?confidence={rows[0]['confidence']}")
    assert resp.mimetype == "text/csv"
    assert "attachment; filename=findings-" in resp.headers["Content-Disposition"]
    text = resp.get_data(as_text=True)
    assert text.startswith("﻿Resource,")
    parsed = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    assert len(parsed) == sum(1 for r in rows if r["confidence"] == rows[0]["confidence"])
    assert {p["Confidence"] for p in parsed} == {rows[0]["confidence"]}


def test_csv_export_neutralises_formulas(
    client: FlaskClient, make_billing_csv: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tasks.analyze

    def hostile(path: str) -> object:
        res = real(path)
        bad = replace(res.findings[0], resource_name='=HYPERLINK("http://evil.example.com","x")')
        return replace(res, findings=(bad, *res.findings[1:]))

    monkeypatch.setattr(tasks, "analyze", hostile)
    url = upload(client, make_billing_csv(days=10, anomaly_rate=0.3).read_bytes())
    text = client.get(f"{url}/findings.csv").get_data(as_text=True)
    assert "\n=HYPERLINK" not in text
    assert "'=HYPERLINK" in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [("=1+1", "'=1+1"), ("+x", "'+x"), ("-x", "'-x"), ("@x", "'@x"), ("ok", "ok"),
     (None, ""), (3.14159, "3.14"), (["a", "b"], "a; b")],
)  # fmt: skip
def test_csv_cell(value: object, expected: str) -> None:
    assert csv_cell(value) == expected


def test_detail_page_and_status_form(client: FlaskClient, analysis_url: str) -> None:
    fid = _findings(client, analysis_url)[0]["id"]
    page = client.get(f"/findings/{fid}").get_data(as_text=True)
    assert "Recommended action" in page and "Why it was flagged" in page
    assert "No changes yet" in page

    resp = client.post(
        f"/findings/{fid}/status", data={"status": "false_positive", "note": "Planned capacity"}
    )
    assert resp.status_code == 302
    page = client.get(f"/findings/{fid}").get_data(as_text=True)
    assert "Marked false positive." in page
    assert "Open → False positive" in page and "Planned capacity" in page

    overview = client.get(analysis_url).get_data(as_text=True)
    assert "False positive" in overview


def test_status_form_errors_are_shown(client: FlaskClient, analysis_url: str) -> None:
    fid = _findings(client, analysis_url)[0]["id"]
    client.post(f"/findings/{fid}/status", data={"status": "snoozed"})
    assert "Choose the date the snooze ends." in client.get(f"/findings/{fid}").get_data(
        as_text=True
    )
    client.post(f"/findings/{fid}/status", data={"status": "nonsense"})
    assert "Not a valid choice" in client.get(f"/findings/{fid}").get_data(as_text=True)


def test_snoozing_from_the_form(client: FlaskClient, analysis_url: str) -> None:
    fid = _findings(client, analysis_url)[0]["id"]
    until = (triage.today() + timedelta(days=14)).isoformat()
    client.post(f"/findings/{fid}/status", data={"status": "snoozed", "snoozed_until": until})
    body = client.get(f"{analysis_url}/findings?status=snoozed").get_data(as_text=True)
    assert f"until {until}" in body


def test_back_link_returns_to_the_filtered_table(client: FlaskClient, analysis_url: str) -> None:
    fid = _findings(client, analysis_url)[0]["id"]
    table = f"{analysis_url}/findings?status=open"
    page = client.get(f"/findings/{fid}", headers={"Referer": f"http://localhost{table}"})
    assert f'href="{table}"' in page.get_data(as_text=True)
    evil = client.get(f"/findings/{fid}", headers={"Referer": "https://evil.example.com/x"})
    assert "evil.example.com" not in evil.get_data(as_text=True)


def test_pages_are_tenant_scoped(app: Flask, client: FlaskClient, analysis_url: str) -> None:
    fid = _findings(client, analysis_url)[0]["id"]
    other = app.test_client()
    signup(other, "mallory@example.com", "Other")
    assert other.get(f"{analysis_url}/findings").status_code == 404
    assert other.get(f"{analysis_url}/findings.csv").status_code == 404
    assert other.get(f"/findings/{fid}").status_code == 404
    assert other.post(f"/findings/{fid}/status", data={"status": "fixed"}).status_code == 404


def test_findings_of_an_unfinished_analysis_redirect(client: FlaskClient) -> None:
    url = upload(client, b"UsageDate,EffectiveCost,ConsumedQuantity\n2024-01-01,5,1\n")
    resp = client.get(f"{url}/findings")
    assert resp.status_code == 302 and resp.headers["Location"] == url
