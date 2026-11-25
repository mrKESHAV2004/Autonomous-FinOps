from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from finops_app.storage import LocalStorage, StorageError, make_key
from finops_app.uploads import UploadRejected, check_contents, check_filename

HEADER = "UsageDate,EffectiveCost,ConsumedQuantity\n"


def write(tmp_path: Path, content: bytes, name: str = "f.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


# ---- storage ----------------------------------------------------------------


def test_key_is_prefixed_by_org_and_month() -> None:
    key = make_key("abc123", datetime(2026, 3, 9, tzinfo=UTC))
    assert key.startswith("abc123/2026/03/") and key.endswith(".csv")
    assert make_key("abc123") != make_key("abc123")


def test_key_refuses_unsafe_org_id() -> None:
    with pytest.raises(StorageError):
        make_key("../etc")


def test_put_read_delete(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path / "store")
    src = write(tmp_path, b"a,b\n1,2\n")
    key = make_key("org1")

    assert store.put_file(key, src) == 8
    assert not src.exists()
    assert store.local_path(key).read_bytes() == b"a,b\n1,2\n"
    assert store.exists(key)
    assert store.delete(key) is True
    assert store.delete(key) is False
    with pytest.raises(FileNotFoundError):
        store.local_path(key)


@pytest.mark.parametrize("key", ["../x.csv", "org/../../x.csv", "/abs.csv", "org//x.csv", ""])
def test_keys_cannot_escape_the_root(tmp_path: Path, key: str) -> None:
    with pytest.raises(StorageError):
        LocalStorage(tmp_path).exists(key)


# ---- upload checks -----------------------------------------------------------


@pytest.mark.parametrize("name", ["bill.CSV", "a.b.csv"])
def test_csv_names_pass(name: str) -> None:
    assert check_filename(name) == name


@pytest.mark.parametrize(
    ("name", "message"),
    [
        (None, "select a file"),
        ("", "select a file"),
        ("x.txt", "Only CSV"),
        ("x.csv.exe", "Only CSV"),
    ],
)
def test_bad_names_are_rejected(name: str | None, message: str) -> None:
    with pytest.raises(UploadRejected, match=message):
        check_filename(name)


def test_counts_data_rows_with_or_without_trailing_newline(tmp_path: Path) -> None:
    body = HEADER + "2024-01-01,1,1\n2024-01-02,2,2"
    assert check_contents(write(tmp_path, body.encode()), max_rows=10).row_count == 2
    assert check_contents(write(tmp_path, (body + "\n").encode()), max_rows=10).row_count == 2


def test_utf8_bom_is_accepted(tmp_path: Path) -> None:
    path = write(tmp_path, b"\xef\xbb\xbf" + (HEADER + "2024-01-01,1,1\n").encode())
    assert check_contents(path, max_rows=10).size_bytes == path.stat().st_size


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (HEADER.encode(), "no data rows"),
        (b"\x89PNG\r\n\x1a\n\x00\x00binary", "binary data"),
        (b"caf\xe9,b\n1,2\n" + b"x" * 100, "UTF-8"),
        (b"just one column\nvalue\n", "comma-separated header"),
    ],
)
def test_non_csv_content_is_rejected(tmp_path: Path, content: bytes, message: str) -> None:
    with pytest.raises(UploadRejected, match=message):
        check_contents(write(tmp_path, content), max_rows=10)


def test_row_cap(tmp_path: Path) -> None:
    body = HEADER + "2024-01-01,1,1\n" * 11
    with pytest.raises(UploadRejected, match="11 rows; the limit is 10"):
        check_contents(write(tmp_path, body.encode()), max_rows=10)
