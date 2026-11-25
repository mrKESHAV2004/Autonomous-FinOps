from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from finops_app import analysis


def _upload(client: FlaskClient, content: bytes, filename: str = "billing.csv") -> str:
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_landing_page(client: FlaskClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Launch system" in resp.get_data(as_text=True)


def test_upload_page(client: FlaskClient) -> None:
    resp = client.get("/upload")
    assert resp.status_code == 200
    assert 'id="uploadForm"' in resp.get_data(as_text=True)


def test_sample_csv_download(client: FlaskClient) -> None:
    resp = client.get("/sample")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert resp.get_data(as_text=True).startswith("UsageDate,ServiceCategory,EffectiveCost")


def test_post_without_file_field(client: FlaskClient) -> None:
    resp = client.post("/upload", data={}, follow_redirects=True)
    assert "No file selected" in resp.get_data(as_text=True)


def test_post_with_empty_filename(client: FlaskClient) -> None:
    assert "Please select a file" in _upload(client, b"x", filename="")


@pytest.mark.parametrize("name", ["data.txt", "data.csv.exe", "data"])
def test_rejects_non_csv(client: FlaskClient, name: str) -> None:
    assert "Only CSV files are supported" in _upload(client, b"a,b\n1,2", filename=name)


def test_accepts_uppercase_extension(
    client: FlaskClient, make_billing_csv: Callable[..., Path]
) -> None:
    body = _upload(client, make_billing_csv(days=5).read_bytes(), filename="BILLING.CSV")
    assert "Cloud Waste Analysis Complete" in body


def test_missing_columns_shows_validation_message(client: FlaskClient) -> None:
    body = _upload(client, b"Date,Cost\n2024-01-01,5\n")
    assert "Missing required column(s)" in body


def test_too_few_rows_shows_validation_message(client: FlaskClient) -> None:
    csv = b"UsageDate,EffectiveCost,ConsumedQuantity\n2024-01-01,5,1\n"
    assert "Insufficient data" in _upload(client, csv)


def test_too_large_upload_is_rejected(client: FlaskClient) -> None:
    big = b"a" * (2 * 1024 * 1024)  # test config limit is 1 MB
    assert "File is too large" in _upload(client, big)


def test_internal_errors_do_not_leak_details(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_path: str) -> dict[str, object]:
        raise RuntimeError("secret /etc/internal/path")

    monkeypatch.setattr(analysis, "run_analysis", boom)
    body = _upload(client, b"UsageDate,EffectiveCost,ConsumedQuantity\n")

    assert "internal error" in body
    assert "/etc/internal/path" not in body


def test_successful_upload_renders_dashboard_and_saves_file(
    client: FlaskClient, make_billing_csv: Callable[..., Path], config: object
) -> None:
    body = _upload(client, make_billing_csv(days=10).read_bytes())

    assert "Cloud Waste Analysis Complete" in body
    assert "data:image/png;base64," in body
    saved = list(Path(config.upload_dir).glob("*_billing.csv"))  # type: ignore[attr-defined]
    assert len(saved) == 1


def test_filename_is_sanitised(
    client: FlaskClient, make_billing_csv: Callable[..., Path], config: object
) -> None:
    _upload(client, make_billing_csv(days=5).read_bytes(), filename="../../evil.csv")

    upload_dir = Path(config.upload_dir)  # type: ignore[attr-defined]
    names = [p.name for p in upload_dir.iterdir()]
    assert len(names) == 1
    assert names[0].endswith("_evil.csv")
    assert not (upload_dir.parent.parent / "evil.csv").exists()
