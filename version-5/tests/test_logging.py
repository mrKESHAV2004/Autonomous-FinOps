from __future__ import annotations

import json
import logging

from finops_app.logging_config import JsonFormatter, configure_logging


def test_json_formatter_includes_extra_fields() -> None:
    record = logging.makeLogRecord(
        {"name": "finops.test", "levelname": "INFO", "msg": "hello %s", "args": ("world",)}
    )
    record.upload = "file.csv"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "finops.test"
    assert payload["upload"] == "file.csv"
    assert "ts" in payload


def test_json_formatter_includes_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.getLogger("t").makeRecord(
            "t", logging.ERROR, __file__, 1, "failed", None, exc_info=__import__("sys").exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc"]


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    configure_logging("DEBUG")
    configure_logging("INFO", json_logs=True)

    ours = [h for h in root.handlers if h.get_name() == "finops"]
    assert len(ours) == 1
    assert isinstance(ours[0].formatter, JsonFormatter)
    assert root.level == logging.INFO
