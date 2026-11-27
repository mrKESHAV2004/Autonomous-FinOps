"""Google Cloud BigQuery billing export connector stub."""

from __future__ import annotations

from typing import Any

from finops_app.connectors.base import (
    BaseConnector,
    ConnectorVerificationResult,
    DiscoveredExport,
)


class GcpConnector(BaseConnector):
    """Google Cloud billing export connector."""

    def __init__(
        self,
        *,
        project_id: str,
        dataset_id: str,
        table_name: str,
        service_account_email: str,
    ) -> None:
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_name = table_name
        self.service_account_email = service_account_email

    def verify(self) -> ConnectorVerificationResult:
        return ConnectorVerificationResult(
            success=False,
            message="Google Cloud BigQuery billing export connector is in preview. Please use manual FOCUS CSV upload or AWS connector.",
            details={"provider": "gcp", "project_id": self.project_id},
        )

    def list_exports(self) -> list[DiscoveredExport]:
        return []

    def download_export(self, key: str, dest: Any = None) -> bytes | int:
        raise NotImplementedError("GCP download not yet implemented")
