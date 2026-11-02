from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MIN_IMAGE_SIDE = 64


def load_chart_image(path: str | Path) -> tuple[np.ndarray | None, str | None]:
    """Validate compressed image metadata before decoding full pixel data."""
    image_path = Path(path)
    try:
        if not image_path.is_file():
            return None, "The chart image file does not exist."
        size = image_path.stat().st_size
        if size <= 0:
            return None, "The chart image file is empty."
        if size > MAX_IMAGE_BYTES:
            return None, f"The chart image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB analysis limit."
        payload = image_path.read_bytes()
        if not payload:
            return None, "The chart image file is empty."
        if len(payload) > MAX_IMAGE_BYTES:
            return None, f"The chart image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB analysis limit."

        # Pillow reads dimensions from the header and verifies the file before
        # OpenCV allocates the decoded image. This blocks compressed pixel bombs.
        with Image.open(io.BytesIO(payload)) as preview:
            width, height = preview.size
            if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
                return None, f"The chart image is too small; both dimensions must be at least {MIN_IMAGE_SIDE} pixels."
            if width * height > MAX_IMAGE_PIXELS:
                return None, f"The chart image exceeds the {MAX_IMAGE_PIXELS:,}-pixel safety limit."
            preview.verify()

    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        return None, f"Unable to validate chart image: {type(exc).__name__}: {exc}"

    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        return None, "The image could not be decoded as a 3-channel colour image."
    decoded_height, decoded_width = image.shape[:2]
    if decoded_width != width or decoded_height != height:
        return None, "Image dimensions changed between header validation and decoding."
    return image, None
