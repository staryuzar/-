from __future__ import annotations

from statistics import median
from typing import Any

import cv2
import numpy as np


def extract_native_geometry_guided_bars(
    bullish: np.ndarray,
    bearish: np.ndarray,
    *,
    native_slot_centers: Any,
    plot_left: int,
    plot_top: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract pixel-supported candles in windows centred on native MT5 X anchors."""
    height, width = bullish.shape
    stats: dict[str, Any] = {
        "status": "NOT_READY", "mode": "mt5_native_geometry_guided",
        "slots_considered": 0, "occupied_slots": 0,
        "rejected_empty_pixels": 0, "rejected_components": 0,
        "rejected_off_center": 0, "rejected_body": 0,
        "mapping_verified": False, "decision_eligible": False,
    }
    if not isinstance(native_slot_centers, list):
        stats.update(status="NATIVE_SLOTS_NOT_PROVIDED")
        return [], stats

    slots: list[tuple[int, float]] = []
    seen: set[int] = set()
    for item in native_slot_centers:
        if not isinstance(item, dict):
            continue
        try:
            slot, x = int(item["slot_index"]), float(item["x_px"]) - plot_left
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if slot < 0 or slot in seen or not np.isfinite(x):
            stats.update(status="NATIVE_SLOT_METADATA_INVALID")
            return [], stats
        seen.add(slot)
        slots.append((slot, x))
    slots.sort(key=lambda row: row[1])
    if len(slots) < 8:
        stats.update(status="NATIVE_SLOTS_INSUFFICIENT", slots_considered=len(slots))
        return [], stats
    xs = [x for _, x in slots]
    if any(xs[i] <= xs[i - 1] for i in range(1, len(xs))):
        stats.update(status="NATIVE_SLOT_X_NOT_MONOTONIC")
        return [], stats
    if xs[0] < -1 or xs[-1] > width + 1:
        stats.update(status="NATIVE_SLOT_OUTSIDE_PLOT")
        return [], stats
    gaps = [xs[i] - xs[i - 1] for i in range(1, len(xs))]
    spacing = float(median(gaps))
    if not np.isfinite(spacing) or spacing < 2:
        stats.update(status="NATIVE_SLOT_SPACING_INVALID")
        return [], stats
    stats.update(status="READY_PROVISIONAL", slots_considered=len(slots),
                 native_median_spacing_px=round(spacing, 3))

    output: list[dict[str, Any]] = []
    residuals: list[float] = []
    purities: list[float] = []
    for i, (slot_id, center) in enumerate(slots):
        left_gap = gaps[i - 1] if i else gaps[0]
        right_gap = gaps[i] if i < len(gaps) else gaps[-1]
        local_spacing = min(left_gap, right_gap)
        half = max(2, int(np.floor(local_spacing * 0.40)))
        x0 = max(0, int(np.floor(center - half)))
        x1 = min(width, int(np.ceil(center + half)) + 1)
        if x1 - x0 < 3:
            stats["rejected_components"] += 1
            continue
        local_mask = bullish[:, x0:x1] | bearish[:, x0:x1]
        if local_mask.size == 0 or not int(local_mask.sum()):
            stats["rejected_empty_pixels"] += 1
            continue

        kernel_h = max(3, int(round(local_spacing * 0.30)))
        if kernel_h % 2 == 0:
            kernel_h += 1
        kernel_h = min(kernel_h, height if height % 2 else max(1, height - 1))
        kernel = np.ones((max(1, kernel_h), 1), dtype=np.uint8)
        core = cv2.morphologyEx(local_mask.astype(np.uint8) * 255,
                                cv2.MORPH_OPEN, kernel) > 0
        if not int(core.sum()):
            stats["rejected_empty_pixels"] += 1
            continue

        count, labels, component_stats, centroids = cv2.connectedComponentsWithStats(
            core.astype(np.uint8), connectivity=8
        )
        retained = np.zeros(core.shape, dtype=bool)
        max_w = max(3, int(np.ceil(local_spacing * 0.60)))
        min_h = max(kernel_h, int(round(local_spacing * 0.22)))
        min_area = max(5, kernel_h * 2)
        local_center = center - x0
        center_tol = min(4.5, max(2.0, local_spacing * 0.25))
        for component_id in range(1, int(count)):
            _, _, comp_w, comp_h, comp_area = (
                int(v) for v in component_stats[component_id]
            )
            if comp_w > max_w or comp_h < min_h or comp_area < min_area or comp_h < comp_w * 0.60:
                continue
            if abs(float(centroids[component_id][0]) - local_center) > center_tol:
                stats["rejected_off_center"] += 1
                continue
            retained[labels == component_id] = True
        if int(retained.sum()) < max(5, kernel_h * 2):
            stats["rejected_components"] += 1
            continue

        support = cv2.dilate(retained.astype(np.uint8) * 255, kernel) > 0
        bull = bullish[:, x0:x1] & support
        bear = bearish[:, x0:x1] & support
        nb, nr = int(bull.sum()), int(bear.sum())
        total = nb + nr
        if total < max(8, int(height * 0.004)) or nb == nr:
            stats["rejected_components"] += 1
            continue
        purity = max(nb, nr) / total
        if purity < 0.70:
            stats["rejected_components"] += 1
            continue

        roi = bull | bear
        ys, pxs = np.where(roi)
        if len(ys) < 5 or len(pxs) < 5:
            stats["rejected_components"] += 1
            continue
        measured_x = float(np.median(pxs + x0))
        residual = abs(measured_x - center)
        if residual > center_tol:
            stats["rejected_off_center"] += 1
            continue
        row_width = roi.sum(axis=1)
        strongest = int(row_width.max()) if len(row_width) else 0
        if strongest < 2:
            stats["rejected_body"] += 1
            continue
        body_rows = np.flatnonzero(row_width >= max(1, int(np.ceil(strongest * 0.75))))
        if len(body_rows) == 0:
            stats["rejected_body"] += 1
            continue
        high_y, low_y = int(ys.min()), int(ys.max())
        body_top, body_bottom = int(body_rows.min()), int(body_rows.max())
        if not high_y <= body_top <= body_bottom <= low_y:
            stats["rejected_body"] += 1
            continue
        active_x = np.flatnonzero(roi.any(axis=0))
        output.append({
            "x_px": round(measured_x + plot_left, 3),
            "width_px": int(active_x.max() - active_x.min() + 1) if len(active_x) else 1,
            "high_y_px": high_y + plot_top, "low_y_px": low_y + plot_top,
            "body_top_y_px": body_top + plot_top,
            "body_bottom_y_px": body_bottom + plot_top,
            "colour": "GREEN" if nb > nr else "RED", "shape": "normal",
            "body_ratio": round(min(1.0, (body_bottom - body_top + 1) / max(1, low_y - high_y + 1)), 3),
            "colour_purity": round(purity, 4),
            "bullish_colour_pixels": nb, "bearish_colour_pixels": nr,
            "palette_mode": "native_geometry_guided",
            "native_slot_hint": slot_id,
            "native_center_residual_px": round(residual, 3),
        })
        residuals.append(residual)
        purities.append(purity)

    stats.update({
        "occupied_slots": len(output),
        "mean_colour_purity": round(float(np.mean(purities)), 4) if purities else 0.0,
        "median_native_x_residual_px": round(float(np.median(residuals)), 3) if residuals else None,
        "maximum_native_x_residual_px": round(max(residuals), 3) if residuals else None,
        "mapping_verified": False, "decision_eligible": False,
        "reason": "Provisional native-centred pixel extraction; exact X assignment and independent OHLC hold-out remain mandatory.",
    })
    return sorted(output, key=lambda row: row["x_px"]), stats
