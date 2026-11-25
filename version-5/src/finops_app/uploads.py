"""Checks an uploaded file before anything is stored or queued.

Size is capped by Flask's ``MAX_CONTENT_LENGTH``; here we check the name, that
the bytes really are a text CSV, and the row count.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

ALLOWED_EXTENSIONS = (".csv",)
SNIFF_BYTES = 64 * 1024
CHUNK_BYTES = 1024 * 1024
MIN_COLUMNS = 2


class UploadRejected(ValueError):
    """The file cannot be analysed; the message is safe to show the user."""


@dataclass(frozen=True)
class UploadCheck:
    size_bytes: int
    row_count: int


def check_filename(filename: str | None) -> str:
    """Return the filename, or raise with a user-facing reason."""
    if not filename:
        raise UploadRejected("Please select a file")
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise UploadRejected("Only CSV files are supported")
    return filename


def check_contents(path: Path, max_rows: int) -> UploadCheck:
    """Sniff the first bytes as CSV text and count data rows."""
    size = path.stat().st_size
    if size == 0:
        raise UploadRejected("The file is empty.")
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    _sniff(head)
    rows = _count_lines(path) - 1  # minus the header
    if rows < 1:
        raise UploadRejected("The file has a header but no data rows.")
    if rows > max_rows:
        raise UploadRejected(
            f"The file has {rows:,} rows; the limit is {max_rows:,}. Split it by month and upload each part."
        )
    return UploadCheck(size_bytes=size, row_count=rows)


def _sniff(head: bytes) -> None:
    if b"\x00" in head:
        raise UploadRejected("This doesn't look like a CSV file (it contains binary data).")
    try:
        text = head.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        # A multi-byte character may be cut at the sniff boundary.
        if exc.start < len(head) - 3:
            raise UploadRejected(
                "This doesn't look like a CSV file (it isn't UTF-8 text)."
            ) from exc
        text = head[: exc.start].decode("utf-8-sig")
    first_line = text.splitlines()[0] if text else ""
    header = next(csv.reader(io.StringIO(first_line)), [])
    if len([c for c in header if c.strip()]) < MIN_COLUMNS:
        raise UploadRejected("This doesn't look like a CSV file (no comma-separated header row).")


def _count_lines(path: Path) -> int:
    count, last = 0, b"\n"
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_BYTES):
            count += chunk.count(b"\n")
            last = chunk[-1:]
    return count + (0 if last == b"\n" else 1)
