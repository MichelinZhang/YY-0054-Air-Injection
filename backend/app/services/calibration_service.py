"""Calibration service: maps pixel/tick measurements to physical units.

Provides a calibration profile that converts raw tick_delta or pixel_delta
into physical volume (mL) based on known tube geometry and scale parameters.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path

from app.config import BASE_DIR


CALIBRATION_FILE = BASE_DIR / "data" / "calibration.json"

_DEFAULT_SCALE_MM_PER_TICK = 1.0
_DEFAULT_TUBE_INNER_DIAMETER_MM = 3.0


@dataclass
class CalibrationProfile:
    """Active calibration profile mapping ticks/pixels to physical units."""
    profile_name: str = "default"
    scale_mm_per_tick: float = _DEFAULT_SCALE_MM_PER_TICK
    tube_inner_diameter_mm: float = _DEFAULT_TUBE_INNER_DIAMETER_MM
    pixels_per_mm: float | None = None
    reference_tick_count: int | None = None
    reference_pixel_span: float | None = None
    volume_unit: str = "mL"
    notes: str = ""

    @property
    def tube_cross_section_area_mm2(self) -> float:
        import math
        r = self.tube_inner_diameter_mm / 2.0
        return math.pi * r * r

    def tick_delta_to_mm(self, tick_delta: float) -> float:
        return tick_delta * self.scale_mm_per_tick

    def tick_delta_to_volume_ml(self, tick_delta: float) -> float:
        length_mm = self.tick_delta_to_mm(tick_delta)
        volume_mm3 = length_mm * self.tube_cross_section_area_mm2
        return volume_mm3 / 1000.0

    def pixel_delta_to_mm(self, pixel_delta: float) -> float | None:
        if self.pixels_per_mm is None or self.pixels_per_mm <= 0:
            return None
        return pixel_delta / self.pixels_per_mm

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tube_cross_section_area_mm2"] = self.tube_cross_section_area_mm2
        return d

    @classmethod
    def from_dict(cls, data: dict) -> CalibrationProfile:
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class CalibrationService:
    _instance: CalibrationService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> CalibrationService:
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
        self._profile = self._load_or_default()

    @property
    def profile(self) -> CalibrationProfile:
        return self._profile

    def _load_or_default(self) -> CalibrationProfile:
        if CALIBRATION_FILE.exists():
            try:
                data = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
                return CalibrationProfile.from_dict(data)
            except (json.JSONDecodeError, TypeError):
                pass
        return CalibrationProfile()

    def update_profile(self, updates: dict) -> CalibrationProfile:
        current = asdict(self._profile)
        current.update({k: v for k, v in updates.items() if v is not None})
        self._profile = CalibrationProfile.from_dict(current)
        self._save()
        return self._profile

    def calibrate_from_reference(
        self,
        known_tick_count: int,
        known_length_mm: float,
        measured_pixel_span: float | None = None,
    ) -> CalibrationProfile:
        """Compute calibration from a known reference measurement."""
        if known_tick_count <= 0:
            raise ValueError("Reference tick count must be positive")
        if known_length_mm <= 0:
            raise ValueError("Reference length must be positive")

        scale = known_length_mm / known_tick_count
        updates: dict = {
            "scale_mm_per_tick": scale,
            "reference_tick_count": known_tick_count,
        }
        if measured_pixel_span is not None and measured_pixel_span > 0:
            updates["pixels_per_mm"] = measured_pixel_span / known_length_mm
            updates["reference_pixel_span"] = measured_pixel_span
        return self.update_profile(updates)

    def convert_reading(self, tick_delta: float, pixel_delta: float) -> dict:
        """Convert raw measurement to physical units using current profile."""
        p = self._profile
        length_mm = p.tick_delta_to_mm(tick_delta)
        volume_ml = p.tick_delta_to_volume_ml(tick_delta)
        result = {
            "length_mm": round(length_mm, 3),
            "volume_ml": round(volume_ml, 4),
            "volume_unit": p.volume_unit,
            "scale_mm_per_tick": p.scale_mm_per_tick,
            "tube_diameter_mm": p.tube_inner_diameter_mm,
        }
        px_mm = p.pixel_delta_to_mm(pixel_delta)
        if px_mm is not None:
            result["pixel_length_mm"] = round(px_mm, 3)
        return result

    def _save(self) -> None:
        CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_FILE.write_text(
            json.dumps(self._profile.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


calibration_service = CalibrationService()
