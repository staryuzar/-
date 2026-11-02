from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MIN_IMAGE_SIDE = 64


def load_chart_image(path: str | Path) -> tuple[np.ndarray | None, str | None]:
    """Read a chart safely and reject empty, oversized or implausible images."""
    image_path = Path(path)
    try:
        if not image_path.is_file():
            return None, "The chart image file does not exist."
        size = image_path.stat().st_size
        if size <= 0:
            return None, "The chart image file is empty."
        if size > MAX_IMAGE_BYTES:
            return None, f"The chart image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB analysis limit."
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    except (OSError, ValueError) as exc:
        return None, f"Unable to access chart image: {type(exc).__name__}: {exc}"

    if image is None or image.ndim != 3 or image.shape[2] != 3:
        return None, "The image could not be decoded as a 3-channel colour image."
    height, width = image.shape[:2]
    if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
        return None, f"The chart image is too small; both dimensions must be at least {MIN_IMAGE_SIDE} pixels."
    if width * height > MAX_IMAGE_PIXELS:
        return None, f"The chart image exceeds the {MAX_IMAGE_PIXELS:,}-pixel safety limit."
    if not np.isfinite(image).all():
        return None, "The decoded image contains invalid pixel values."
    return image, None
