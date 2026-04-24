import cv2
import numpy as np

from app.models import MeasureRequest, Point2D, RectROI
from app.services.reading_assist_service import ReadingAssistService


def test_reading_assist_with_edge_snap() -> None:
    svc = ReadingAssistService()

    img = np.full((300, 200, 3), 80, dtype=np.uint8)
    for y in range(80, 241, 10):
        cv2.line(img, (84, y), (116, y), (235, 235, 235), 1)
    cv2.line(img, (98, 100), (102, 100), (255, 255, 255), 3)
    cv2.line(img, (98, 200), (102, 200), (255, 255, 255), 3)
    req = MeasureRequest(
        camera_id="cam-a",
        column_id=1,
        top_point=Point2D(x=100, y=104),
        bottom_point=Point2D(x=100, y=196),
        roi=RectROI(x=60, y=70, width=80, height=160),
    )
    out = svc.measure(req, img)
    assert out.tick_delta >= 0
    assert out.pixel_delta > 0
    assert out.confidence > 0.3
