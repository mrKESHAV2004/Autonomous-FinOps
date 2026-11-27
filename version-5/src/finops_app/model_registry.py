"""Model Registry service and CLI.

Tracks detector and forecaster versions, algorithms, training windows, and
evaluation metrics, with one-command promotion and rollback capabilities.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from finops_app.config import Config
from finops_app.db import Database
from finops_app.models import ModelVersion, utcnow


class RegistryError(ValueError):
    """Raised when a model version operation cannot be completed."""


def register_version(
    session: Session,
    model_name: str,
    version: str,
    algorithm: str,
    *,
    metrics: dict[str, Any] | None = None,
    description: str | None = None,
    training_window_start: str | None = None,
    training_window_end: str | None = None,
    deploy_now: bool = False,
) -> ModelVersion:
    """Register a new model version in the registry."""
    existing = session.scalars(
        select(ModelVersion).where(
            ModelVersion.model_name == model_name,
            ModelVersion.version == version,
        )
    ).first()
    if existing is not None:
        raise RegistryError(f"Model {model_name} version {version} already exists")

    model_ver = ModelVersion(
        model_name=model_name,
        version=version,
        algorithm=algorithm,
        description=description,
        training_window_start=training_window_start,
        training_window_end=training_window_end,
        metrics=metrics or {},
        is_active=False,
    )
    session.add(model_ver)
    session.flush()

    if deploy_now:
        promote_version(session, model_name, version)

    return model_ver


def get_active_version(session: Session, model_name: str) -> ModelVersion | None:
    """Get the currently deployed active version of a model."""
    return session.scalars(
        select(ModelVersion).where(
            ModelVersion.model_name == model_name,
            ModelVersion.is_active.is_(True),
        )
    ).first()


def promote_version(session: Session, model_name: str, version: str) -> ModelVersion:
    """Promote a specific model version to be the active production model."""
    target = session.scalars(
        select(ModelVersion).where(
            ModelVersion.model_name == model_name,
            ModelVersion.version == version,
        )
    ).first()
    if target is None:
        raise RegistryError(f"Model {model_name} version {version} not found in registry")

    # Deactivate currently active version(s)
    actives = session.scalars(
        select(ModelVersion).where(
            ModelVersion.model_name == model_name,
            ModelVersion.is_active.is_(True),
        )
    ).all()
    for cur in actives:
        cur.is_active = False

    target.is_active = True
    target.deployed_at = utcnow()
    return target


def rollback_version(session: Session, model_name: str) -> ModelVersion:
    """Roll back to the previous version when regression or performance drop is detected."""
    active = get_active_version(session, model_name)
    if active is None:
        raise RegistryError(f"No active version found for model {model_name} to roll back from")

    # Find the candidate previous version (ordered by created_at desc, created before active version)
    previous = session.scalars(
        select(ModelVersion)
        .where(
            ModelVersion.model_name == model_name,
            ModelVersion.id != active.id,
            ModelVersion.created_at < active.created_at,
        )
        .order_by(ModelVersion.created_at.desc())
    ).first()

    if previous is None:
        raise RegistryError(f"No previous version available for model {model_name} to roll back to")

    active.is_active = False
    previous.is_active = True
    previous.deployed_at = utcnow()
    return previous


def list_versions(session: Session, model_name: str | None = None) -> list[ModelVersion]:
    """List all registered models and versions."""
    query = select(ModelVersion).order_by(ModelVersion.created_at.desc())
    if model_name:
        query = query.where(ModelVersion.model_name == model_name)
    return list(session.scalars(query).all())


def models_cli_main(argv: Sequence[str] | None = None) -> int:
    """CLI for managing model versions, promotions, and rollbacks."""
    parser = argparse.ArgumentParser(
        prog="finops-models",
        description="Manage FinOps ML and Rule models in the Model Registry.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    list_p = sub.add_parser("list", help="list registered model versions")
    list_p.add_argument("--name", help="filter by model name (detector or forecaster)")
    list_p.add_argument("--json", action="store_true", help="output JSON")

    # register
    reg_p = sub.add_parser("register", help="register a new model version")
    reg_p.add_argument("--name", required=True, help="model name (e.g. detector, forecaster)")
    reg_p.add_argument("--version", required=True, help="version identifier (e.g. v1.1.0)")
    reg_p.add_argument("--algorithm", required=True, help="algorithm or architecture name")
    reg_p.add_argument("--description", help="model description and change rationale")
    reg_p.add_argument("--metrics", help="JSON string with evaluation metrics")
    reg_p.add_argument(
        "--promote", action="store_true", help="promote immediately after registration"
    )

    # promote
    prom_p = sub.add_parser("promote", help="promote a version to active production")
    prom_p.add_argument("--name", required=True)
    prom_p.add_argument("--version", required=True)

    # rollback
    roll_p = sub.add_parser("rollback", help="roll back to previous stable model version")
    roll_p.add_argument("--name", required=True)

    args = parser.parse_args(argv)
    cfg = Config.from_env()
    db = Database(cfg.database_url)

    try:
        with db.session() as session:
            if args.command == "list":
                models = list_versions(session, args.name)
                if args.json:
                    payload = [
                        {
                            "id": m.id,
                            "model_name": m.model_name,
                            "version": m.version,
                            "algorithm": m.algorithm,
                            "is_active": m.is_active,
                            "metrics": m.metrics,
                            "created_at": m.created_at.isoformat(),
                            "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
                        }
                        for m in models
                    ]
                    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
                else:
                    sys.stdout.write(
                        f"{'NAME':<15} {'VERSION':<10} {'ACTIVE':<8} {'ALGORITHM':<30}\n"
                    )
                    sys.stdout.write("-" * 65 + "\n")
                    for m in models:
                        active_mark = "YES" if m.is_active else "no"
                        sys.stdout.write(
                            f"{m.model_name:<15} {m.version:<10} {active_mark:<8} {m.algorithm:<30}\n"
                        )

            elif args.command == "register":
                metrics_dict = json.loads(args.metrics) if args.metrics else {}
                m = register_version(
                    session,
                    args.name,
                    args.version,
                    args.algorithm,
                    metrics=metrics_dict,
                    description=args.description,
                    deploy_now=args.promote,
                )
                session.commit()
                sys.stdout.write(
                    f"Registered model {m.model_name} version {m.version} (active: {m.is_active})\n"
                )

            elif args.command == "promote":
                m = promote_version(session, args.name, args.version)
                session.commit()
                sys.stdout.write(f"Promoted model {m.model_name} version {m.version} to ACTIVE\n")

            elif args.command == "rollback":
                m = rollback_version(session, args.name)
                session.commit()
                sys.stdout.write(
                    f"Rolled back model {m.model_name} to version {m.version} (now ACTIVE)\n"
                )

    finally:
        db.dispose()

    return 0
