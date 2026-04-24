from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Point2D(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class RectROI(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CameraInfo(BaseModel):
    camera_id: str
    serial_number: str
    model_name: str
    transport: str
    online: bool = True
    sdk_index: int | None = None


class CameraConfig(BaseModel):
    camera_id: str
    exposure_time_us: float | None = None
    gain: float | None = None
    frame_rate: float | None = None


class FloatRange(BaseModel):
    min: float
    max: float


class CameraSettings(BaseModel):
    camera_id: str
    mode: Literal["real", "mock"]
    exposure_time_us: float | None = None
    gain: float | None = None
    exposure_range: FloatRange | None = None
    gain_range: FloatRange | None = None


class CameraSettingsUpdate(BaseModel):
    exposure_time_us: float | None = None
    gain: float | None = None


class LightIOConfig(BaseModel):
    line_selector: str = "Line1"
    line_source: str = "ExposureStartActive"
    strobe_duration_us: int = 0
    strobe_delay_us: int = 0
    strobe_pre_delay_us: int = 0


class ColumnROIConfig(BaseModel):
    camera_id: str
    column_id: int = Field(ge=1, le=4)
    roi: RectROI


class OpenSessionRequest(BaseModel):
    selection_mode: Literal["auto", "manual"] = "auto"
    selected_camera_ids: list[str] = Field(default_factory=list)
    max_camera_count: int = Field(default=2, ge=1, le=2)
    force_mock: bool = False
    use_mock_when_unavailable: bool = True
    light_config: LightIOConfig = Field(default_factory=LightIOConfig)


class OpenSessionResponse(BaseModel):
    session_id: str
    active_camera_ids: list[str]
    column_camera_map: dict[int, str]
    using_mock: bool
    detected_real_camera_count: int = Field(ge=0)
    applied_selection_mode: Literal["auto", "manual"]


class SessionState(BaseModel):
    session_id: str | None
    active_camera_ids: list[str]
    column_camera_map: dict[int, str]
    using_mock: bool


class MeasureRequest(BaseModel):
    camera_id: str
    column_id: int = Field(ge=1, le=4)
    top_point: Point2D
    bottom_point: Point2D
    roi: RectROI | None = None


class ReadingRecord(BaseModel):
    reading_id: str
    camera_id: str
    column_id: int
    top_tick: float
    bottom_tick: float
    tick_delta: float
    pixel_delta: float
    top_point: Point2D
    bottom_point: Point2D
    confidence: float = Field(ge=0, le=1)
    measured_at: datetime


class SaveResultRequest(BaseModel):
    measurements: list[ReadingRecord]
    operator: str | None = None
    note: str | None = None


class SaveResultResponse(BaseModel):
    record_id: str
    json_path: str
    image_paths: list[str]


class ErrorResponse(BaseModel):
    detail: str


class LightResponse(BaseModel):
    camera_id: str
    light_on: bool
    mode: Literal["real", "mock"]
