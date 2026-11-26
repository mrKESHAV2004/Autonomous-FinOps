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


def evaluate_budget(budget: Budget, analysis: Analysis) -> BudgetStatus:
    """Evaluate one budget against an analysis result."""
    total_spend = analysis.total_spend or 0.0
    period_days = max(1, analysis.period_days or 30)

    # Estimate 30-day projected spend
    # If forecast points exist, sum the next 30 days of forecasts, otherwise extrapolate
    forecast_points = analysis.forecast_points
    if forecast_points:
        projected_spend = sum(p.value for p in forecast_points[:30])
    else:
        projected_spend = (total_spend / period_days) * 30.0

    if budget.scope_type == "total":
        current = total_spend
        projected = projected_spend
    elif budget.scope_type == "service":
        target = (budget.scope_value or "").lower()
        # Filter findings and cost for service
        matching_findings = [f for f in analysis.findings if f.service.lower() == target]
        current = sum(f.total_cost for f in matching_findings)
        projected = (current / period_days) * 30.0
    elif budget.scope_type == "account":
        target = (budget.scope_value or "").lower()
        matching_findings = [f for f in analysis.findings if (f.account or "").lower() == target]
        current = sum(f.total_cost for f in matching_findings)
        projected = (current / period_days) * 30.0
    else:
        current = total_spend
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
