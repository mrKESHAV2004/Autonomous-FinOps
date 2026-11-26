"""Alerts views: configure Slack webhooks and email notifications, view alert history."""

from __future__ import annotations

import logging

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from werkzeug.wrappers import Response

from finops_app import repository as repo
from finops_app.alerts import AlertEvent, send_email_notification, send_slack_notification
from finops_app.auth import current_org_id, role_required
from finops_app.db import get_session
from finops_app.forms import AlertConfigForm, ConfirmForm

logger = logging.getLogger(__name__)

bp = Blueprint("alerts", __name__, url_prefix="/alerts")


@bp.get("")
@role_required("viewer")
def index() -> str:
    session = get_session()
    org_id = current_org_id()
    configs = repo.list_alert_configs(session, org_id)
    history = repo.list_alert_history(session, org_id, limit=30)

    return render_template(
        "alerts.html",
        configs=configs,
        history=history,
        alert_form=AlertConfigForm(),
        confirm_form=ConfirmForm(),
        active="alerts",
    )


@bp.post("")
@role_required("admin")
def save_config() -> Response:
    form = AlertConfigForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", "danger")
        return redirect(url_for("alerts.index"))

    session = get_session()
    org_id = current_org_id()

    try:
        cfg = repo.save_alert_config(
            session,
            org_id=org_id,
            channel_type=form.channel_type.data or "slack",
            destination=form.destination.data or "",
            notify_high_confidence=bool(form.notify_high_confidence.data),
            notify_budget_exceeded=bool(form.notify_budget_exceeded.data),
            notify_spend_spikes=bool(form.notify_spend_spikes.data),
            spike_threshold_percent=float(form.spike_threshold_percent.data or 20.0),
            is_active=bool(form.is_active.data),
        )
        repo.audit(
            session,
            org_id,
            "alert_config.saved",
            "alert_config",
            cfg.id,
            {"channel_type": cfg.channel_type},
        )
        session.commit()
        flash("Alert channel configured successfully.", "success")
    except Exception as exc:
        session.rollback()
        logger.exception("Failed to save alert config")
        flash(f"Error saving alert config: {exc}", "danger")

    return redirect(url_for("alerts.index"))


@bp.post("/<config_id>/delete")
@role_required("admin")
def delete(config_id: str) -> Response:
    session = get_session()
    org_id = current_org_id()

    ok = repo.delete_alert_config(session, org_id, config_id)
    if not ok:
        abort(404)
    repo.audit(session, org_id, "alert_config.deleted", "alert_config", config_id)
    session.commit()
    flash("Alert configuration deleted.", "info")
    return redirect(url_for("alerts.index"))


@bp.post("/<config_id>/test")
@role_required("admin")
def test_channel(config_id: str) -> Response:
    session = get_session()
    org_id = current_org_id()
    cfg = repo.get_alert_config(session, org_id, config_id)
    if not cfg:
        abort(404)

    test_event = AlertEvent(
        event_type="test_alert",
        summary="Test notification from Autonomous-FinOps. Notifications are active!",
        details={"status": "ok"},
    )

    if cfg.channel_type == "slack":
        ok, err = send_slack_notification(cfg.destination, test_event, "Test Org")
    else:
        ok, err = send_email_notification(cfg.destination, test_event, "Test Org")

    if ok:
        flash(f"Test notification sent successfully to {cfg.destination}.", "success")
    else:
        flash(f"Test notification failed: {err}", "danger")

    return redirect(url_for("alerts.index"))
