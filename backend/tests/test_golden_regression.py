"""Golden-set regression tests for the measurement algorithm.

Loads real camera images + expected-result sidecars from tests/golden_data/
and verifies the reading-assist service produces results within tolerance.

To add a new golden case:
  1. Place an image (PNG/JPG) in tests/golden_data/
  2. Create a matching .json sidecar (see golden_data/README.md)
  3. Run: uv run pytest tests/test_golden_regression.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

GOLDEN_DIR = Path(__file__).parent / "golden_data"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}


def discover_golden_cases() -> list[tuple[Path, dict]]:
    cases = []
    for img_path in sorted(GOLDEN_DIR.iterdir()):
        if img_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        json_path = img_path.with_suffix(".json")
        if not json_path.exists():
            continue
        spec = json.loads(json_path.read_text(encoding="utf-8"))
        cases.append((img_path, spec))
    return cases


GOLDEN_CASES = discover_golden_cases()


def _load_image(path: Path) -> np.ndarray:
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot load image: {path}")
    return img


@pytest.mark.skipif(len(GOLDEN_CASES) == 0, reason="No golden images found in tests/golden_data/")
@pytest.mark.parametrize(
    "img_path,spec",
    GOLDEN_CASES,
    ids=[p.stem for p, _ in GOLDEN_CASES],
)
def test_golden_measurement(img_path: Path, spec: dict):
    from app.models import MeasureRequest, Point2D, RectROI
    from app.services.reading_assist_service import ReadingAssistService

    service = ReadingAssistService()
    frame = _load_image(img_path)

    roi = RectROI(**spec["roi"]) if "roi" in spec else None
    req = MeasureRequest(
        camera_id="golden",
        column_id=1,
        top_point=Point2D(**spec["top_point"]),
        bottom_point=Point2D(**spec["bottom_point"]),
        roi=roi,
    )

    result = service.measure(req, frame)

    if "expected_tick_delta" in spec:
        tol = spec.get("tolerance_tick", 1.0)
        assert abs(result.tick_delta - spec["expected_tick_delta"]) <= tol, (
            f"tick_delta {result.tick_delta} not within ±{tol} of expected {spec['expected_tick_delta']}"
        )

    if "expected_pixel_delta" in spec:
        tol = spec.get("tolerance_pixel", 20.0)
        assert abs(result.pixel_delta - spec["expected_pixel_delta"]) <= tol, (
            f"pixel_delta {result.pixel_delta} not within ±{tol} of expected {spec['expected_pixel_delta']}"
        )

    min_conf = spec.get("min_confidence", 0.15)
    assert result.confidence >= min_conf, (
        f"confidence {result.confidence} below minimum {min_conf}"
    )


@pytest.mark.skipif(len(GOLDEN_CASES) == 0, reason="No golden images found")
@pytest.mark.parametrize(
    "img_path,spec",
    GOLDEN_CASES,
    ids=[p.stem for p, _ in GOLDEN_CASES],
)
def test_golden_bubble_detection(img_path: Path, spec: dict):
    """If golden spec includes bubble expectations, verify auto-detection."""
    if "expected_bubble_top_y" not in spec:
        pytest.skip("No bubble expectations in spec")

    import cv2
    from app.models import RectROI
    from app.services.reading_assist_service import ReadingAssistService

    service = ReadingAssistService()
    frame = _load_image(img_path)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    roi = RectROI(**spec["roi"]) if "roi" in spec else None
    x = int(spec["top_point"]["x"])

    result = service.detect_bubble_boundaries(gray, x, roi)
    assert result["detected"], f"Bubble not detected in {img_path.name}"

    tol = spec.get("tolerance_bubble_y", 15.0)
    assert abs(result["bubble_top"]["y"] - spec["expected_bubble_top_y"]) <= tol
    assert abs(result["bubble_bottom"]["y"] - spec["expected_bubble_bottom_y"]) <= tol


def test_synthetic_basic():
    """Smoke test with a synthetic gradient image (always runs)."""
    from app.models import MeasureRequest, Point2D
    from app.services.reading_assist_service import ReadingAssistService

    service = ReadingAssistService()
    h, w = 480, 640
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for row in range(h):
        v = int(255 * row / h)
        img[row, :] = v

    req = MeasureRequest(
        camera_id="synthetic",
        column_id=1,
        top_point=Point2D(x=320, y=100),
        bottom_point=Point2D(x=320, y=380),
    )

    result = service.measure(req, img)
    assert result.pixel_delta > 0
    assert 0.0 <= result.confidence <= 1.0


def test_synthetic_bubble_detection():
    """Smoke test for bubble detection with synthetic image."""
    import cv2
    from app.services.reading_assist_service import ReadingAssistService

    service = ReadingAssistService()
    h, w = 480, 640
    img = np.full((h, w), 40, dtype=np.uint8)
    img[150:350, 280:360] = 200

    result = service.detect_bubble_boundaries(img, 320, None)
    assert result["detected"]
    assert abs(result["bubble_top"]["y"] - 150) < 20
    assert abs(result["bubble_bottom"]["y"] - 350) < 20
