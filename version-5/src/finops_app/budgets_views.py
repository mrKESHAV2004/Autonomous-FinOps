"""Budgets views: set monthly budget targets and track spend and forecasts against them."""

from __future__ import annotations

import logging

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from werkzeug.wrappers import Response

from finops_app import repository as repo
from finops_app.auth import current_org_id, role_required
from finops_app.budgets import evaluate_budgets
from finops_app.db import get_session
from finops_app.forms import BudgetForm, ConfirmForm

logger = logging.getLogger(__name__)

bp = Blueprint("budgets", __name__, url_prefix="/budgets")


@bp.get("")
@role_required("viewer")
def index() -> str:
    session = get_session()
    org_id = current_org_id()
    budgets = repo.list_budgets(session, org_id)

    # Get latest analysis to evaluate current budget statuses
    history = repo.list_analyses(session, org_id, limit=1)
    latest_analysis = history[0] if history else None
    budget_statuses = evaluate_budgets(session, org_id, latest_analysis) if latest_analysis else []

    # Map status by budget_id for easy display
    status_map = {s.budget_id: s for s in budget_statuses}

    return render_template(
        "budgets.html",
        budgets=budgets,
        status_map=status_map,
        latest_analysis=latest_analysis,
        budget_form=BudgetForm(),
        confirm_form=ConfirmForm(),
        active="budgets",
    )


@bp.post("")
@role_required("analyst")
def save_budget() -> Response:
    form = BudgetForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", "danger")
        return redirect(url_for("budgets.index"))

    session = get_session()
    org_id = current_org_id()

    try:
        budget = repo.upsert_budget(
            session,
            org_id=org_id,
            scope_type=form.scope_type.data or "total",
            scope_value=form.scope_value.data,
            monthly_amount=float(form.monthly_amount.data or 0.0),
        )
        repo.audit(
            session,
            org_id,
            "budget.saved",
            "budget",
            budget.id,
            {"scope_type": budget.scope_type, "amount": budget.monthly_amount},
        )
        session.commit()
        flash("Budget saved successfully.", "success")
    except Exception as exc:
        session.rollback()
        logger.exception("Failed to save budget")
        flash(f"Error saving budget: {exc}", "danger")

    return redirect(url_for("budgets.index"))


@bp.post("/<budget_id>/delete")
@role_required("admin")
def delete(budget_id: str) -> Response:
    session = get_session()
    org_id = current_org_id()

    ok = repo.delete_budget(session, org_id, budget_id)
    if not ok:
        abort(404)
    repo.audit(session, org_id, "budget.deleted", "budget", budget_id)
    session.commit()
    flash("Budget deleted.", "info")
    return redirect(url_for("budgets.index"))
