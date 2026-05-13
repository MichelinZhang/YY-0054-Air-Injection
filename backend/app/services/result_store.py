from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.config import IS_PRODUCTION, MOCK_SAVE_ALLOWED
from app.errors import AppError, ErrorCode
from app.models import ReadingRecord, SaveResultRequest, SaveResultResponse
from app.services.audit_logger import AuditEvent, audit_logger
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
            label = f"C{item.column_id}: tick \u0394 {item.tick_delta:.1f}"
            text_origin = (p2[0] + 10, max(24, p2[1] - 10))
            cv2.putText(
                canvas, label, text_origin,
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
            )
        return canvas

    @staticmethod
    def _compute_checksum(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        dir_path = path.parent
        fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def validate_save_request(
        self,
        payload: SaveResultRequest,
        latest_frames: dict[str, FramePacket],
        *,
        using_mock: bool = False,
    ) -> None:
        if not payload.measurements:
            raise AppError(422, ErrorCode.SAVE_NO_MEASUREMENTS, "No measurements to save")

        if IS_PRODUCTION and not payload.operator:
            raise AppError(422, ErrorCode.SAVE_OPERATOR_REQUIRED, "Operator identity is required in production mode")

        if using_mock and not MOCK_SAVE_ALLOWED:
            audit_logger.log(
                AuditEvent.SAVE_BLOCKED,
                operator=payload.operator,
                details={"reason": "mock_in_production", "measurement_count": len(payload.measurements)},
            )
            raise AppError(403, ErrorCode.SAVE_MOCK_BLOCKED, "Saving results from mock cameras is blocked in production")

        required_camera_ids = {m.camera_id for m in payload.measurements}
        missing_frames = required_camera_ids - set(latest_frames.keys())
        if missing_frames:
            raise AppError(
                409, ErrorCode.SAVE_FRAME_MISSING,
                "Frame data missing for cameras referenced in measurements",
                detail=f"Missing: {', '.join(sorted(missing_frames))}",
            )

    def save(
        self,
        payload: SaveResultRequest,
        latest_frames: dict[str, FramePacket],
        *,
        using_mock: bool = False,
        session_id: str | None = None,
    ) -> SaveResultResponse:
        self.validate_save_request(payload, latest_frames, using_mock=using_mock)

        now = datetime.now()
        record_id = now.strftime("%Y%m%d_%H%M%S_") + now.strftime("%f")
        out_dir = self.base_dir / record_id
        out_dir.mkdir(parents=True, exist_ok=True)

        image_paths: list[str] = []
        disk_image_paths: list[str] = []
        image_checksums: dict[str, str] = {}
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
            img_bytes = image_path.read_bytes()
            image_checksums[camera_id] = self._compute_checksum(img_bytes)
            disk_image_paths.append(str(image_path))
            image_paths.append(f"/results/{record_id}/{camera_id}.png")

        json_path = out_dir / "result.json"
        serializable = {
            "record_id": record_id,
            "created_at": now.isoformat(timespec="seconds"),
            "operator": payload.operator,
            "note": payload.note,
            "session_id": session_id,
            "using_mock": using_mock,
            "measurements": [item.model_dump(mode="json") for item in payload.measurements],
            "image_paths": image_paths,
            "disk_image_paths": disk_image_paths,
            "image_checksums": image_checksums,
        }
        json_content = json.dumps(serializable, ensure_ascii=False, indent=2)
        serializable["data_checksum"] = self._compute_checksum(json_content.encode("utf-8"))
        json_content_final = json.dumps(serializable, ensure_ascii=False, indent=2)
        self._atomic_write_text(json_path, json_content_final)

        audit_logger.log(
            AuditEvent.RESULT_SAVED,
            operator=payload.operator,
            session_id=session_id,
            details={
                "record_id": record_id,
                "measurement_count": len(payload.measurements),
                "using_mock": using_mock,
            },
        )

        return SaveResultResponse(
            record_id=record_id,
            json_path=str(json_path),
            image_paths=image_paths,
        )

    def verify_record_integrity(self, record_id: str) -> dict[str, bool]:
        record_dir = self.base_dir / record_id
        json_path = record_dir / "result.json"
        if not json_path.exists():
            return {"exists": False}
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"json_valid": False}

        results: dict[str, bool] = {"json_valid": True}
        for camera_id, expected_hash in data.get("image_checksums", {}).items():
            img_path = record_dir / f"{camera_id}.png"
            if not img_path.exists():
                results[f"image_{camera_id}"] = False
                continue
            actual_hash = self._compute_checksum(img_path.read_bytes())
            results[f"image_{camera_id}"] = actual_hash == expected_hash
        return results

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
                audit_logger.log_error(
                    ErrorCode.SAVE_INTEGRITY_ERROR.value,
                    f"Corrupted result.json in {folder.name}",
                    details={"record_dir": folder.name},
                )
                continue
        return records
