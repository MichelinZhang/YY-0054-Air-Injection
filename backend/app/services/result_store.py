from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.models import ReadingRecord, SaveResultRequest, SaveResultResponse
from app.services.camera_adapter import FramePacket


@dataclass
class StoredRecord:
    record_id: str
    created_at: str
    operator: str | None
    note: str | None
    measurement_count: int
    json_path: str
    image_paths: list[str]


class ResultStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _draw_measurements(image: np.ndarray, records: list[ReadingRecord]) -> np.ndarray:
        canvas = image.copy()
        for item in records:
            p1 = (int(round(item.top_point.x)), int(round(item.top_point.y)))
            p2 = (int(round(item.bottom_point.x)), int(round(item.bottom_point.y)))
            color = (56, 214, 255)
            cv2.line(canvas, p1, p2, color, 2, cv2.LINE_AA)
            cv2.circle(canvas, p1, 6, (255, 128, 95), -1, cv2.LINE_AA)
            cv2.circle(canvas, p2, 6, (95, 238, 171), -1, cv2.LINE_AA)
            label = f"C{item.column_id}: tick Δ {item.tick_delta:.1f}"
            text_origin = (p2[0] + 10, max(24, p2[1] - 10))
            cv2.putText(
                canvas,
                label,
                text_origin,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        return canvas

    def save(
        self,
        payload: SaveResultRequest,
        latest_frames: dict[str, FramePacket],
    ) -> SaveResultResponse:
        now = datetime.now()
        record_id = now.strftime("%Y%m%d_%H%M%S_") + now.strftime("%f")
        out_dir = self.base_dir / record_id
        out_dir.mkdir(parents=True, exist_ok=True)

        image_paths: list[str] = []
        disk_image_paths: list[str] = []
        measurements_by_camera: dict[str, list[ReadingRecord]] = {}
        for item in payload.measurements:
            measurements_by_camera.setdefault(item.camera_id, []).append(item)

        for camera_id, records in measurements_by_camera.items():
            frame = latest_frames.get(camera_id)
            if frame is None:
                continue
            annotated = self._draw_measurements(frame.image_bgr, records)
            image_path = out_dir / f"{camera_id}.png"
            cv2.imwrite(str(image_path), annotated)
            disk_image_paths.append(str(image_path))
            image_paths.append(f"/results/{record_id}/{camera_id}.png")

        json_path = out_dir / "result.json"
        serializable = {
            "record_id": record_id,
            "created_at": now.isoformat(timespec="seconds"),
            "operator": payload.operator,
            "note": payload.note,
            "measurements": [item.model_dump(mode="json") for item in payload.measurements],
            "image_paths": image_paths,
            "disk_image_paths": disk_image_paths,
        }
        json_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        return SaveResultResponse(
            record_id=record_id,
            json_path=str(json_path),
            image_paths=image_paths,
        )

    def list_records(self) -> list[dict]:
        records: list[dict] = []
        for folder in sorted(self.base_dir.glob("*"), reverse=True):
            if not folder.is_dir():
                continue
            json_path = folder / "result.json"
            if not json_path.exists():
                continue
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                records.append(data)
            except json.JSONDecodeError:
                continue
        return records
