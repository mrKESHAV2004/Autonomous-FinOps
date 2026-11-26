from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from finops_app import create_app
from finops_app.config import Config
from finops_app.security import content_security_policy
from web_helpers import PASSWORD, csrf_token, signup


def test_every_page_sends_security_headers(anon_client: FlaskClient) -> None:
    resp = anon_client.get("/login")
    h = resp.headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
    csp = h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "Strict-Transport-Security" not in h  # only in production


def test_inline_scripts_carry_this_requests_nonce(client: FlaskClient) -> None:
    resp = client.get("/upload")
    nonce = re.search(r"'nonce-([^']+)'", resp.headers["Content-Security-Policy"])
    assert nonce
    body = resp.get_data(as_text=True)
    assert f'<script nonce="{nonce.group(1)}">' in body
    assert "onchange=" not in body and "onclick=" not in body
    other = client.get("/upload").headers["Content-Security-Policy"]
    assert nonce.group(1) not in other  # a new nonce per request


def test_csp_allows_only_the_font_hosts() -> None:
    csp = content_security_policy("abc")
    assert "script-src 'self' 'nonce-abc'" in csp
    assert "https://fonts.googleapis.com" in csp and "https://cdn.fontshare.com" in csp


def test_signed_in_pages_are_not_cached(client: FlaskClient, anon_client: FlaskClient) -> None:
    assert client.get("/analyses").headers["Cache-Control"] == "no-store"
    assert anon_client.get("/").headers.get("Cache-Control") != "no-store"


def test_production_adds_hsts_and_secure_cookies(config: Config) -> None:
    app = create_app(replace(config, env="production", auto_migrate=True))
    resp = app.test_client().get("/login")
    assert resp.headers["Strict-Transport-Security"].startswith("max-age=31536000")
    assert app.config["SESSION_COOKIE_SECURE"] is True


# ------------------------------------------------------------------ CSRF


@pytest.fixture
def csrf_app(config: Config) -> Flask:
    return create_app(replace(config, csrf=True))


def test_forms_without_a_csrf_token_are_refused(csrf_app: Flask) -> None:
    c = csrf_app.test_client()
    resp = c.post("/signup", data={"email": "a@example.com", "password": PASSWORD, "org_name": "A"})
    assert resp.status_code == 400  # refused before the view runs; nothing created
    assert "This form has expired" in resp.get_data(as_text=True)
    assert c.get("/analyses").status_code == 302


def test_a_real_browser_flow_with_csrf_tokens_works(
    csrf_app: Flask, make_billing_csv: object
) -> None:
    c = csrf_app.test_client()
    token = csrf_token(c.get("/signup").get_data(as_text=True))
    resp = c.post(
        "/signup",
        data={"csrf_token": token, "email": "a@example.com", "password": PASSWORD, "org_name": "A"},
    )
    assert resp.status_code == 302

    page = c.get("/upload").get_data(as_text=True)
    upload_token = csrf_token(page)
    assert c.post("/upload", data={}).status_code == 400  # no token
    assert "This form has expired" in c.post("/upload", data={}).get_data(as_text=True)
    ok = c.post("/upload", data={"csrf_token": upload_token})
    assert ok.status_code == 302  # token accepted; "No file selected" flashed

    assert c.post("/logout").status_code == 400
    assert c.get("/analyses").status_code == 200  # logout without a token did nothing
    c.post("/logout", data={"csrf_token": csrf_token(c.get("/analyses").get_data(as_text=True))})
    assert c.get("/analyses").status_code == 302


def test_member_changes_need_a_csrf_token(csrf_app: Flask) -> None:
    c = csrf_app.test_client()
    token = csrf_token(c.get("/signup").get_data(as_text=True))
    c.post(
        "/signup",
        data={"csrf_token": token, "email": "a@example.com", "password": PASSWORD, "org_name": "A"},
    )
    assert c.post("/members", data={"email": "b@example.com", "role": "viewer"}).status_code == 400


# ------------------------------------------------------------------ rate limits


@pytest.fixture
def limited_app(config: Config) -> Flask:
    return create_app(replace(config, rate_limits=True))


def test_login_is_rate_limited_per_client(limited_app: Flask) -> None:
    c = limited_app.test_client()
    codes = [
        c.post("/login", data={"email": f"u{i}@example.com", "password": "x" * 14}).status_code
        for i in range(11)
    ]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429
    page = c.post("/login", data={"email": "z@example.com", "password": "x"})
    assert "Too many requests" in page.get_data(as_text=True)
    assert c.get("/login").status_code == 200  # only POSTs count


def test_signup_is_rate_limited(limited_app: Flask) -> None:
    c = limited_app.test_client()
    codes = []
    for i in range(6):
        codes.append(
            c.post(
                "/signup",
                data={"email": f"s{i}@example.com", "password": "short", "org_name": "S"},
            ).status_code
        )
    assert codes[-1] == 429


def test_upload_is_rate_limited(limited_app: Flask, tmp_path: Path) -> None:
    c = limited_app.test_client()
    signup(c)
    codes = [c.post("/upload", data={}).status_code for _ in range(21)]
    assert codes[:20] == [302] * 20
    assert codes[20] == 429


def test_static_files_do_not_count_against_the_general_limit(limited_app: Flask) -> None:
    c = limited_app.test_client()
    resp = c.get("/static/css/app.css")
    assert resp.status_code == 200
    assert "X-RateLimit-Limit" not in resp.headers
    assert "X-RateLimit-Limit" in c.get("/login").headers


def test_login_email_key_is_per_client_and_bounded(app: Flask) -> None:
    from finops_app.security import login_email_key

    with app.test_request_context(
        "/login",
        method="POST",
        data={"email": " Ann@Example.com "},
        environ_base={"REMOTE_ADDR": "10.0.0.1"},
    ):
        assert login_email_key() == "login-email:10.0.0.1:ann@example.com"
    with app.test_request_context(
        "/login",
        method="POST",
        data={"email": "x" * 5000},
        environ_base={"REMOTE_ADDR": "10.0.0.2"},
    ):
        assert len(login_email_key()) < 400


def test_only_failed_sign_ins_count_per_email() -> None:
    from werkzeug.wrappers import Response

    from finops_app.security import failed_sign_in

    assert failed_sign_in(Response(status=200)) is True
    assert failed_sign_in(Response(status=302)) is False


def test_production_without_redis_warns_about_shared_limits(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    create_app(replace(config, env="production", rate_limits=True))
    assert "Rate limits are counted per process" in caplog.text
