"""Response headers, the CSP nonce, CSRF and rate limits.

Every page gets a strict Content Security Policy: scripts run only with the
per-request nonce (``{{ csp_nonce() }}`` in templates), styles and fonts come
from this app and the two font hosts, and the page can't be framed.
"""

from __future__ import annotations

import logging
import secrets

from flask import Flask, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.wrappers import Response

from finops_app.config import Config

logger = logging.getLogger(__name__)

FONT_CSS_HOSTS = "https://api.fontshare.com https://fonts.googleapis.com"
FONT_FILE_HOSTS = "https://cdn.fontshare.com https://fonts.gstatic.com"
HSTS = "max-age=31536000; includeSubDomains"

# Limits (per client IP unless noted). Tuned for people, not scripts.
LOGIN_LIMIT = "10 per minute"
LOGIN_EMAIL_LIMIT = "20 per hour"  # failed attempts per email address and client
SIGNUP_LIMIT = "5 per hour"
UPLOAD_LIMIT = "20 per hour"
STATUS_LIMIT = "120 per minute"
DEFAULT_LIMIT = "300 per minute"

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[DEFAULT_LIMIT],
    default_limits_exempt_when=lambda: request.endpoint == "static",
)


def init_app(app: Flask, cfg: Config) -> None:
    if cfg.trusted_proxies:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app, x_for=cfg.trusted_proxies, x_proto=cfg.trusted_proxies
        )
    app.config.update(
        WTF_CSRF_ENABLED=cfg.csrf,
        WTF_CSRF_TIME_LIMIT=None,  # the token lives as long as the session
        RATELIMIT_ENABLED=cfg.rate_limits,
        RATELIMIT_STORAGE_URI=cfg.redis_url or "memory://",
        RATELIMIT_HEADERS_ENABLED=True,
    )
    if cfg.env == "production" and cfg.rate_limits and not cfg.redis_url:
        logger.warning(
            "Rate limits are counted per process: set FINOPS_REDIS_URL so all web "
            "processes share them"
        )
    csrf.init_app(app)
    limiter.init_app(app)
    app.jinja_env.globals["csp_nonce"] = csp_nonce
    hsts = cfg.env == "production"

    @app.after_request
    def _headers(response: Response) -> Response:
        return add_security_headers(response, hsts=hsts)


def csp_nonce() -> str:
    """This request's script nonce (made on first use)."""
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    nonce: str = g.csp_nonce
    return nonce


def content_security_policy(nonce: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}'",
            f"style-src 'self' {FONT_CSS_HOSTS}",
            f"font-src 'self' {FONT_FILE_HOSTS}",
            "img-src 'self' data:",
            "connect-src 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "object-src 'none'",
        )
    )


def add_security_headers(response: Response, *, hsts: bool) -> Response:
    headers = response.headers
    headers.setdefault("Content-Security-Policy", content_security_policy(csp_nonce()))
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if hsts:
        headers.setdefault("Strict-Transport-Security", HSTS)
    if current_user.is_authenticated and not request.path.startswith("/static/"):
        # Billing data must not linger in shared or proxy caches.
        headers["Cache-Control"] = "no-store"
    return response


EMAIL_KEY_MAX = 320


def login_email_key() -> str:
    """Rate-limit key: the email tried, from this client.

    Keyed per client too, so nobody can lock someone else out by failing
    sign-ins for their address from elsewhere.
    """
    email = (request.form.get("email") or "").strip().lower()[:EMAIL_KEY_MAX]
    return f"login-email:{get_remote_address()}:{email}"


def failed_sign_in(response: Response) -> bool:
    """Only failed attempts (the form shown again) count against the limit."""
    return response.status_code != 302
