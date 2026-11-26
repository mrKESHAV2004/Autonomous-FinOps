"""Pages for one analysis's findings: the table, CSV export, detail and status."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from finops_app import finding_queries as fq
from finops_app import repository as repo
from finops_app import serializers as ser
from finops_app import triage
from finops_app.auth import current_org_id, role_required
from finops_app.db import get_session
from finops_app.finding_text import explained_signals, recommended_action, signal_name
from finops_app.forms import StatusForm
from finops_app.models import Analysis, Finding
from finops_app.routes import bp

CSV_COLUMNS = (
    ("Resource", "label"),
    ("Resource ID", "resource_id"),
    ("Service", "service"),
    ("Region", "region"),
    ("Account", "account"),
    ("Total cost", "total_cost"),
    ("Estimated waste", "estimated_waste"),
    ("Estimated monthly waste", "estimated_monthly_waste"),
    ("Confidence", "confidence"),
    ("Status", "status_label"),
    ("Snoozed until", "snoozed_until"),
    ("Why", "reasons"),
)
# A cell starting with one of these is run as a formula by spreadsheet apps.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _succeeded(analysis_id: str) -> Analysis:
    found = repo.get_analysis(get_session(), current_org_id(), analysis_id)
    if found is None:
        abort(404)
    if found.status != "succeeded":
        return redirect(url_for("web.show_analysis", analysis_id=analysis_id))  # type: ignore[return-value]
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


@bp.get("/analyses/<analysis_id>/findings")
@role_required("viewer")
def findings(analysis_id: str) -> str | Response:
    a = _succeeded(analysis_id)
    if not isinstance(a, Analysis):
        return a
    session = get_session()
    if triage.wake_expired_snoozes(session, a.org_id, a.id):
        session.commit()
    query = fq.FindingQuery.from_args(request.args)
    page = fq.list_page(session, a.org_id, a.id, query)
    return render_template(
        "findings.html",
        analysis=a,
        query=query,
        page=page,
        rows=[ser.finding_dict(f) for f in page.items],
        facets=fq.facets(session, a.org_id, a.id),
        summary=fq.status_summary(session, a.org_id, a.id),
        status_labels=triage.STATUS_LABELS,
        per_page_choices=fq.PER_PAGE_CHOICES,
    )


@bp.get("/analyses/<analysis_id>/findings.csv")
@role_required("viewer")
def export_findings(analysis_id: str) -> Response:
    a = _succeeded(analysis_id)
    if not isinstance(a, Analysis):
        return a
    query = fq.FindingQuery.from_args(request.args)
    rows = fq.all_matching(get_session(), a.org_id, a.id, query)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([title for title, _ in CSV_COLUMNS])
    for f in rows:
        data = ser.finding_dict(f)
        writer.writerow([csv_cell(data[key]) for _, key in CSV_COLUMNS])
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        "﻿" + buffer.getvalue(),  # BOM so Excel reads UTF-8
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=findings-{stamp}.csv"},
    )


def csv_cell(value: object) -> str:
    """A CSV cell that spreadsheet apps show as text, never run as a formula."""
    if value is None:
        return ""
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value)
    if isinstance(value, float):
        return f"{value:.2f}"
    text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


@bp.get("/findings/<finding_id>")
@role_required("viewer")
def finding_detail(finding_id: str) -> str:
    f = _finding(finding_id)
    session = get_session()
    form = StatusForm(status=f.status if f.status != "open" else "acknowledged")
    return render_template(
        "finding.html",
        f=f,
        data=ser.finding_dict(f),
        analysis=f.analysis,
        events=triage.events_for(session, f.org_id, f.id),
        signals=explained_signals(f.signals),
        action=recommended_action(f.signals),
        signal_name=signal_name,
        form=form,
        status_labels=triage.STATUS_LABELS,
        today=triage.today(),
        back=_back_link(f),
    )


def _back_link(f: Finding) -> str:
    """Return to the filtered table the user came from, if it was ours."""
    ref = request.referrer or ""
    table = url_for("web.findings", analysis_id=f.analysis_id)
    marker = ref.find(table)
    if marker != -1 and ref.startswith(request.host_url):
        return ref[marker:]
    return table


@bp.post("/findings/<finding_id>/status")
@role_required("analyst")
def change_status(finding_id: str) -> Response:
    f = _finding(finding_id)
    form = StatusForm()
    target = url_for("web.finding_detail", finding_id=f.id)
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(str(error), "warning")
        return redirect(target)  # type: ignore[return-value]
    session = get_session()
    try:
        triage.set_status(
            session,
            f,
            form.status.data or "",
            user_id=current_user.id,
            note=form.note.data,
            snoozed_until=form.snoozed_until.data,
        )
    except triage.TriageError as exc:
        session.rollback()
        flash(str(exc), "warning")
        return redirect(target)  # type: ignore[return-value]
    session.commit()
    flash(f"Marked {triage.STATUS_LABELS[f.status].lower()}.", "info")
    return redirect(target)  # type: ignore[return-value]
