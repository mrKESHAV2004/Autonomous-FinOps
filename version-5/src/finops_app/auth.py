"""Sign-up, sign-in and the organisation each request acts for.

The active organisation is kept in the session and re-checked against the
user's memberships on every request, so removing someone takes effect at
once. Routes read it with :func:`current_org_id` and :func:`current_role`;
nothing takes an org id from the URL or a form.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from typing import Any, TypeVar, cast
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_url,
    login_user,
    logout_user,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from finops_app import accounts
from finops_app.config import Config
from finops_app.db import get_session
from finops_app.forms import ConfirmForm, LoginForm, SignupForm, SwitchOrgForm
from finops_app.models import Membership, User
from finops_app.repository import audit
from finops_app.security import (
    LOGIN_EMAIL_LIMIT,
    LOGIN_LIMIT,
    SIGNUP_LIMIT,
    failed_sign_in,
    limiter,
    login_email_key,
)

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)
login_manager = LoginManager()
ORG_SESSION_KEY = "org_id"
F = TypeVar("F", bound=Callable[..., Any])
# Pages a signed-in user with no organisation can still reach.
_NO_ORG_ENDPOINTS = frozenset(
    {"auth.logout", "auth.no_org", "static", "web.home", "web.sample_data"}
)


@dataclass(frozen=True)
class SignedInUser(UserMixin):
    """What Flask-Login keeps for the current user (not the ORM row)."""

    id: str
    email: str
    name: str | None

    @classmethod
    def of(cls, user: User) -> SignedInUser:
        return cls(id=user.id, email=user.email, name=user.name)


@dataclass(frozen=True)
class ActiveMembership:
    org_id: str
    org_name: str
    role: str
    membership_id: str


def init_app(app: Flask, cfg: Config) -> None:
    app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(hours=cfg.session_hours),
        SESSION_REFRESH_EACH_REQUEST=True,  # the timeout counts from the last request
    )
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.session_protection = "basic"
    app.before_request(_load_active_org)
    app.context_processor(_template_context)
    app.register_blueprint(bp)


@login_manager.unauthorized_handler
def _unauthorized() -> Response | tuple[Response, int]:
    """API calls get a 401; pages redirect to sign-in and come back after."""
    if request.path.startswith("/api/"):
        body = {"success": False, "data": None, "error": "Sign in first."}
        return jsonify(body), 401
    flash(login_manager.login_message, "info")
    return redirect(login_url("auth.login", request.url))


@login_manager.user_loader
def _load_user(user_id: str) -> SignedInUser | None:
    user = accounts.get_user(get_session(), user_id)
    return SignedInUser.of(user) if user is not None else None


def _load_active_org() -> Response | None:
    if request.endpoint == "static" or not current_user.is_authenticated:
        return None
    members = accounts.memberships_for(get_session(), current_user.id)
    if not members:
        g.active = None
        if request.endpoint in _NO_ORG_ENDPOINTS:
            return None
        return redirect(url_for("auth.no_org"))
    chosen = next((m for m in members if m.org_id == session.get(ORG_SESSION_KEY)), members[0])
    session[ORG_SESSION_KEY] = chosen.org_id
    g.active = _active(chosen)
    g.memberships = [_active(m) for m in members]
    return None


def _active(m: Membership) -> ActiveMembership:
    return ActiveMembership(
        org_id=m.org_id, org_name=m.organization.name, role=m.role, membership_id=m.id
    )


def _template_context() -> dict[str, Any]:
    return {
        "active_org": g.get("active"),
        "memberships": g.get("memberships", []),
        "can": lambda role: accounts.can(current_role(), role),
        "signout_form": ConfirmForm() if current_user.is_authenticated else None,
    }


def current_org_id() -> str:
    active: ActiveMembership | None = g.get("active")
    if active is None:
        abort(403)
    return active.org_id


def current_role() -> str | None:
    active: ActiveMembership | None = g.get("active")
    return active.role if active is not None else None


def role_required(role: str) -> Callable[[F], F]:
    """Sign-in plus at least ``role`` in the active organisation, else 403."""

    def decorator(view: F) -> F:
        @wraps(view)
        @login_required
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not accounts.can(current_role(), role):
                abort(403)
            return view(*args, **kwargs)

        return cast(F, wrapped)

    return decorator


def _safe_next(target: str | None) -> str:
    """``target`` if it is a path on this site, else the history page."""
    if target:
        parts = urlsplit(target)
        same_site = not parts.scheme and not parts.netloc
        if same_site and target.startswith("/") and not target.startswith(("//", "/\\")):
            return target
    return url_for("web.history")


def _start_session(user: User) -> None:
    """Sign in with a fresh session (nothing from before sign-in carries over)."""
    session.clear()
    session.permanent = True
    login_user(SignedInUser.of(user))


# ------------------------------------------------------------------ routes


@bp.route("/signup", methods=["GET", "POST"])
@limiter.limit(SIGNUP_LIMIT, methods=["POST"])
def signup() -> str | Response:
    if current_user.is_authenticated:
        return redirect(url_for("web.history"))
    form = SignupForm()
    if form.validate_on_submit():
        db = get_session()
        try:
            user = accounts.create_user(db, form.email.data, form.password.data, form.name.data)
            org = accounts.create_org(db, form.org_name.data, user)
            db.commit()
        except accounts.AccountError as exc:
            db.rollback()
            form.form_errors.append(str(exc))
        except IntegrityError:
            db.rollback()
            form.form_errors.append("An account with this email already exists. Sign in instead.")
        else:
            _start_session(user)
            session[ORG_SESSION_KEY] = org.id
            logger.info("Signed up", extra={"user": user.id, "org": org.id})
            return redirect(url_for("web.index"))
    return render_template("auth.html", form=form, mode="signup")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_LIMIT, methods=["POST"])
@limiter.limit(
    LOGIN_EMAIL_LIMIT, methods=["POST"], key_func=login_email_key, deduct_when=failed_sign_in
)
def login() -> str | Response:
    if current_user.is_authenticated:
        return redirect(_safe_next(request.args.get("next")))
    form = LoginForm()
    if form.validate_on_submit():
        db = get_session()
        user = accounts.authenticate(db, form.email.data, form.password.data)
        if user is None:
            known = accounts.get_user_by_email(db, form.email.data)
            if known is not None:
                audit(db, None, "login.failed", "user", known.id, user_id=known.id)
                db.commit()
            logger.info("Sign-in failed")
            form.form_errors.append("Email or password is incorrect.")
        else:
            first = accounts.memberships_for(db, user.id)
            audit(
                db,
                first[0].org_id if first else None,
                "login.succeeded",
                "user",
                user.id,
                user_id=user.id,
            )
            db.commit()
            _start_session(user)
            return redirect(_safe_next(request.args.get("next")))
    return render_template("auth.html", form=form, mode="login")


@bp.post("/logout")
def logout() -> Response:
    if ConfirmForm().validate_on_submit():
        logout_user()
        session.clear()
        flash("You're signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.post("/org/switch")
@login_required
def switch_org() -> Response:
    form = SwitchOrgForm()
    if not form.validate_on_submit():
        abort(400)
    if accounts.membership(get_session(), form.org_id.data, current_user.id) is None:
        abort(404)
    session[ORG_SESSION_KEY] = form.org_id.data
    return redirect(url_for("web.history"))


@bp.get("/no-organisation")
@login_required
def no_org() -> str | Response:
    if g.get("active") is not None:
        return redirect(url_for("web.history"))
    return render_template("no_org.html")
