import json
import logging
import sys
from contextvars import ContextVar

# Set by the request-ID middleware in api.py at the start of each request,
# read here so every log line emitted while handling that request --
# across api.py, rag_service.py, database.py, wherever -- carries the same
# ID without threading it through every function signature by hand.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED_LOG_RECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, instead of a free-text string.

    Render's log viewer (and any real log aggregator) can filter/query by
    field this way -- e.g. every line for one request_id, or every line
    at ERROR level -- instead of grepping formatted strings. Extra fields
    passed via `logger.info("msg", extra={"doc_id": doc_id})` are included
    automatically.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_KEYS:
                payload[key] = value
        return json.dumps(payload, default=str)


def setup_logging(name: str = "documind", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # avoid duplicate handlers if this is called more than once (e.g. test re-imports)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
