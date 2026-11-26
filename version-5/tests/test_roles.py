"""What each role may do, enforced on the server (not only hidden in the UI)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from web_helpers import member_id, signup, upload


@pytest.fixture
def team(app: Flask, client: FlaskClient) -> dict[str, FlaskClient]:
    """The owner (``client``) plus one member of Acme for each other role."""
    members = {"owner": client}
    for role in ("admin", "analyst", "viewer"):
        c = app.test_client()
        signup(c, f"{role}@acme.example.com", f"{role} home")
        client.post("/members", data={"email": f"{role}@acme.example.com", "role": role})
        page = client.get("/members").get_data(as_text=True)
        assert f"{role}@acme.example.com" in page
        _switch_to_acme(c)
        members[role] = c
    return members


def _switch_to_acme(c: FlaskClient) -> None:
    page = c.get("/analyses").get_data(as_text=True)
    marker = page.index(">Acme ")
    org_field = page.rfind('name="org_id" value="', 0, marker)
    org_id = page[org_field + len('name="org_id" value="') :].split('"', 1)[0]
    assert c.post("/org/switch", data={"org_id": org_id}).status_code == 302


def test_viewer_reads_but_cannot_upload(
    team: dict[str, FlaskClient], make_billing_csv: Callable[..., Path]
) -> None:
    url = upload(team["analyst"], make_billing_csv(days=5).read_bytes())
    viewer = team["viewer"]
    assert viewer.get(url).status_code == 200
    assert viewer.get("/analyses").status_code == 200
    assert viewer.get("/upload").status_code == 403
    assert viewer.post("/upload", data={}).status_code == 403
    assert "Analyze new dataset" not in viewer.get("/analyses").get_data(as_text=True)


def test_only_admins_and_owners_manage_members(team: dict[str, FlaskClient]) -> None:
    for role in ("analyst", "viewer"):
        assert team[role].get("/members").status_code == 403
        assert team[role].post("/members", data={"email": "x@example.com"}).status_code == 403
    assert team["admin"].get("/members").status_code == 200


def test_admin_cannot_promote_to_admin_or_touch_owners(team: dict[str, FlaskClient]) -> None:
    admin = team["admin"]
    page = admin.get("/members").get_data(as_text=True)
    viewer = member_id(page, "viewer@acme.example.com")

    admin.post(f"/members/{viewer}/role", data={"role": "admin"})
    assert "Only an owner can give the admin role" in admin.get("/members").get_data(as_text=True)

    admin.post(f"/members/{viewer}/role", data={"role": "analyst"})
    assert "is now analyst" in admin.get("/members").get_data(as_text=True)


def test_admin_cannot_remove_the_owner(app: Flask, team: dict[str, FlaskClient]) -> None:
    from sqlalchemy import select

    from finops_app.db import Database
    from finops_app.models import Membership, Organization, User

    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        acme = s.scalars(select(Organization).where(Organization.name == "Acme")).one()
        owner = s.scalars(
            select(Membership)
            .join(User)
            .where(Membership.org_id == acme.id, User.email == "owner@acme.example.com")
        ).one()
    team["admin"].post(f"/members/{owner.id}/remove")
    assert "owner@acme.example.com" in team["owner"].get("/members").get_data(as_text=True)


def _own_membership_id(app: Flask, email: str) -> str:
    from sqlalchemy import select

    from finops_app.db import Database
    from finops_app.models import Membership, Organization, User

    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        acme = s.scalars(select(Organization).where(Organization.name == "Acme")).one()
        return s.scalars(
            select(Membership.id)
            .join(User)
            .where(Membership.org_id == acme.id, User.email == email)
        ).one()


def test_last_owner_cannot_leave_or_be_demoted(app: Flask, team: dict[str, FlaskClient]) -> None:
    owner = team["owner"]
    me = _own_membership_id(app, "owner@acme.example.com")
    owner.post(f"/members/{me}/role", data={"role": "viewer"})
    assert "needs at least one owner" in owner.get("/members").get_data(as_text=True)
    owner.post(f"/members/{me}/remove")
    assert "needs at least one owner" in owner.get("/members").get_data(as_text=True)


def test_with_two_owners_one_may_demote_the_other(app: Flask, team: dict[str, FlaskClient]) -> None:
    owner = team["owner"]
    page = owner.get("/members").get_data(as_text=True)
    admin = member_id(page, "admin@acme.example.com")
    owner.post(f"/members/{admin}/role", data={"role": "owner"})
    assert "admin@acme.example.com is now owner" in owner.get("/members").get_data(as_text=True)

    # Now two owners: the second may demote the first.
    second = team["admin"]
    first = member_id(second.get("/members").get_data(as_text=True), "owner@acme.example.com")
    second.post(f"/members/{first}/role", data={"role": "viewer"})
    assert "is now viewer" in second.get("/members").get_data(as_text=True)


def test_adding_an_unknown_email_or_an_existing_member_explains_why(
    client: FlaskClient, team: dict[str, FlaskClient]
) -> None:
    body = client.post("/members", data={"email": "ghost@example.com", "role": "viewer"})
    assert body.status_code == 400
    assert "Ask them to sign up first" in body.get_data(as_text=True)
    again = client.post("/members", data={"email": "viewer@acme.example.com", "role": "viewer"})
    assert "already a member" in again.get_data(as_text=True)


def test_upload_records_who_uploaded(
    app: Flask, team: dict[str, FlaskClient], make_billing_csv: Callable[..., Path]
) -> None:
    from sqlalchemy import select

    from finops_app.db import Database
    from finops_app.models import Dataset, User

    upload(team["analyst"], make_billing_csv(days=5).read_bytes())
    db: Database = app.extensions["finops_db"]
    with db.session() as s:
        ds = s.scalars(select(Dataset)).one()
        user = s.get(User, ds.uploaded_by)
        assert user is not None and user.email == "analyst@acme.example.com"
