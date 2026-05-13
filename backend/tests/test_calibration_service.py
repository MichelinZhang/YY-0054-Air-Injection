from fastapi.testclient import TestClient

from app.main import app


def test_calibration_get_returns_profile() -> None:
    client = TestClient(app)
    resp = client.get("/api/calibration")
    assert resp.status_code == 200
    data = resp.json()
    assert "scale_mm_per_tick" in data
    assert "tube_inner_diameter_mm" in data


def test_calibration_post_requires_auth() -> None:
    client = TestClient(app)
    resp = client.post("/api/calibration", json={"scale_mm_per_tick": 1.5})
    assert resp.status_code == 403


def test_calibration_from_reference_requires_auth() -> None:
    client = TestClient(app)
    resp = client.post("/api/calibration/from-reference", json={
        "known_tick_count": 10,
        "known_length_mm": 10.0,
    })
    assert resp.status_code == 403
