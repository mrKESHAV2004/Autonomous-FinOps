"""Phase 4b: read-only share links, the savings tracker and the sample shortcut."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select, update

from finops_app.db import Database
from finops_app.models import ShareLink, utcnow
from finops_app.sample_data import sample_csv
from web_helpers import signup, upload


def _bill(idle: tuple[str, ...], busy: tuple[str, ...] = ("busy-a", "busy-b", "busy-c")) -> bytes:
    lines = ["UsageDate,ServiceCategory,ResourceId,EffectiveCost,ConsumedQuantity"]
    for d in range(1, 11):
        for r in idle:
            lines.append(f"2024-01-{d:02d},Compute,{r},40,0")
        for r in busy:
            lines.append(f"2024-01-{d:02d},Compute,{r},40,60")
    return "\n".join(lines).encode()


def _finding_ids(client: FlaskClient, url: str) -> dict[str, str]:
    aid = url.rsplit("/", 1)[1]
    rows = client.get(f"/api/v1/analyses/{aid}/findings?per_page=100").get_json()["data"]
    return {r["resource_id"]: r["id"] for r in rows}


def _share(client: FlaskClient, url: str, days: int = 7) -> str:
    resp = client.post(f"{url}/share", data={"days": days}, follow_redirects=True)
    found = re.search(
        r'id="new-link" type="text" readonly value="http://localhost(/share/[^"]+)"',
        resp.get_data(as_text=True),
    )
    assert found, "new link not shown"
    return found.group(1)


@pytest.fixture
def report(client: FlaskClient) -> str:
    return upload(client, sample_csv().encode(), "q1.csv")


# ------------------------------------------------------------------ sharing


def test_shared_link_shows_a_read_only_overview(
    app: Flask, client: FlaskClient, anon_client: FlaskClient, report: str
) -> None:
    link = _share(client, report)
    resp = anon_client.get(link)
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Read-only report from Acme" in body and "Biggest open findings" in body
    assert "/findings/" not in body and 'class="tabs"' not in body  # no way into the app
    assert "Sign in" not in body
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["X-Robots-Tag"] == "noindex"
    data = anon_client.get(f"{link}/data.json").get_json()["data"]
    assert data["daily"]["costs"] and data["waste_by_service"]

    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        stored = s.scalars(select(ShareLink.token_hash)).one()
    assert link.rsplit("/", 1)[1] not in stored  # only the hash is kept


def test_revoked_and_expired_links_stop_working(
    app: Flask, client: FlaskClient, anon_client: FlaskClient, report: str
) -> None:
    first, second = _share(client, report), _share(client, report, days=30)
    page = client.get(report).get_data(as_text=True)
    assert page.count("/revoke") == 2
    revoke = re.search(r'action="(/share-links/[0-9a-f]{32}/revoke)"', page)
    assert revoke
    client.post(revoke.group(1))
    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        s.execute(
            update(ShareLink)
            .where(ShareLink.revoked_at.is_(None))
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
    assert anon_client.get(first).status_code == 404
    assert anon_client.get(second).status_code == 404
    assert anon_client.get(f"{second}/data.json").status_code == 404
    assert anon_client.get("/share/not-a-real-token").status_code == 404


def test_only_admins_create_and_revoke_links(app: Flask, client: FlaskClient, report: str) -> None:
    link = _share(client, report)
    analyst = app.test_client()
    signup(analyst, "ana@example.com", "Ana home")
    client.post("/members", data={"email": "ana@example.com", "role": "analyst"})
    page = analyst.get("/analyses").get_data(as_text=True)
    marker = page.index(">Acme ")
    start = page.rfind('name="org_id" value="', 0, marker) + len('name="org_id" value="')
    analyst.post("/org/switch", data={"org_id": page[start:].split('"', 1)[0]})
    assert analyst.post(f"{report}/share", data={"days": 7}).status_code == 403
    assert "Share a read-only report" not in analyst.get(report).get_data(as_text=True)
    assert client.post(f"{report}/share", data={"days": 3}).status_code == 400

    outsider = app.test_client()
    signup(outsider, "out@example.com", "Elsewhere")
    revoke = re.search(
        r'action="(/share-links/[0-9a-f]{32}/revoke)"', client.get(report).get_data(as_text=True)
    )
    assert revoke
    assert outsider.post(revoke.group(1)).status_code == 404
    assert outsider.post(f"{report}/share", data={"days": 7}).status_code == 404
    assert app.test_client().get(link).status_code == 200


# ------------------------------------------------------------------ savings


def test_savings_tracks_fixed_resources_across_uploads(client: FlaskClient) -> None:
    assert "Nothing marked fixed yet" in client.get("/savings").get_data(as_text=True)
    jan = upload(client, _bill(("idle-1", "idle-2")), "jan.csv")
    ids = _finding_ids(client, jan)
    for rid in ("idle-1", "idle-2"):
        client.post(f"/findings/{ids[rid]}/status", data={"status": "fixed"})
    assert "Waiting for next upload" in client.get("/savings").get_data(as_text=True)

    upload(client, _bill(("idle-1",), ("busy-a", "busy-b", "busy-c", "idle-2")), "feb.csv")
    body = client.get("/savings").get_data(as_text=True)
    assert "Gone from latest upload" in body  # idle-2 is now in use
    assert "Still flagged" in body  # idle-1 is still idle
    assert "feb.csv" in body


# ------------------------------------------------------------------ first run


def test_one_click_sample_analysis(client: FlaskClient) -> None:
    empty = client.get("/analyses").get_data(as_text=True)
    assert "Analyse the sample" in empty
    resp = client.post("/sample")
    assert resp.status_code == 302
    body = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "sample-billing.csv" in body and "Biggest open findings" in body


def test_sample_file_is_a_usable_focus_export(anon_client: FlaskClient) -> None:
    text = anon_client.get("/sample").get_data(as_text=True)
    assert text.splitlines()[0].endswith("ResourceId,RegionId,SubAccountId")
    assert len(text.splitlines()) == 1 + 30 * 24


def test_theme_switch_is_on_app_pages(client: FlaskClient) -> None:
    body = client.get("/analyses").get_data(as_text=True)
    assert "js/theme.js" in body and "data-theme-toggle" in body
