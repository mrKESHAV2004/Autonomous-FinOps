"""Filtering, sorting and paging an analysis's findings.

Used by the findings page, the JSON API and the CSV export, so all three
agree on what a filter means. Every query starts from ``scoped()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from finops_app.models import Finding
from finops_app.repository import scoped
from finops_app.triage import ACTIVE_STATUSES, STATUSES

PER_PAGE_CHOICES = (25, 50, 100)
DEFAULT_PER_PAGE = 25
FILTER_FIELDS = ("service", "region", "account", "confidence", "status")
SEARCH_MAX = 200
SORTS: dict[str, tuple[Any, ...]] = {
    "waste": (Finding.est_waste.desc(), Finding.rank),
    "monthly": (Finding.est_monthly_waste.desc(), Finding.rank),
    "cost": (Finding.total_cost.desc(), Finding.rank),
    "name": (func.coalesce(Finding.resource_name, Finding.resource_id, Finding.resource_key),),
}
DEFAULT_SORT = "waste"


@dataclass(frozen=True)
class FindingQuery:
    service: str | None = None
    region: str | None = None
    account: str | None = None
    confidence: str | None = None
    status: str | None = None
    q: str | None = None
    sort: str = DEFAULT_SORT
    page: int = 1
    per_page: int = DEFAULT_PER_PAGE

    @classmethod
    def from_args(cls, args: Mapping[str, str]) -> FindingQuery:
        """Parse query-string arguments; anything invalid falls back to the default."""
        values = {f: (args.get(f) or "").strip()[:SEARCH_MAX] or None for f in FILTER_FIELDS}
        if values["status"] not in (*STATUSES, "active", None):
            values["status"] = None
        sort = args.get("sort", DEFAULT_SORT)
        return cls(
            **values,
            q=(args.get("q") or "").strip()[:SEARCH_MAX] or None,
            sort=sort if sort in SORTS else DEFAULT_SORT,
            page=_int(args.get("page"), 1, minimum=1),
            per_page=_per_page(args.get("per_page")),
        )

    def args(self, **changes: Any) -> dict[str, Any]:
        """Non-default values as query-string arguments (for links)."""
        query = replace(self, **changes)
        out = {f: getattr(query, f) for f in (*FILTER_FIELDS, "q") if getattr(query, f)}
        if query.sort != DEFAULT_SORT:
            out["sort"] = query.sort
        if query.page != 1:
            out["page"] = query.page
        if query.per_page != DEFAULT_PER_PAGE:
            out["per_page"] = query.per_page
        return out

    @property
    def is_filtered(self) -> bool:
        return any(getattr(self, f) for f in (*FILTER_FIELDS, "q"))


@dataclass(frozen=True)
class Page:
    items: list[Finding]
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per_page))


def _int(raw: str | None, default: int, *, minimum: int) -> int:
    try:
        value = int(raw or "")
    except ValueError:
        return default
    return max(value, minimum)


def _per_page(raw: str | None) -> int:
    value = _int(raw, DEFAULT_PER_PAGE, minimum=1)
    return value if value in PER_PAGE_CHOICES else DEFAULT_PER_PAGE


def filtered(org_id: str, analysis_id: str, query: FindingQuery) -> Select[tuple[Finding]]:
    stmt = scoped(Finding, org_id).where(Finding.analysis_id == analysis_id)
    for field in ("service", "region", "account", "confidence"):
        value = getattr(query, field)
        if value:
            stmt = stmt.where(getattr(Finding, field) == value)
    if query.status == "active":
        stmt = stmt.where(Finding.status.in_(ACTIVE_STATUSES))
    elif query.status:
        stmt = stmt.where(Finding.status == query.status)
    if query.q:
        pattern = "%" + _escape_like(query.q.lower()) + "%"
        stmt = stmt.where(
            or_(
                *(
                    func.lower(col).like(pattern, escape="\\")
                    for col in (Finding.resource_name, Finding.resource_id, Finding.resource_key)
                )
            )
        )
    return stmt


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_page(session: Session, org_id: str, analysis_id: str, query: FindingQuery) -> Page:
    base = filtered(org_id, analysis_id, query)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    last_page = max(1, -(-total // query.per_page))
    page = min(query.page, last_page)
    items = list(
        session.scalars(
            base.order_by(*SORTS[query.sort])
            .offset((page - 1) * query.per_page)
            .limit(query.per_page)
        )
    )
    return Page(items=items, total=total, page=page, per_page=query.per_page)


def all_matching(
    session: Session, org_id: str, analysis_id: str, query: FindingQuery
) -> list[Finding]:
    """Every finding matching the filters (no paging), for export."""
    return list(session.scalars(filtered(org_id, analysis_id, query).order_by(*SORTS[query.sort])))


def facets(session: Session, org_id: str, analysis_id: str) -> dict[str, list[str]]:
    """Distinct values for each filter, for the filter menus."""
    out: dict[str, list[str]] = {}
    for field in ("service", "region", "account", "confidence"):
        col = getattr(Finding, field)
        stmt = (
            select(col)
            .where(Finding.org_id == org_id, Finding.analysis_id == analysis_id, col.is_not(None))
            .distinct()
            .order_by(col)
        )
        out[field] = [v for v in session.scalars(stmt) if v]
    return out


def status_summary(session: Session, org_id: str, analysis_id: str) -> dict[str, dict[str, float]]:
    """Count and estimated waste per status, every status present (zeros included)."""
    stmt = (
        select(Finding.status, func.count(), func.coalesce(func.sum(Finding.est_waste), 0.0))
        .where(Finding.org_id == org_id, Finding.analysis_id == analysis_id)
        .group_by(Finding.status)
    )
    summary = {s: {"count": 0, "waste": 0.0} for s in STATUSES}
    for status, count, waste in session.execute(stmt):
        summary[status] = {"count": int(count), "waste": float(waste)}
    return summary
