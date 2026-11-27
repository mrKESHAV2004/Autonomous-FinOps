"""Model quality evaluation: Precision@k, confusion matrix, and waste realization.

Collects user triage decisions (fixed/acknowledged vs false_positive) to compute
Precision@k, False Positive Rates, and confirmed savings realization.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from finops_app.config import Config
from finops_app.db import Database
from finops_app.models import Finding as DbFinding
from finops_app.repository import scoped
from finops_core.evaluation import (
    LabelledFinding,
    confusion_metrics,
    evaluate_ranking,
    waste_realization,
)
from finops_core.models import Finding as CoreFinding


def extract_evaluation_set(session: Session, org_id: str) -> list[LabelledFinding]:
    """Extract labelled findings from historical triage decisions for one organization."""
    query = (
        scoped(DbFinding, org_id)
        .where(DbFinding.status.in_(["fixed", "acknowledged", "false_positive"]))
        .order_by(DbFinding.status_changed_at.desc().nullslast(), DbFinding.id.desc())
    )
    rows = session.scalars(query).all()

    seen_keys: set[str] = set()
    items: list[LabelledFinding] = []
    for r in rows:
        if r.resource_key in seen_keys:
            continue
        seen_keys.add(r.resource_key)
        core = CoreFinding(
            resource_key=r.resource_key,
            resource_id=r.resource_id,
            resource_name=r.resource_name,
            service=r.service,
            region=r.region,
            account=r.account,
            unit=r.unit,
            total_cost=r.total_cost,
            total_usage=r.total_usage,
            days_active=r.days_active,
            estimated_waste=r.est_waste,
            estimated_monthly_waste=r.est_monthly_waste,
            confidence=r.confidence,
            signals=tuple(r.signals or []),
            reasons=tuple(r.reasons or []),
        )
        label = 1 if r.status in ("fixed", "acknowledged") else 0
        items.append(LabelledFinding(finding=core, label=label))
    return items


def compute_quality_scorecard(session: Session, org_id: str) -> dict[str, Any]:
    """Compute Precision@k, confusion matrix, and waste realization for an org."""
    items = extract_evaluation_set(session, org_id)
    ranking = evaluate_ranking(items)
    confusion = confusion_metrics(items)
    realization = waste_realization(items)

    return {
        "org_id": org_id,
        "ranking_precision": ranking,
        "confusion": confusion,
        "financial_impact": realization,
    }


def eval_main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for finops-eval."""
    parser = argparse.ArgumentParser(
        prog="finops-eval",
        description="Evaluate detector model quality and Precision@k from user feedback.",
    )
    parser.add_argument("--org-id", required=True, help="Organization ID to evaluate")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    db = Database(cfg.database_url)
    try:
        with db.session() as session:
            scorecard = compute_quality_scorecard(session, args.org_id)
    finally:
        db.dispose()

    if args.json:
        sys.stdout.write(json.dumps(scorecard, indent=2) + "\n")
    else:
        conf = scorecard["confusion"]
        rank = scorecard["ranking_precision"]
        fin = scorecard["financial_impact"]
        sys.stdout.write(f"Model Quality Evaluation for Org: {args.org_id}\n")
        sys.stdout.write(f"Total Labelled Decisions: {conf['total_evaluated']}\n")
        sys.stdout.write(f"Precision: {conf['precision'] * 100:.1f}%\n")
        sys.stdout.write(f"False Positive Rate: {conf['false_positive_rate'] * 100:.1f}%\n")
        sys.stdout.write("Precision@k:\n")
        for k, v in rank.items():
            sys.stdout.write(f"  {k}: {v * 100:.1f}%\n")
        sys.stdout.write(f"Waste Realization Rate: {fin['waste_realization_rate_pct']}%\n")
        sys.stdout.write(f"Confirmed Savings: ${fin['confirmed_real_waste']:,.2f}\n")
    return 0
