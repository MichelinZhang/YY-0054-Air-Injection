from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import DEFAULT_WS_FPS, FRONTEND_DIST_DIR, RESULTS_DIR
from app.models import (
    CameraSettings,
    CameraSettingsUpdate,
    ErrorResponse,
    MeasureRequest,
    OpenSessionRequest,
    OpenSessionResponse,
    SaveResultRequest,
    SaveResultResponse,
    SessionState,
)
from app.services.light_controller import LightController
from app.services.reading_assist_service import ReadingAssistService
from app.services.result_store import ResultStore
from app.services.session_manager import SessionManager
from app.utils.image_utils import encode_jpeg_base64


app = FastAPI(
    title="Hikvision Air Column Assistant",
    version="0.1.0",
    description="YY 0054-2010 blood dialysis air injection test support system.",
)

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/results", StaticFiles(directory=RESULTS_DIR), name="results")

session_manager = SessionManager()
light_controller = LightController(session_manager)
reading_service = ReadingAssistService()
result_store = ResultStore(RESULTS_DIR)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "sdk_available": session_manager.sdk_available, "sdk_error": session_manager.sdk_error}


@app.get("/api/cameras")
def list_cameras() -> dict:
    cameras, detected_real_count = session_manager.list_cameras_with_meta()
    return {
        "items": [c.model_dump() for c in cameras],
        "detected_real_camera_count": detected_real_count,
        "sdk_available": session_manager.sdk_available,
        "sdk_error": session_manager.sdk_error,
    }


@app.post(
    "/api/session/open",
    response_model=OpenSessionResponse,
    responses={400: {"model": ErrorResponse}},
)
def open_session(payload: OpenSessionRequest) -> OpenSessionResponse:
    try:
        return session_manager.open_session(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/session/close", response_model=SessionState)
def close_session() -> SessionState:
    session_manager.close_session()
    return session_manager.get_state()


@app.get("/api/session/state", response_model=SessionState)
def session_state() -> SessionState:
    return session_manager.get_state()


@app.post("/api/light/{camera_id}/on")
def light_on(camera_id: str) -> dict:
    try:
        res = light_controller.set_light(camera_id, True)
        return res.model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/light/{camera_id}/off")
def light_off(camera_id: str) -> dict:
    try:
        res = light_controller.set_light(camera_id, False)
        return res.model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/calibration")
def calibrate_disabled() -> dict:
    raise HTTPException(status_code=410, detail="Calibration mode is removed. Use reading-assist measure flow.")


@app.post("/api/measure")
def measure(payload: MeasureRequest) -> dict:
    frame = session_manager.get_latest_frame(payload.camera_id)
    if frame is None:
        raise HTTPException(status_code=409, detail="No frame available from selected camera.")
    try:
        result = reading_service.measure(payload, frame.image_bgr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.get("/api/camera/{camera_id}/settings", response_model=CameraSettings)
def get_camera_settings(camera_id: str) -> CameraSettings:
    try:
        data = session_manager.get_camera_settings(camera_id)
        return CameraSettings.model_validate(data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/camera/{camera_id}/settings", response_model=CameraSettings)
def set_camera_settings(camera_id: str, payload: CameraSettingsUpdate) -> CameraSettings:
    if payload.exposure_time_us is None and payload.gain is None:
        raise HTTPException(status_code=400, detail="At least one setting must be provided.")
    try:
        data = session_manager.set_camera_settings(
            camera_id,
            exposure_time_us=payload.exposure_time_us,
            gain=payload.gain,
        )
        return CameraSettings.model_validate(data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/result/save", response_model=SaveResultResponse)
def save_result(payload: SaveResultRequest) -> SaveResultResponse:
    frames = session_manager.get_all_latest_frames()
    return result_store.save(payload, frames)


@app.get("/api/results")
def get_results() -> dict:
    return {"items": result_store.list_records()}


@app.websocket("/ws/preview")
async def ws_preview(websocket: WebSocket, camera_id: str) -> None:
    await websocket.accept()
    try:
        while True:
            frame = session_manager.get_latest_frame(camera_id)
            status = session_manager.camera_status(camera_id)
            if frame is None:
                await websocket.send_json(
                    {
                        "camera_id": camera_id,
                        "status": "no_frame",
                        **status,
                    }
                )
                await asyncio.sleep(0.2)
                continue
            await websocket.send_json(
                {
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
                }
            )
            await asyncio.sleep(1.0 / DEFAULT_WS_FPS)
    except KeyError:
        await websocket.send_json({"status": "error", "detail": f"Camera not active: {camera_id}"})
    except WebSocketDisconnect:
        return


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
    return {
        "message": "Backend is running. Frontend dist not found.",
        "hint": "Build frontend and place output in frontend/dist.",
    }


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
