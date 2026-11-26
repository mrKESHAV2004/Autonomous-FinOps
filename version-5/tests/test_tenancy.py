"""Two organisations side by side: nothing of one is visible to the other."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select

from finops_app.db import Database
from finops_app.models import AuditLog, Membership, Organization
from web_helpers import member_id, signup, upload


@pytest.fixture
def two_orgs(app: Flask) -> tuple[FlaskClient, FlaskClient]:
    a, b = app.test_client(), app.test_client()
    signup(a, "alice@a.example.com", "Org A")
    signup(b, "bob@b.example.com", "Org B")
    return a, b


@pytest.fixture
def csv_bytes(make_billing_csv: Callable[..., Path]) -> bytes:
    return make_billing_csv(days=5).read_bytes()


def test_one_org_cannot_see_another_orgs_analyses(
    two_orgs: tuple[FlaskClient, FlaskClient], csv_bytes: bytes
) -> None:
    a, b = two_orgs
    url = upload(a, csv_bytes, "secret-a.csv")

    assert a.get(url).status_code == 200
    assert b.get(url).status_code == 404
    assert b.get(url + "/status").status_code == 404
    assert "secret-a.csv" not in b.get("/analyses").get_data(as_text=True)
    assert "secret-a.csv" in a.get("/analyses").get_data(as_text=True)


def test_the_404_page_does_not_say_whose_data_it_is(
    two_orgs: tuple[FlaskClient, FlaskClient], csv_bytes: bytes
) -> None:
    a, b = two_orgs
    url = upload(a, csv_bytes)
    body = b.get(url).get_data(as_text=True)
    assert "Org A" not in body
    assert "bill.csv" not in body


def test_members_page_lists_only_your_org(two_orgs: tuple[FlaskClient, FlaskClient]) -> None:
    a, b = two_orgs
    page = a.get("/members").get_data(as_text=True)
    assert "alice@a.example.com" in page
    assert "bob@b.example.com" not in page


def test_cannot_change_or_remove_a_member_of_another_org(
    app: Flask, two_orgs: tuple[FlaskClient, FlaskClient]
) -> None:
    a, b = two_orgs
    viewer = app.test_client()
    signup(viewer, "vic@b.example.com", "Vic's own")
    b.post("/members", data={"email": "vic@b.example.com", "role": "viewer"})
    vic = member_id(b.get("/members").get_data(as_text=True), "vic@b.example.com")

    assert a.post(f"/members/{vic}/role", data={"role": "owner"}).status_code == 404
    assert a.post(f"/members/{vic}/remove").status_code == 404
    assert "vic@b.example.com" in b.get("/members").get_data(as_text=True)


def test_cannot_switch_to_an_org_you_do_not_belong_to(
    app: Flask, two_orgs: tuple[FlaskClient, FlaskClient], csv_bytes: bytes
) -> None:
    a, b = two_orgs
    upload(a, csv_bytes, "secret-a.csv")
    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        org_a = s.scalars(select(Organization).where(Organization.name == "Org A")).one().id

    assert b.post("/org/switch", data={"org_id": org_a}).status_code == 404
    with b.session_transaction() as sess:  # even a tampered session is re-checked
        sess["org_id"] = org_a
    assert "secret-a.csv" not in b.get("/analyses").get_data(as_text=True)


def test_member_of_two_orgs_switches_between_them(
    app: Flask, two_orgs: tuple[FlaskClient, FlaskClient], csv_bytes: bytes
) -> None:
    a, b = two_orgs
    upload(b, csv_bytes, "from-b.csv")
    b.post("/members", data={"email": "alice@a.example.com", "role": "viewer"})
    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        org_b = s.scalars(select(Organization).where(Organization.name == "Org B")).one().id

    assert "from-b.csv" not in a.get("/analyses").get_data(as_text=True)
    assert a.post("/org/switch", data={"org_id": org_b}).status_code == 302
    page = a.get("/analyses").get_data(as_text=True)
    assert "from-b.csv" in page
    assert "Org A" in page and "Org B" in page  # the switcher lists both
    assert a.get("/upload").status_code == 403  # a viewer in Org B


def test_removed_member_loses_access_at_once(
    app: Flask, two_orgs: tuple[FlaskClient, FlaskClient], csv_bytes: bytes
) -> None:
    _, b = two_orgs
    url = upload(b, csv_bytes)
    carol = app.test_client()
    signup(carol, "carol@example.com", "Carol's")
    b.post("/members", data={"email": "carol@example.com", "role": "viewer"})
    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        org_b = s.scalars(select(Organization).where(Organization.name == "Org B")).one().id
    carol.post("/org/switch", data={"org_id": org_b})
    assert carol.get(url).status_code == 200

    b.post(
        f"/members/{member_id(b.get('/members').get_data(as_text=True), 'carol@example.com')}/remove"
    )
    assert carol.get(url).status_code == 404


def test_user_with_no_org_sees_an_explanation(app: Flask, client: FlaskClient) -> None:
    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        for m in s.scalars(select(Membership)):
            s.delete(m)

    resp = client.get("/analyses")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/no-organisation"
    assert "a member of any organisation" in client.get("/no-organisation").get_data(as_text=True)
    assert client.get("/upload").status_code == 302


def test_audit_log_records_member_changes(
    app: Flask, two_orgs: tuple[FlaskClient, FlaskClient]
) -> None:
    a, _ = two_orgs
    a.post("/members", data={"email": "bob@b.example.com", "role": "analyst"})
    bob = member_id(a.get("/members").get_data(as_text=True), "bob@b.example.com")
    a.post(f"/members/{bob}/role", data={"role": "viewer"})
    a.post(f"/members/{bob}/remove")
    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        actions = [e.action for e in s.scalars(select(AuditLog).order_by(AuditLog.created_at))]
    assert {"member.added", "member.role_changed", "member.removed"} <= set(actions)
