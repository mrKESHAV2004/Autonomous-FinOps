"""Object storage for raw uploads.

Keys are ``<org_id>/<yyyy>/<mm>/<dataset-key>.csv`` so one org's files share a
prefix. :class:`LocalStorage` keeps them under a directory; an S3 backend with
the same interface arrives with production deployment (Phase 6).
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Protocol

from finops_app.models import new_id, utcnow

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


class StorageError(RuntimeError):
    """A key is malformed or points outside the storage root."""


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
