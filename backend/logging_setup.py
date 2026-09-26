"""
backend/logging_setup.py — structured JSON logging (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
One line = one JSON object, to both the console and logs/jarvis.log. A contextvar
carries a per-request id so every log line for a request can be correlated
("why did JARVIS do this?"). Secrets are never logged by this module.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        # attach any structured extras passed via logger.info(..., extra={...})
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    fmt = JsonFormatter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fileh = logging.FileHandler(log_file, encoding="utf-8")
        fileh.setFormatter(fmt)
        root.addHandler(fileh)

    # keep uvicorn's access noise structured too, but quieter
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    return logging.getLogger("jarvis")


def get_logger(name: str = "jarvis") -> logging.Logger:
    return logging.getLogger(name)
