from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models import (
    CameraInfo,
    LightIOConfig,
    OpenSessionRequest,
    OpenSessionResponse,
    SessionState,
)
from app.services.camera_adapter import (
    BaseCameraDevice,
    FramePacket,
    HikMvsCameraDevice,
    MockCameraDevice,
    MvsSdkContext,
    make_mock_camera_infos,
)


@dataclass
class CameraRuntime:
    info: CameraInfo
    device: BaseCameraDevice
    stop_event: threading.Event = field(default_factory=threading.Event)
    worker: threading.Thread | None = None
    latest_frame: FramePacket | None = None
    last_frame_ts: float = field(default_factory=time.time)
    fps: float = 0.0
    light_on: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionManager:
    def __init__(self) -> None:
        self.sdk = MvsSdkContext()
        self._session_id: str | None = None
        self._column_camera_map: dict[int, str] = {}
        self._using_mock = False
        self._light_cfg = LightIOConfig()
        self._runtimes: dict[str, CameraRuntime] = {}
        self._global_lock = threading.Lock()

    @property
    def sdk_available(self) -> bool:
        return self.sdk.available

    @property
    def sdk_error(self) -> str | None:
        return self.sdk.error

    def list_cameras(self) -> list[CameraInfo]:
        return self.list_cameras_with_meta()[0]

    def list_cameras_with_meta(self) -> tuple[list[CameraInfo], int]:
        cameras = self.sdk.enumerate_cameras() if self.sdk.available else []
        if cameras:
            return cameras, len(cameras)
        return make_mock_camera_infos(2), 0

    def get_state(self) -> SessionState:
        return SessionState(
            session_id=self._session_id,
            active_camera_ids=list(self._runtimes.keys()),
            column_camera_map=self._column_camera_map,
            using_mock=self._using_mock,
        )

    def _build_column_mapping(self, camera_ids: list[str]) -> dict[int, str]:
        if not camera_ids:
            return {}
        if len(camera_ids) == 1:
            return {1: camera_ids[0], 2: camera_ids[0], 3: camera_ids[0], 4: camera_ids[0]}
        return {1: camera_ids[0], 2: camera_ids[0], 3: camera_ids[1], 4: camera_ids[1]}

    @staticmethod
    def _is_gige_transport(transport: str) -> bool:
        return transport in {"GigE", "GenTL-GigE"}

    @classmethod
    def _sort_camera_candidates(cls, cameras: list[CameraInfo]) -> list[CameraInfo]:
        return sorted(
            cameras,
            key=lambda cam: (
                0 if cls._is_gige_transport(cam.transport) else 1,
                cam.camera_id,
            ),
        )

    def _stream_worker(self, runtime: CameraRuntime) -> None:
        while not runtime.stop_event.is_set():
            frame = runtime.device.grab_frame(timeout_ms=1000)
            if frame is None:
                time.sleep(0.01)
                continue

            now_ts = time.time()
            dt = max(now_ts - runtime.last_frame_ts, 1e-6)
            runtime.last_frame_ts = now_ts
            runtime.fps = 0.86 * runtime.fps + 0.14 * (1.0 / dt) if runtime.fps else (1.0 / dt)
            with runtime.lock:
                runtime.latest_frame = frame

    @staticmethod
    def _mock_visible_columns(mock_index: int, total: int) -> list[int]:
        if total <= 1:
            return [1, 2, 3, 4]
        return [1, 2] if mock_index == 0 else [3, 4]

    def open_session(self, req: OpenSessionRequest) -> OpenSessionResponse:
        with self._global_lock:
            self.close_session()

            max_count = max(1, min(req.max_camera_count, 2))
            all_real = [] if req.force_mock else (self.sdk.enumerate_cameras() if self.sdk.available else [])
            sorted_real = self._sort_camera_candidates(all_real)
            detected_real_count = len(sorted_real)
            applied_selection_mode = req.selection_mode
            selected_real: list[CameraInfo] = []
            if sorted_real:
                if req.selection_mode == "manual" and req.selected_camera_ids:
                    by_id = {x.camera_id: x for x in sorted_real}
                    selected_real = [by_id[camera_id] for camera_id in req.selected_camera_ids if camera_id in by_id]
                else:
                    selected_real = sorted_real[:max_count]

            selected_real = selected_real[:max_count]
            runtimes: dict[str, CameraRuntime] = {}
            using_mock = False

            if req.force_mock:
                using_mock = True
                mock_infos = make_mock_camera_infos(max_count)
                for idx, info in enumerate(mock_infos):
                    device = MockCameraDevice(
                        info.camera_id,
                        visible_columns=self._mock_visible_columns(idx, len(mock_infos)),
                    )
                    device.open()
                    device.start_grabbing()
                    runtime = CameraRuntime(info=info, device=device)
                    runtime.worker = threading.Thread(
                        target=self._stream_worker,
                        args=(runtime,),
                        name=f"stream-{info.camera_id}",
                        daemon=True,
                    )
                    runtime.worker.start()
                    runtimes[info.camera_id] = runtime
            elif selected_real:
                for info in selected_real:
                    device = HikMvsCameraDevice(self.sdk, info)
                    device.open()
                    device.start_grabbing()
                    runtime = CameraRuntime(info=info, device=device)
                    runtime.worker = threading.Thread(
                        target=self._stream_worker,
                        args=(runtime,),
                        name=f"stream-{info.camera_id}",
                        daemon=True,
                    )
                    runtime.worker.start()
                    runtimes[info.camera_id] = runtime
            else:
                if not req.use_mock_when_unavailable:
                    raise RuntimeError(
                        "No real camera available, and mock fallback is disabled."
                    )
                using_mock = True
                if req.selection_mode == "auto":
                    mock_count = 1
                else:
                    mock_count = (
                        max(1, min(max_count, len(req.selected_camera_ids)))
                        if req.selected_camera_ids
                        else 1
                    )
                mock_infos = make_mock_camera_infos(mock_count)
                for idx, info in enumerate(mock_infos):
                    device = MockCameraDevice(
                        info.camera_id,
                        visible_columns=self._mock_visible_columns(idx, len(mock_infos)),
                    )
                    device.open()
                    device.start_grabbing()
                    runtime = CameraRuntime(info=info, device=device)
                    runtime.worker = threading.Thread(
                        target=self._stream_worker,
                        args=(runtime,),
                        name=f"stream-{info.camera_id}",
                        daemon=True,
                    )
                    runtime.worker.start()
                    runtimes[info.camera_id] = runtime

            self._runtimes = runtimes
            self._session_id = uuid.uuid4().hex
            self._using_mock = using_mock
            self._light_cfg = req.light_config
            active_ids = list(runtimes.keys())
            self._column_camera_map = self._build_column_mapping(active_ids)
            return OpenSessionResponse(
                session_id=self._session_id,
                active_camera_ids=active_ids,
                column_camera_map=self._column_camera_map,
                using_mock=using_mock,
                detected_real_camera_count=detected_real_count,
                applied_selection_mode=applied_selection_mode,
            )

    def close_session(self) -> None:
        for runtime in self._runtimes.values():
            runtime.stop_event.set()
            if runtime.worker and runtime.worker.is_alive():
                runtime.worker.join(timeout=1.2)
            try:
                runtime.device.stop_grabbing()
            finally:
                runtime.device.close()

        self._runtimes = {}
        self._session_id = None
        self._column_camera_map = {}
        self._using_mock = False

    def set_light(self, camera_id: str, on: bool) -> tuple[bool, str]:
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            raise KeyError(f"Camera not active: {camera_id}")
        runtime.device.set_light(on, self._light_cfg)
        runtime.light_on = on
        return runtime.device.is_mock, camera_id

    def get_camera_settings(self, camera_id: str) -> dict:
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            raise KeyError(f"Camera not active: {camera_id}")
        settings = runtime.device.get_settings()
        settings["camera_id"] = camera_id
        return settings

    def set_camera_settings(
        self,
        camera_id: str,
        exposure_time_us: float | None = None,
        gain: float | None = None,
    ) -> dict:
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            raise KeyError(f"Camera not active: {camera_id}")
        settings = runtime.device.set_settings(exposure_time_us=exposure_time_us, gain=gain)
        settings["camera_id"] = camera_id
        return settings

    def get_latest_frame(self, camera_id: str) -> FramePacket | None:
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            return None
        with runtime.lock:
            frame = runtime.latest_frame
            return frame

    def get_all_latest_frames(self) -> dict[str, FramePacket]:
        frames: dict[str, FramePacket] = {}
        for camera_id in list(self._runtimes.keys()):
            frame = self.get_latest_frame(camera_id)
            if frame is not None:
                frames[camera_id] = frame
        return frames

    def camera_status(self, camera_id: str) -> dict[str, float | bool | str]:
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            raise KeyError(f"Camera not active: {camera_id}")
        frame = self.get_latest_frame(camera_id)
        return {
            "camera_id": camera_id,
            "fps": round(runtime.fps, 2),
            "light_on": runtime.light_on,
            "has_frame": frame is not None,
            "last_frame_at": frame.timestamp.isoformat() if frame else None,
            "using_mock": runtime.device.is_mock,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
