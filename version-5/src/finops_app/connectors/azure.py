"""Azure Cost Management connector stub (FOCUS exports to Azure Blob Storage)."""

from __future__ import annotations

from typing import Any

from finops_app.connectors.base import (
    BaseConnector,
    ConnectorVerificationResult,
    DiscoveredExport,
)


class AzureConnector(BaseConnector):
    """Azure Cost Management FOCUS export connector."""

    def __init__(
        self,
        *,
        storage_account: str,
        container: str,
        client_id: str,
        tenant_id: str,
        prefix: str = "",
    ) -> None:
        self.storage_account = storage_account
        self.container = container
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.prefix = prefix

    def verify(self) -> ConnectorVerificationResult:
        return ConnectorVerificationResult(
            success=False,
            message="Azure Cost Management connector is in preview. Please use manual FOCUS CSV upload or AWS connector.",
            details={"provider": "azure", "storage_account": self.storage_account},
        )

    def list_exports(self) -> list[DiscoveredExport]:
        return []

    def download_export(self, key: str, dest: Any = None) -> bytes | int:
        raise NotImplementedError("Azure download not yet implemented")
