from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BASE_DIR
MVS_IMPORT_DIR = REPO_ROOT / "Python" / "MvImport"
RESULTS_DIR = BASE_DIR / "data" / "results"
FRONTEND_DIST_DIR = REPO_ROOT / "frontend" / "dist"

DEFAULT_WS_FPS = 20
