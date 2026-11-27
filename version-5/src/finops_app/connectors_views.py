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

    from flask import session as flask_session

    # Provide a server-generated external ID stored in session for new AWS connections
    suggested_external_id = flask_session.get("suggested_external_id")
    if not suggested_external_id:
        suggested_external_id = uuid.uuid4().hex
        flask_session["suggested_external_id"] = suggested_external_id

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
    import os
    import re
    from flask import session as flask_session

    form = AwsConnectionForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", "danger")
        return redirect(url_for("connectors.index"))

    role_arn = form.role_arn.data or ""
    own_account = os.environ.get("FINOPS_AWS_ACCOUNT_ID") or os.environ.get("AWS_ACCOUNT_ID")
    if own_account:
        m = re.search(r"arn:aws(?:-[a-z]+)?:iam::(\d+):role/", role_arn)
        if m and m.group(1) == own_account:
            flash("Role ARN cannot point to internal FinOps AWS account.", "danger")
            return redirect(url_for("connectors.index"))

    session = get_session()
    org_id = current_org_id()
    # Server-generated external ID (never accept client-specified IDs)
    external_id = flask_session.pop("suggested_external_id", None) or uuid.uuid4().hex

    try:
        conn = repo.create_connection(
            session,
            org_id=org_id,
            provider="aws",
            name=form.name.data or "AWS Connection",
            role_arn=role_arn,
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
