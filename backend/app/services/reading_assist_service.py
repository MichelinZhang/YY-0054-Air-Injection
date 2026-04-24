from __future__ import annotations

import uuid
from datetime import datetime, timezone

import cv2
import numpy as np

from app.models import MeasureRequest, Point2D, ReadingRecord, RectROI


class ReadingAssistService:
    @staticmethod
    def _in_roi(point: Point2D, roi: RectROI) -> bool:
        return roi.x <= point.x <= roi.x + roi.width and roi.y <= point.y <= roi.y + roi.height

    @staticmethod
    def _refine_y_with_edge(
        gray: np.ndarray,
        point: Point2D,
        roi: RectROI | None,
        radius: int = 16,
        x_half_span: int = 3,
    ) -> tuple[Point2D, float]:
        h, w = gray.shape[:2]
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
        confidence = float(np.clip(grad[idx] / 55.0, 0.0, 1.0))
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

        x_min = max(0, int(x) - 18)
        x_max = min(w - 1, int(x) + 18)
        strip = gray[y_min : y_max + 1, x_min : x_max + 1]
        if strip.shape[0] < 4:
            return []

        strip = cv2.GaussianBlur(strip, (3, 3), 0)
        row_signal = strip.mean(axis=1).astype(np.float32)
        grad = np.abs(np.diff(row_signal))
        if grad.size < 3:
            return []

        threshold = max(float(np.percentile(grad, 90)), float(grad.mean() + 0.8 * grad.std()))
        candidate_rows = np.where(grad >= threshold)[0] + y_min
        grouped = self._group_rows(candidate_rows)
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

        return ReadingRecord(
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
