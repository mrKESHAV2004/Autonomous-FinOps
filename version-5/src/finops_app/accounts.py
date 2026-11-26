"""Users, organisations and memberships, and the rules for changing them.

Roles, from least to most access: viewer (read results), analyst (also
upload), admin (also manage analysts and viewers), owner (everything,
including other admins and owners). An organisation always keeps at least
one owner.
"""

from __future__ import annotations

import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from finops_app.models import Membership, Organization, User, utcnow
from finops_app.repository import audit, scoped

ROLES = ("viewer", "analyst", "admin", "owner")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
SLUG_MAX = 40

_hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths take as long.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


class AccountError(ValueError):
    """A change is not allowed; the message is safe to show the user."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def can(role: str | None, needed: str) -> bool:
    """True when ``role`` is at least ``needed``."""
    return role in ROLE_RANK and ROLE_RANK[role] >= ROLE_RANK[needed]


# ------------------------------------------------------------------ passwords


def check_password_rules(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"Use at least {MIN_PASSWORD_LENGTH} characters for the password.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AccountError(f"Use at most {MAX_PASSWORD_LENGTH} characters for the password.")
    if password.strip().lower() == normalize_email(email):
        raise AccountError("The password can't be your email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def authenticate(session: Session, email: str, password: str) -> User | None:
    """The user if the password matches, else None (same timing either way)."""
    user = get_user_by_email(session, email)
    stored = user.password_hash if user is not None and user.password_hash else _DUMMY_HASH
    try:
        _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return None
    if user is None or user.password_hash is None:
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    return user


# ------------------------------------------------------------------ users and orgs


def get_user(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalars(select(User).where(User.email == normalize_email(email))).first()


def create_user(session: Session, email: str, password: str, name: str | None = None) -> User:
    email = normalize_email(email)
    check_password_rules(password, email)
    if get_user_by_email(session, email) is not None:
        raise AccountError("An account with this email already exists. Sign in instead.")
    user = User(
        email=email, name=(name or "").strip() or None, password_hash=hash_password(password)
    )
    session.add(user)
    session.flush()
    return user


def create_org(session: Session, name: str, owner: User) -> Organization:
    """A new organisation with ``owner`` as its first owner."""
    org = Organization(name=name.strip(), slug=_slug(name))
    session.add(org)
    session.flush()
    session.add(Membership(org_id=org.id, user_id=owner.id, role="owner"))
    audit(session, org.id, "org.created", "organization", org.id, user_id=owner.id)
    session.flush()
    return org


def get_org_by_slug(session: Session, slug: str) -> Organization | None:
    return session.scalars(select(Organization).where(Organization.slug == slug)).first()


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:SLUG_MAX] or "org"
    return f"{base}-{secrets.token_hex(3)}"


# ------------------------------------------------------------------ memberships


def memberships_for(session: Session, user_id: str) -> list[Membership]:
    """The user's memberships, oldest first (the first is the default org)."""
    stmt = (
        select(Membership)
        .where(Membership.user_id == user_id)
        .options(selectinload(Membership.organization))
        .order_by(Membership.created_at)
    )
    return list(session.scalars(stmt))


def membership(session: Session, org_id: str, user_id: str) -> Membership | None:
    stmt = scoped(Membership, org_id).where(Membership.user_id == user_id)
    return session.scalars(stmt).first()


def list_members(session: Session, org_id: str) -> list[Membership]:
    stmt = scoped(Membership, org_id).join(Membership.user).order_by(User.email)
    return list(session.scalars(stmt))


def get_member(session: Session, org_id: str, membership_id: str) -> Membership | None:
    stmt = scoped(Membership, org_id).where(Membership.id == membership_id)
    return session.scalars(stmt).first()


def assignable_roles(actor_role: str) -> tuple[str, ...]:
    """Roles ``actor_role`` may give: owners any, admins those below admin."""
    if actor_role == "owner":
        return ROLES
    return tuple(r for r in ROLES if ROLE_RANK[r] < ROLE_RANK.get(actor_role, 0))


def can_manage(actor_role: str, target_role: str) -> bool:
    """Owners manage everyone; admins manage analysts and viewers."""
    if actor_role == "owner":
        return True
    return can(actor_role, "admin") and ROLE_RANK[target_role] < ROLE_RANK[actor_role]


def add_member(
    session: Session, org_id: str, actor: Membership, email: str, role: str
) -> Membership:
    _check_assignable(actor, role)
    user = get_user_by_email(session, email)
    if user is None:
        raise AccountError("No account uses that email. Ask them to sign up first, then add them.")
    if membership(session, org_id, user.id) is not None:
        raise AccountError("That person is already a member.")
    added = Membership(org_id=org_id, user_id=user.id, role=role)
    session.add(added)
    session.flush()
    audit(session, org_id, "member.added", "user", user.id, {"role": role}, user_id=actor.user_id)
    return added


def change_role(session: Session, actor: Membership, target: Membership, role: str) -> None:
    _check_can_manage(actor, target)
    _check_assignable(actor, role)
    if target.role == "owner" and role != "owner":
        keep_an_owner(session, target)
    old, target.role = target.role, role
    audit(
        session,
        target.org_id,
        "member.role_changed",
        "user",
        target.user_id,
        {"from": old, "to": role},
        user_id=actor.user_id,
    )


def remove_member(session: Session, actor: Membership, target: Membership) -> None:
    _check_can_manage(actor, target)
    if target.role == "owner":
        keep_an_owner(session, target)
    audit(
        session,
        target.org_id,
        "member.removed",
        "user",
        target.user_id,
        {"role": target.role},
        user_id=actor.user_id,
    )
    session.delete(target)


def _check_assignable(actor: Membership, role: str) -> None:
    if role not in ROLE_RANK:
        raise AccountError("Choose a valid role.")
    if role not in assignable_roles(actor.role):
        raise AccountError(f"Only an owner can give the {role} role.")


def _check_can_manage(actor: Membership, target: Membership) -> None:
    if actor.org_id != target.org_id or not can_manage(actor.role, target.role):
        raise AccountError("You can't change this member.")


def keep_an_owner(session: Session, leaving: Membership) -> None:
    """Refuse when ``leaving`` is the org's last owner.

    Locks the organisation row first (PostgreSQL), so two owners demoting each
    other at once can't both pass the count.
    """
    session.execute(
        select(Organization.id).where(Organization.id == leaving.org_id).with_for_update()
    )
    owners = session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.org_id == leaving.org_id, Membership.role == "owner")
    )
    if (owners or 0) <= 1:
        raise AccountError(
            "An organisation needs at least one owner. Make someone else owner first."
        )
