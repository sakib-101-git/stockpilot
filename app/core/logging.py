"""Structured JSON logging with an automatically-attached request ID.

Uses stdlib logging with a custom formatter, not a new dependency — this
project already integrates a lot of purpose-built libraries (MLflow,
Evidently, OR-Tools); logging is simple enough to build directly rather
than add another one.
"""

import contextvars
import json
import logging
import sys
import uuid

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_with_fields(logger: logging.Logger, level: int, message: str, **fields) -> None:
    """Logs a message with extra structured fields attached, e.g.
    log_with_fields(logger, logging.INFO, "forecast generated",
                     tenant_id=str(tenant_id), duration_ms=1234)
    """
    logger.log(level, message, extra={"extra_fields": fields})


def new_request_id() -> str:
    return str(uuid.uuid4())
