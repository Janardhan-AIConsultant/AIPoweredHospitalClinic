"""Structured JSON logging with request-id correlation and PII masking."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.utils.pii import mask_text, redact_mapping

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "request_id": request_id_ctx.get(),
            "message": mask_text(record.getMessage()),
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD}
        payload.update(redact_mapping(extras))
        if record.exc_info:
            payload["exception"] = mask_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by middleware access log
