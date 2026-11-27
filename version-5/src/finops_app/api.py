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


# --- Connectors API ---


@bp.get("/connectors")
@role_required("viewer")
def list_connectors() -> tuple[Response, int]:
    conns = repo.list_connections(get_session(), current_org_id())
    data = [
        {
            "id": c.id,
            "provider": c.provider,
            "name": c.name,
            "role_arn": c.role_arn,
            "external_id": c.external_id,
            "s3_bucket": c.s3_bucket,
            "s3_prefix": c.s3_prefix,
            "region": c.region,
            "status": c.status,
            "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None,
            "last_error": c.last_error,
        }
        for c in conns
    ]
    return ok(data)


@bp.post("/connectors/aws")
@role_required("analyst")
def add_aws_connector() -> tuple[Response, int]:
    import os
    import re
    import uuid

    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    role_arn = payload.get("role_arn")
    s3_bucket = payload.get("s3_bucket")
    region = payload.get("region") or "us-east-1"
    if not name or not role_arn or not s3_bucket:
        return fail("name, role_arn and s3_bucket are required.", 400)

    if not re.match(r"^arn:aws(?:-[a-z]+)?:iam::\d+:role/[\w+=,.@\-_/]+$", str(role_arn)):
        return fail("Invalid IAM role ARN format.", 400)
    if not re.match(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", str(s3_bucket)):
        return fail("Invalid S3 bucket name.", 400)
    if not re.match(r"^[a-z]{2}(?:-[a-z]+)+-\d+$", str(region)):
        return fail("Invalid AWS region format.", 400)

    own_account = os.environ.get("FINOPS_AWS_ACCOUNT_ID") or os.environ.get("AWS_ACCOUNT_ID")
    if own_account:
        m = re.search(r"arn:aws(?:-[a-z]+)?:iam::(\d+):role/", str(role_arn))
        if m and m.group(1) == own_account:
            return fail("Role ARN cannot point to internal FinOps AWS account.", 400)

    session = get_session()
    org_id = current_org_id()
    # Server-generated external ID (never accept client-supplied ID)
    external_id = uuid.uuid4().hex
    conn = repo.create_connection(
        session,
        org_id=org_id,
        provider="aws",
        name=name,
        role_arn=role_arn,
        external_id=external_id,
        s3_bucket=s3_bucket,
        s3_prefix=payload.get("s3_prefix"),
        region=region,
    )
    repo.audit(session, org_id, "connection.created", "cloud_connection", conn.id)
    session.commit()
    return ok(
        {
            "id": conn.id,
            "name": conn.name,
            "external_id": conn.external_id,
            "status": conn.status,
        },
        status=201,
    )


@bp.post("/connectors/<connection_id>/verify")
@role_required("analyst")
def verify_connector(connection_id: str) -> tuple[Response, int]:
    from finops_app.connectors.sync import get_connector

    session = get_session()
    conn = repo.get_connection(session, current_org_id(), connection_id)
    if not conn:
        abort(404)
    res = get_connector(conn).verify()
    conn.status = "active" if res.success else "error"
    conn.last_error = None if res.success else res.message
    repo.audit(session, conn.org_id, "connection.verified", "cloud_connection", conn.id)
    session.commit()
    return ok({"success": res.success, "message": res.message, "status": conn.status})


# --- Budgets API ---


@bp.get("/budgets")
@role_required("viewer")
def list_budgets_api() -> tuple[Response, int]:
    from finops_app.budgets import evaluate_budgets

    session = get_session()
    org_id = current_org_id()
    budgets = repo.list_budgets(session, org_id)

    history = repo.list_analyses(session, org_id, limit=1)
    latest_analysis = history[0] if history else None
    statuses = evaluate_budgets(session, org_id, latest_analysis) if latest_analysis else []
    status_by_id = {s.budget_id: s for s in statuses}

    data = [
        {
            "id": b.id,
            "scope_type": b.scope_type,
            "scope_value": b.scope_value,
            "monthly_amount": b.monthly_amount,
            "status": (
                {
                    "current_spend": status_by_id[b.id].current_spend,
                    "projected_spend": status_by_id[b.id].projected_spend,
                    "percent_used": status_by_id[b.id].percent_used,
                    "is_exceeded": status_by_id[b.id].is_exceeded,
                }
                if b.id in status_by_id
                else None
            ),
        }
        for b in budgets
    ]
    return ok(data)


@bp.post("/budgets")
@role_required("analyst")
def save_budget_api() -> tuple[Response, int]:
    payload = request.get_json(silent=True) or {}
    scope_type = payload.get("scope_type", "total")
    scope_value = payload.get("scope_value")
    try:
        monthly_amount = float(payload.get("monthly_amount", 0))
    except (TypeError, ValueError):
        return fail("monthly_amount must be a positive number.", 400)
    if monthly_amount <= 0:
        return fail("monthly_amount must be greater than zero.", 400)

    session = get_session()
    org_id = current_org_id()
    b = repo.upsert_budget(session, org_id, scope_type, scope_value, monthly_amount)
    repo.audit(session, org_id, "budget.saved", "budget", b.id)
    session.commit()
    return ok(
        {"id": b.id, "scope_type": b.scope_type, "monthly_amount": b.monthly_amount}, status=201
    )


# --- Alerts API ---


@bp.get("/alerts")
@role_required("viewer")
def list_alerts_api() -> tuple[Response, int]:
    session = get_session()
    org_id = current_org_id()
    from finops_app.alerts import mask_destination

    configs = repo.list_alert_configs(session, org_id)
    history = repo.list_alert_history(session, org_id, limit=20)
    data = {
        "configs": [
            {
                "id": c.id,
                "channel_type": c.channel_type,
                "destination": mask_destination(c.destination, c.channel_type),
                "notify_high_confidence": c.notify_high_confidence,
                "notify_budget_exceeded": c.notify_budget_exceeded,
                "notify_spend_spikes": c.notify_spend_spikes,
                "spike_threshold_percent": c.spike_threshold_percent,
                "is_active": c.is_active,
            }
            for c in configs
        ],
        "recent_history": [
            {
                "id": h.id,
                "event_type": h.event_type,
                "summary": h.summary,
                "channel_type": h.channel_type,
                "status": h.status,
                "created_at": h.created_at.isoformat(),
            }
            for h in history
        ],
    }
    return ok(data)


@bp.post("/alerts")
@role_required("admin")
def save_alert_api() -> tuple[Response, int]:
    from finops_app.alerts import is_safe_webhook_url

    payload = request.get_json(silent=True) or {}
    channel_type = payload.get("channel_type", "slack")
    destination = payload.get("destination")
    if not destination:
        return fail("destination is required.", 400)

    if channel_type == "slack":
        safe, reason = is_safe_webhook_url(destination)
        if not safe:
            return fail(f"Invalid webhook URL: {reason}", 400)

    session = get_session()
    org_id = current_org_id()
    cfg = repo.save_alert_config(
        session,
        org_id=org_id,
        channel_type=channel_type,
        destination=destination,
        notify_high_confidence=payload.get("notify_high_confidence", True),
        notify_budget_exceeded=payload.get("notify_budget_exceeded", True),
        notify_spend_spikes=payload.get("notify_spend_spikes", True),
        spike_threshold_percent=float(payload.get("spike_threshold_percent", 20.0)),
        is_active=payload.get("is_active", True),
    )
    repo.audit(session, org_id, "alert_config.saved", "alert_config", cfg.id)
    session.commit()
    return ok(
        {"id": cfg.id, "channel_type": cfg.channel_type, "destination": cfg.destination}, status=201
    )


@bp.get("/model-quality/precision")
@role_required("viewer")
def model_quality_precision() -> tuple[Response, int]:
    from finops_app.model_quality import compute_quality_scorecard

    session = get_session()
    scorecard = compute_quality_scorecard(session, current_org_id())
    return ok(scorecard)


@bp.get("/models")
@role_required("viewer")
def list_models_api() -> tuple[Response, int]:
    from finops_app.model_registry import list_versions

    session = get_session()
    models = list_versions(session)
    data = [
        {
            "id": m.id,
            "model_name": m.model_name,
            "version": m.version,
            "algorithm": m.algorithm,
            "is_active": m.is_active,
            "metrics": m.metrics,
            "created_at": m.created_at.isoformat(),
            "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
        }
        for m in models
    ]
    return ok(data)


@bp.post("/models/<name>/rollback")
@role_required("admin")
def rollback_model_api(name: str) -> tuple[Response, int]:
    import os

    from flask import current_app

    from finops_app.model_registry import RegistryError, rollback_version

    platform_admin_org = os.environ.get("FINOPS_PLATFORM_ADMIN_ORG") or current_app.config.get(
        "PLATFORM_ADMIN_ORG"
    )
    org_id = current_org_id()
    if not platform_admin_org or org_id != platform_admin_org:
        return fail("Platform administrator access required to roll back global models.", 403)

    session = get_session()
    try:
        prev = rollback_version(session, name)
        repo.audit(session, current_org_id(), "model.rollback", "model_version", prev.id)
        session.commit()
        return ok(
            {
                "model_name": prev.model_name,
                "version": prev.version,
                "is_active": prev.is_active,
                "deployed_at": prev.deployed_at.isoformat() if prev.deployed_at else None,
            }
        )
    except RegistryError as exc:
        return fail(str(exc), 400)
