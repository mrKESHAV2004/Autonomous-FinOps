"""``finops-users``: create accounts and give them access from the command line.

Mainly for granting access to the "default" organisation, which holds data
uploaded before accounts existed::

    finops-users create --email you@example.com --org default --role owner

The password is read from the terminal (or one line of stdin with
``--password-stdin``), never from the command line.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence

from finops_app import accounts
from finops_app import repository as repo
from finops_app.config import Config
from finops_app.db import Database
from finops_app.logging_config import configure_logging
from finops_app.models import Membership


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise accounts.AccountError("The passwords don't match.")
    return first


def create_member(db: Database, email: str, org_slug: str, role: str, password: str | None) -> str:
    """Create the user if needed and give them ``role`` in the org; returns a summary."""
    with db.session() as session:
        if org_slug == repo.DEFAULT_ORG_SLUG:
            org_id = repo.default_org_id(session)
        else:
            org = accounts.get_org_by_slug(session, org_slug)
            if org is None:
                raise accounts.AccountError(f"No organisation with the slug {org_slug!r}.")
            org_id = org.id
        user = accounts.get_user_by_email(session, email)
        created = user is None
        if user is None:
            if password is None:
                raise accounts.AccountError("A new account needs a password.")
            user = accounts.create_user(session, email, password)
        existing = accounts.membership(session, org_id, user.id)
        if existing is not None:
            if existing.role == "owner" and role != "owner":
                accounts.keep_an_owner(session, existing)
            existing.role = role
        else:
            session.add(Membership(org_id=org_id, user_id=user.id, role=role))
        repo.audit(session, org_id, "member.added_by_cli", "user", user.id, {"role": role})
        return f"{'Created' if created else 'Updated'} {user.email}: {role} of {org_slug}."


def users_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finops-users", description="Manage user accounts.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create a user (if new) and add them to an org")
    create.add_argument("--email", required=True)
    create.add_argument("--org", default=repo.DEFAULT_ORG_SLUG, help="organisation slug")
    create.add_argument("--role", choices=accounts.ROLES, default="owner")
    create.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    configure_logging(cfg.log_level, json_logs=cfg.log_json)
    db = Database(cfg.database_url)
    try:
        exists = False
        with db.session() as session:
            exists = accounts.get_user_by_email(session, args.email) is not None
        password = None if exists else _read_password(args.password_stdin)
        summary = create_member(db, args.email, args.org, args.role, password)
    except accounts.AccountError as exc:
        sys.stderr.write(f"finops-users: {exc}\n")
        return 1
    finally:
        db.dispose()
    sys.stdout.write(summary + "\n")
    return 0
