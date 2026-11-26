"""Sign-up and sign-in helpers for web tests."""

from __future__ import annotations

import io
import re

from flask.testing import FlaskClient

PASSWORD = "correct horse battery staple"


def signup(
    client: FlaskClient, email: str = "owner@acme.example.com", org: str = "Acme", name: str = ""
) -> None:
    resp = client.post(
        "/signup", data={"name": name, "email": email, "password": PASSWORD, "org_name": org}
    )
    assert resp.status_code == 302, resp.get_data(as_text=True)


def login(client: FlaskClient, email: str, password: str = PASSWORD) -> FlaskClient:
    resp = client.post("/login", data={"email": email, "password": password})
    assert resp.status_code == 302, resp.get_data(as_text=True)
    return client


def upload(client: FlaskClient, content: bytes, filename: str = "bill.csv") -> str:
    """POST an upload; returns the analysis URL it redirects to."""
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302, resp.get_data(as_text=True)
    location: str = resp.headers["Location"]
    return location


def csrf_token(html: str) -> str:
    found = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html) or re.search(
        r'name="csrf_token" value="([^"]+)"', html
    )
    assert found, "no CSRF token in page"
    return found.group(1)


def member_id(html: str, email: str) -> str:
    """The membership id in the remove-form action on the row for ``email``."""
    row = html[html.index(email) :]
    found = re.search(r"/members/([0-9a-f]{32})/remove", row)
    assert found, f"no remove form for {email}"
    return found.group(1)
