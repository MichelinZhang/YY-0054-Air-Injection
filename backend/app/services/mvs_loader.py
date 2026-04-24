from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from app.config import MVS_IMPORT_DIR


@dataclass
class MvsLoadResult:
    available: bool
    module: ModuleType | None
    error: str | None = None


def load_mvs_module() -> MvsLoadResult:
    mvs_path = Path(MVS_IMPORT_DIR)
    if not mvs_path.exists():
        return MvsLoadResult(False, None, f"MvImport directory not found: {mvs_path}")

    if str(mvs_path) not in sys.path:
        sys.path.insert(0, str(mvs_path))

    try:
        module = importlib.import_module("MvCameraControl_class")
        return MvsLoadResult(True, module, None)
    except Exception as exc:  # pragma: no cover - depends on host SDK runtime
        return MvsLoadResult(False, None, str(exc))

