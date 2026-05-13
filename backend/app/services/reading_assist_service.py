from __future__ import annotations

import uuid
from datetime import datetime, timezone

import cv2
import numpy as np

from app.models import MeasureRequest, Point2D, ReadingRecord, RectROI


CONFIDENCE_REJECT_THRESHOLD = 0.15
CONFIDENCE_WARN_THRESHOLD = 0.40


class ReadingAssistService:
    @staticmethod
    def _in_roi(point: Point2D, roi: RectROI) -> bool:
        return roi.x <= point.x <= roi.x + roi.width and roi.y <= point.y <= roi.y + roi.height

    @staticmethod
    def _adaptive_radius(image_height: int) -> int:
        """Scale search radius relative to image size."""
        return max(16, int(image_height * 0.04))

    @staticmethod
    def _adaptive_x_span(image_width: int) -> int:
        """Scale horizontal averaging span relative to image width."""
        return max(3, int(image_width * 0.005))

    @staticmethod
    def _refine_y_with_edge(
        gray: np.ndarray,
        point: Point2D,
        roi: RectROI | None,
        radius: int | None = None,
        x_half_span: int | None = None,
    ) -> tuple[Point2D, float]:
        h, w = gray.shape[:2]
        if radius is None:
            radius = max(16, int(h * 0.04))
        if x_half_span is None:
            x_half_span = max(3, int(w * 0.005))

        x = int(np.clip(round(point.x), 0, w - 1))
        y = int(np.clip(round(point.y), 0, h - 1))

        y_min = max(0, y - radius)
        y_max = min(h - 1, y + radius)
        if roi is not None:
            y_min = max(y_min, roi.y)
            y_max = min(y_max, roi.y + roi.height)
            if y_min >= y_max:
                return point, 0.2

        x_min = max(0, x - x_half_span)
        x_max = min(w - 1, x + x_half_span)
        strip = gray[y_min : y_max + 1, x_min : x_max + 1]
        if strip.shape[0] < 3:
            return point, 0.2

        row_signal = strip.mean(axis=1)
        grad = np.abs(np.diff(row_signal))
        if grad.size == 0:
            return point, 0.2
        idx = int(np.argmax(grad))
        refined_y = y_min + idx
        grad_range = float(grad.max() - grad.min()) if grad.size > 1 else 1.0
        normalizer = max(grad_range, float(np.std(row_signal)) * 2.0, 1.0)
        confidence = float(np.clip(grad[idx] / normalizer, 0.0, 1.0))
        return Point2D(x=float(x), y=float(refined_y)), confidence

    @staticmethod
    def _group_rows(rows: np.ndarray, merge_gap: int = 2) -> list[int]:
        if rows.size == 0:
            return []
        grouped: list[list[int]] = [[int(rows[0])]]
        for v in rows[1:]:
            iv = int(v)
            if iv - grouped[-1][-1] <= merge_gap:
                grouped[-1].append(iv)
            else:
                grouped.append([iv])
        return [int(round(sum(g) / len(g))) for g in grouped]

    def _detect_tick_lines(self, gray: np.ndarray, x: int, roi: RectROI | None) -> list[int]:
        h, w = gray.shape[:2]
        y_min = 0
        y_max = h - 1
        if roi is not None:
            y_min = max(0, roi.y)
            y_max = min(h - 1, roi.y + roi.height)
        if y_min >= y_max:
            return []

        x_half = max(18, int(w * 0.015))
        x_min = max(0, int(x) - x_half)
        x_max = min(w - 1, int(x) + x_half)
        strip = gray[y_min : y_max + 1, x_min : x_max + 1]
        if strip.shape[0] < 4:
            return []

        ksize = max(3, (strip.shape[0] // 80) * 2 + 1)
        strip = cv2.GaussianBlur(strip, (ksize, ksize), 0)
        row_signal = strip.mean(axis=1).astype(np.float32)
        grad = np.abs(np.diff(row_signal))
        if grad.size < 3:
            return []

        p90 = float(np.percentile(grad, 90))
        adaptive_threshold = max(p90, float(grad.mean() + grad.std()))
        candidate_rows = np.where(grad >= adaptive_threshold)[0] + y_min
        merge_gap = max(2, int(h * 0.003))
        grouped = self._group_rows(candidate_rows, merge_gap=merge_gap)

        if len(grouped) >= 3:
            spacings = np.diff(grouped)
            median_spacing = float(np.median(spacings))
            if median_spacing > 0:
                filtered = [grouped[0]]
                for i in range(1, len(grouped)):
                    spacing = grouped[i] - filtered[-1]
                    if spacing > median_spacing * 0.4:
                        filtered.append(grouped[i])
                grouped = filtered

        return sorted(grouped)

    @staticmethod
    def _snap_to_tick(y: float, ticks: list[int]) -> tuple[float, float, float]:
        if not ticks:
            return float(y), float(round(y)), 0.25

        arr = np.asarray(ticks, dtype=np.float32)
        idx = int(np.argmin(np.abs(arr - float(y))))
        snapped_y = float(arr[idx])
        tick_value = float(idx)
        snap_distance = abs(snapped_y - float(y))
        snap_confidence = float(np.clip(1.0 - (snap_distance / 8.0), 0.0, 1.0))
        return snapped_y, tick_value, snap_confidence

    @staticmethod
    def detect_bubble_boundaries(
        gray: np.ndarray,
        x: int,
        roi: RectROI | None,
        x_half: int | None = None,
    ) -> dict:
        """Auto-detect bubble top and bottom boundaries in a tube column.

        Uses intensity profile analysis: the bubble region is brighter
        (lighter) than the surrounding liquid.  We find the two sharpest
        dark-to-light and light-to-dark transitions along the vertical axis.
        """
        h, w = gray.shape[:2]
        if x_half is None:
            x_half = max(8, int(w * 0.008))
        x_min = max(0, x - x_half)
        x_max = min(w - 1, x + x_half)

        y_min, y_max = 0, h - 1
        if roi is not None:
            y_min = max(0, roi.y)
            y_max = min(h - 1, roi.y + roi.height)
        if y_max - y_min < 20:
            return {"detected": False, "reason": "ROI too small"}

        strip = gray[y_min:y_max + 1, x_min:x_max + 1]
        if strip.shape[0] < 20:
            return {"detected": False, "reason": "Strip too short"}

        ksize = max(3, (strip.shape[0] // 60) * 2 + 1)
        smoothed = cv2.GaussianBlur(strip, (ksize, ksize), 0)
        profile = smoothed.mean(axis=1).astype(np.float32)
        grad = np.diff(profile)

        if grad.size < 10:
            return {"detected": False, "reason": "Insufficient gradient data"}

        top_idx = int(np.argmax(grad))
        bottom_idx = int(np.argmin(grad))

        if top_idx >= bottom_idx:
            top_idx, bottom_idx = bottom_idx, top_idx

        bubble_top_y = y_min + top_idx
        bubble_bottom_y = y_min + bottom_idx

        top_strength = abs(float(grad[top_idx]))
        bottom_strength = abs(float(grad[bottom_idx if bottom_idx < len(grad) else -1]))
        grad_std = float(np.std(grad))
        confidence = float(np.clip(
            min(top_strength, bottom_strength) / max(grad_std * 3.0, 1.0), 0.0, 1.0
        ))

        return {
            "detected": True,
            "bubble_top": {"x": float(x), "y": float(bubble_top_y)},
            "bubble_bottom": {"x": float(x), "y": float(bubble_bottom_y)},
            "pixel_span": float(bubble_bottom_y - bubble_top_y),
            "confidence": round(confidence, 3),
            "profile_length": int(len(profile)),
        }

    def measure(self, req: MeasureRequest, frame_bgr: np.ndarray) -> ReadingRecord:
        roi = req.roi
        if roi is not None:
            if not self._in_roi(req.top_point, roi) or not self._in_roi(req.bottom_point, roi):
                raise ValueError("Top/Bottom points must stay inside ROI.")

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        top_refined, conf_top = self._refine_y_with_edge(gray, req.top_point, roi)
        bottom_refined, conf_bottom = self._refine_y_with_edge(gray, req.bottom_point, roi)

        ticks = self._detect_tick_lines(gray, int(round(req.top_point.x)), roi)
        top_y_snap, top_tick, conf_snap_top = self._snap_to_tick(top_refined.y, ticks)
        bottom_y_snap, bottom_tick, conf_snap_bottom = self._snap_to_tick(bottom_refined.y, ticks)

        top_point = Point2D(x=top_refined.x, y=top_y_snap)
        bottom_point = Point2D(x=bottom_refined.x, y=bottom_y_snap)
        pixel_delta = abs(bottom_point.y - top_point.y)
        tick_delta = abs(bottom_tick - top_tick)
        confidence = float(
            np.clip((conf_top + conf_bottom + conf_snap_top + conf_snap_bottom) / 4.0, 0.0, 1.0)
        )

        if confidence < CONFIDENCE_REJECT_THRESHOLD:
            raise ValueError(
                f"Measurement rejected: confidence {confidence:.0%} is below "
                f"minimum threshold {CONFIDENCE_REJECT_THRESHOLD:.0%}. "
                f"Adjust camera position or lighting and retry."
            )

        if confidence < CONFIDENCE_WARN_THRESHOLD:
            confidence_level = "low"
        elif confidence < 0.70:
            confidence_level = "medium"
        else:
            confidence_level = "high"

        record = ReadingRecord(
            reading_id=uuid.uuid4().hex,
            camera_id=req.camera_id,
            column_id=req.column_id,
            top_tick=top_tick,
            bottom_tick=bottom_tick,
            tick_delta=tick_delta,
            pixel_delta=float(pixel_delta),
            top_point=top_point,
            bottom_point=bottom_point,
            confidence=confidence,
            measured_at=datetime.now(timezone.utc),
        )
        record._confidence_level = confidence_level
        record._tick_count = len(ticks)
        return record
