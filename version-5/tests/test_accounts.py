from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from finops_app import accounts
from finops_app import repository as repo
from finops_app.db import Database, upgrade
from finops_app.models import AuditLog, Membership, User
from finops_app.users_cli import create_member, users_main
from web_helpers import PASSWORD


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    url = f"sqlite:///{tmp_path / 'acc.db'}"
    upgrade(url)
    database = Database(url)
    yield database
    database.dispose()


def test_role_ladder() -> None:
    assert accounts.can("owner", "viewer") and accounts.can("analyst", "analyst")
    assert not accounts.can("viewer", "analyst")
    assert not accounts.can(None, "viewer") and not accounts.can("root", "viewer")
    assert accounts.assignable_roles("owner") == accounts.ROLES
    assert accounts.assignable_roles("admin") == ("viewer", "analyst")
    assert accounts.can_manage("admin", "analyst") and not accounts.can_manage("admin", "admin")
    assert not accounts.can_manage("analyst", "viewer")


def test_authenticate(db: Database) -> None:
    with db.session() as s:
        accounts.create_user(s, "Pat@Example.com", PASSWORD)
    with db.session() as s:
        assert accounts.authenticate(s, "pat@example.com", "wrong password!") is None
        assert accounts.authenticate(s, "nobody@example.com", PASSWORD) is None
        user = accounts.authenticate(s, " PAT@example.com ", PASSWORD)
        assert user is not None and user.last_login_at is not None


def test_outdated_hashes_are_upgraded_on_sign_in(db: Database) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    with db.session() as s:
        s.add(User(email="old@example.com", password_hash=weak))
    with db.session() as s:
        assert accounts.authenticate(s, "old@example.com", PASSWORD) is not None
    with db.session() as s:
        stored = s.scalars(select(User.password_hash)).one()
        assert stored != weak


def test_account_without_password_cannot_sign_in(db: Database) -> None:
    with db.session() as s:
        s.add(User(email="sso@example.com", password_hash=None))
    with db.session() as s:
        assert accounts.authenticate(s, "sso@example.com", PASSWORD) is None


def test_org_slugs_are_unique_and_url_safe(db: Database) -> None:
    with db.session() as s:
        user = accounts.create_user(s, "a@example.com", PASSWORD)
        one = accounts.create_org(s, "Acme & Co!", user)
        two = accounts.create_org(s, "Acme & Co!", user)
        assert one.slug.startswith("acme-co-") and one.slug != two.slug
        assert accounts.create_org(s, "!!!", user).slug.startswith("org-")


def test_password_length_limits() -> None:
    with pytest.raises(accounts.AccountError, match="at most"):
        accounts.check_password_rules("x" * 129, "a@example.com")


def test_invalid_role_is_refused(db: Database) -> None:
    with db.session() as s:
        user = accounts.create_user(s, "a@example.com", PASSWORD)
        org = accounts.create_org(s, "A", user)
        owner = accounts.membership(s, org.id, user.id)
        assert owner is not None
        with pytest.raises(accounts.AccountError, match="valid role"):
            accounts.add_member(s, org.id, owner, "a@example.com", "superuser")


# ------------------------------------------------------------------ finops-users


def test_cli_grants_access_to_the_default_org(db: Database) -> None:
    summary = create_member(db, "ops@example.com", "default", "admin", PASSWORD)
    assert summary == "Created ops@example.com: admin of default."
    with db.session() as s:
        m = s.scalars(select(Membership)).one()
        assert m.org_id == repo.default_org_id(s) and m.role == "admin"
        assert s.scalars(select(AuditLog.action)).all() == ["member.added_by_cli"]

    again = create_member(db, "ops@example.com", "default", "viewer", None)
    assert again.startswith("Updated")
    with db.session() as s:
        assert s.scalars(select(Membership.role)).one() == "viewer"


def test_cli_errors(db: Database) -> None:
    with pytest.raises(accounts.AccountError, match="No organisation"):
        create_member(db, "a@example.com", "nope", "owner", PASSWORD)
    with pytest.raises(accounts.AccountError, match="needs a password"):
        create_member(db, "a@example.com", "default", "owner", None)


def test_cli_main_reads_the_password_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    upgrade(url)
    monkeypatch.setenv("FINOPS_DATABASE_URL", url)
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    assert users_main(["create", "--email", "c@example.com", "--password-stdin"]) == 0
    assert "Created c@example.com: owner of default." in capsys.readouterr().out

    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert users_main(["create", "--email", "d@example.com", "--password-stdin"]) == 1
    assert "at least 12 characters" in capsys.readouterr().err


def test_cli_main_rejects_mismatched_passwords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    upgrade(url)
    monkeypatch.setenv("FINOPS_DATABASE_URL", url)
    answers = iter([PASSWORD, PASSWORD + "x"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))
    assert users_main(["create", "--email", "e@example.com"]) == 1
    assert "don't match" in capsys.readouterr().err


def test_cli_cannot_demote_the_last_owner(db: Database) -> None:
    create_member(db, "solo@example.com", "default", "owner", PASSWORD)
    with pytest.raises(accounts.AccountError, match="at least one owner"):
        create_member(db, "solo@example.com", "default", "viewer", None)
