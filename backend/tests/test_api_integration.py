import time

from fastapi.testclient import TestClient
import numpy as np

from app.main import app, session_manager


def _wait_frame(camera_id: str) -> bool:
    for _ in range(20):
        if session_manager.get_latest_frame(camera_id) is not None:
            return True
        time.sleep(0.1)
    return False


def test_api_flow_mock_mode() -> None:
    client = TestClient(app)

    cameras = client.get("/api/cameras")
    assert cameras.status_code == 200
    assert cameras.json()["items"]
    assert "detected_real_camera_count" in cameras.json()

    open_resp = client.post("/api/session/open", json={"max_camera_count": 1, "use_mock_when_unavailable": True})
    assert open_resp.status_code == 200
    body = open_resp.json()
    camera_id = body["active_camera_ids"][0]
    assert body["applied_selection_mode"] == "auto"
    assert body["detected_real_camera_count"] >= 0

    assert _wait_frame(camera_id)

    cal_resp = client.post("/api/calibration", json={"entries": []})
    assert cal_resp.status_code == 410

    measure_resp = client.post(
        "/api/measure",
        json={
            "camera_id": camera_id,
            "column_id": 1,
            "top_point": {"x": 130, "y": 180},
            "bottom_point": {"x": 130, "y": 300},
            "roi": {"x": 80, "y": 120, "width": 120, "height": 240},
        },
    )
    assert measure_resp.status_code == 200
    reading = measure_resp.json()
    assert "tick_delta" in reading
    assert reading["pixel_delta"] > 0

    save_resp = client.post(
        "/api/result/save",
        json={"measurements": [reading], "operator": "tester", "note": "integration"},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["record_id"]

    history = client.get("/api/results")
    assert history.status_code == 200
    assert isinstance(history.json()["items"], list)

    close_resp = client.post("/api/session/close")
    assert close_resp.status_code == 200


def test_open_session_force_mock() -> None:
    client = TestClient(app)

    open_resp = client.post(
        "/api/session/open",
        json={
            "max_camera_count": 2,
            "force_mock": True,
            "use_mock_when_unavailable": False,
        },
    )
    assert open_resp.status_code == 200
    body = open_resp.json()
    assert body["using_mock"] is True
    assert body["applied_selection_mode"] == "auto"
    assert len(body["active_camera_ids"]) == 2
    assert all(camera_id.startswith("mock-cam-") for camera_id in body["active_camera_ids"])
    assert _wait_frame(body["active_camera_ids"][0])
    assert _wait_frame(body["active_camera_ids"][1])

    cam1 = body["active_camera_ids"][0]
    cam2 = body["active_camera_ids"][1]
    runtime1 = session_manager._runtimes[cam1]
    runtime2 = session_manager._runtimes[cam2]
    assert getattr(runtime1.device, "visible_columns", None) == [1, 2]
    assert getattr(runtime2.device, "visible_columns", None) == [3, 4]

    close_resp = client.post("/api/session/close")
    assert close_resp.status_code == 200


def test_open_session_auto_without_real_uses_single_mock() -> None:
    client = TestClient(app)

    open_resp = client.post(
        "/api/session/open",
        json={
            "selection_mode": "auto",
            "max_camera_count": 2,
            "use_mock_when_unavailable": True,
        },
    )
    assert open_resp.status_code == 200
    body = open_resp.json()
    assert body["using_mock"] is True
    assert body["applied_selection_mode"] == "auto"
    assert len(body["active_camera_ids"]) == 1
    assert body["column_camera_map"] == {
        "1": body["active_camera_ids"][0],
        "2": body["active_camera_ids"][0],
        "3": body["active_camera_ids"][0],
        "4": body["active_camera_ids"][0],
    }

    close_resp = client.post("/api/session/close")
    assert close_resp.status_code == 200


def test_open_session_manual_keeps_legacy_mock_fallback_count() -> None:
    client = TestClient(app)

    open_resp = client.post(
        "/api/session/open",
        json={
            "selection_mode": "manual",
            "selected_camera_ids": ["cam-a", "cam-b"],
            "max_camera_count": 2,
            "use_mock_when_unavailable": True,
        },
    )
    assert open_resp.status_code == 200
    body = open_resp.json()
    assert body["using_mock"] is True
    assert body["applied_selection_mode"] == "manual"
    assert len(body["active_camera_ids"]) == 2

    close_resp = client.post("/api/session/close")
    assert close_resp.status_code == 200


def test_camera_settings_mock_and_static_bubble() -> None:
    client = TestClient(app)
    open_resp = client.post("/api/session/open", json={"max_camera_count": 1, "force_mock": True})
    assert open_resp.status_code == 200
    camera_id = open_resp.json()["active_camera_ids"][0]
    assert _wait_frame(camera_id)

    get_resp = client.get(f"/api/camera/{camera_id}/settings")
    assert get_resp.status_code == 200
    before = get_resp.json()
    assert before["mode"] == "mock"

    set_resp = client.post(f"/api/camera/{camera_id}/settings", json={"exposure_time_us": 7000, "gain": 2.5})
    assert set_resp.status_code == 200
    after = set_resp.json()
    assert abs(after["exposure_time_us"] - 7000) < 1e-6
    assert abs(after["gain"] - 2.5) < 1e-6

    time.sleep(0.2)
    frame1 = session_manager.get_latest_frame(camera_id)
    time.sleep(0.08)
    frame2 = session_manager.get_latest_frame(camera_id)
    assert frame1 is not None and frame2 is not None

    h, w = frame1.image_bgr.shape[:2]
    x = int(w * 0.2)
    roi1 = frame1.image_bgr[45 : h - 45, x - 9 : x + 9]
    roi2 = frame2.image_bgr[45 : h - 45, x - 9 : x + 9]
    mask1 = (roi1[:, :, 0] > 180) & (roi1[:, :, 1] > 180) & (roi1[:, :, 2] > 180)
    mask2 = (roi2[:, :, 0] > 180) & (roi2[:, :, 1] > 180) & (roi2[:, :, 2] > 180)
    y1 = np.where(mask1)[0]
    y2 = np.where(mask2)[0]
    assert y1.size > 0 and y2.size > 0
    assert abs(float(y1.mean()) - float(y2.mean())) < 1.0

    close_resp = client.post("/api/session/close")
    assert close_resp.status_code == 200
