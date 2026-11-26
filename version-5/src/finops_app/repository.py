"""Data access. Every query over customer data goes through :func:`scoped`.

``org_id`` always comes from the signed-in user's active membership (see
:mod:`finops_app.auth`), never from the request. Users, organisations and
memberships live in :mod:`finops_app.accounts`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from finops_app.models import (
    Analysis,
    AuditLog,
    Dataset,
    Finding,
    FindingEvent,
    ForecastPoint,
    Membership,
    Organization,
    utcnow,
)
from finops_core.models import AnalysisResult, ForecastResult
from finops_core.models import Finding as ResultFinding

DEFAULT_ORG_SLUG = "default"
DEFAULT_ORG_NAME = "Default organization"
HISTORY_LIMIT = 100

T = TypeVar("T", Dataset, Analysis, Finding, ForecastPoint, AuditLog, Membership, FindingEvent)


def scoped(model: type[T], org_id: str) -> Select[tuple[T]]:
    """``SELECT model WHERE org_id = :org_id``: the only way to start a query."""
    if not org_id:
        raise ValueError("org_id is required for every customer-data query")
    return select(model).where(model.org_id == org_id)


def default_org_id(session: Session) -> str:
    """Id of the "default" organisation, which holds data uploaded before accounts.

    Created if missing. ``finops-users create --org default`` gives someone access.
    """
    org = session.scalars(select(Organization).where(Organization.slug == DEFAULT_ORG_SLUG)).first()
    if org is None:
        org = Organization(slug=DEFAULT_ORG_SLUG, name=DEFAULT_ORG_NAME)
        session.add(org)
        session.flush()
    return org.id


def create_upload(
    session: Session,
    org_id: str,
    *,
    original_filename: str,
    storage_key: str,
    size_bytes: int,
    row_count: int,
    uploaded_by: str | None = None,
) -> Analysis:
    """Record a dataset and a queued analysis of it."""
    dataset = Dataset(
        org_id=org_id,
        uploaded_by=uploaded_by,
        original_filename=original_filename,
        storage_key=storage_key,
        size_bytes=size_bytes,
        row_count=row_count,
    )
    session.add(dataset)
    session.flush()
    analysis = Analysis(org_id=org_id, dataset_id=dataset.id, status="queued")
    session.add(analysis)
    session.flush()
    audit(
        session,
        org_id,
        "analysis.queued",
        "analysis",
        analysis.id,
        {"dataset": dataset.id},
        user_id=uploaded_by,
    )
    return analysis


def get_analysis(session: Session, org_id: str, analysis_id: str) -> Analysis | None:
    return session.scalars(scoped(Analysis, org_id).where(Analysis.id == analysis_id)).first()


def list_analyses(session: Session, org_id: str, limit: int = HISTORY_LIMIT) -> list[Analysis]:
    stmt = scoped(Analysis, org_id).order_by(Analysis.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def mark_running(session: Session, analysis: Analysis) -> None:
    analysis.status = "running"
    analysis.started_at = utcnow()
    analysis.error_message = None


def mark_failed(session: Session, analysis: Analysis, message: str) -> None:
    analysis.status = "failed"
    analysis.finished_at = utcnow()
    analysis.error_message = message
    audit(session, analysis.org_id, "analysis.failed", "analysis", analysis.id)


def save_result(session: Session, analysis: Analysis, result: AnalysisResult) -> None:
    """Store an engine result on ``analysis`` and mark it succeeded."""
    org_id = analysis.org_id
    analysis.analysis_version = result.analysis_version
    analysis.records = result.records
    analysis.resources = result.resources
    analysis.period_start = result.period_start
    analysis.period_end = result.period_end
    analysis.period_days = result.period_days
    analysis.total_spend = result.total_spend
    analysis.total_waste = result.total_waste
    analysis.forecast_method = result.forecast.method
    analysis.forecast_backtest_mae = result.forecast.backtest_mae
    analysis.daily_dates = list(result.daily_dates)
    analysis.daily_costs = list(result.daily_costs)
    analysis.findings = [
        Finding(
            org_id=org_id,
            rank=rank,
            resource_key=f.resource_key,
            resource_id=f.resource_id,
            resource_name=f.resource_name,
            service=f.service,
            region=f.region,
            account=f.account,
            unit=f.unit,
            total_cost=f.total_cost,
            total_usage=f.total_usage,
            days_active=f.days_active,
            est_waste=f.estimated_waste,
            est_monthly_waste=f.estimated_monthly_waste,
            confidence=f.confidence,
            signals=list(f.signals),
            reasons=list(f.reasons),
        )
        for rank, f in enumerate(result.findings)
    ]
    fc = result.forecast
    analysis.forecast_points = [
        ForecastPoint(org_id=org_id, day=day, value=value, lower=lower, upper=upper)
        for day, value, lower, upper in zip(fc.dates, fc.values, fc.lower, fc.upper, strict=True)
    ]
    analysis.status = "succeeded"
    analysis.finished_at = utcnow()
    audit(session, org_id, "analysis.succeeded", "analysis", analysis.id)


def load_result(analysis: Analysis) -> AnalysisResult:
    """Rebuild the engine's result from a stored, succeeded analysis."""
    if analysis.status != "succeeded":
        raise ValueError(f"analysis {analysis.id} has no result (status {analysis.status})")
    points = analysis.forecast_points
    return AnalysisResult(
        analysis_version=analysis.analysis_version or "",
        records=analysis.records or 0,
        resources=analysis.resources or 0,
        period_start=analysis.period_start,
        period_end=analysis.period_end,
        period_days=analysis.period_days or 0,
        total_spend=analysis.total_spend or 0.0,
        daily_dates=tuple(analysis.daily_dates or ()),
        daily_costs=tuple(float(c) for c in analysis.daily_costs or ()),
        findings=tuple(_to_result_finding(f) for f in analysis.findings),
        forecast=ForecastResult(
            method=analysis.forecast_method or "none",
            dates=tuple(p.day for p in points),
            values=tuple(p.value for p in points),
            lower=tuple(p.lower for p in points),
            upper=tuple(p.upper for p in points),
            backtest_mae=analysis.forecast_backtest_mae,
        ),
    )


def _to_result_finding(f: Finding) -> ResultFinding:
    return ResultFinding(
        resource_key=f.resource_key,
        resource_id=f.resource_id,
        resource_name=f.resource_name,
        service=f.service,
        region=f.region,
        account=f.account,
        unit=f.unit,
        total_cost=f.total_cost,
        total_usage=f.total_usage,
        days_active=f.days_active,
        estimated_waste=f.est_waste,
        estimated_monthly_waste=f.est_monthly_waste,
        confidence=f.confidence,
        signals=tuple(f.signals),
        reasons=tuple(f.reasons),
    )


def datasets_with_raw_before(session: Session, cutoff: datetime) -> list[Dataset]:
    """Datasets (all orgs) whose raw file is older than ``cutoff`` and still stored.

    The one deliberate cross-tenant query: retention runs for every org.
    """
    stmt = select(Dataset).where(Dataset.created_at < cutoff, Dataset.raw_deleted_at.is_(None))
    return list(session.scalars(stmt))


def audit(
    session: Session,
    org_id: str | None,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
    *,
    user_id: str | None = None,
) -> None:
    """Append one audit entry; ``org_id`` is None only for account events."""
    session.add(
        AuditLog(
            org_id=org_id,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )
