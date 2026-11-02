from __future__ import annotations

from typing import Any

import cv2
import numpy as np

def _groups(columns:np.ndarray,gap:int=2)->list[tuple[int,int]]:
    indices=np.flatnonzero(columns)
    if len(indices)==0:
        return []
    result=[]
    start=previous=int(indices[0])
    for value in indices[1:]:
        current=int(value)
        if current-previous>gap+1:
            result.append((start,previous))
            start=current
        previous=current
    result.append((start,previous))
    return result

PALETTE_PRESETS: dict[str, dict[str, list[tuple[int, int]]]] = {
    "auto": {"bullish": [(34, 96), (97, 140)], "bearish": [(0, 30), (160, 179)]},
    "green_red": {"bullish": [(34, 96)], "bearish": [(0, 12), (165, 179)]},
    "blue_orange": {"bullish": [(97, 140)], "bearish": [(8, 30), (165, 179)]},
    "teal_magenta": {"bullish": [(75, 110)], "bearish": [(135, 179)]},
}


def _hue_mask(hsv: np.ndarray, ranges: list[tuple[int, int]]) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in ranges:
        part = cv2.inRange(
            hsv,
            np.array([lower, 45, 35], dtype=np.uint8),
            np.array([upper, 255, 255], dtype=np.uint8),
        )
        mask = cv2.bitwise_or(mask, part)
    return mask


