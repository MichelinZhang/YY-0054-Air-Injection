from app.models import CameraInfo
from app.services.session_manager import SessionManager


def test_sort_camera_candidates_prefers_gige_then_camera_id() -> None:
    cams = [
        CameraInfo(
            camera_id="usb-2",
            serial_number="S2",
            model_name="USB Cam 2",
            transport="USB3",
            online=True,
            sdk_index=1,
        ),
        CameraInfo(
            camera_id="gige-2",
            serial_number="G2",
            model_name="GigE Cam 2",
            transport="GigE",
            online=True,
            sdk_index=2,
        ),
        CameraInfo(
            camera_id="gige-1",
            serial_number="G1",
            model_name="GigE Cam 1",
            transport="GenTL-GigE",
            online=True,
            sdk_index=0,
        ),
        CameraInfo(
            camera_id="usb-1",
            serial_number="S1",
            model_name="USB Cam 1",
            transport="USB3",
            online=True,
            sdk_index=3,
        ),
    ]

    sorted_cams = SessionManager._sort_camera_candidates(cams)
    assert [cam.camera_id for cam in sorted_cams] == ["gige-1", "gige-2", "usb-1", "usb-2"]


def test_build_column_mapping_one_and_two_cameras() -> None:
    mgr = SessionManager.__new__(SessionManager)
    assert mgr._build_column_mapping(["cam-a"]) == {1: "cam-a", 2: "cam-a", 3: "cam-a", 4: "cam-a"}
    assert mgr._build_column_mapping(["cam-a", "cam-b"]) == {1: "cam-a", 2: "cam-a", 3: "cam-b", 4: "cam-b"}
