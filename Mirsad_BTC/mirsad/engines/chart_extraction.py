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

def _extract_slot_guided_bars(
    bullish: np.ndarray,
    bearish: np.ndarray,
    raw_candle_core: np.ndarray,
    vertical_kernel: np.ndarray,
    *,
    expected_candle_count: int,
    plot_left: int,
    plot_top: int,
    minimum_activity: int,
    min_component_height: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover candles one expected slot at a time when overlays join global components.

    The expected count is only a spatial hint: empty slots remain empty and no
    candle is synthesized. The caller keeps the legacy projection result unless
    this path yields materially more high-purity candle candidates.
    """
    height, width = raw_candle_core.shape
    slot_width = width / expected_candle_count
    output: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {
        "mode": "expected_slot_hint",
        "slots_considered": expected_candle_count,
        "occupied_slots": 0,
        "rejected_low_activity": 0,
        "rejected_component_quality": 0,
        "rejected_low_pixels": 0,
        "rejected_mixed_palette": 0,
    }

    for slot_index in range(expected_candle_count):
        slot_left = max(0, int(round(slot_index * slot_width)))
        slot_right = min(width, int(round((slot_index + 1) * slot_width)))
        if slot_right <= slot_left:
            diagnostics["rejected_low_activity"] += 1
            continue
        center = int(round((slot_index + 0.5) * slot_width))
        half_window = max(2, int(round(slot_width * 0.23)))
        candidate_left = max(slot_left, center - half_window)
        candidate_right = min(slot_right, center + half_window + 1)
        if candidate_right <= candidate_left:
            diagnostics["rejected_low_activity"] += 1
            continue

        local_core = raw_candle_core[:, candidate_left:candidate_right]
        if local_core.size == 0 or int(local_core.sum()) == 0:
            diagnostics["rejected_low_activity"] += 1
            continue

        component_count, component_labels, component_stats, _ = cv2.connectedComponentsWithStats(
            local_core.astype(np.uint8),
            connectivity=8,
        )
        retained = np.zeros(local_core.shape, dtype=bool)
        max_local_component_width = max(3, int(np.ceil(slot_width * 0.60)))
        min_vertical_bar_height = max(
            min_component_height * 2,
            int(round(slot_width * 0.50)),
        )
        for component_id in range(1, int(component_count)):
            _, _, comp_width, comp_height, comp_area = (
                int(value) for value in component_stats[component_id]
            )
            if comp_width > max_local_component_width:
                continue
            if comp_height < min_vertical_bar_height or comp_area < max(5, min_component_height):
                continue
            if comp_height < comp_width * 0.80:
                continue
            retained[component_labels == component_id] = True

        if int(retained.sum()) < max(5, minimum_activity * 2):
            diagnostics["rejected_component_quality"] += 1
            continue

        support = cv2.dilate(
            retained.astype(np.uint8) * 255,
            vertical_kernel,
        ) > 0
        bull_roi = bullish[:, candidate_left:candidate_right] & support
        bear_roi = bearish[:, candidate_left:candidate_right] & support
        bull_pixels = int(bull_roi.sum())
        bear_pixels = int(bear_roi.sum())
        total_pixels = bull_pixels + bear_pixels
        if total_pixels < max(8, int(height * 0.006)) or bull_pixels == bear_pixels:
            diagnostics["rejected_low_pixels"] += 1
            continue

        purity = max(bull_pixels, bear_pixels) / total_pixels
        if purity < 0.68:
            diagnostics["rejected_mixed_palette"] += 1
            continue

        roi = bull_roi | bear_roi
        ys, xs = np.where(roi)
        if len(ys) < 5 or len(xs) == 0:
            diagnostics["rejected_low_pixels"] += 1
            continue

        column_activity = retained.sum(axis=0)
        maximum_activity = int(column_activity.max()) if len(column_activity) else 0
        mean_activity = float(column_activity.mean()) if len(column_activity) else 0.0
        vertical_dominance = maximum_activity / max(mean_activity, 1e-9)
        if maximum_activity < minimum_activity or vertical_dominance < 1.15:
            diagnostics["rejected_low_activity"] += 1
            continue
        strongest_columns = np.flatnonzero(column_activity == maximum_activity)
        candle_center = int(round(float(np.mean(strongest_columns))))
        x_px_local = candidate_left + candle_center

        y_high, y_low = int(ys.min()), int(ys.max())
        row_width = roi.sum(axis=1)
        strongest_row = int(row_width.max())
        body_rows = np.flatnonzero(
            row_width >= max(1, int(np.ceil(strongest_row * 0.48)))
        )
        if len(body_rows) == 0:
            diagnostics["rejected_component_quality"] += 1
            continue
        body_top, body_bottom = int(body_rows.min()), int(body_rows.max())
        total_height = max(1, y_low - y_high + 1)
        body_height = max(1, body_bottom - body_top + 1)
        colour = "GREEN" if bull_pixels > bear_pixels else "RED"
        active_x = np.flatnonzero(roi.any(axis=0))
        bar_width = int(active_x.max() - active_x.min() + 1) if len(active_x) else 1
        output.append({
            "x_px": x_px_local + plot_left,
            "width_px": bar_width,
            "high_y_px": y_high + plot_top,
            "low_y_px": y_low + plot_top,
            "body_top_y_px": body_top + plot_top,
            "body_bottom_y_px": body_bottom + plot_top,
            "colour": colour,
            "shape": "normal",
            "body_ratio": round(min(1.0, body_height / total_height), 3),
            "colour_purity": round(purity, 4),
            "vertical_dominance": round(vertical_dominance, 4),
            "bullish_colour_pixels": bull_pixels,
            "bearish_colour_pixels": bear_pixels,
            "palette_mode": "slot_guided",
            "slot_index": slot_index,
        })

    diagnostics["occupied_slots"] = len(output)
    return sorted(output, key=lambda item: item["x_px"]), diagnostics



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

    # Moving averages and Bollinger boundaries can use the same hue as candles.
    # First require vertical persistence, then discard connected components that
    # span many candle slots (long overlays) or are too short to be a wick/body.
    # This avoids merging a full-width MA curve with every candle.
    desired_kernel_height = max(7, int(round(area.shape[0] * 0.018)))
    if desired_kernel_height % 2 == 0:
        desired_kernel_height += 1
    largest_odd_height = area.shape[0] if area.shape[0] % 2 else max(1, area.shape[0] - 1)
    vertical_kernel_height = max(1, min(desired_kernel_height, largest_odd_height))
    vertical_kernel = np.ones((vertical_kernel_height, 1), dtype=np.uint8)
    raw_candle_core = cv2.morphologyEx(
        mask.astype(np.uint8) * 255,
        cv2.MORPH_OPEN,
        vertical_kernel,
    ) > 0

    bars: list[dict[str, Any]] = []
    max_bar_width = max(6, min(32, int(round(area.shape[1] * 0.02))))
    try:
        expected_candle_count = int(meta.get("expected_candle_count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        expected_candle_count = 0
    if expected_candle_count and not 2 <= expected_candle_count <= 500:
        raise ValueError("expected_candle_count must be between 2 and 500")
    slot_width = None
    if expected_candle_count > 0:
        slot_width = area.shape[1] / expected_candle_count
        max_bar_width = max(max_bar_width, min(48, int(round(slot_width * 1.05))))

    # Connected components let us reject long MA/Bollinger traces before they
    # join candles into one full-width projection group. Candle bodies and wicks
    # are vertically persistent and occupy only a fraction of a candle slot.
    component_count, component_labels, component_stats, _ = cv2.connectedComponentsWithStats(
        raw_candle_core.astype(np.uint8),
        connectivity=8,
    )
    candle_core = np.zeros(raw_candle_core.shape, dtype=bool)
    component_diagnostics = {
        "raw_components": max(0, int(component_count) - 1),
        "retained_components": 0,
        "rejected_wide_components": 0,
        "rejected_short_components": 0,
        "rejected_flat_components": 0,
    }
    min_component_height = max(vertical_kernel_height, int(np.ceil(area.shape[0] * 0.018)))
    for component_id in range(1, int(component_count)):
        x, y, component_width, component_height, component_area = (
            int(value) for value in component_stats[component_id]
        )
        if component_width > max_bar_width:
            component_diagnostics["rejected_wide_components"] += 1
            continue
        if component_height < min_component_height or component_area < max(5, min_component_height):
            component_diagnostics["rejected_short_components"] += 1
            continue
        if component_height < component_width * 0.80:
            component_diagnostics["rejected_flat_components"] += 1
            continue
        candle_core[component_labels == component_id] = True
        component_diagnostics["retained_components"] += 1

    # Expand retained candle components only along y to recover anti-aliased
    # body/wick edges. Excluded long overlay components stay excluded.
    candle_support = cv2.dilate(
        candle_core.astype(np.uint8) * 255,
        vertical_kernel,
    ) > 0
    candle_bullish = bullish & candle_support
    candle_bearish = bearish & candle_support

    activity = candle_core.sum(axis=0)
    minimum_activity = max(1, int(np.ceil(area.shape[0] * 0.0008)))
    groups = _groups(activity >= minimum_activity, gap=2)
    rejection_counts = {"wide_group": 0, "low_pixel_count": 0, "mixed_palette": 0, "short_component": 0, "no_body": 0}
    if diagnostics is not None:
        diagnostics.update({
            "palette_mode": palette_mode,
            "bullish_palette_pixels": int(bullish.sum()),
            "bearish_palette_pixels": int(bearish.sum()),
            "raw_active_columns": int(np.count_nonzero(mask.sum(axis=0) >= minimum_activity)),
            "morphology_active_columns": int(np.count_nonzero(raw_candle_core.sum(axis=0) >= minimum_activity)),
            "active_columns": int(np.count_nonzero(activity >= minimum_activity)),
            "vertical_kernel_height": vertical_kernel_height,
            "component_filter": component_diagnostics,
            "minimum_component_height": min_component_height,
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
    slot_diagnostics: dict[str, Any] = {"mode": "disabled", "occupied_slots": 0}
    selected_mode = "projection_groups"
    if expected_candle_count > 0:
        slot_bars, slot_diagnostics = _extract_slot_guided_bars(
            bullish, bearish, raw_candle_core, vertical_kernel,
            expected_candle_count=expected_candle_count,
            plot_left=left, plot_top=top,
            minimum_activity=minimum_activity,
            min_component_height=min_component_height,
        )
        slot_mean_purity = (
            float(np.mean([bar["colour_purity"] for bar in slot_bars]))
            if slot_bars else 0.0
        )
        minimum_slot_recovery = max(
            8,
            int(np.ceil(expected_candle_count * 0.40)),
            len(bars) + 1,
        )
        # Only replace the legacy parser when slot evidence recovers more bars
        # and average palette purity remains high; otherwise retain old output.
        if (
            len(slot_bars) >= minimum_slot_recovery
            and slot_mean_purity >= 0.75
        ):
            bars = slot_bars
            selected_mode = "expected_slot_hint"
        slot_diagnostics["mean_colour_purity"] = round(slot_mean_purity, 4)
        slot_diagnostics["minimum_recovery_threshold"] = minimum_slot_recovery
        slot_diagnostics["adopted"] = selected_mode == "expected_slot_hint"

    if diagnostics is not None:
        diagnostics["accepted_bars"] = len(bars)
        diagnostics["rejected_groups"] = rejection_counts
        diagnostics["slot_guided_extraction"] = slot_diagnostics
        diagnostics["segmentation_mode"] = selected_mode
    return sorted(bars, key=lambda item: item["x_px"])
