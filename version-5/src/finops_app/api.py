"""JSON API (``/api/v1``) over the same sign-in, roles and org scoping as the pages.

Every response is ``{"success": bool, "data": ..., "error": str | None}``;
lists add ``"meta"`` with paging. POSTs need the ``X-CSRFToken`` header.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint, Response, abort, jsonify, request
from flask_login import current_user

from finops_app import finding_queries as fq
from finops_app import repository as repo
from finops_app import serializers as ser
from finops_app import triage
from finops_app.auth import current_org_id, role_required
from finops_app.db import get_session
from finops_app.models import Analysis, Finding

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def ok(data: Any, meta: dict[str, Any] | None = None, status: int = 200) -> tuple[Response, int]:
    body: dict[str, Any] = {"success": True, "data": data, "error": None}
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status


def fail(message: str, status: int) -> tuple[Response, int]:
    return jsonify({"success": False, "data": None, "error": message}), status


def _analysis(analysis_id: str, *, finished: bool = True) -> Analysis:
    found = repo.get_analysis(get_session(), current_org_id(), analysis_id)
    if found is None:
        abort(404)
    if finished and found.status != "succeeded":
        abort(409)
    return found


def _finding(finding_id: str) -> Finding:
    found = (
        get_session()
        .scalars(repo.scoped(Finding, current_org_id()).where(Finding.id == finding_id))
        .first()
    )
    if found is None:
        abort(404)
    return found


@bp.get("/analyses")
@role_required("viewer")
def list_analyses() -> tuple[Response, int]:
    analyses = repo.list_analyses(get_session(), current_org_id())
    return ok([ser.analysis_dict(a) for a in analyses])


@bp.get("/analyses/<analysis_id>")
@role_required("viewer")
def get_analysis(analysis_id: str) -> tuple[Response, int]:
    a = _analysis(analysis_id, finished=False)
    data = ser.analysis_dict(a)
    if a.status == "succeeded":
        session = get_session()
        triage.wake_expired_snoozes(session, a.org_id, a.id)
        session.commit()
        result = repo.load_result(a)
        data |= {
            "period": {"start": a.period_start, "end": a.period_end, "days": a.period_days},
            "records": a.records,
            "resources": a.resources,
            "findings": len(a.findings),
            "confidence": result.confidence_summary(),
            "waste_by_service": result.waste_by_service(),
            "by_status": fq.status_summary(session, a.org_id, a.id),
        }
    return ok(data)


@bp.get("/analyses/<analysis_id>/series")
@role_required("viewer")
def get_series(analysis_id: str) -> tuple[Response, int]:
    return ok(ser.series_dict(_analysis(analysis_id)))


@bp.get("/analyses/<analysis_id>/findings")
@role_required("viewer")
def list_findings(analysis_id: str) -> tuple[Response, int]:
    a = _analysis(analysis_id)
    query = fq.FindingQuery.from_args(request.args)
    page = fq.list_page(get_session(), a.org_id, a.id, query)
    meta = {"total": page.total, "page": page.page, "per_page": page.per_page, "pages": page.pages}
    return ok([ser.finding_dict(f) for f in page.items], meta)


@bp.get("/findings/<finding_id>")
@role_required("viewer")
def get_finding(finding_id: str) -> tuple[Response, int]:
    f = _finding(finding_id)
    events = triage.events_for(get_session(), f.org_id, f.id)
    return ok(ser.finding_detail_dict(f, events))


@bp.post("/findings/<finding_id>/status")
@role_required("analyst")
def change_status(finding_id: str) -> tuple[Response, int]:
    f = _finding(finding_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return fail("Send a JSON object.", 400)
    status, note, until = payload.get("status"), payload.get("note"), payload.get("snoozed_until")
    if not isinstance(status, str) or not isinstance(note, str | None):
        return fail("status must be a string and note a string or null.", 400)
    try:
        snooze = date.fromisoformat(until) if isinstance(until, str) and until else None
    except ValueError:
        return fail("snoozed_until must be a date like 2026-12-31.", 400)
    session = get_session()
    try:
        triage.set_status(
            session, f, status, user_id=current_user.id, note=note, snoozed_until=snooze
        )
    except triage.TriageError as exc:
        session.rollback()
        return fail(str(exc), 422)
    session.commit()
    return ok(ser.finding_detail_dict(f, triage.events_for(session, f.org_id, f.id)))
