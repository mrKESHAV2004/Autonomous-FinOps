"""The finding workflow: statuses, changes with history, and carry-over.

A finding is Open until someone acts on it. Analysts and above can move it to
Acknowledged, Fixed, Snoozed (until a date) or False positive, with a note.
Every change is a :class:`~finops_app.models.FindingEvent`.

Each upload creates new finding rows, so :func:`carry_over` copies decisions
forward by ``resource_key``: false positives, acknowledgements and live
snoozes stay; a resource marked fixed that shows up again is reopened.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from sqlalchemy.orm import Session, selectinload

from finops_app.models import Analysis, Finding, FindingEvent, utcnow
from finops_app.repository import audit, scoped

STATUSES = ("open", "acknowledged", "fixed", "snoozed", "false_positive")
STATUS_LABELS = {
    "open": "Open",
    "acknowledged": "Acknowledged",
    "fixed": "Fixed",
    "snoozed": "Snoozed",
    "false_positive": "False positive",
}
# Statuses that still count as money being wasted.
ACTIVE_STATUSES = ("open", "acknowledged")
NOTE_MAX = 1000
MAX_SNOOZE_DAYS = 365
_LOOKUP_CHUNK = 500


class TriageError(ValueError):
    """The change is not allowed; the message is safe to show the user."""


def today() -> date:
    return utcnow().date()


def set_status(
    session: Session,
    finding: Finding,
    status: str,
    *,
    user_id: str | None,
    note: str | None = None,
    snoozed_until: date | None = None,
) -> FindingEvent:
    """Change ``finding``'s status and record why."""
    note = (note or "").strip() or None
    _check_change(finding, status, note, snoozed_until)
    event = _apply(
        session,
        finding,
        status,
        user_id=user_id,
        note=note,
        snoozed_until=snoozed_until if status == "snoozed" else None,
    )
    audit(
        session,
        finding.org_id,
        "finding.status_changed",
        "finding",
        finding.id,
        {"from": event.from_status, "to": status},
        user_id=user_id,
    )
    return event


def _check_change(finding: Finding, status: str, note: str | None, until: date | None) -> None:
    if status not in STATUSES:
        raise TriageError("Choose a valid status.")
    if note is not None and len(note) > NOTE_MAX:
        raise TriageError(f"Keep the note under {NOTE_MAX} characters.")
    if status == "snoozed":
        if until is None:
            raise TriageError("Choose the date the snooze ends.")
        if until <= today():
            raise TriageError("The snooze must end after today.")
        if until > today() + timedelta(days=MAX_SNOOZE_DAYS):
            raise TriageError(f"Snooze for at most {MAX_SNOOZE_DAYS} days.")
    elif status == finding.status:
        raise TriageError(f"This finding is already {STATUS_LABELS[status].lower()}.")


def _apply(
    session: Session,
    finding: Finding,
    status: str,
    *,
    user_id: str | None,
    note: str | None,
    snoozed_until: date | None,
) -> FindingEvent:
    event = FindingEvent(
        org_id=finding.org_id,
        finding_id=finding.id,
        user_id=user_id,
        from_status=finding.status,
        to_status=status,
        note=note,
        snoozed_until=snoozed_until,
        created_at=utcnow(),
    )
    finding.status = status
    finding.snoozed_until = snoozed_until
    finding.status_changed_at = event.created_at
    session.add(event)
    return event


def wake_expired_snoozes(session: Session, org_id: str, analysis_id: str) -> int:
    """Reopen this analysis's findings whose snooze has ended; returns how many."""
    due = list(
        session.scalars(
            scoped(Finding, org_id).where(
                Finding.analysis_id == analysis_id,
                Finding.status == "snoozed",
                Finding.snoozed_until <= today(),
            )
        )
    )
    for finding in due:
        _apply(session, finding, "open", user_id=None, note="Snooze ended.", snoozed_until=None)
    return len(due)


def carry_over(session: Session, analysis: Analysis) -> int:
    """Copy earlier decisions onto ``analysis``'s new findings; returns how many changed."""
    by_key = {f.resource_key: f for f in analysis.findings}
    changed = 0
    for key, previous in _latest_earlier_findings(session, analysis, list(by_key)).items():
        carried = _carried_status(previous)
        if carried is None:
            continue
        status, until, note = carried
        _apply(session, by_key[key], status, user_id=None, note=note, snoozed_until=until)
        changed += 1
    return changed


def _carried_status(previous: Finding) -> tuple[str, date | None, str] | None:
    when = previous.analysis.created_at.strftime("%Y-%m-%d")
    source = f"{previous.analysis.dataset.original_filename} ({when})"
    if previous.status in ("false_positive", "acknowledged"):
        label = STATUS_LABELS[previous.status].lower()
        return previous.status, None, f"Marked {label} in {source}."
    if previous.status == "snoozed" and previous.snoozed_until and previous.snoozed_until > today():
        return "snoozed", previous.snoozed_until, f"Snoozed in {source}."
    if previous.status == "fixed":
        return "open", None, f"Marked fixed in {source}, but it still appears in this upload."
    return None


def _latest_earlier_findings(
    session: Session, analysis: Analysis, keys: list[str]
) -> dict[str, Finding]:
    """For each key, the finding from the most recent earlier analysis, if it was triaged."""
    latest: dict[str, Finding] = {}
    for chunk in _chunks(keys, _LOOKUP_CHUNK):
        stmt = (
            scoped(Finding, analysis.org_id)
            .join(Finding.analysis)
            .options(selectinload(Finding.analysis).selectinload(Analysis.dataset))
            .where(
                Finding.resource_key.in_(chunk),
                Finding.analysis_id != analysis.id,
                Analysis.status == "succeeded",
                Analysis.created_at <= analysis.created_at,
            )
            .order_by(Analysis.created_at.desc())
        )
        for finding in session.scalars(stmt):
            latest.setdefault(finding.resource_key, finding)
    return {k: f for k, f in latest.items() if f.status != "open"}


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def events_for(session: Session, org_id: str, finding_id: str) -> list[FindingEvent]:
    """A finding's history, newest first."""
    stmt = (
        scoped(FindingEvent, org_id)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.created_at.desc())
    )
    return list(session.scalars(stmt))
