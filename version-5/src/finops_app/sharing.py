"""Read-only share links to one analysis, and the savings page.

A link is ``/share/<token>``; only the token's SHA-256 is stored, so a
database leak doesn't leak working links. Owners and admins create links
(7 or 30 days) and can revoke them; anyone holding a live link sees the
overview without signing in.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from flask import Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from finops_app import analysis as dashboard
from finops_app import finding_queries as fq
from finops_app import repository as repo
from finops_app import serializers as ser
from finops_app import triage
from finops_app.auth import current_org_id, role_required
from finops_app.db import get_session
from finops_app.models import Analysis, ShareLink, utcnow
from finops_app.routes import OVERVIEW_TOP, bp
from finops_app.savings import CONFIRMED, STILL_FLAGGED, WAITING, savings

EXPIRY_CHOICES = (7, 30)
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_link(session: Session, analysis: Analysis, user_id: str, days: int) -> str:
    """Create a link and return its token (shown once, never stored)."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    link = ShareLink(
        org_id=analysis.org_id,
        analysis_id=analysis.id,
        token_hash=_hash(token),
        created_by=user_id,
        expires_at=utcnow() + timedelta(days=days),
    )
    session.add(link)
    session.flush()
    repo.audit(
        session, analysis.org_id, "share.created", "analysis", analysis.id,
        {"link": link.id, "days": days}, user_id=user_id,
    )  # fmt: skip
    return token


def live_link(session: Session, token: str) -> ShareLink | None:
    stmt = select(ShareLink).where(
        ShareLink.token_hash == _hash(token),
        ShareLink.revoked_at.is_(None),
        ShareLink.expires_at > utcnow(),
    )
    return session.scalars(stmt).first()


def live_links(session: Session, org_id: str, analysis_id: str) -> list[ShareLink]:
    stmt = (
        repo.scoped(ShareLink, org_id)
        .where(
            ShareLink.analysis_id == analysis_id,
            ShareLink.revoked_at.is_(None),
            ShareLink.expires_at > utcnow(),
        )
        .order_by(ShareLink.created_at.desc())
    )
    return list(session.scalars(stmt))


# ------------------------------------------------------------------ routes


@bp.post("/analyses/<analysis_id>/share")
@role_required("admin")
def create_share(analysis_id: str) -> Response:
    session = get_session()
    found = repo.get_analysis(session, current_org_id(), analysis_id)
    if found is None or found.status != "succeeded":
        abort(404)
    days = request.form.get("days", type=int)
    if days not in EXPIRY_CHOICES:
        abort(400)
    token = create_link(session, found, current_user.id, days)
    session.commit()
    flash(url_for("web.shared_report", token=token, _external=True), "share")
    return redirect(url_for("web.show_analysis", analysis_id=analysis_id) + "#share-title")  # type: ignore[return-value]


@bp.post("/share-links/<link_id>/revoke")
@role_required("admin")
def revoke_share(link_id: str) -> Response:
    session = get_session()
    link = session.scalars(
        repo.scoped(ShareLink, current_org_id()).where(ShareLink.id == link_id)
    ).first()
    if link is None:
        abort(404)
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        repo.audit(
            session, link.org_id, "share.revoked", "analysis", link.analysis_id,
            {"link": link.id}, user_id=current_user.id,
        )  # fmt: skip
        session.commit()
    flash("Link revoked. Anyone using it now gets “not found”.", "info")
    return redirect(url_for("web.show_analysis", analysis_id=link.analysis_id) + "#share-title")  # type: ignore[return-value]


def _shared(token: str) -> tuple[ShareLink, Analysis]:
    link = live_link(get_session(), token)
    if link is None or link.analysis.status != "succeeded":
        abort(404)
    return link, link.analysis


@bp.get("/share/<token>")
def shared_report(token: str) -> Response:
    link, found = _shared(token)
    session = get_session()
    top = fq.list_page(
        session, found.org_id, found.id, fq.FindingQuery(status="active", per_page=OVERVIEW_TOP)
    )
    html = render_template(
        "dashboard.html",
        shared=True,
        share_expires=link.expires_at,
        org_name=_org_name(found),
        results=dashboard.build_dashboard(repo.load_result(found), found.finished_at),
        analysis=found,
        summary=fq.status_summary(session, found.org_id, found.id),
        top=[ser.finding_dict(f) for f in top.items],
        active_total=top.total,
        status_labels=triage.STATUS_LABELS,
        series=ser.series_dict(found),
        data_url=url_for("web.shared_data", token=token),
    )
    resp = Response(html)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"  # the token is in the URL
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


def _org_name(found: Analysis) -> str:
    from finops_app.models import Organization

    org = get_session().get(Organization, found.org_id)
    return org.name if org else ""


@bp.get("/share/<token>/data.json")
def shared_data(token: str) -> Response:
    _, found = _shared(token)
    data = ser.series_dict(found) | {"waste_by_service": repo.load_result(found).waste_by_service()}
    resp = jsonify({"success": True, "data": data, "error": None})
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@bp.get("/savings")
@role_required("viewer")
def savings_page() -> str:
    return render_template(
        "savings.html",
        s=savings(get_session(), current_org_id()),
        CONFIRMED=CONFIRMED,
        STILL_FLAGGED=STILL_FLAGGED,
        WAITING=WAITING,
    )
