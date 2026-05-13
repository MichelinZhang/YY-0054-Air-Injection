from __future__ import annotations

import os
from pathlib import Path
from typing import Literal


ENV: Literal["development", "production"] = os.environ.get("APP_ENV", "development").lower()  # type: ignore[assignment]
if ENV not in ("development", "production"):
    ENV = "development"

IS_PRODUCTION = ENV == "production"

BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BASE_DIR
MVS_IMPORT_DIR = REPO_ROOT / "Python" / "MvImport"
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", str(BASE_DIR / "data" / "results")))
FRONTEND_DIST_DIR = REPO_ROOT / "frontend" / "dist"
AUDIT_LOG_DIR = Path(os.environ.get("AUDIT_LOG_DIR", str(BASE_DIR / "data" / "audit_logs")))

DEFAULT_WS_FPS = int(os.environ.get("WS_FPS", "20"))

CORS_ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if IS_PRODUCTION
    else ["*"]
)

AUTH_SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "dev-only-insecure-key-change-in-production")
AUTH_TOKEN_EXPIRE_HOURS = int(os.environ.get("AUTH_TOKEN_EXPIRE_HOURS", "24"))
AUTH_ENABLED = IS_PRODUCTION or os.environ.get("AUTH_ENABLED", "").lower() in ("1", "true", "yes")

MOCK_SAVE_ALLOWED = not IS_PRODUCTION
