from fastapi.testclient import TestClient

from app.main import app


def test_calibration_api_is_gone() -> None:
    client = TestClient(app)
    resp = client.post("/api/calibration", json={"entries": []})
    assert resp.status_code == 410
