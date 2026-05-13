"""Unified error code system for medical device compliance (IEC 62304)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel


class ErrorCode(str, Enum):
    # Authentication & Authorization (1xxx)
    AUTH_TOKEN_MISSING = "E1001"
    AUTH_TOKEN_INVALID = "E1002"
    AUTH_TOKEN_EXPIRED = "E1003"
    AUTH_PERMISSION_DENIED = "E1004"

    # Session (2xxx)
    SESSION_OPEN_FAILED = "E2001"
    SESSION_NOT_ACTIVE = "E2002"
    SESSION_CAMERA_UNAVAILABLE = "E2003"

    # Camera & Device (3xxx)
    CAMERA_NOT_FOUND = "E3001"
    CAMERA_NOT_ACTIVE = "E3002"
    CAMERA_SETTINGS_FAILED = "E3003"
    CAMERA_NO_FRAME = "E3004"

    # Measurement (4xxx)
    MEASURE_INVALID_POINTS = "E4001"
    MEASURE_NO_FRAME = "E4002"
    MEASURE_ALGORITHM_ERROR = "E4003"

    # Result Storage (5xxx)
    SAVE_NO_MEASUREMENTS = "E5001"
    SAVE_FRAME_MISSING = "E5002"
    SAVE_MOCK_BLOCKED = "E5003"
    SAVE_INTEGRITY_ERROR = "E5004"
    SAVE_OPERATOR_REQUIRED = "E5005"

    # Calibration (6xxx)
    CALIBRATION_REMOVED = "E6001"

    # General (9xxx)
    INTERNAL_ERROR = "E9001"
    VALIDATION_ERROR = "E9002"
    NOT_FOUND = "E9003"
    FEATURE_DISABLED = "E9004"


class AppErrorResponse(BaseModel):
    error_code: str
    message: str
    detail: str | None = None


class AppError(HTTPException):
    """Application-level error with structured error code."""

    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        message: str,
        detail: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.error_detail = detail
        body = {
            "error_code": error_code.value,
            "message": message,
        }
        if detail:
            body["detail"] = detail
        super().__init__(status_code=status_code, detail=body, headers=headers)
