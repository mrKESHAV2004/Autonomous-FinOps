"""Object storage for raw uploads.

Keys are ``<org_id>/<yyyy>/<mm>/<dataset-key>.csv`` so one org's files share a
prefix. :class:`LocalStorage` keeps them under a directory; :class:`S3Storage`
backs them by Amazon S3 or S3-compatible object stores (Phase 6).
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from finops_app.models import new_id, utcnow

if TYPE_CHECKING:
    from finops_app.config import Config

logger = logging.getLogger(__name__)

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


class StorageError(RuntimeError):
    """A key is malformed, points outside the storage root, or S3 failed."""


class Storage(Protocol):
    def put_file(self, key: str, source: Path) -> int: ...
    def local_path(self, key: str) -> Path: ...
    def delete(self, key: str) -> bool: ...
    def exists(self, key: str) -> bool: ...


def make_key(org_id: str, now: datetime | None = None) -> str:
    """A fresh, org-prefixed key for one raw upload."""
    if not _SAFE_SEGMENT.match(org_id):
        raise StorageError("org_id is not a safe key segment")
    when = now or utcnow()
    return f"{org_id}/{when:%Y}/{when:%m}/{new_id()}.csv"


class LocalStorage:
    """Files under ``root``; keys never escape it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if not parts or any(not p or p in (".", "..") for p in parts):
            raise StorageError(f"invalid storage key: {key!r}")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError(f"storage key escapes the root: {key!r}")
        return path

    def put_file(self, key: str, source: Path) -> int:
        """Move ``source`` to ``key``; returns its size in bytes."""
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), dest)
        return dest.stat().st_size

    def local_path(self, key: str) -> Path:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return path

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage:
    """Object storage backed by Amazon S3 or S3-compatible object store."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        s3_client: Any = None,
        cache_dir: Path | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = s3_client
        self.endpoint_url = endpoint_url
        self.cache_dir = (
            cache_dir.resolve()
            if cache_dir is not None
            else (Path(tempfile.gettempdir()) / "finops_s3_cache").resolve()
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3

        self._client = boto3.client("s3", endpoint_url=self.endpoint_url)
        return self._client

    def _s3_key(self, key: str) -> str:
        parts = key.split("/")
        if not parts or any(not p or p in (".", "..") for p in parts):
            raise StorageError(f"invalid storage key: {key!r}")
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def _local_cache_path(self, key: str) -> Path:
        dest = (self.cache_dir / key).resolve()
        if not dest.is_relative_to(self.cache_dir):
            raise StorageError(f"storage key escapes the root: {key!r}")
        return dest

    def put_file(self, key: str, source: Path) -> int:
        """Upload ``source`` to S3 ``key``; returns its size in bytes."""
        s3_key = self._s3_key(key)
        if not source.exists():
            raise FileNotFoundError(str(source))
        size = source.stat().st_size
        client = self._get_client()
        try:
            client.upload_file(str(source), self.bucket, s3_key)
        except Exception as exc:
            raise StorageError(f"failed to upload {key} to S3: {exc}") from exc
        dest = self._local_cache_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(source), dest)
        except Exception:
            logger.debug("Failed to populate local S3 cache for %s", key, exc_info=True)
        return size

    def local_path(self, key: str) -> Path:
        """Fetch ``key`` into local cache directory if not present, then return Path."""
        s3_key = self._s3_key(key)
        dest = self._local_cache_path(key)
        if dest.exists():
            return dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        client = self._get_client()
        from botocore.exceptions import ClientError

        try:
            client.download_file(self.bucket, s3_key, str(dest))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "403"):
                raise FileNotFoundError(key) from exc
            raise StorageError(f"failed to download {key} from S3: {exc}") from exc
        except Exception as exc:
            raise StorageError(f"failed to download {key} from S3: {exc}") from exc

        return dest

    def delete(self, key: str) -> bool:
        if not self.exists(key):
            return False
        s3_key = self._s3_key(key)
        client = self._get_client()
        try:
            client.delete_object(Bucket=self.bucket, Key=s3_key)
        except Exception as exc:
            raise StorageError(f"S3 deletion failed for {key}: {exc}") from exc
        dest = self._local_cache_path(key)
        dest.unlink(missing_ok=True)
        return True

    def exists(self, key: str) -> bool:
        s3_key = self._s3_key(key)
        client = self._get_client()
        from botocore.exceptions import ClientError

        try:
            client.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                return False
            raise StorageError(f"failed to check existence of {key}: {exc}") from exc
        except Exception as exc:
            raise StorageError(f"failed to check existence of {key}: {exc}") from exc


def build_storage(cfg: Config) -> Storage:
    """Build the configured storage provider (LocalStorage or S3Storage)."""
    if cfg.storage_backend == "s3":
        if not cfg.s3_bucket:
            raise StorageError("FINOPS_S3_BUCKET is required when FINOPS_STORAGE_BACKEND=s3")
        return S3Storage(
            bucket=cfg.s3_bucket,
            prefix=cfg.s3_prefix,
            cache_dir=cfg.upload_dir,
            endpoint_url=cfg.s3_endpoint_url,
        )
    return LocalStorage(cfg.upload_dir)
