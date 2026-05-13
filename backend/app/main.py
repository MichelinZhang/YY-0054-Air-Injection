from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import Role, UserContext, get_current_user, require_role, verify_ws_token
from app.config import (
    AUDIT_LOG_DIR,
    AUTH_ENABLED,
    CORS_ALLOWED_ORIGINS,
    DEFAULT_WS_FPS,
    ENV,
    FRONTEND_DIST_DIR,
    IS_PRODUCTION,
    MOCK_SAVE_ALLOWED,
    RESULTS_DIR,
)
from app.errors import AppError, ErrorCode
from app.models import (
    CameraSettings,
    CameraSettingsUpdate,
    MeasureRequest,
    OpenSessionRequest,
    OpenSessionResponse,
    SaveResultRequest,
    SaveResultResponse,
    SessionState,
)
from app.services.audit_logger import AuditEvent, audit_logger
from app.services.light_controller import LightController
from app.services.calibration_service import calibration_service
from app.services.reading_assist_service import ReadingAssistService
from app.services.result_store import ResultStore
from app.services.session_manager import SessionManager
from app.utils.image_utils import encode_jpeg_base64


app = FastAPI(
    title="Hikvision Air Column Assistant",
    version="0.2.0",
    description="YY 0054-2010 blood dialysis air injection test support system (medical device compliant).",
)

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/results", StaticFiles(directory=RESULTS_DIR), name="results")

session_manager = SessionManager()
light_controller = LightController(session_manager)
reading_service = ReadingAssistService()
result_store = ResultStore(RESULTS_DIR)


# --- Health & Info ---

@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "env": ENV,
        "auth_enabled": AUTH_ENABLED,
        "mock_save_allowed": MOCK_SAVE_ALLOWED,
        "sdk_available": session_manager.sdk_available,
        "sdk_error": session_manager.sdk_error,
    }


# --- Camera Enumeration ---

@app.get("/api/cameras")
def list_cameras(user: UserContext = Depends(get_current_user)) -> dict:
    cameras, detected_real_count = session_manager.list_cameras_with_meta()
    return {
        "items": [c.model_dump() for c in cameras],
        "detected_real_camera_count": detected_real_count,
        "sdk_available": session_manager.sdk_available,
        "sdk_error": session_manager.sdk_error,
    }


# --- Session Management ---

@app.post("/api/session/open", response_model=OpenSessionResponse)
def open_session(
    payload: OpenSessionRequest,
    user: UserContext = Depends(get_current_user),
) -> OpenSessionResponse:
    if IS_PRODUCTION and payload.force_mock:
        raise AppError(403, ErrorCode.AUTH_PERMISSION_DENIED, "Force mock is not allowed in production")

    try:
        result = session_manager.open_session(payload)
    except Exception as exc:
        audit_logger.log_error(
            ErrorCode.SESSION_OPEN_FAILED.value,
            str(exc),
            operator=user.username,
        )
        raise AppError(400, ErrorCode.SESSION_OPEN_FAILED, "Failed to open session", detail=str(exc)) from exc

    audit_logger.log(
        AuditEvent.SESSION_OPENED,
        operator=user.username,
        session_id=result.session_id,
        details={
            "using_mock": result.using_mock,
            "camera_count": len(result.active_camera_ids),
            "force_mock": payload.force_mock,
        },
    )
    if result.using_mock:
        audit_logger.log(
            AuditEvent.MOCK_MODE_ACTIVATED,
            operator=user.username,
            session_id=result.session_id,
            details={"force_mock": payload.force_mock},
        )
    return result


@app.post("/api/session/close", response_model=SessionState)
def close_session(user: UserContext = Depends(get_current_user)) -> SessionState:
    old_session_id = session_manager._session_id
    session_manager.close_session()
    audit_logger.log(
        AuditEvent.SESSION_CLOSED,
        operator=user.username,
        session_id=old_session_id,
    )
    return session_manager.get_state()


@app.get("/api/session/state", response_model=SessionState)
def session_state(user: UserContext = Depends(get_current_user)) -> SessionState:
    return session_manager.get_state()


# --- Light Control ---

@app.post("/api/light/{camera_id}/on")
def light_on(camera_id: str, user: UserContext = Depends(get_current_user)) -> dict:
    try:
        res = light_controller.set_light(camera_id, True)
    except KeyError as exc:
        raise AppError(404, ErrorCode.CAMERA_NOT_ACTIVE, str(exc)) from exc
    except Exception as exc:
        raise AppError(400, ErrorCode.CAMERA_SETTINGS_FAILED, str(exc)) from exc

    audit_logger.log(
        AuditEvent.LIGHT_TOGGLED,
        operator=user.username,
        session_id=session_manager._session_id,
        details={"camera_id": camera_id, "light_on": True},
    )
    return res.model_dump()


