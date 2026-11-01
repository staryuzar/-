from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

def _groups(columns: np.ndarray, gap: int = 2) -> list[tuple[int, int]]:
    indices = np.flatnonzero(columns)
    if len(indices) == 0:
        return []
    result: list[tuple[int, int]] = []
    start = previous = int(indices[0])
    for value in indices[1:]:
        current = int(value)
        if current - previous > gap + 1:
            result.append((start, previous))
            start = current
        previous = current
    result.append((start, previous))
    return result

def _extract_bars(image: np.ndarray) -> list[dict[str, Any]]:
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([32, 45, 40]), np.array([95, 255, 255]))
    red_a = cv2.inRange(hsv, np.array([0, 55, 45]), np.array([12, 255, 255]))
    red_b = cv2.inRange(hsv, np.array([168, 55, 45]), np.array([180, 255, 255]))
    red = cv2.bitwise_or(red_a, red_b)
    colour_mask = cv2.bitwise_or(green, red)
    activity = (colour_mask > 0).sum(axis=0)
    groups = _groups(activity > max(2, int(height * 0.0025)), gap=2)
    bars: list[dict[str, Any]] = []
    for left, right in groups:
        if right - left > 18 or right - left < 0:
            continue
        roi_g = green[:, left:right + 1] > 0
        roi_r = red[:, left:right + 1] > 0
        roi = roi_g | roi_r
        ys, xs = np.where(roi)
        if len(ys) < 4:
            continue
        top, bottom = int(ys.min()), int(ys.max())
        row_width = roi.sum(axis=1)
        strongest = int(row_width.max())
        if strongest <= 0:
            continue
        body_rows = np.flatnonzero(row_width >= max(1, int(strongest * 0.55)))
        if len(body_rows) == 0:
            continue
        body_top, body_bottom = int(body_rows.min()), int(body_rows.max())
        total_h = max(1, bottom - top + 1)
        body_h = max(1, body_bottom - body_top + 1)
        green_pixels, red_pixels = int(roi_g.sum()), int(roi_r.sum())
        colour = "GREEN" if green_pixels >= red_pixels else "RED"
        body_ratio = min(1.0, body_h / total_h)
        upper = max(0, body_top - top)
        lower = max(0, bottom - body_bottom)
        shape = "normal"
        if body_ratio <= 0.12:
            shape = "doji_candidate"
        elif lower >= 2 * body_h and upper <= body_h:
            shape = "hammer_candidate"
        elif upper >= 2 * body_h and lower <= body_h:
            shape = "shooting_star_candidate"
        bars.append({
            "x": int((left + right) / 2), "top_px": top, "bottom_px": bottom,
            "body_top_px": body_top, "body_bottom_px": body_bottom,
            "colour": colour, "shape": shape, "body_ratio": round(body_ratio, 3),
        })
    return bars

def analyze_chart_image(image_path: str | Path) -> dict[str, Any]:
    path = Path(image_path)
    result: dict[str, Any] = {
        "engine": "chart_visual_analysis", "method": "OpenCV classical computer vision",
        "ai_used": False, "image": path.name, "analyzed_at_ms": int(time.time() * 1000),
    }
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return {**result, "status": "ERROR", "error": "The image could not be read."}
    height, width = image.shape[:2]
    bars = _extract_bars(image)
    counts = {"GREEN": sum(1 for b in bars if b["colour"] == "GREEN"),
              "RED": sum(1 for b in bars if b["colour"] == "RED")}
    patterns = []
    for bar in bars[-12:]:
        if bar["shape"] != "normal":
            patterns.append({"candidate": bar["shape"], "bar_x": bar["x"],
                             "colour": bar["colour"], "confidence": "LOW"})
    bias = "mixed"
    if len(bars) >= 5:
        recent = bars[-5:]
        green_count = sum(1 for b in recent if b["colour"] == "GREEN")
        red_count = 5 - green_count
        bias = "bullish_visual" if green_count >= 4 else (
            "bearish_visual" if red_count >= 4 else "mixed")
    state = "READY" if len(bars) >= 5 else "LOW_DETECTION"
    return {
        **result, "status": state, "image_width": width, "image_height": height,
        "detected_bar_count": len(bars), "colour_counts": counts,
        "recent_visual_bias": bias, "pattern_candidates": patterns,
        "bars": bars[-80:],
        "limitations": [
            "Pixel geometry is approximate and depends on chart theme and screenshot quality.",
            "Price-axis calibration and exact numeric indicator reading are not yet enabled.",
            "Candidate patterns are contextual hints, not confirmed trade signals.",
        ],
    }
