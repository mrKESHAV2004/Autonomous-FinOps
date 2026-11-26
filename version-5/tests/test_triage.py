"""The finding workflow rules and carry-over between uploads."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from factories import finding, result
from finops_app import repository as repo
from finops_app import triage
from finops_app.db import Database, upgrade
from finops_app.models import Analysis, AuditLog, Finding, FindingEvent


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    url = f"sqlite:///{tmp_path / 'triage.db'}"
    upgrade(url)
    database = Database(url)
    yield database
    database.dispose()


def _analysis(db: Database, keys: tuple[str, ...] = ("i-1", "i-2"), name: str = "a.csv") -> str:
    """A succeeded analysis in the default org with one finding per key."""
    with db.session() as s:
        org = repo.default_org_id(s)
        a = repo.create_upload(
            s, org, original_filename=name, storage_key=f"k-{name}", size_bytes=1, row_count=1
        )
        found = tuple(finding(resource_key=k, resource_id=k) for k in keys)
        repo.save_result(s, a, result(findings=found))
        s.flush()
        triage.carry_over(s, a)
        return a.id


def _get(s, analysis_id: str, key: str) -> Finding:
    return s.scalars(
        select(Finding).where(Finding.analysis_id == analysis_id, Finding.resource_key == key)
    ).one()


def test_set_status_records_history_and_audit(db: Database) -> None:
    aid = _analysis(db)
    with db.session() as s:
        f = _get(s, aid, "i-1")
        triage.set_status(s, f, "false_positive", user_id=None, note="  It's a DR standby  ")
    with db.session() as s:
        f = _get(s, aid, "i-1")
        assert f.status == "false_positive" and f.status_changed_at is not None
        (event,) = f.events
        assert (event.from_status, event.to_status, event.note) == (
            "open",
            "false_positive",
            "It's a DR standby",
        )
        assert s.scalars(select(AuditLog.action)).all()[-1] == "finding.status_changed"


@pytest.mark.parametrize(
    ("status", "until_days", "message"),
    [
        ("deleted", None, "valid status"),
        ("open", None, "already open"),
        ("snoozed", None, "date the snooze ends"),
        ("snoozed", 0, "after today"),
        ("snoozed", 400, "at most 365 days"),
    ],
)
def test_invalid_changes_are_refused(
    db: Database, status: str, until_days: int | None, message: str
) -> None:
    aid = _analysis(db)
    until = None if until_days is None else triage.today() + timedelta(days=until_days)
    with db.session() as s, pytest.raises(triage.TriageError, match=message):
        triage.set_status(s, _get(s, aid, "i-1"), status, user_id=None, snoozed_until=until)


def test_long_notes_are_refused(db: Database) -> None:
    aid = _analysis(db)
    with db.session() as s, pytest.raises(triage.TriageError, match="under 1000"):
        triage.set_status(s, _get(s, aid, "i-1"), "fixed", user_id=None, note="x" * 1001)


def test_snooze_date_is_dropped_for_other_statuses(db: Database) -> None:
    aid = _analysis(db)
    with db.session() as s:
        f = _get(s, aid, "i-1")
        triage.set_status(s, f, "fixed", user_id=None, snoozed_until=triage.today())
        assert f.snoozed_until is None


def test_expired_snoozes_reopen(db: Database) -> None:
    aid = _analysis(db)
    with db.session() as s:
        f = _get(s, aid, "i-1")
        triage.set_status(
            s, f, "snoozed", user_id=None, snoozed_until=triage.today() + timedelta(days=3)
        )
        f.snoozed_until = triage.today()  # time passes
    with db.session() as s:
        org = repo.default_org_id(s)
        assert triage.wake_expired_snoozes(s, org, aid) == 1
        assert triage.wake_expired_snoozes(s, org, aid) == 0
    with db.session() as s:
        f = _get(s, aid, "i-1")
        assert f.status == "open"
        assert f.events[0].note == "Snooze ended."


def test_decisions_carry_over_to_the_next_upload(db: Database) -> None:
    first = _analysis(db, ("fp", "ack", "snz", "fix", "new-open"), "jan.csv")
    with db.session() as s:
        triage.set_status(s, _get(s, first, "fp"), "false_positive", user_id=None)
        triage.set_status(s, _get(s, first, "ack"), "acknowledged", user_id=None)
        triage.set_status(
            s,
            _get(s, first, "snz"),
            "snoozed",
            user_id=None,
            snoozed_until=triage.today() + timedelta(days=10),
        )
        triage.set_status(s, _get(s, first, "fix"), "fixed", user_id=None)

    second = _analysis(db, ("fp", "ack", "snz", "fix", "new-open", "brand-new"), "feb.csv")
    with db.session() as s:
        got = {k: _get(s, second, k) for k in ("fp", "ack", "snz", "fix", "new-open", "brand-new")}
        assert got["fp"].status == "false_positive"
        assert got["ack"].status == "acknowledged"
        assert got["snz"].status == "snoozed"
        assert got["snz"].snoozed_until == triage.today() + timedelta(days=10)
        assert got["fix"].status == "open"
        assert "still appears" in (got["fix"].events[0].note or "")
        assert "jan.csv" in (got["fp"].events[0].note or "")
        assert got["new-open"].status == "open" and not got["new-open"].events
        assert got["brand-new"].status == "open"


def test_carry_over_uses_the_latest_decision(db: Database) -> None:
    first = _analysis(db, ("r",), "one.csv")
    with db.session() as s:
        triage.set_status(s, _get(s, first, "r"), "false_positive", user_id=None)
    second = _analysis(db, ("r",), "two.csv")
    with db.session() as s:
        triage.set_status(s, _get(s, second, "r"), "open", user_id=None, note="Actually real")
    third = _analysis(db, ("r",), "three.csv")
    with db.session() as s:
        assert _get(s, third, "r").status == "open"


def test_expired_snooze_does_not_carry_over(db: Database) -> None:
    first = _analysis(db, ("r",), "one.csv")
    with db.session() as s:
        f = _get(s, first, "r")
        triage.set_status(
            s, f, "snoozed", user_id=None, snoozed_until=triage.today() + timedelta(days=2)
        )
        f.snoozed_until = triage.today() - timedelta(days=1)
    second = _analysis(db, ("r",), "two.csv")
    with db.session() as s:
        assert _get(s, second, "r").status == "open"


def test_carry_over_never_crosses_organisations(db: Database) -> None:
    first = _analysis(db, ("shared-key",), "a.csv")
    with db.session() as s:
        triage.set_status(s, _get(s, first, "shared-key"), "false_positive", user_id=None)
        from finops_app.models import Organization

        other = Organization(slug="other", name="Other")
        s.add(other)
        s.flush()
        a = repo.create_upload(
            s, other.id, original_filename="b.csv", storage_key="k-b", size_bytes=1, row_count=1
        )
        repo.save_result(s, a, result(findings=(finding(resource_key="shared-key"),)))
        s.flush()
        assert triage.carry_over(s, a) == 0
        assert a.findings[0].status == "open"


def test_events_for_is_newest_first(db: Database) -> None:
    aid = _analysis(db)
    with db.session() as s:
        f = _get(s, aid, "i-1")
        triage.set_status(s, f, "acknowledged", user_id=None)
        triage.set_status(s, f, "fixed", user_id=None)
    with db.session() as s:
        org = repo.default_org_id(s)
        f = _get(s, aid, "i-1")
        events = triage.events_for(s, org, f.id)
        assert [e.to_status for e in events] == ["fixed", "acknowledged"]
        assert s.scalars(select(FindingEvent)).all()
        assert s.get(Analysis, aid) is not None