@app.post("/api/light/{camera_id}/off")
def light_off(camera_id: str, user: UserContext = Depends(get_current_user)) -> dict:
    try:
        res = light_controller.set_light(camera_id, False)
    except KeyError as exc:
        raise AppError(404, ErrorCode.CAMERA_NOT_ACTIVE, str(exc)) from exc
    except Exception as exc:
        raise AppError(400, ErrorCode.CAMERA_SETTINGS_FAILED, str(exc)) from exc

    audit_logger.log(
        AuditEvent.LIGHT_TOGGLED,
        operator=user.username,
        session_id=session_manager._session_id,
        details={"camera_id": camera_id, "light_on": False},
    )
    return res.model_dump()


# --- Deprecated Calibration ---

@app.get("/api/calibration")
def get_calibration(user: UserContext = Depends(get_current_user)) -> dict:
    return calibration_service.profile.to_dict()


@app.post("/api/calibration")
def update_calibration(payload: dict, user: UserContext = Depends(require_role(Role.ENGINEER))) -> dict:
    try:
        profile = calibration_service.update_profile(payload)
    except (ValueError, TypeError) as exc:
        raise AppError(400, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    audit_logger.log(
        AuditEvent.CAMERA_SETTINGS_CHANGED,
        operator=user.username,
        details={"action": "calibration_updated", "profile": profile.to_dict()},
    )
    return profile.to_dict()


@app.post("/api/calibration/from-reference")
def calibrate_from_reference(payload: dict, user: UserContext = Depends(require_role(Role.ENGINEER))) -> dict:
    try:
        profile = calibration_service.calibrate_from_reference(
            known_tick_count=int(payload["known_tick_count"]),
            known_length_mm=float(payload["known_length_mm"]),
            measured_pixel_span=payload.get("measured_pixel_span"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise AppError(400, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    return profile.to_dict()


# --- Measurement ---

@app.post("/api/measure")
def measure(payload: MeasureRequest, user: UserContext = Depends(get_current_user)) -> dict:
    frame = session_manager.get_latest_frame(payload.camera_id)
    if frame is None:
        raise AppError(409, ErrorCode.MEASURE_NO_FRAME, "No frame available from selected camera.")
    try:
        result = reading_service.measure(payload, frame.image_bgr)
    except ValueError as exc:
        raise AppError(400, ErrorCode.MEASURE_INVALID_POINTS, str(exc)) from exc

    physical = calibration_service.convert_reading(result.tick_delta, result.pixel_delta)
    confidence_level = getattr(result, "_confidence_level", "unknown")
    tick_count = getattr(result, "_tick_count", 0)

    audit_logger.log(
        AuditEvent.MEASUREMENT_TAKEN,
        operator=user.username,
        session_id=session_manager._session_id,
        details={
            "camera_id": payload.camera_id,
            "column_id": payload.column_id,
            "tick_delta": result.tick_delta,
            "confidence": result.confidence,
            "confidence_level": confidence_level,
            "volume_ml": physical.get("volume_ml"),
        },
    )
    response = result.model_dump(mode="json")
    response["physical"] = physical
    response["confidence_level"] = confidence_level
    response["detected_tick_count"] = tick_count
    return response


# --- Auto Bubble Detection ---

@app.post("/api/detect-bubble")
def detect_bubble(payload: dict, user: UserContext = Depends(get_current_user)) -> dict:
    camera_id = payload.get("camera_id")
    column_id = payload.get("column_id", 1)
    x = payload.get("x")
    if not camera_id or x is None:
        raise AppError(400, ErrorCode.VALIDATION_ERROR, "camera_id and x are required")

    frame = session_manager.get_latest_frame(camera_id)
    if frame is None:
        raise AppError(409, ErrorCode.MEASURE_NO_FRAME, "No frame available")

    import cv2
    from app.models import RectROI
    gray = cv2.cvtColor(frame.image_bgr, cv2.COLOR_BGR2GRAY)
    roi_data = payload.get("roi")
    roi = RectROI(**roi_data) if roi_data else None

    result = reading_service.detect_bubble_boundaries(gray, int(x), roi)
    result["camera_id"] = camera_id
    result["column_id"] = column_id
    return result


# --- Camera Settings ---

@app.get("/api/camera/{camera_id}/settings", response_model=CameraSettings)
def get_camera_settings(camera_id: str, user: UserContext = Depends(get_current_user)) -> CameraSettings:
    try:
        data = session_manager.get_camera_settings(camera_id)
        return CameraSettings.model_validate(data)
    except KeyError as exc:
        raise AppError(404, ErrorCode.CAMERA_NOT_ACTIVE, str(exc)) from exc
    except Exception as exc:
        raise AppError(400, ErrorCode.CAMERA_SETTINGS_FAILED, str(exc)) from exc


@app.post("/api/camera/{camera_id}/settings", response_model=CameraSettings)
def set_camera_settings(
    camera_id: str,
    payload: CameraSettingsUpdate,
    user: UserContext = Depends(get_current_user),
) -> CameraSettings:
    if payload.exposure_time_us is None and payload.gain is None:
        raise AppError(400, ErrorCode.CAMERA_SETTINGS_FAILED, "At least one setting must be provided.")
    try:
        data = session_manager.set_camera_settings(
            camera_id,
            exposure_time_us=payload.exposure_time_us,
            gain=payload.gain,
        )
    except KeyError as exc:
        raise AppError(404, ErrorCode.CAMERA_NOT_ACTIVE, str(exc)) from exc
    except Exception as exc:
        raise AppError(400, ErrorCode.CAMERA_SETTINGS_FAILED, str(exc)) from exc

    audit_logger.log(
        AuditEvent.CAMERA_SETTINGS_CHANGED,
        operator=user.username,
        session_id=session_manager._session_id,
        details={
            "camera_id": camera_id,
            "exposure_time_us": payload.exposure_time_us,
            "gain": payload.gain,
        },
    )
    return CameraSettings.model_validate(data)


# --- Result Save & History ---

@app.post("/api/result/save", response_model=SaveResultResponse)
def save_result(payload: SaveResultRequest, user: UserContext = Depends(get_current_user)) -> SaveResultResponse:
    frames = session_manager.get_all_latest_frames()
    return result_store.save(
        payload,
        frames,
        using_mock=session_manager._using_mock,
        session_id=session_manager._session_id,
    )


@app.get("/api/results")
def get_results(user: UserContext = Depends(get_current_user)) -> dict:
    return {"items": result_store.list_records()}


@app.get("/api/results/{record_id}/verify")
def verify_result(record_id: str, user: UserContext = Depends(get_current_user)) -> dict:
    return {"record_id": record_id, "integrity": result_store.verify_record_integrity(record_id)}


# --- WebSocket Preview ---

@app.websocket("/ws/preview")
async def ws_preview(websocket: WebSocket, camera_id: str, token: str | None = None) -> None:
    ws_user = verify_ws_token(token)
    await websocket.accept()
    try:
        while True:
            frame = session_manager.get_latest_frame(camera_id)
            status = session_manager.camera_status(camera_id)
            if frame is None:
                await websocket.send_json({"camera_id": camera_id, "status": "no_frame", **status})
                await asyncio.sleep(0.2)
                continue
            await websocket.send_json({
                "camera_id": camera_id,
                "status": "ok",
                "width": int(frame.image_bgr.shape[1]),
                "height": int(frame.image_bgr.shape[0]),
                "timestamp": frame.timestamp.isoformat(),
                "frame_no": frame.frame_no,
                "lost_packets": frame.lost_packets,
                "exposure_time_us": frame.exposure_time_us,
                "gain": frame.gain,
                "jpeg_base64": encode_jpeg_base64(frame.image_bgr),
                **status,
            })
            await asyncio.sleep(1.0 / DEFAULT_WS_FPS)
    except KeyError:
        await websocket.send_json({"status": "error", "detail": f"Camera not active: {camera_id}"})
    except WebSocketDisconnect:
        return


# --- SPA Fallback ---

def _dist_file(path: str) -> Path | None:
    if not FRONTEND_DIST_DIR.exists():
        return None
    candidate = (FRONTEND_DIST_DIR / path).resolve()
    if FRONTEND_DIST_DIR.resolve() not in candidate.parents and candidate != FRONTEND_DIST_DIR.resolve():
        return None
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


@app.get("/")
def root():
    if FRONTEND_DIST_DIR.exists() and (FRONTEND_DIST_DIR / "index.html").exists():
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
    return {"message": "Backend is running. Frontend dist not found."}


@app.get("/{full_path:path}")
def spa_files(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    file_path = _dist_file(full_path)
    if file_path:
        return FileResponse(file_path)
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Frontend asset not found")
