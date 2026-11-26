"""Base interface and data transfer objects for cloud billing connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ConnectorVerificationResult:
    """Outcome of attempting to connect to a cloud provider."""

    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveredExport:
    """A billing export file located in cloud storage."""

    key: str
    last_modified: datetime
    size_bytes: int
    etag: str | None = None


class BaseConnector(ABC):
    """Abstract interface for cloud billing export connectors."""

    @abstractmethod
    def verify(self) -> ConnectorVerificationResult:
        """Verify IAM/API access to the cloud provider and billing exports."""
        ...

    @abstractmethod
    def list_exports(self) -> list[DiscoveredExport]:
        """List available billing export files ordered newest to oldest."""
        ...

    @abstractmethod
    def download_export(self, key: str) -> bytes:
        """Download a specific export object as raw bytes."""
        ...
