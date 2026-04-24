from __future__ import annotations

import base64

import cv2
import numpy as np


def encode_jpeg_base64(image_bgr: np.ndarray, quality: int = 82) -> str:
    ok, encoded = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Failed to encode preview JPEG")
    return base64.b64encode(encoded.tobytes()).decode("ascii")

