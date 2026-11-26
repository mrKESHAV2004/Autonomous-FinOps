"""SQLAlchemy models: tenants, uploads, analyses and their results.

Every table that holds customer data carries ``org_id``; queries go through
:mod:`finops_app.repository`, which always filters by it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ID_LENGTH = 32


def new_id() -> str:
    """Random, unguessable primary key (hex UUID4)."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255))  # argon2; None = no password
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # owner | admin | analyst | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship()
    user: Mapped[User] = relationship()


class CloudConnection(Base):
    """External cloud billing connector (AWS CUR 2.0 / FOCUS, Azure, GCP)."""

    __tablename__ = "cloud_connections"
    __table_args__ = (
        Index("ix_cloud_connections_org", "org_id"),
        UniqueConstraint("org_id", "name", name="uq_cloud_connection_org_name"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))  # "aws" | "azure" | "gcp"
    name: Mapped[str] = mapped_column(String(128))
    role_arn: Mapped[str | None] = mapped_column(String(255))
    external_id: Mapped[str] = mapped_column(String(64), default=new_id)
    s3_bucket: Mapped[str | None] = mapped_column(String(255))
    s3_prefix: Mapped[str | None] = mapped_column(String(512))
    region: Mapped[str | None] = mapped_column(String(64))  # e.g. "us-east-1"
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | active | error
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship()
    datasets: Mapped[list[Dataset]] = relationship(back_populates="connection")


class Dataset(Base):
    """One uploaded billing file. The raw bytes live in object storage."""

    __tablename__ = "datasets"
    __table_args__ = (Index("ix_datasets_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_connections.id", ondelete="SET NULL")
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connection: Mapped[CloudConnection | None] = relationship(back_populates="datasets")
    analyses: Mapped[list[Analysis]] = relationship(back_populates="dataset")


class Analysis(Base):
    """One run of the engine over a dataset, and its headline results."""

    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    analysis_version: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    records: Mapped[int | None] = mapped_column(Integer)
    resources: Mapped[int | None] = mapped_column(Integer)
    period_start: Mapped[str | None] = mapped_column(String(10))
    period_end: Mapped[str | None] = mapped_column(String(10))
    period_days: Mapped[int | None] = mapped_column(Integer)
    total_spend: Mapped[float | None] = mapped_column(Float)
    total_waste: Mapped[float | None] = mapped_column(Float)
    forecast_method: Mapped[str | None] = mapped_column(String(32))
    forecast_backtest_mae: Mapped[float | None] = mapped_column(Float)
    daily_dates: Mapped[list[Any] | None] = mapped_column(JSON)
    daily_costs: Mapped[list[Any] | None] = mapped_column(JSON)

    dataset: Mapped[Dataset] = relationship(back_populates="analyses")
    findings: Mapped[list[Finding]] = relationship(
        back_populates="analysis", order_by="Finding.rank", cascade="all, delete-orphan"
    )
    forecast_points: Mapped[list[ForecastPoint]] = relationship(
        order_by="ForecastPoint.day", cascade="all, delete-orphan"
    )


class Finding(Base):
    """One wasteful resource found by an analysis."""

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_org_analysis", "org_id", "analysis_id"),
        Index("ix_findings_org_resource", "org_id", "resource_key"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(Integer)
    resource_key: Mapped[str] = mapped_column(String(512))
    resource_id: Mapped[str | None] = mapped_column(String(512))
    resource_name: Mapped[str | None] = mapped_column(String(512))
    service: Mapped[str] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(100))
    account: Mapped[str | None] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(100))
    total_cost: Mapped[float] = mapped_column(Float)
    total_usage: Mapped[float] = mapped_column(Float)
    days_active: Mapped[int] = mapped_column(Integer)
    est_waste: Mapped[float] = mapped_column(Float)
    est_monthly_waste: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(16))
    signals: Mapped[list[Any]] = mapped_column(JSON)
    reasons: Mapped[list[Any]] = mapped_column(JSON)
    # open | acknowledged | fixed | snoozed | false_positive (see finops_app.triage)
    status: Mapped[str] = mapped_column(String(16), default="open")
    snoozed_until: Mapped[date | None] = mapped_column(Date)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    analysis: Mapped[Analysis] = relationship(back_populates="findings")
    events: Mapped[list[FindingEvent]] = relationship(
        back_populates="finding",
        order_by="FindingEvent.created_at.desc()",
        cascade="all, delete-orphan",
    )


class FindingEvent(Base):
    """One status change on a finding: who, when, from what to what, and why."""

    __tablename__ = "finding_events"
    __table_args__ = (Index("ix_finding_events_org_finding", "org_id", "finding_id"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    from_status: Mapped[str] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    snoozed_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    finding: Mapped[Finding] = relationship(back_populates="events")
    user: Mapped[User | None] = relationship()


class ForecastPoint(Base):
    __tablename__ = "forecast_points"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[str] = mapped_column(String(10))
    value: Mapped[float] = mapped_column(Float)
    lower: Mapped[float] = mapped_column(Float)
    upper: Mapped[float] = mapped_column(Float)


class AuditLog(Base):
    """Who did what. ``org_id`` is empty only for account events (a failed login)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShareLink(Base):
    """A read-only link to one analysis. Only a hash of the token is stored."""

    __tablename__ = "share_links"
    __table_args__ = (Index("ix_share_links_org_analysis", "org_id", "analysis_id"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    analysis: Mapped[Analysis] = relationship()


class Budget(Base):
    """Monthly budget target per scope (total spend, account, service, or tag)."""

    __tablename__ = "budgets"
    __table_args__ = (
        Index("ix_budgets_org", "org_id"),
        UniqueConstraint("org_id", "scope_type", "scope_value", name="uq_budget_org_scope"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    scope_type: Mapped[str] = mapped_column(String(32))  # total | account | service | tag
    scope_value: Mapped[str | None] = mapped_column(String(255))  # None for "total"
    monthly_amount: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship()


class AlertConfig(Base):
    """Notification channel configuration (Slack webhook or Email) and trigger preferences."""

    __tablename__ = "alert_configs"
    __table_args__ = (Index("ix_alert_configs_org", "org_id"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    channel_type: Mapped[str] = mapped_column(String(32))  # slack | email
    destination: Mapped[str] = mapped_column(String(512))  # Webhook URL or email address
    notify_high_confidence: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_budget_exceeded: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_spend_spikes: Mapped[bool] = mapped_column(Boolean, default=True)
    spike_threshold_percent: Mapped[float] = mapped_column(Float, default=20.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship()


class AlertHistory(Base):
    """Log of dispatched alert notifications."""

    __tablename__ = "alert_history"
    __table_args__ = (Index("ix_alert_history_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    analysis_id: Mapped[str | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"))
    channel_type: Mapped[str] = mapped_column(String(32))  # slack | email
    event_type: Mapped[str] = mapped_column(
        String(64)
    )  # high_confidence | budget_exceeded | spend_spike
    summary: Mapped[str] = mapped_column(String(512))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))  # sent | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelVersion(Base):
    """Model Registry record tracking versions, training windows, and quality metrics."""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uq_model_versions_name_ver"),
        Index("ix_model_versions_name_active", "model_name", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=new_id)
    model_name: Mapped[str] = mapped_column(String(64))  # detector | forecaster
    version: Mapped[str] = mapped_column(String(32))  # e.g. v1.0.0
    algorithm: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(512))
    training_window_start: Mapped[str | None] = mapped_column(String(10))
    training_window_end: Mapped[str | None] = mapped_column(String(10))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
