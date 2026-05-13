"""P0 compliance tests: auth, audit, mock isolation, data integrity, error codes."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "development")

from app.main import app, session_manager, result_store
from app.services.audit_logger import audit_logger, AuditEvent


def _wait_frame(camera_id: str) -> bool:
    for _ in range(20):
        if session_manager.get_latest_frame(camera_id) is not None:
            return True
        time.sleep(0.1)
    return False


class TestErrorCodeStructure:
    """Verify that errors return structured error_code + message."""

    def test_calibration_post_requires_auth(self):
        client = TestClient(app)
        resp = client.post("/api/calibration", json={})
        assert resp.status_code == 403

    def test_calibration_get_returns_profile(self):
        client = TestClient(app)
        resp = client.get("/api/calibration")
        assert resp.status_code == 200
        assert "scale_mm_per_tick" in resp.json()

    def test_measure_no_frame_returns_error_code(self):
        client = TestClient(app)
        resp = client.post("/api/measure", json={
            "camera_id": "nonexistent",
            "column_id": 1,
            "top_point": {"x": 10, "y": 10},
            "bottom_point": {"x": 10, "y": 50},
        })
        assert resp.status_code == 409
        body = resp.json()["detail"]
        assert body["error_code"] == "E4002"

    def test_camera_settings_not_active_returns_error_code(self):
        client = TestClient(app)
        resp = client.get("/api/camera/nonexistent/settings")
        assert resp.status_code == 404
        body = resp.json()["detail"]
        assert body["error_code"] == "E3002"


class TestMockIsolation:
    """Verify mock save blocking in production mode."""

    def test_save_allowed_in_dev_mode(self):
        client = TestClient(app)
        open_resp = client.post("/api/session/open", json={
            "max_camera_count": 1, "force_mock": True,
        })
        assert open_resp.status_code == 200
        camera_id = open_resp.json()["active_camera_ids"][0]
        assert _wait_frame(camera_id)

        measure_resp = client.post("/api/measure", json={
            "camera_id": camera_id,
            "column_id": 1,
            "top_point": {"x": 130, "y": 180},
            "bottom_point": {"x": 130, "y": 300},
        })
        assert measure_resp.status_code == 200
        reading = measure_resp.json()

        save_resp = client.post("/api/result/save", json={
            "measurements": [reading], "operator": "tester", "note": "dev test",
        })
        assert save_resp.status_code == 200
        client.post("/api/session/close")

    def test_save_blocked_in_production_with_mock(self):
        with patch("app.services.result_store.MOCK_SAVE_ALLOWED", False):
            client = TestClient(app)
            open_resp = client.post("/api/session/open", json={
                "max_camera_count": 1, "force_mock": True,
            })
            assert open_resp.status_code == 200
            camera_id = open_resp.json()["active_camera_ids"][0]
            assert _wait_frame(camera_id)

            measure_resp = client.post("/api/measure", json={
                "camera_id": camera_id,
                "column_id": 1,
                "top_point": {"x": 130, "y": 180},
                "bottom_point": {"x": 130, "y": 300},
            })
            assert measure_resp.status_code == 200
            reading = measure_resp.json()

            save_resp = client.post("/api/result/save", json={
                "measurements": [reading], "operator": "tester", "note": "prod test",
            })
            assert save_resp.status_code == 403
            body = save_resp.json()["detail"]
            assert body["error_code"] == "E5003"
            client.post("/api/session/close")


class TestDataIntegrity:
    """Verify pre-save validation and atomic writes."""

    def test_save_fails_when_no_measurements(self):
        client = TestClient(app)
        resp = client.post("/api/result/save", json={
            "measurements": [], "operator": "tester",
        })
        assert resp.status_code == 422

    def test_save_fails_when_frame_missing(self):
        client = TestClient(app)
        open_resp = client.post("/api/session/open", json={
            "max_camera_count": 1, "force_mock": True,
        })
        camera_id = open_resp.json()["active_camera_ids"][0]
        assert _wait_frame(camera_id)

        measure_resp = client.post("/api/measure", json={
            "camera_id": camera_id,
            "column_id": 1,
            "top_point": {"x": 130, "y": 180},
            "bottom_point": {"x": 130, "y": 300},
        })
        reading = measure_resp.json()
        reading["camera_id"] = "fake-camera-999"

        save_resp = client.post("/api/result/save", json={
            "measurements": [reading], "operator": "tester",
        })
        assert save_resp.status_code == 409
        body = save_resp.json()["detail"]
        assert body["error_code"] == "E5002"
        client.post("/api/session/close")

    def test_saved_record_has_checksums(self):
        client = TestClient(app)
        open_resp = client.post("/api/session/open", json={
            "max_camera_count": 1, "force_mock": True,
        })
        camera_id = open_resp.json()["active_camera_ids"][0]
        assert _wait_frame(camera_id)

        measure_resp = client.post("/api/measure", json={
            "camera_id": camera_id,
            "column_id": 1,
            "top_point": {"x": 130, "y": 180},
            "bottom_point": {"x": 130, "y": 300},
        })
        reading = measure_resp.json()

        save_resp = client.post("/api/result/save", json={
            "measurements": [reading], "operator": "tester",
        })
        assert save_resp.status_code == 200
        record_id = save_resp.json()["record_id"]

        verify_resp = client.get(f"/api/results/{record_id}/verify")
        assert verify_resp.status_code == 200
        integrity = verify_resp.json()["integrity"]
        assert integrity.get("json_valid") is True
        client.post("/api/session/close")


class TestOperatorEnforcement:
    """Verify operator identity requirement in production."""

    def test_operator_not_required_in_dev(self):
        client = TestClient(app)
        open_resp = client.post("/api/session/open", json={
            "max_camera_count": 1, "force_mock": True,
        })
        camera_id = open_resp.json()["active_camera_ids"][0]
        assert _wait_frame(camera_id)

        measure_resp = client.post("/api/measure", json={
            "camera_id": camera_id,
            "column_id": 1,
            "top_point": {"x": 130, "y": 180},
            "bottom_point": {"x": 130, "y": 300},
        })
        reading = measure_resp.json()

        save_resp = client.post("/api/result/save", json={
            "measurements": [reading], "operator": None,
        })
        assert save_resp.status_code == 200
        client.post("/api/session/close")

    def test_operator_required_in_production(self):
        with patch("app.services.result_store.IS_PRODUCTION", True), \
             patch("app.services.result_store.MOCK_SAVE_ALLOWED", True):
            client = TestClient(app)
            open_resp = client.post("/api/session/open", json={
                "max_camera_count": 1, "force_mock": True,
            })
            camera_id = open_resp.json()["active_camera_ids"][0]
            assert _wait_frame(camera_id)

            measure_resp = client.post("/api/measure", json={
                "camera_id": camera_id,
                "column_id": 1,
                "top_point": {"x": 130, "y": 180},
                "bottom_point": {"x": 130, "y": 300},
            })
            reading = measure_resp.json()

            save_resp = client.post("/api/result/save", json={
                "measurements": [reading], "operator": None,
            })
            assert save_resp.status_code == 422
            body = save_resp.json()["detail"]
            assert body["error_code"] == "E5005"
            client.post("/api/session/close")


class TestHealthEndpoint:
    """Verify health endpoint exposes compliance-relevant info."""

    def test_health_returns_env_info(self):
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "env" in body
        assert "auth_enabled" in body
        assert "mock_save_allowed" in body
        assert body["ok"] is True


class TestAuditLog:
    """Verify audit events are generated for critical operations."""

    def test_session_open_generates_audit(self, tmp_path):
        with patch.object(audit_logger, "_log_dir", tmp_path):
            client = TestClient(app)
            client.post("/api/session/open", json={
                "max_camera_count": 1, "force_mock": True,
            })
            client.post("/api/session/close")
