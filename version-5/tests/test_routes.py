from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from finops_app import create_app, tasks
from finops_app.config import Config
from web_helpers import login, signup


def _upload(client: FlaskClient, content: bytes, filename: str = "billing.csv") -> str:
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_landing_page(anon_client: FlaskClient) -> None:
    resp = anon_client.get("/")
    assert resp.status_code == 200
    assert "Launch system" in resp.get_data(as_text=True)


def test_upload_page(client: FlaskClient) -> None:
    resp = client.get("/upload")
    assert resp.status_code == 200
    assert 'id="uploadForm"' in resp.get_data(as_text=True)


def test_sample_csv_download(anon_client: FlaskClient) -> None:
    resp = anon_client.get("/sample")
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


def test_header_only_file_is_rejected_before_queueing(client: FlaskClient) -> None:
    assert "no data rows" in _upload(client, b"UsageDate,EffectiveCost,ConsumedQuantity\n")


def test_too_large_upload_is_rejected(client: FlaskClient) -> None:
    big = b"a" * (2 * 1024 * 1024)  # test config limit is 1 MB
    assert "File is too large" in _upload(client, big)


def test_internal_errors_do_not_leak_details(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, make_billing_csv: Callable[..., Path]
) -> None:
    def boom(_path: str) -> object:
        raise RuntimeError("secret /etc/internal/path")

    monkeypatch.setattr(tasks, "analyze", boom)
    body = _upload(client, make_billing_csv(days=5).read_bytes())

    assert "internal error" in body
    assert "/etc/internal/path" not in body


def test_successful_upload_renders_dashboard_and_stores_file(
    client: FlaskClient, make_billing_csv: Callable[..., Path], config: Config
) -> None:
    body = _upload(client, make_billing_csv(days=10).read_bytes())

    assert "Cloud Waste Analysis Complete" in body
    assert "data:image/png;base64," in body
    stored = [p for p in Path(config.upload_dir).rglob("*.csv") if ".incoming" not in p.parts]
    assert len(stored) == 1
    assert not list((Path(config.upload_dir) / ".incoming").iterdir())


def test_filename_is_sanitised_and_never_used_as_a_path(
    client: FlaskClient, make_billing_csv: Callable[..., Path], config: Config
) -> None:
    _upload(client, make_billing_csv(days=5).read_bytes(), filename="../../evil.csv")

    upload_dir = Path(config.upload_dir)
    assert not (upload_dir.parent.parent / "evil.csv").exists()
    assert not list(upload_dir.rglob("evil.csv"))
    assert "evil.csv" in client.get("/analyses").get_data(as_text=True)


def test_upload_redirects_to_the_analysis_page(
    client: FlaskClient, make_billing_csv: Callable[..., Path]
) -> None:
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(make_billing_csv(days=5).read_bytes()), "bill.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/analyses/")


def test_status_endpoint_reports_the_result(
    client: FlaskClient, make_billing_csv: Callable[..., Path]
) -> None:
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(make_billing_csv(days=5).read_bytes()), "bill.csv")},
        content_type="multipart/form-data",
    )
    url = resp.headers["Location"]
    status = client.get(url + "/status").get_json()
    assert status["status"] == "succeeded"
    assert status["error"] is None
    assert status["url"] == url


def test_failed_analysis_shows_its_reason(client: FlaskClient) -> None:
    body = _upload(client, b"UsageDate,EffectiveCost,ConsumedQuantity\n2024-01-01,5,1\n")
    assert "didn’t finish" in body
    assert "Insufficient data" in body


def test_results_survive_an_app_restart(
    config: Config, make_billing_csv: Callable[..., Path]
) -> None:
    first = create_app(config).test_client()
    signup(first)
    resp = first.post(
        "/upload",
        data={"file": (io.BytesIO(make_billing_csv(days=5).read_bytes()), "bill.csv")},
        content_type="multipart/form-data",
    )
    url = resp.headers["Location"]

    restarted = login(create_app(config).test_client(), "owner@acme.example.com")
    assert "Cloud Waste Analysis Complete" in restarted.get(url).get_data(as_text=True)


def test_history_lists_past_analyses(
    client: FlaskClient, make_billing_csv: Callable[..., Path]
) -> None:
    assert "No analyses yet" in client.get("/analyses").get_data(as_text=True)
    _upload(client, make_billing_csv(days=5).read_bytes(), filename="march.csv")
    _upload(
        client, b"UsageDate,EffectiveCost,ConsumedQuantity\n2024-01-01,5,1\n", filename="tiny.csv"
    )

    body = client.get("/analyses").get_data(as_text=True)
    assert body.index("tiny.csv") < body.index("march.csv")  # newest first
    assert "Succeeded" in body and "Failed" in body


def test_unknown_analysis_is_404(client: FlaskClient) -> None:
    assert client.get("/analyses/" + "0" * 32).status_code == 404
    assert client.get("/analyses/" + "0" * 32 + "/status").status_code == 404


def test_rejected_upload_is_not_stored(client: FlaskClient, config: Config) -> None:
    assert "binary data" in _upload(client, b"\x00\x01\x02,\x03\n")
    assert not [p for p in Path(config.upload_dir).rglob("*.csv")]
    assert "No analyses yet" in client.get("/analyses").get_data(as_text=True)


def test_resource_names_are_escaped_on_the_dashboard(
    client: FlaskClient, make_billing_csv: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    real = tasks.analyze

    def with_hostile_name(path: str) -> object:
        res = real(path)
        hostile = replace(res.findings[0], resource_name="<script>alert(1)</script>")
        return replace(res, findings=(hostile, *res.findings[1:]))

    monkeypatch.setattr(tasks, "analyze", with_hostile_name)
    body = _upload(client, make_billing_csv(days=10, anomaly_rate=0.3).read_bytes())

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
