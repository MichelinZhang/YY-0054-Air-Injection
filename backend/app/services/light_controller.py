from __future__ import annotations

from app.models import LightResponse
from app.services.session_manager import SessionManager


class LightController:
    def __init__(self, session_manager: SessionManager) -> None:
        self.session_manager = session_manager

    def set_light(self, camera_id: str, on: bool) -> LightResponse:
        is_mock, _ = self.session_manager.set_light(camera_id, on)
        return LightResponse(
            camera_id=camera_id,
            light_on=on,
            mode="mock" if is_mock else "real",
        )

