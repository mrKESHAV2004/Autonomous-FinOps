from __future__ import annotations

from datetime import timedelta

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select

from finops_app.db import Database
from finops_app.models import AuditLog, User
from web_helpers import PASSWORD, login, signup


def _db(app: Flask) -> Database:
    db: Database = app.extensions["finops_db"]
    return db


def test_app_pages_need_sign_in(anon_client: FlaskClient) -> None:
    for path in ("/upload", "/analyses", "/analyses/" + "0" * 32, "/members"):
        resp = anon_client.get(path)
        assert resp.status_code == 302, path
        assert resp.headers["Location"].startswith("/login?next=")


def test_status_endpoint_needs_sign_in(anon_client: FlaskClient) -> None:
    assert anon_client.get("/analyses/" + "0" * 32 + "/status").status_code == 302


def test_signup_creates_owner_and_lands_on_upload(anon_client: FlaskClient, app: Flask) -> None:
    resp = anon_client.post(
        "/signup",
        data={
            "name": "Ada",
            "email": "  Ada@Example.COM ",
            "password": PASSWORD,
            "org_name": "Ada Labs",
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/upload"
    page = anon_client.get("/upload").get_data(as_text=True)
    assert "Ada Labs" in page
    with _db(app).session() as s:
        user = s.scalars(select(User)).one()
        assert user.email == "ada@example.com"
        assert user.password_hash and user.password_hash.startswith("$argon2")
        assert PASSWORD not in user.password_hash


def test_signup_rejects_short_password_and_duplicate_email(anon_client: FlaskClient) -> None:
    short = anon_client.post(
        "/signup", data={"email": "a@example.com", "password": "short", "org_name": "A"}
    )
    assert "at least 12 characters" in short.get_data(as_text=True)

    signup(anon_client, "b@example.com", "B")
    anon_client.post("/logout")
    again = anon_client.post(
        "/signup", data={"email": "B@example.com", "password": PASSWORD, "org_name": "B2"}
    )
    assert "already exists" in again.get_data(as_text=True)


def test_signup_rejects_password_equal_to_email(anon_client: FlaskClient) -> None:
    email = "longaddress@example.com"
    body = anon_client.post(
        "/signup", data={"email": email, "password": email, "org_name": "A"}
    ).get_data(as_text=True)
    assert "be your email address" in body


def test_login_logout_round_trip(app: Flask) -> None:
    c = app.test_client()
    signup(c)
    c.post("/logout")
    assert c.get("/analyses").status_code == 302

    login(c, "OWNER@acme.example.com")
    assert c.get("/analyses").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_message(
    app: Flask, anon_client: FlaskClient
) -> None:
    signup(app.test_client())
    wrong = anon_client.post(
        "/login", data={"email": "owner@acme.example.com", "password": "x" * 14}
    ).get_data(as_text=True)
    unknown = anon_client.post(
        "/login", data={"email": "nobody@example.com", "password": "x" * 14}
    ).get_data(as_text=True)
    assert "Email or password is incorrect." in wrong
    assert "Email or password is incorrect." in unknown
    assert "already exists" not in unknown
    with _db(app).session() as s:
        actions = [a.action for a in s.scalars(select(AuditLog))]
    assert actions.count("login.failed") == 1  # only for the real account


def test_successful_login_is_audited(app: Flask) -> None:
    c = app.test_client()
    signup(c)
    c.post("/logout")
    login(c, "owner@acme.example.com")
    with _db(app).session() as s:
        entry = s.scalars(select(AuditLog).where(AuditLog.action == "login.succeeded")).one()
        assert entry.org_id is not None
        user = s.scalars(select(User)).one()
        assert user.last_login_at is not None


def test_next_parameter_only_redirects_within_the_site(app: Flask) -> None:
    signup(app.test_client())
    for target, expected in (
        ("/analyses", "/analyses"),
        ("https://evil.example.com/", "/analyses"),
        ("//evil.example.com/", "/analyses"),
        ("/\\evil.example.com", "/analyses"),
        ("/members", "/members"),
    ):
        c = app.test_client()
        resp = c.post(
            f"/login?next={target}",
            data={"email": "owner@acme.example.com", "password": PASSWORD},
        )
        assert resp.headers["Location"] == expected, target


def test_signed_in_users_are_sent_past_login_and_signup(client: FlaskClient) -> None:
    assert client.get("/login").status_code == 302
    assert client.get("/signup").status_code == 302


def test_session_cookie_is_http_only_and_expires(app: Flask) -> None:
    c = app.test_client()
    resp = c.post(
        "/signup",
        data={"email": "c@example.com", "password": PASSWORD, "org_name": "C"},
    )
    cookie = resp.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Expires=" in cookie  # a permanent session, so the idle timeout applies
    assert app.permanent_session_lifetime == timedelta(hours=8)


def test_signing_in_starts_a_fresh_session(app: Flask) -> None:
    c = app.test_client()
    signup(c)
    c.post("/logout")
    with c.session_transaction() as sess:
        sess["planted"] = "by-attacker"
    login(c, "owner@acme.example.com")
    with c.session_transaction() as sess:
        assert "planted" not in sess


def test_logout_needs_post(client: FlaskClient) -> None:
    assert client.get("/logout").status_code == 405
    assert client.get("/analyses").status_code == 200
