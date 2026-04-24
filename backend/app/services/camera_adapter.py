from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from ctypes import POINTER, byref, c_bool, c_ubyte, cast, memset, sizeof
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from app.models import CameraInfo, LightIOConfig
from app.services.mvs_loader import load_mvs_module


@dataclass
class FramePacket:
    image_bgr: np.ndarray
    timestamp: datetime
    frame_no: int
    lost_packets: int
    exposure_time_us: float | None = None
    gain: float | None = None


class BaseCameraDevice(ABC):
    camera_id: str

    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def start_grabbing(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop_grabbing(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def grab_frame(self, timeout_ms: int = 1000) -> FramePacket | None:
        raise NotImplementedError

    @abstractmethod
    def set_light(self, on: bool, cfg: LightIOConfig) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_settings(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def set_settings(self, exposure_time_us: float | None = None, gain: float | None = None) -> dict:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        raise NotImplementedError


class MvsSdkContext:
    def __init__(self) -> None:
        self._load = load_mvs_module()
        self.module = self._load.module
        self.available = self._load.available and self.module is not None
        self.error = self._load.error
        self._initialized = False
        if self.available:
            self.initialize()

    def initialize(self) -> None:
        if not self.available or self._initialized:
            return
        ret = self.module.MvCamera.MV_CC_Initialize()
        if ret != 0:
            self.available = False
            self.error = f"MV_CC_Initialize failed: 0x{ret:x}"
            return
        self._initialized = True

    def finalize(self) -> None:
        if self.available and self._initialized:
            self.module.MvCamera.MV_CC_Finalize()
            self._initialized = False

    def _decode_char(self, ctypes_char_array: Any) -> str:
        byte_str = memoryview(ctypes_char_array).tobytes()
        null_index = byte_str.find(b"\x00")
        if null_index != -1:
            byte_str = byte_str[:null_index]
        for enc in ("gbk", "utf-8", "latin-1"):
            try:
                return byte_str.decode(enc)
            except UnicodeDecodeError:
                continue
        return byte_str.decode("latin-1", errors="replace")

    def _transport_name(self, tlayer_type: int) -> str:
        m = self.module
        mapping = {
            int(getattr(m, "MV_GIGE_DEVICE", -1)): "GigE",
            int(getattr(m, "MV_USB_DEVICE", -2)): "USB3",
            int(getattr(m, "MV_GENTL_GIGE_DEVICE", -3)): "GenTL-GigE",
            int(getattr(m, "MV_GENTL_CAMERALINK_DEVICE", -4)): "CameraLink",
            int(getattr(m, "MV_GENTL_CXP_DEVICE", -5)): "CoaXPress",
            int(getattr(m, "MV_GENTL_XOF_DEVICE", -6)): "XoF",
        }
        return mapping.get(int(tlayer_type), f"Unknown({tlayer_type})")

    def _tlayer_mask(self) -> int:
        m = self.module
        names = [
            "MV_GIGE_DEVICE",
            "MV_USB_DEVICE",
            "MV_GENTL_GIGE_DEVICE",
            "MV_GENTL_CAMERALINK_DEVICE",
            "MV_GENTL_CXP_DEVICE",
            "MV_GENTL_XOF_DEVICE",
        ]
        mask = 0
        for n in names:
            mask |= int(getattr(m, n, 0))
        return mask

    def enumerate_cameras(self) -> list[CameraInfo]:
        if not self.available:
            return []

        m = self.module
        device_list = m.MV_CC_DEVICE_INFO_LIST()
        tlayer = self._tlayer_mask()
        if tlayer == 0:
            return []

        ret = m.MvCamera.MV_CC_EnumDevicesEx2(
            tlayer,
            device_list,
            "",
            int(getattr(m, "SortMethod_SerialNumber", 0)),
        )
        if ret != 0:
            ret = m.MvCamera.MV_CC_EnumDevices(tlayer, device_list)
            if ret != 0:
                return []

        infos: list[CameraInfo] = []
        for idx in range(device_list.nDeviceNum):
            dev_info = cast(
                device_list.pDeviceInfo[idx], POINTER(m.MV_CC_DEVICE_INFO)
            ).contents
            model_name = ""
            serial = ""
            tlayer_type = int(dev_info.nTLayerType)
            if tlayer_type in (
                int(getattr(m, "MV_GIGE_DEVICE", -1)),
                int(getattr(m, "MV_GENTL_GIGE_DEVICE", -2)),
            ):
                model_name = self._decode_char(
                    dev_info.SpecialInfo.stGigEInfo.chModelName
                )
                serial = self._decode_char(dev_info.SpecialInfo.stGigEInfo.chSerialNumber)
            elif tlayer_type == int(getattr(m, "MV_USB_DEVICE", -3)):
                model_name = self._decode_char(
                    dev_info.SpecialInfo.stUsb3VInfo.chModelName
                )
                serial = self._decode_char(dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber)
            elif tlayer_type == int(getattr(m, "MV_GENTL_CAMERALINK_DEVICE", -4)):
                model_name = self._decode_char(dev_info.SpecialInfo.stCMLInfo.chModelName)
                serial = self._decode_char(dev_info.SpecialInfo.stCMLInfo.chSerialNumber)
            elif tlayer_type == int(getattr(m, "MV_GENTL_CXP_DEVICE", -5)):
                model_name = self._decode_char(dev_info.SpecialInfo.stCXPInfo.chModelName)
                serial = self._decode_char(dev_info.SpecialInfo.stCXPInfo.chSerialNumber)
            elif tlayer_type == int(getattr(m, "MV_GENTL_XOF_DEVICE", -6)):
                model_name = self._decode_char(dev_info.SpecialInfo.stXoFInfo.chModelName)
                serial = self._decode_char(dev_info.SpecialInfo.stXoFInfo.chSerialNumber)

            camera_id = serial.strip() or f"cam-{idx + 1}"
            infos.append(
                CameraInfo(
                    camera_id=camera_id,
                    serial_number=serial.strip() or camera_id,
                    model_name=model_name.strip() or "Hikvision Camera",
                    transport=self._transport_name(tlayer_type),
                    online=True,
                    sdk_index=idx,
                )
            )
        return infos


class MockCameraDevice(BaseCameraDevice):
    def __init__(
        self,
        camera_id: str,
        width: int = 1280,
        height: int = 720,
        visible_columns: list[int] | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.visible_columns = sorted(visible_columns or [1, 2, 3, 4])
        self._opened = False
        self._grabbing = False
        self._light_on = False
        self._frame_no = 0
        self._lock = threading.Lock()
        self._exposure_time_us = 4500.0
        self._gain = 0.0
        self._exposure_range = (100.0, 30000.0)
        self._gain_range = (0.0, 24.0)

    @property
    def is_mock(self) -> bool:
        return True

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False
        self._grabbing = False

    def start_grabbing(self) -> None:
        if not self._opened:
            raise RuntimeError("Mock camera is not opened")
        self._grabbing = True

    def stop_grabbing(self) -> None:
        self._grabbing = False

    def set_light(self, on: bool, cfg: LightIOConfig) -> None:
        _ = cfg
        with self._lock:
            self._light_on = on

    def get_settings(self) -> dict:
        return {
            "mode": "mock",
            "exposure_time_us": self._exposure_time_us,
            "gain": self._gain,
            "exposure_range": {"min": self._exposure_range[0], "max": self._exposure_range[1]},
            "gain_range": {"min": self._gain_range[0], "max": self._gain_range[1]},
        }

    def set_settings(self, exposure_time_us: float | None = None, gain: float | None = None) -> dict:
        if exposure_time_us is not None:
            mn, mx = self._exposure_range
            self._exposure_time_us = float(np.clip(float(exposure_time_us), mn, mx))
        if gain is not None:
            mn, mx = self._gain_range
            self._gain = float(np.clip(float(gain), mn, mx))
        return self.get_settings()

    def _column_x(self, column_id: int) -> int:
        pos = {1: 0.20, 2: 0.40, 3: 0.60, 4: 0.80}
        return int(self.width * pos.get(column_id, 0.5))

    def _draw_ruler(self, img: np.ndarray, x: int, label: str) -> None:
        h = img.shape[0]
        cv2.rectangle(img, (x - 30, 30), (x + 30, h - 30), (230, 230, 230), -1)
        for mm in range(0, 111):
            y = 40 + int(mm * (h - 80) / 110)
            tick = 20 if mm % 10 == 0 else 10 if mm % 5 == 0 else 5
            cv2.line(img, (x - 30, y), (x - 30 + tick, y), (70, 70, 70), 1)
            if mm % 10 == 0 and mm > 0:
                cv2.putText(
                    img,
                    str(mm // 10),
                    (x - 12, y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (20, 20, 20),
                    1,
                    cv2.LINE_AA,
                )
        cv2.putText(
            img,
            label,
            (x + 40, int(h * 0.5)),
            cv2.FONT_HERSHEY_DUPLEX,
            1.0,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )

    def _draw_tube(self, img: np.ndarray, x: int, idx: int) -> None:
        h = img.shape[0]
        tube_top = 35
        tube_bottom = h - 35
        cv2.rectangle(img, (x - 9, tube_top), (x + 9, tube_bottom), (72, 80, 94), -1)
        fixed_ratio = 0.30 + 0.13 * (idx - 1)
        bubble_top = int(tube_top + fixed_ratio * (tube_bottom - tube_top))
        bubble_bottom = bubble_top + int(0.12 * (tube_bottom - tube_top))
        cv2.rectangle(img, (x - 8, bubble_top), (x + 8, bubble_bottom), (220, 240, 255), -1)
        cv2.rectangle(img, (x - 8, tube_top), (x + 8, tube_bottom), (110, 120, 138), 1)

    def grab_frame(self, timeout_ms: int = 1000) -> FramePacket | None:
        _ = timeout_ms
        if not self._grabbing:
            return None
        self._frame_no += 1
        exposure_scale = np.clip((self._exposure_time_us / 4500.0), 0.6, 1.8)
        gain_scale = 1.0 + np.clip(self._gain / 24.0, 0.0, 1.0) * 0.25
        light = (1.15 if self._light_on else 0.8) * exposure_scale * gain_scale
        base = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        gradient = np.linspace(18, 36, self.height, dtype=np.uint8)[:, None]
        base[:, :, 0] = (gradient * light).clip(0, 255).astype(np.uint8)
        base[:, :, 1] = (gradient * light * 1.02).clip(0, 255).astype(np.uint8)
        base[:, :, 2] = (gradient * light * 1.05).clip(0, 255).astype(np.uint8)

        for column_id in self.visible_columns:
            x = self._column_x(column_id)
            self._draw_ruler(base, x - 35, str(column_id))
            self._draw_tube(base, x, column_id)

        cv2.putText(
            base,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            (20, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (230, 232, 238),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            base,
            f"MOCK {self.camera_id} | LIGHT {'ON' if self._light_on else 'OFF'}",
            (20, self.height - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (188, 222, 255),
            2,
            cv2.LINE_AA,
        )

        return FramePacket(
            image_bgr=base,
            timestamp=datetime.now(timezone.utc),
            frame_no=self._frame_no,
            lost_packets=0,
            exposure_time_us=self._exposure_time_us,
            gain=self._gain,
        )


class HikMvsCameraDevice(BaseCameraDevice):
    def __init__(self, sdk_ctx: MvsSdkContext, info: CameraInfo) -> None:
        if not sdk_ctx.available:
            raise RuntimeError("MVS SDK is unavailable")
        self.sdk = sdk_ctx
        self.m = sdk_ctx.module
        self.info = info
        self.camera_id = info.camera_id
        self.cam = self.m.MvCamera()
        self._opened = False
        self._grabbing = False
        self._frame_no = 0
        self._light_on = False

        self._mono_pixel_types = {
            int(getattr(self.m, x))
            for x in (
                "PixelType_Gvsp_Mono8",
                "PixelType_Gvsp_Mono10",
                "PixelType_Gvsp_Mono10_Packed",
                "PixelType_Gvsp_Mono12",
                "PixelType_Gvsp_Mono12_Packed",
                "PixelType_Gvsp_Mono14",
                "PixelType_Gvsp_Mono16",
            )
            if hasattr(self.m, x)
        }
        self._hb_pixel_types = {
            int(getattr(self.m, x))
            for x in (
                "PixelType_Gvsp_HB_Mono8",
                "PixelType_Gvsp_HB_Mono10",
                "PixelType_Gvsp_HB_Mono10_Packed",
                "PixelType_Gvsp_HB_Mono12",
                "PixelType_Gvsp_HB_Mono12_Packed",
                "PixelType_Gvsp_HB_Mono16",
                "PixelType_Gvsp_HB_BayerGR8",
                "PixelType_Gvsp_HB_BayerRG8",
                "PixelType_Gvsp_HB_BayerGB8",
                "PixelType_Gvsp_HB_BayerBG8",
                "PixelType_Gvsp_HB_BayerGR10",
                "PixelType_Gvsp_HB_BayerRG10",
                "PixelType_Gvsp_HB_BayerGB10",
                "PixelType_Gvsp_HB_BayerBG10",
                "PixelType_Gvsp_HB_BayerGR12",
                "PixelType_Gvsp_HB_BayerRG12",
                "PixelType_Gvsp_HB_BayerGB12",
                "PixelType_Gvsp_HB_BayerBG12",
                "PixelType_Gvsp_HB_RGB8_Packed",
                "PixelType_Gvsp_HB_BGR8_Packed",
                "PixelType_Gvsp_HB_YUV422_Packed",
                "PixelType_Gvsp_HB_YUV422_YUYV_Packed",
            )
            if hasattr(self.m, x)
        }

    @property
    def is_mock(self) -> bool:
        return False

    def _ensure_ok(self, ret: int, message: str) -> None:
        if ret != 0:
            raise RuntimeError(f"{message} failed: 0x{ret:x}")

    def open(self) -> None:
        if self._opened:
            return
        all_infos = self.sdk.enumerate_cameras()
        match = next((x for x in all_infos if x.camera_id == self.camera_id), None)
        if match is None or match.sdk_index is None:
            raise RuntimeError(f"Camera not found: {self.camera_id}")

        device_list = self.m.MV_CC_DEVICE_INFO_LIST()
        tlayer = self.sdk._tlayer_mask()
        ret = self.m.MvCamera.MV_CC_EnumDevicesEx2(
            tlayer,
            device_list,
            "",
            int(getattr(self.m, "SortMethod_SerialNumber", 0)),
        )
        if ret != 0:
            self._ensure_ok(self.m.MvCamera.MV_CC_EnumDevices(tlayer, device_list), "EnumDevices")
        st_device_info = cast(
            device_list.pDeviceInfo[match.sdk_index], POINTER(self.m.MV_CC_DEVICE_INFO)
        ).contents

        self._ensure_ok(self.cam.MV_CC_CreateHandle(st_device_info), "CreateHandle")
        self._ensure_ok(
            self.cam.MV_CC_OpenDevice(getattr(self.m, "MV_ACCESS_Exclusive", 1), 0),
            "OpenDevice",
        )

        if int(st_device_info.nTLayerType) in (
            int(getattr(self.m, "MV_GIGE_DEVICE", -1)),
            int(getattr(self.m, "MV_GENTL_GIGE_DEVICE", -2)),
        ):
            packet_size = self.cam.MV_CC_GetOptimalPacketSize()
            if int(packet_size) > 0:
                self.cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size)

        self.cam.MV_CC_SetEnumValueByString("TriggerMode", "Off")
        self._opened = True

    def close(self) -> None:
        if not self._opened:
            return
        try:
            if self._grabbing:
                self.stop_grabbing()
            self.cam.MV_CC_CloseDevice()
        finally:
            self.cam.MV_CC_DestroyHandle()
            self._opened = False

    def start_grabbing(self) -> None:
        if not self._opened:
            raise RuntimeError("Camera is not opened")
        if self._grabbing:
            return
        self._ensure_ok(self.cam.MV_CC_StartGrabbing(), "StartGrabbing")
        self._grabbing = True

    def stop_grabbing(self) -> None:
        if not self._grabbing:
            return
        self.cam.MV_CC_StopGrabbing()
        self._grabbing = False

    def set_light(self, on: bool, cfg: LightIOConfig) -> None:
        if not self._opened:
            raise RuntimeError("Camera is not opened")

        self.cam.MV_CC_SetEnumValueByString("LineSelector", cfg.line_selector)
        self.cam.MV_CC_SetEnumValueByString("LineSource", cfg.line_source)
        self.cam.MV_CC_SetIntValueEx("StrobeLineDuration", cfg.strobe_duration_us)
        self.cam.MV_CC_SetIntValueEx("StrobeLineDelay", cfg.strobe_delay_us)
        self.cam.MV_CC_SetIntValueEx("StrobeLinePreDelay", cfg.strobe_pre_delay_us)
        self._ensure_ok(self.cam.MV_CC_SetBoolValue("StrobeEnable", bool(on)), "Set StrobeEnable")
        self._light_on = on

    def _read_float_info(self, node_name: str) -> tuple[float | None, dict | None]:
        if not hasattr(self.m, "MVCC_FLOATVALUE"):
            return None, None
        st_val = self.m.MVCC_FLOATVALUE()
        memset(byref(st_val), 0, sizeof(st_val))
        ret = self.cam.MV_CC_GetFloatValue(node_name, st_val)
        if ret != 0:
            return None, None
        cur = float(st_val.fCurValue)
        rng = {
            "min": float(getattr(st_val, "fMin", cur)),
            "max": float(getattr(st_val, "fMax", cur)),
        }
        return cur, rng

    def get_settings(self) -> dict:
        exposure, exposure_range = self._read_float_info("ExposureTime")
        gain, gain_range = self._read_float_info("Gain")
        return {
            "mode": "real",
            "exposure_time_us": exposure,
            "gain": gain,
            "exposure_range": exposure_range,
            "gain_range": gain_range,
        }

    def set_settings(self, exposure_time_us: float | None = None, gain: float | None = None) -> dict:
        if exposure_time_us is not None:
            self.cam.MV_CC_SetEnumValueByString("ExposureAuto", "Off")
            ret = self.cam.MV_CC_SetFloatValue("ExposureTime", float(exposure_time_us))
            self._ensure_ok(ret, "Set ExposureTime")
        if gain is not None:
            self.cam.MV_CC_SetEnumValueByString("GainAuto", "Off")
            ret = self.cam.MV_CC_SetFloatValue("Gain", float(gain))
            self._ensure_ok(ret, "Set Gain")
        return self.get_settings()

    def _is_hb_pixel(self, pixel_type: int) -> bool:
        return int(pixel_type) in self._hb_pixel_types

    def _is_mono_pixel(self, pixel_type: int) -> bool:
        return int(pixel_type) in self._mono_pixel_types

    def _read_float(self, node_name: str) -> float | None:
        if not hasattr(self.m, "MVCC_FLOATVALUE"):
            return None
        st_val = self.m.MVCC_FLOATVALUE()
        memset(byref(st_val), 0, sizeof(st_val))
        ret = self.cam.MV_CC_GetFloatValue(node_name, st_val)
        if ret != 0:
            return None
        return float(st_val.fCurValue)

    def grab_frame(self, timeout_ms: int = 1000) -> FramePacket | None:
        if not self._grabbing:
            return None

        st_out = self.m.MV_FRAME_OUT()
        memset(byref(st_out), 0, sizeof(st_out))
        ret = self.cam.MV_CC_GetImageBuffer(st_out, timeout_ms)
        if ret != 0 or st_out.pBufAddr is None:
            return None

        try:
            width = int(st_out.stFrameInfo.nWidth)
            height = int(st_out.stFrameInfo.nHeight)
            frame_no = int(st_out.stFrameInfo.nFrameNum)
            lost_packets = int(getattr(st_out.stFrameInfo, "nLostPacket", 0))
            src_data = st_out.pBufAddr
            src_len = int(st_out.stFrameInfo.nFrameLen)
            src_pixel_type = int(st_out.stFrameInfo.enPixelType)

            if self._is_hb_pixel(src_pixel_type):
                decode_len = max(width * height * 3, src_len)
                decode_buffer = (c_ubyte * decode_len)()
                decode_param = self.m.MV_CC_HB_DECODE_PARAM()
                memset(byref(decode_param), 0, sizeof(decode_param))
                decode_param.pSrcBuf = src_data
                decode_param.nSrcLen = src_len
                decode_param.pDstBuf = decode_buffer
                decode_param.nDstBufSize = decode_len
                ret = self.cam.MV_CC_HBDecode(decode_param)
                self._ensure_ok(ret, "HBDecode")
                src_data = decode_param.pDstBuf
                src_len = int(decode_param.nDstBufLen)
                src_pixel_type = int(decode_param.enDstPixelType)

            channels = 1 if self._is_mono_pixel(src_pixel_type) else 3
            dst_pixel_type = (
                int(getattr(self.m, "PixelType_Gvsp_Mono8"))
                if channels == 1
                else int(getattr(self.m, "PixelType_Gvsp_RGB8_Packed"))
            )
            dst_len = width * height * channels
            dst_buffer = (c_ubyte * dst_len)()

            convert_param = self.m.MV_CC_PIXEL_CONVERT_PARAM_EX()
            memset(byref(convert_param), 0, sizeof(convert_param))
            convert_param.nWidth = width
            convert_param.nHeight = height
            convert_param.pSrcData = src_data
            convert_param.nSrcDataLen = src_len
            convert_param.enSrcPixelType = src_pixel_type
            convert_param.enDstPixelType = dst_pixel_type
            convert_param.pDstBuffer = dst_buffer
            convert_param.nDstBufferSize = dst_len

            self._ensure_ok(self.cam.MV_CC_ConvertPixelTypeEx(convert_param), "ConvertPixelType")
            arr = np.frombuffer(dst_buffer, dtype=np.uint8, count=dst_len)
            if channels == 1:
                mono = arr.reshape(height, width)
                frame_bgr = cv2.cvtColor(mono, cv2.COLOR_GRAY2BGR)
            else:
                rgb = arr.reshape(height, width, 3)
                frame_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            self._frame_no = frame_no
            return FramePacket(
                image_bgr=frame_bgr,
                timestamp=datetime.now(timezone.utc),
                frame_no=frame_no,
                lost_packets=lost_packets,
                exposure_time_us=self._read_float("ExposureTime"),
                gain=self._read_float("Gain"),
            )
        finally:
            self.cam.MV_CC_FreeImageBuffer(st_out)


def make_mock_camera_infos(count: int = 2) -> list[CameraInfo]:
    return [
        CameraInfo(
            camera_id=f"mock-cam-{idx + 1}",
            serial_number=f"MOCK{idx + 1:04d}",
            model_name="Mock Vision Simulator",
            transport="Simulated",
            online=True,
            sdk_index=None,
        )
        for idx in range(count)
    ]
