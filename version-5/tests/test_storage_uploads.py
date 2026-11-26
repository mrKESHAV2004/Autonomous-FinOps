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


def test_s3_storage_put_download_delete(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    from finops_app.storage import S3Storage

    mock_client = MagicMock()
    store = S3Storage(
        bucket="test-bucket",
        prefix="billing-prefix",
        s3_client=mock_client,
        cache_dir=tmp_path / "cache",
    )
    src = write(tmp_path, b"col1,col2\n10,20\n")
    key = make_key("org1")

    # Put
    size = store.put_file(key, src)
    assert size == 16
    mock_client.upload_file.assert_called_once_with(
        str(src), "test-bucket", f"billing-prefix/{key}"
    )

    # Exists - true
    mock_client.head_object.return_value = {"ContentLength": 16}
    assert store.exists(key) is True
    mock_client.head_object.assert_called_with(Bucket="test-bucket", Key=f"billing-prefix/{key}")

    # Local path returns cached file
    cached = store.local_path(key)
    assert cached.exists()
    assert cached.read_bytes() == b"col1,col2\n10,20\n"

    # Delete
    assert store.delete(key) is True
    mock_client.delete_object.assert_called_once_with(
        Bucket="test-bucket", Key=f"billing-prefix/{key}"
    )
    assert not cached.exists()

    # Exists - false
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "head_object"
    )
    assert store.exists(key) is False

    # Download when not in cache
    mock_client.download_file.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
        "download_file",
    )
    with pytest.raises(FileNotFoundError):
        store.local_path("org1/2026/03/missing.csv")


def test_s3_storage_invalid_keys(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from finops_app.storage import S3Storage

    store = S3Storage(bucket="b", s3_client=MagicMock(), cache_dir=tmp_path)
    with pytest.raises(StorageError):
        store.exists("../escape.csv")


def test_build_storage_factory(tmp_path: Path) -> None:
    from finops_app.config import Config
    from finops_app.storage import S3Storage, build_storage

    local_cfg = Config(upload_dir=tmp_path / "uploads", storage_backend="local")
    local_store = build_storage(local_cfg)
    assert isinstance(local_store, LocalStorage)

    s3_cfg = Config(
        upload_dir=tmp_path / "uploads",
        storage_backend="s3",
        s3_bucket="my-bucket",
        s3_prefix="my-prefix",
    )
    s3_store = build_storage(s3_cfg)
    assert isinstance(s3_store, S3Storage)
    assert s3_store.bucket == "my-bucket"
    assert s3_store.prefix == "my-prefix"

    invalid_cfg = Config(upload_dir=tmp_path / "uploads", storage_backend="s3", s3_bucket=None)
    with pytest.raises(StorageError, match="FINOPS_S3_BUCKET is required"):
        build_storage(invalid_cfg)


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
