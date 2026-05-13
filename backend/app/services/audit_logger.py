"""Structured audit logging for medical device compliance (ISO 13485 / IEC 62304).

All critical operations are logged with structured JSON records for traceability.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.config import AUDIT_LOG_DIR


class AuditEvent(str, Enum):
    SESSION_OPENED = "session.opened"
    SESSION_CLOSED = "session.closed"
    MEASUREMENT_TAKEN = "measurement.taken"
    RESULT_SAVED = "result.saved"
    CAMERA_SETTINGS_CHANGED = "camera.settings_changed"
    LIGHT_TOGGLED = "light.toggled"
    MOCK_MODE_ACTIVATED = "mock.activated"
    AUTH_LOGIN = "auth.login"
    AUTH_FAILED = "auth.failed"
    ERROR_OCCURRED = "error.occurred"
    SAVE_BLOCKED = "save.blocked"


class AuditLogger:
    _instance: AuditLogger | None = None
    _lock = threading.Lock()

    def __new__(cls) -> AuditLogger:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._log_dir = AUDIT_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

        self._logger = logging.getLogger("audit")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        handler = logging.handlers.TimedRotatingFileHandler(
            str(self._log_dir / "audit.jsonl"),
            when="midnight",
            backupCount=365,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        if not self._logger.handlers:
            self._logger.addHandler(handler)

    def log(
        self,
        event: AuditEvent,
        *,
        operator: str | None = None,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event.value,
            "operator": operator,
            "session_id": session_id,
            "details": details or {},
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        self._logger.info(line)

    def log_error(
        self,
        error_code: str,
        message: str,
        *,
        operator: str | None = None,
        session_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.log(
            AuditEvent.ERROR_OCCURRED,
            operator=operator,
            session_id=session_id,
            details={
                "error_code": error_code,
                "message": message,
                **(context or {}),
            },
        )


audit_logger = AuditLogger()
