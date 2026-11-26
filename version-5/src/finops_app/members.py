"""The members page: who belongs to the active organisation, and their roles."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user
from werkzeug.wrappers import Response

from finops_app import accounts
from finops_app.auth import current_org_id, role_required
from finops_app.db import get_session
from finops_app.forms import AddMemberForm, ChangeRoleForm, ConfirmForm
from finops_app.models import Membership

bp = Blueprint("members", __name__, url_prefix="/members")


def _actor() -> Membership:
    actor = accounts.membership(get_session(), current_org_id(), current_user.id)
    if actor is None:
        abort(403)
    return actor


def _target(membership_id: str) -> Membership:
    target = accounts.get_member(get_session(), current_org_id(), membership_id)
    if target is None:
        abort(404)
    return target


def _page(add_form: AddMemberForm | None = None, status: int = 200) -> tuple[str, int]:
    actor = _actor()
    roles = accounts.assignable_roles(actor.role)
    form = add_form or AddMemberForm()
    form.role.choices = [(r, r.capitalize()) for r in roles]
    html = render_template(
        "members.html",
        members=accounts.list_members(get_session(), actor.org_id),
        actor=actor,
        add_form=form,
        confirm_form=ConfirmForm(),
        roles=roles,
        can_manage=accounts.can_manage,
    )
    return html, status


@bp.get("")
@role_required("admin")
def index() -> tuple[str, int]:
    return _page()


@bp.post("")
@role_required("admin")
def add() -> Response | tuple[str, int]:
    form = AddMemberForm()
    form.role.choices = [(r, r) for r in accounts.ROLES]
    if not form.validate_on_submit():
        return _page(form, 400)
    db = get_session()
    try:
        accounts.add_member(db, current_org_id(), _actor(), form.email.data, form.role.data)
        db.commit()
    except accounts.AccountError as exc:
        db.rollback()
        form.form_errors.append(str(exc))
        return _page(form, 400)
    flash(f"Added {accounts.normalize_email(form.email.data)} as {form.role.data}.", "info")
    return redirect(url_for("members.index"))


@bp.post("/<membership_id>/role")
@role_required("admin")
def change_role(membership_id: str) -> Response:
    form = ChangeRoleForm()
    form.role.choices = [(r, r) for r in accounts.ROLES]
    target = _target(membership_id)
    if not form.validate_on_submit():
        abort(400)
    db = get_session()
    try:
        accounts.change_role(db, _actor(), target, form.role.data)
        db.commit()
        flash(f"{target.user.email} is now {form.role.data}.", "info")
    except accounts.AccountError as exc:
        db.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("members.index"))


@bp.post("/<membership_id>/remove")
@role_required("admin")
def remove(membership_id: str) -> Response:
    target = _target(membership_id)
    if not ConfirmForm().validate_on_submit():
        abort(400)
    db = get_session()
    email = target.user.email
    try:
        accounts.remove_member(db, _actor(), target)
        db.commit()
        flash(f"Removed {email}.", "info")
    except accounts.AccountError as exc:
        db.rollback()
        flash(str(exc), "warning")
    return redirect(url_for("members.index"))
