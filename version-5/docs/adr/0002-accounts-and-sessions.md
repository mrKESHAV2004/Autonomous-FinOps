# ADR 0002: Server-side sign-in with Flask-Login, orgs chosen per request

**Status:** accepted, 2026-11-26 (Phase 3)

## Context

Phase 3 adds accounts and lets several organisations share one deployment.
The plan's bar: two orgs side by side with no data leakage. The app is
server-rendered Flask; there is no separate front end or public API yet.

## Decisions

1. **Flask-Login with Flask's signed-cookie session**, not JWTs or a token API.
   Every page is rendered by the server, so a cookie session is simplest and
   works with CSRF tokens. A JSON API (Phase 4+) can add tokens later.
2. **argon2id** (`argon2-cffi`) for passwords. Hashes are upgraded on the next
   sign-in when the parameters change. An unknown email is checked against a
   dummy hash, so both answers take the same time.
3. **The active organisation is chosen per request.** The session stores only
   which org the user last picked; `auth._load_active_org` re-reads the user's
   memberships on every request and falls back to the first one. Removing a
   member takes effect on their next click, and a tampered session can't reach
   an org the user isn't in. Routes call `current_org_id()`; nothing reads an
   org id from the URL or a form.
4. **Four fixed roles** (viewer < analyst < admin < owner) in `accounts.py`,
   checked by `role_required(...)` on each route. Admins manage only roles
   below their own; owners manage everyone; the last owner can't leave or be
   demoted.
5. **No email-based invites or password reset yet.** There is no email service.
   People sign up, then an admin adds them by email. `finops-users create`
   covers operators (e.g. granting access to the pre-Phase-3 `default` org).
6. **Security headers written by hand** (`security.py`, about 40 lines) instead
   of Flask-Talisman, which is barely maintained. CSP uses a per-request nonce;
   inline event handlers were removed.
7. **Flask-Limiter**, counters in Redis when configured (shared by all web
   processes), in memory otherwise (per process; fine for one dev server).

## Consequences

- Sign-up reveals whether an email already has an account. Sign-in does not.
  Sign-up is limited to 5 per hour per IP, which keeps probing slow.
- Restarting a dev server without `FINOPS_SECRET_KEY` signs everyone out.
- Behind a load balancer, `FINOPS_TRUSTED_PROXIES` must be set or every
  client shares the proxy's rate-limit bucket.
- Still to come: OAuth (Google, GitHub), password reset and email invites
  once an email service exists, and API tokens with the Phase 4 JSON API.
