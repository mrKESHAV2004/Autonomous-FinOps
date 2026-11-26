"""Savings tracker: did resources marked Fixed stop being flagged?

shortcut: a fixed resource counts as saved when the org's latest upload no
longer flags it; we don't store per-resource spend for unflagged resources,
so this can't measure the actual drop. Upgrade when the engine keeps spend for
every resource (then compare cost before and after).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finops_app.models import Analysis, Finding
from finops_app.repository import scoped

CONFIRMED, STILL_FLAGGED, WAITING = "confirmed", "still_flagged", "waiting"


@dataclass(frozen=True)
class SavingsRow:
    finding: Finding
    verdict: str


@dataclass(frozen=True)
class Savings:
    rows: list[SavingsRow]
    latest: Analysis | None

    def monthly(self, verdict: str | None = None) -> float:
        return sum(r.finding.est_monthly_waste for r in self.rows if verdict in (None, r.verdict))

    def count(self, verdict: str) -> int:
        return sum(1 for r in self.rows if r.verdict == verdict)


def savings(session: Session, org_id: str) -> Savings:
    latest = session.scalars(
        scoped(Analysis, org_id)
        .where(Analysis.status == "succeeded")
        .order_by(Analysis.created_at.desc())
    ).first()
    fixed = session.scalars(
        scoped(Finding, org_id)
        .join(Finding.analysis)
        .where(Finding.status == "fixed")
        .order_by(Analysis.created_at.desc())
    )
    newest_per_key: dict[str, Finding] = {}
    for f in fixed:
        newest_per_key.setdefault(f.resource_key, f)
    flagged_now: set[str] = set()
    if latest is not None:
        flagged_now = set(
            session.scalars(
                select(Finding.resource_key).where(
                    Finding.org_id == org_id, Finding.analysis_id == latest.id
                )
            )
        )
    rows = [
        SavingsRow(f, _verdict(f, latest, flagged_now))
        for f in sorted(newest_per_key.values(), key=lambda f: -f.est_monthly_waste)
    ]
    return Savings(rows=rows, latest=latest)


def _verdict(f: Finding, latest: Analysis | None, flagged_now: set[str]) -> str:
    if latest is None or f.analysis_id == latest.id:
        return WAITING
    return STILL_FLAGGED if f.resource_key in flagged_now else CONFIRMED