def _extract_bars(
    image: np.ndarray, meta: dict[str, Any], diagnostics: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    height, width = image.shape[:2]
    left = int(meta.get("plot_left_px", 0) or 0)
    right_value = int(meta.get("plot_right_px", 0) or 0)
    right = width if right_value <= 0 else right_value
    top = int(meta.get("plot_top_px", 0) or 0)
    bottom_value = int(meta.get("plot_bottom_px", 0) or 0)
    bottom = height if bottom_value <= 0 else bottom_value
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("plot bounds must be inside the image and have positive width/height")

    area = image[top:bottom, left:right]
    if area.size == 0:
        return []
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    palette_mode = str(meta.get("palette_mode", "auto")).strip().lower()
    if palette_mode not in PALETTE_PRESETS:
        raise ValueError(f"Unsupported palette_mode: {palette_mode}")
    palette = PALETTE_PRESETS[palette_mode]
    bullish = _hue_mask(hsv, palette["bullish"]) > 0
    bearish = _hue_mask(hsv, palette["bearish"]) > 0
    mask = bullish | bearish

    # Moving-average curves and other colored indicators can run across nearly
    # every x-column. Retain vertically persistent candle cores/wicks for the
    # column projection; use the original color masks below for OHLC geometry.
    desired_kernel_height = max(3, int(round(area.shape[0] * 0.015)))
    if desired_kernel_height % 2 == 0:
        desired_kernel_height += 1
    largest_odd_height = area.shape[0] if area.shape[0] % 2 else max(1, area.shape[0] - 1)
    vertical_kernel_height = max(1, min(desired_kernel_height, largest_odd_height))
    vertical_kernel = np.ones((vertical_kernel_height, 1), dtype=np.uint8)
    candle_core = cv2.morphologyEx(
        mask.astype(np.uint8) * 255,
        cv2.MORPH_OPEN,
        vertical_kernel,
    ) > 0
    # Expand the candle core only along y to restore the original wick/body
    # edges; indicator lines removed by opening stay excluded from OHLC geometry.
    candle_support = cv2.dilate(
        candle_core.astype(np.uint8) * 255,
        vertical_kernel,
    ) > 0
    candle_bullish = bullish & candle_support
    candle_bearish = bearish & candle_support

    activity = candle_core.sum(axis=0)
    minimum_activity = max(1, int(np.ceil(area.shape[0] * 0.0008)))
    # Allow tiny anti-alias gaps between wick/body pixels, as seen in resized web charts.
    groups = _groups(activity >= minimum_activity, gap=2)
    bars: list[dict[str, Any]] = []
    # Public chart images vary significantly in resolution and candle thickness.
    # A 1.2% / 18 px cap discarded valid ~19 px candles on high-resolution charts.
    max_bar_width = max(6, min(32, int(round(area.shape[1] * 0.02))))
    try:
        expected_candle_count = int(meta.get("expected_candle_count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        expected_candle_count = 0
    if expected_candle_count and not 2 <= expected_candle_count <= 500:
        raise ValueError("expected_candle_count must be between 2 and 500")
    if expected_candle_count > 0:
        # Fixed-window educational renders have known candle slots. Use the
        # slot geometry so thick bodies are not mistaken for overlays.
        slot_width = area.shape[1] / expected_candle_count
        max_bar_width = max(max_bar_width, min(48, int(round(slot_width * 1.05))))
    rejection_counts = {"wide_group": 0, "low_pixel_count": 0, "mixed_palette": 0, "short_component": 0, "no_body": 0}
    if diagnostics is not None:
        diagnostics.update({
            "palette_mode": palette_mode,
            "bullish_palette_pixels": int(bullish.sum()),
            "bearish_palette_pixels": int(bearish.sum()),
            "raw_active_columns": int(np.count_nonzero(mask.sum(axis=0) >= minimum_activity)),
            "active_columns": int(np.count_nonzero(activity >= minimum_activity)),
            "vertical_kernel_height": vertical_kernel_height,
            "indicator_pixels_suppressed": int(
                mask.sum() - np.count_nonzero(candle_bullish | candle_bearish)
            ),
            "projection_groups": len(groups),
            "projection_group_widths": [int(x1 - x0 + 1) for x0, x1 in groups[:500]],
            "minimum_activity_per_column": minimum_activity,
            "maximum_bar_width": max_bar_width,
        })

    for x0, x1 in groups:
        group_width = x1 - x0 + 1
        if group_width > max_bar_width:
            rejection_counts["wide_group"] += 1
            continue
        bull_roi = candle_bullish[:, x0:x1 + 1]
        bear_roi = candle_bearish[:, x0:x1 + 1]
        bull_pixels = int(bull_roi.sum())
        bear_pixels = int(bear_roi.sum())
        total_pixels = bull_pixels + bear_pixels
        if total_pixels < max(8, int(area.shape[0] * 0.008)) or bull_pixels == bear_pixels:
            rejection_counts["low_pixel_count"] += 1
            continue
        colour_purity = max(bull_pixels, bear_pixels) / total_pixels
        if colour_purity < 0.68:
            rejection_counts["mixed_palette"] += 1
            continue
        colour = "GREEN" if bull_pixels > bear_pixels else "RED"
        roi = bull_roi | bear_roi
        ys, _ = np.where(roi)
        if len(ys) < 5:
            rejection_counts["short_component"] += 1
            continue
        y_high, y_low = int(ys.min()), int(ys.max())
        row_width = roi.sum(axis=1)
        strongest = int(row_width.max())
        if strongest <= 0:
            continue
        body_rows = np.flatnonzero(row_width >= max(1, int(np.ceil(strongest * 0.48))))
        if len(body_rows) == 0:
            rejection_counts["no_body"] += 1
            continue
        body_top, body_bottom = int(body_rows.min()), int(body_rows.max())
        total_h = max(1, y_low - y_high + 1)
        body_h = max(1, body_bottom - body_top + 1)
        upper, lower = max(0, body_top - y_high), max(0, y_low - body_bottom)
        ratio = min(1.0, body_h / total_h)

        # Single-candle patterns are classified later using prior-candle context.
        shape = "normal"

        bars.append({
            "x_px": int((x0 + x1) / 2) + left,
            "width_px": group_width,
            "high_y_px": y_high + top,
            "low_y_px": y_low + top,
            "body_top_y_px": body_top + top,
            "body_bottom_y_px": body_bottom + top,
            "colour": colour,
            "shape": shape,
            "body_ratio": round(ratio, 3),
            "colour_purity": round(colour_purity, 4),
            "bullish_colour_pixels": bull_pixels,
            "bearish_colour_pixels": bear_pixels,
            "palette_mode": palette_mode,
        })
    if diagnostics is not None:
        diagnostics["accepted_bars"] = len(bars)
        diagnostics["rejected_groups"] = rejection_counts
    return sorted(bars, key=lambda item: item["x_px"])
