"""Budget evaluation engine: compares billing analysis spend and forecast to budget limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from finops_app import repository as repo

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from finops_app.models import Analysis, Budget


@dataclass(frozen=True)
class BudgetStatus:
    """Evaluation of a single budget against an analysis."""

    budget_id: str
    scope_type: str
    scope_value: str | None
    monthly_amount: float
    current_spend: float
    projected_spend: float
    percent_used: float
    is_exceeded: bool


def _service_or_account_spend_from_dataset(
    analysis: Analysis, scope_type: str, target: str
) -> float | None:
    """Read total spend for a service or account directly from raw dataset if accessible."""
    try:
        from flask import current_app

        storage = current_app.extensions.get("finops_storage") if current_app else None
        if not storage or not getattr(analysis, "dataset", None) or not analysis.dataset.storage_key:
            return None
        path = storage.local_path(analysis.dataset.storage_key)
        if not path or not path.exists():
            return None
        import pandas as pd

        if scope_type == "service":
            df = pd.read_csv(
                path, usecols=lambda c: c in ("ServiceName", "EffectiveCost", "BilledCost")
            )
            cost_col = "EffectiveCost" if "EffectiveCost" in df.columns else "BilledCost"
            if "ServiceName" in df.columns and cost_col in df.columns:
                mask = df["ServiceName"].astype(str).str.lower() == target
                return float(df.loc[mask, cost_col].sum())
        elif scope_type == "account":
            df = pd.read_csv(
                path,
                usecols=lambda c: c
                in ("SubAccountId", "BillingAccountId", "EffectiveCost", "BilledCost"),
            )
            cost_col = "EffectiveCost" if "EffectiveCost" in df.columns else "BilledCost"
            acc_col = "SubAccountId" if "SubAccountId" in df.columns else "BillingAccountId"
            if acc_col in df.columns and cost_col in df.columns:
                mask = df[acc_col].astype(str).str.lower() == target
                return float(df.loc[mask, cost_col].sum())
    except Exception:
        pass
    return None


def evaluate_budget(budget: Budget, analysis: Analysis) -> BudgetStatus:
    """Evaluate one budget against an analysis result."""
    total_spend = analysis.total_spend or 0.0
    period_days = max(1, analysis.period_days or 30)

    # Estimate 30-day projected spend
    # If fewer than 30 points (e.g. 7-day model forecast), extrapolate the daily average to 30 days
    forecast_points = analysis.forecast_points
    if forecast_points:
        if len(forecast_points) >= 30:
            projected_spend = sum(p.value for p in forecast_points[:30])
        else:
            projected_spend = (sum(p.value for p in forecast_points) / len(forecast_points)) * 30.0
    else:
        projected_spend = (total_spend / period_days) * 30.0

    if budget.scope_type == "total":
        # Compare monthly spend (normalize 90+ day files to 30-day rate)
        current = (total_spend / period_days) * 30.0 if period_days > 30 else total_spend
        projected = projected_spend
    elif budget.scope_type == "service":
        target = (budget.scope_value or "").lower()
        raw_spend = _service_or_account_spend_from_dataset(analysis, "service", target)
        if raw_spend is not None:
            total_svc_spend = raw_spend
        else:
            matching_findings = [
                f for f in analysis.findings if (f.service or "").lower() == target
            ]
            total_svc_spend = sum(f.total_cost for f in matching_findings)
        current = (
            (total_svc_spend / period_days) * 30.0 if period_days > 30 else total_svc_spend
        )
        projected = (total_svc_spend / period_days) * 30.0
    elif budget.scope_type == "account":
        target = (budget.scope_value or "").lower()
        raw_spend = _service_or_account_spend_from_dataset(analysis, "account", target)
        if raw_spend is not None:
            total_acc_spend = raw_spend
        else:
            matching_findings = [
                f for f in analysis.findings if (f.account or "").lower() == target
            ]
            total_acc_spend = sum(f.total_cost for f in matching_findings)
        current = (
            (total_acc_spend / period_days) * 30.0 if period_days > 30 else total_acc_spend
        )
        projected = (total_acc_spend / period_days) * 30.0
    else:
        current = (total_spend / period_days) * 30.0 if period_days > 30 else total_spend
        projected = projected_spend

    monthly_amount = max(0.01, budget.monthly_amount)
    percent_used = round((current / monthly_amount) * 100.0, 1)
    is_exceeded = (projected > monthly_amount) or (current > monthly_amount)

    return BudgetStatus(
        budget_id=budget.id,
        scope_type=budget.scope_type,
        scope_value=budget.scope_value,
        monthly_amount=budget.monthly_amount,
        current_spend=round(current, 2),
        projected_spend=round(projected, 2),
        percent_used=percent_used,
        is_exceeded=is_exceeded,
    )


def evaluate_budgets(session: Session, org_id: str, analysis: Analysis) -> list[BudgetStatus]:
    """Evaluate all configured budgets for an organisation against an analysis."""
    budgets = repo.list_budgets(session, org_id)
    return [evaluate_budget(b, analysis) for b in budgets]
