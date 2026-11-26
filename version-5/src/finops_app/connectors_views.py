"""Cloud connectors views: connect AWS CUR 2.0 / FOCUS exports, verify access, trigger sync."""

from __future__ import annotations

import logging
import uuid

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from finops_app import repository as repo
from finops_app.auth import current_org_id, role_required
from finops_app.connectors.aws import AwsConnector
from finops_app.connectors.sync import get_connector, sync_connection
from finops_app.db import get_session
from finops_app.forms import AwsConnectionForm, ConfirmForm
from finops_app.models import CloudConnection

logger = logging.getLogger(__name__)

bp = Blueprint("connectors", __name__, url_prefix="/connectors")


def _connection_or_404(connection_id: str) -> CloudConnection:
    conn = repo.get_connection(get_session(), current_org_id(), connection_id)
    if conn is None:
        abort(404)
    return conn


@bp.get("")
@role_required("viewer")
def index() -> str:
    session = get_session()
    org_id = current_org_id()
    connections = repo.list_connections(session, org_id)

    # Provide a fresh external ID for new AWS connections
    suggested_external_id = uuid.uuid4().hex
    cf_template = AwsConnector.generate_cloudformation_template(
        external_id=suggested_external_id,
        s3_bucket="your-cur-export-bucket",
    )

    return render_template(
        "connectors.html",
        connections=connections,
        aws_form=AwsConnectionForm(),
        confirm_form=ConfirmForm(),
        suggested_external_id=suggested_external_id,
        cf_template=cf_template,
        active="connectors",
    )


@bp.post("/aws")
@role_required("analyst")
def add_aws() -> Response:
    form = AwsConnectionForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", "danger")
        return redirect(url_for("connectors.index"))

    session = get_session()
    org_id = current_org_id()
    external_id = request.form.get("external_id") or uuid.uuid4().hex

    try:
        conn = repo.create_connection(
            session,
            org_id=org_id,
            provider="aws",
            name=form.name.data or "AWS Connection",
            role_arn=form.role_arn.data,
            external_id=external_id,
            s3_bucket=form.s3_bucket.data,
            s3_prefix=form.s3_prefix.data,
            region=form.region.data or "us-east-1",
            status="pending",
        )
        repo.audit(session, org_id, "connection.created", "cloud_connection", conn.id)
        session.commit()
        flash(f"AWS connection '{conn.name}' added. Click 'Verify' to test access.", "success")
    except Exception as exc:
        session.rollback()
        logger.exception("Failed to add AWS connection")
        flash(f"Error adding connection: {exc}", "danger")

    return redirect(url_for("connectors.index"))


@bp.post("/<connection_id>/verify")
@role_required("analyst")
def verify(connection_id: str) -> Response:
    conn = _connection_or_404(connection_id)
    session = get_session()

    try:
        connector = get_connector(conn)
        res = connector.verify()
        if res.success:
            conn.status = "active"
            conn.last_error = None
            flash(f"Verified: {res.message}", "success")
        else:
            conn.status = "error"
            conn.last_error = res.message
            flash(f"Verification failed: {res.message}", "danger")
        repo.audit(
            session,
            conn.org_id,
            "connection.verified",
            "cloud_connection",
            conn.id,
            {"success": res.success},
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        flash(f"Verification error: {exc}", "danger")

    return redirect(url_for("connectors.index"))


@bp.post("/<connection_id>/sync")
@role_required("analyst")
def sync(connection_id: str) -> Response:
    conn = _connection_or_404(connection_id)
    session = get_session()
    storage = current_app.extensions["finops_storage"]
    queue = current_app.extensions["finops_queue"]

    try:
        analysis = sync_connection(session, storage, queue, conn, force=True)
        session.commit()
        if analysis:
            flash(f"Sync complete: analysis queued for {conn.name}.", "success")
            return redirect(url_for("web.show_analysis", analysis_id=analysis.id))
        else:
            flash(f"Sync finished for {conn.name}. No new export files found.", "info")
    except Exception as exc:
        session.rollback()
        logger.exception("Sync failed for connection %s", conn.name)
        flash(f"Sync failed: {exc}", "danger")

    return redirect(url_for("connectors.index"))


@bp.post("/<connection_id>/delete")
@role_required("admin")
def delete(connection_id: str) -> Response:
    conn = _connection_or_404(connection_id)
    session = get_session()
    org_id = current_org_id()

    repo.delete_connection(session, org_id, conn.id)
    repo.audit(session, org_id, "connection.deleted", "cloud_connection", conn.id)
    session.commit()
    flash(f"Connection '{conn.name}' deleted.", "info")
    return redirect(url_for("connectors.index"))
