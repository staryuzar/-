from __future__ import annotations

import math
from statistics import median
from typing import Any

GEOMETRY_SCHEMA = "MIR-MT5-CHART-GEOMETRY-1"
_POINT_FIELDS = ("open", "high", "low", "close")


def native_geometry_visible_y_max(native_geometry: Any) -> float | None:
    """Return the greatest provisional image Y among valid visible native OHLC points."""
    if not isinstance(native_geometry, dict) or native_geometry.get("status") != "READY_FOR_PIXEL_ALIGNMENT":
        return None
    bars = native_geometry.get("bars")
    if not isinstance(bars, list):
        return None
    values: list[float] = []
    for bar in bars:
        if not isinstance(bar, dict) or bar.get("valid") is not True or bar.get("visible") is not True:
            continue
        points = bar.get("points_image_px_provisional")
        if not isinstance(points, dict):
            continue
        for point in points.values():
            if not isinstance(point, dict):
                continue
            try:
                y = float(point["y"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(y):
                values.append(y)
    return max(values) if values else None


def native_geometry_slot_centers(
    native_geometry: Any,
    *,
    native_bar_count: int,
    visible_bars: int,
    first_visible_bar_shift: int,
) -> dict[str, Any]:
    """Build provisional image-X anchors for exact MT5 visible-bar slots.

    The source X coordinates come from ChartTimePriceToXY and are scaled only
    by the declared screenshot/source width ratio. They are matching hints, not
    a verified overlay or permission to make a trading decision.
    """
    def fail(status: str, reason: str) -> dict[str, Any]:
        return {
            "status": status,
            "decision_eligible": False,
            "mapping_verified": False,
            "reason": reason,
            "slots": [],
        }

    if not isinstance(native_geometry, dict) or native_geometry.get("status") not in {
        "READY_FOR_PIXEL_ALIGNMENT", "PARTIAL"
    }:
        return fail("GEOMETRY_NOT_READY", "Native geometry is not available for provisional slot matching.")
    if native_bar_count < 8 or visible_bars < 8 or first_visible_bar_shift < 0:
        return fail("INVALID_VIEWPORT", "Native bar count, visible bar count or first-visible shift is invalid.")
    items = native_geometry.get("bars")
    if not isinstance(items, list) or len(items) != native_bar_count:
        return fail("GEOMETRY_BAR_COUNT_MISMATCH", "Native geometry does not cover the complete OHLC array.")

    rightmost_visible_offset = max(0, first_visible_bar_shift - visible_bars + 1)
    slots: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("valid") is not True or item.get("visible") is not True:
            continue
        offset = native_bar_count - 1 - index
        relative_offset = offset - rightmost_visible_offset
        if not 0 <= relative_offset < visible_bars:
            continue
        slot_index = visible_bars - 1 - relative_offset
        try:
            x_px = float(item["x_image_px_provisional"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(x_px) or slot_index in seen:
            continue
        seen.add(slot_index)
        slots.append({"slot_index": slot_index, "x_px": x_px})

    slots.sort(key=lambda item: item["x_px"])
    if len(slots) < 8:
        return {
            **fail("INSUFFICIENT_NATIVE_SLOTS", "At least eight visible native X anchors are required."),
            "native_slot_count": len(slots),
        }
    return {
        "status": "READY_PROVISIONAL",
        "decision_eligible": False,
        "mapping_verified": False,
        "method": "MT5_CHART_TIME_PRICE_TO_XY_WITH_DECLARED_WIDTH_RATIO",
        "native_slot_count": len(slots),
        "slots": slots,
        "reason": "Native X anchors are available for provisional one-to-one candle matching; independent overlay validation remains mandatory.",
    }


def infer_regular_chart_slot_centers(
    extracted_bars: list[dict[str, Any]],
    *,
    expected_candle_count: int,
    image_width: int,
    reference_last_candle_x_ratio: float,
    anchor_tolerance_ratio: float = 0.025,
    minimum_gap_integrity: float = 0.80,
    maximum_gap_multiple: int = 4,
) -> dict[str, Any]:
    """Infer a dataset-scoped regular candle grid from a verified right-edge anchor.

    This fallback is opt-in and intended for benchmark datasets with a known,
    stable right-shift margin. It must never be enabled for live MT5 captures:
    live charts should use native ChartTimePriceToXY slot anchors instead.
    """
    def fail(status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": status,
            "decision_eligible": False,
            "mapping_verified": False,
            "reason": reason,
            "slots": [],
            **extra,
        }

    if expected_candle_count < 8 or image_width < 64:
        return fail("INVALID_GRID_DIMENSIONS", "Expected candle count or image width is too small.")
    if (
        not math.isfinite(reference_last_candle_x_ratio)
        or not 0.0 < reference_last_candle_x_ratio < 1.0
        or not math.isfinite(anchor_tolerance_ratio)
        or anchor_tolerance_ratio <= 0.0
        or not 0.0 < minimum_gap_integrity <= 1.0
        or maximum_gap_multiple < 1
    ):
        return fail("INVALID_GRID_CONFIGURATION", "Right-edge anchor or grid-quality thresholds are invalid.")

    rows: list[dict[str, float]] = []
    for item in extracted_bars:
        if not isinstance(item, dict):
            continue
        try:
            x_px = float(item["x_px"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(x_px):
            rows.append({"x_px": x_px})
    rows.sort(key=lambda item: item["x_px"])
    minimum_rows = max(8, int(math.ceil(expected_candle_count * 0.65)))
    if len(rows) < minimum_rows or len(rows) > int(math.ceil(expected_candle_count * 1.25)):
        return fail(
            "EXTRACTED_COUNT_OUTSIDE_GRID_RANGE",
            "Detected candle count is outside the safe range for regular-grid inference.",
            extracted_bar_count=len(rows),
            minimum_required=minimum_rows,
            expected_candle_count=expected_candle_count,
        )

    rightmost_x = float(rows[-1]["x_px"])
    observed_ratio = rightmost_x / float(image_width)
    anchor_delta = abs(observed_ratio - reference_last_candle_x_ratio)
    if anchor_delta > anchor_tolerance_ratio:
        return fail(
            "RIGHTMOST_ANCHOR_MISMATCH",
            "The rightmost detected candle does not match the dataset's declared last-candle X anchor.",
            observed_rightmost_x_ratio=round(observed_ratio, 5),
            expected_rightmost_x_ratio=round(reference_last_candle_x_ratio, 5),
            anchor_delta_ratio=round(anchor_delta, 5),
            anchor_tolerance_ratio=round(anchor_tolerance_ratio, 5),
        )

    gaps = [
        float(rows[index]["x_px"]) - float(rows[index - 1]["x_px"])
        for index in range(1, len(rows))
    ]
    if not gaps or any(gap <= 0.0 for gap in gaps):
        return fail("NON_MONOTONIC_EXTRACTED_X", "Extracted candle X positions are not strictly increasing.")
    spacing = float(median(gaps))
    if not math.isfinite(spacing) or spacing < 2.5:
        return fail("GRID_SPACING_INVALID", "Median candle spacing is too small or non-finite.")

    gap_tolerance = max(1.5, spacing * 0.22)
    valid_gaps = 0
    gap_multiples: list[int] = []
    for gap in gaps:
        multiple = int(round(gap / spacing))
        if (
            1 <= multiple <= maximum_gap_multiple
            and abs(gap - multiple * spacing) <= gap_tolerance
        ):
            valid_gaps += 1
            gap_multiples.append(multiple)
    integrity = valid_gaps / len(gaps)
    if integrity < minimum_gap_integrity:
        return fail(
            "GRID_GAP_INTEGRITY_LOW",
            "Detected candle gaps do not follow a sufficiently consistent regular grid.",
            median_spacing_px=round(spacing, 3),
            gap_integrity_ratio=round(integrity, 4),
            valid_gap_count=valid_gaps,
            total_gap_count=len(gaps),
        )

    first_x = rightmost_x - spacing * (expected_candle_count - 1)
    if first_x < -gap_tolerance or first_x > image_width * 0.20:
        return fail(
            "GRID_LEFT_EDGE_INCONSISTENT",
            "The inferred first candle falls outside the expected chart-image left margin.",
            inferred_first_x_px=round(first_x, 3),
            image_width_px=image_width,
            median_spacing_px=round(spacing, 3),
        )

    slots = [
        {"slot_index": index, "x_px": first_x + index * spacing}
        for index in range(expected_candle_count)
    ]
    return {
        "status": "READY_PROVISIONAL",
        "decision_eligible": False,
        "mapping_verified": False,
        "method": "DATASET_DECLARED_RIGHTMOST_X_ANCHOR_AND_MEDIAN_GAP",
        "expected_candle_count": expected_candle_count,
        "extracted_bar_count": len(rows),
        "expected_rightmost_x_ratio": round(reference_last_candle_x_ratio, 5),
        "observed_rightmost_x_ratio": round(observed_ratio, 5),
        "anchor_delta_ratio": round(anchor_delta, 5),
        "anchor_tolerance_ratio": round(anchor_tolerance_ratio, 5),
        "median_spacing_px": round(spacing, 3),
        "gap_integrity_ratio": round(integrity, 4),
        "valid_gap_count": valid_gaps,
        "total_gap_count": len(gaps),
        "gap_multiples_sample": gap_multiples[:20],
        "slots": slots,
        "reason": "Dataset-specific regular-grid anchors are provisional; candle OHLC fit and all independent quality gates remain mandatory.",
    }


def assign_native_geometry_slots(
    extracted_bars: list[dict[str, Any]],
    native_slot_centers: Any,
    *,
    source: str = "MT5_NATIVE_GEOMETRY_PROVISIONAL_X",
    clear_existing_slot_ids_on_failure: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assign exact MT5 slot IDs to detected image bars using provisional native X anchors.

    A monotonic one-to-one dynamic-programming match tolerates missing extracted
    candles without ordinal guessing. Assignment is diagnostic only: the later
    OHLC fit and independent image-overlay hold-out must still pass.
    """
    original = [dict(item) for item in extracted_bars if isinstance(item, dict)]

    def fail(status: str, reason: str, **extra: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        cleared_unverified_slot_count = 0
        if clear_existing_slot_ids_on_failure:
            # A failed native-X match must not leave earlier regular-grid IDs
            # looking authoritative to downstream reference-candle matching.
            for item in original:
                if "slot_index" in item:
                    cleared_unverified_slot_count += 1
                item.pop("slot_index", None)
                item.pop("slot_assignment_source", None)
                item.pop("native_geometry_x_residual_px", None)
        diagnostics = {
            "status": status,
            "mapping_verified": False,
            "decision_eligible": False,
            "reason": reason,
            **extra,
        }
        if clear_existing_slot_ids_on_failure:
            diagnostics["cleared_unverified_slot_count"] = cleared_unverified_slot_count
        return original, diagnostics

    if not isinstance(native_slot_centers, list):
        return fail("NATIVE_SLOTS_NOT_PROVIDED", "No native MT5 slot centers were supplied.")
    native_slots: list[dict[str, float | int]] = []
    seen_slots: set[int] = set()
    for item in native_slot_centers:
        if not isinstance(item, dict):
            continue
        try:
            slot = int(item["slot_index"])
            x_px = float(item["x_px"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if slot < 0 or not math.isfinite(x_px) or slot in seen_slots:
            continue
        seen_slots.add(slot)
        native_slots.append({"slot_index": slot, "x_px": x_px})
    native_slots.sort(key=lambda item: float(item["x_px"]))
    if len(native_slots) < 8:
        return fail("INSUFFICIENT_NATIVE_SLOTS", "At least eight unique native slot centers are required.")

    extracted_rows: list[dict[str, Any]] = []
    for original_index, item in enumerate(extracted_bars):
        if not isinstance(item, dict):
            continue
        try:
            x_px = float(item["x_px"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(x_px):
            extracted_rows.append({"original_index": original_index, "x_px": x_px})
    extracted_rows.sort(key=lambda item: float(item["x_px"]))
    if len(extracted_rows) < 8:
        return fail("INSUFFICIENT_EXTRACTED_BARS", "At least eight image candles with finite X coordinates are required.")

    spacings = [
        float(native_slots[index]["x_px"]) - float(native_slots[index - 1]["x_px"])
        for index in range(1, len(native_slots))
        if float(native_slots[index]["x_px"]) > float(native_slots[index - 1]["x_px"])
    ]
    if len(spacings) < 2:
        return fail("NATIVE_X_SPACING_INVALID", "Native candle X anchors do not provide stable spacing.")
    spacing = float(median(spacings))
    tolerance = max(2.5, min(10.0, spacing * 0.30))
    n, m = len(native_slots), len(extracted_rows)

    def match_slots(
        candidate_slots: list[dict[str, Any]], match_tolerance: float
    ) -> list[tuple[int, int]]:
        n, m = len(candidate_slots), len(extracted_rows)
        match_count = [[0] * (m + 1) for _ in range(n + 1)]
        residual_sum = [[0.0] * (m + 1) for _ in range(n + 1)]
        action = [[""] * (m + 1) for _ in range(n + 1)]
        for row in range(1, n + 1):
            action[row][0] = "skip_native"
        for column in range(1, m + 1):
            action[0][column] = "skip_extracted"

        def better(candidate: tuple[int, float], current: tuple[int, float]) -> bool:
            return (
                candidate[0] > current[0]
                or (candidate[0] == current[0] and candidate[1] < current[1] - 1e-9)
            )

        for row in range(1, n + 1):
            for column in range(1, m + 1):
                best = (match_count[row - 1][column], residual_sum[row - 1][column])
                best_action = "skip_native"
                skip_extracted = (
                    match_count[row][column - 1],
                    residual_sum[row][column - 1],
                )
                if better(skip_extracted, best):
                    best, best_action = skip_extracted, "skip_extracted"
                residual = abs(
                    float(candidate_slots[row - 1]["x_px"])
                    - float(extracted_rows[column - 1]["x_px"])
                )
                if residual <= match_tolerance:
                    matched = (
                        match_count[row - 1][column - 1] + 1,
                        residual_sum[row - 1][column - 1] + residual,
                    )
                    if better(matched, best):
                        best, best_action = matched, "match"
                match_count[row][column], residual_sum[row][column] = best
                action[row][column] = best_action

        pairs: list[tuple[int, int]] = []
        row, column = n, m
        while row > 0 or column > 0:
            step = action[row][column] if row >= 0 and column >= 0 else ""
            if step == "match":
                pairs.append((row - 1, column - 1))
                row -= 1
                column -= 1
            elif step == "skip_native" and row > 0:
                row -= 1
            elif step == "skip_extracted" and column > 0:
                column -= 1
            elif row > 0:
                row -= 1
            elif column > 0:
                column -= 1
            else:
                break
        pairs.reverse()
        return pairs

    pairs: list[tuple[int, int]] = []
    aligned_native_slots = [dict(item) for item in native_slots]
    x_scale, x_offset = 1.0, 0.0
    x_refinement_used = False
    x_refinement_source = "NOT_USED"

    # The slot IDs emitted by slot-guided extraction are provisional spatial
    # hints, but they preserve a global slot identity. Use only exact ID
    # correspondences spanning enough of the viewport to estimate the affine
    # screenshot transform; then re-match all candles against transformed native
    # centers. This avoids a local DP match jumping by one candle after scale drift.
    native_index_by_slot = {
        int(item["slot_index"]): index
        for index, item in enumerate(native_slots)
    }
    extracted_index_by_original = {
        int(item["original_index"]): index
        for index, item in enumerate(extracted_rows)
    }
    hint_pairs: list[tuple[int, int]] = []
    for original_index, item in enumerate(extracted_bars):
        if not isinstance(item, dict):
            continue
        try:
            slot = int(item.get("slot_index"))
            float(item["x_px"])
            native_index = native_index_by_slot.get(slot)
            extracted_index = extracted_index_by_original.get(original_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if native_index is not None and extracted_index is not None:
            hint_pairs.append((native_index, extracted_index))

    if len(hint_pairs) >= 8:
        hint_x = [float(native_slots[a]["x_px"]) for a, _ in hint_pairs]
        native_span = max(float(item["x_px"]) for item in native_slots) - min(
            float(item["x_px"]) for item in native_slots
        )
        hint_coverage = (
            (max(hint_x) - min(hint_x)) / native_span if native_span > 0 else 0.0
        )
        seed_pairs = [
            (
                float(native_slots[native_index]["x_px"]),
                float(extracted_rows[extracted_index]["x_px"]),
            )
            for native_index, extracted_index in hint_pairs
        ]
        slopes = [
            (y2 - y1) / (x2 - x1)
            for index, (x1, y1) in enumerate(seed_pairs)
            for x2, y2 in seed_pairs[index + 1:]
            if abs(x2 - x1) >= spacing * 2.0
        ]
        if slopes and hint_coverage >= 0.25:
            candidate_scale = float(median(slopes))
            candidate_offset = float(median(
                y - candidate_scale * x for x, y in seed_pairs
            ))
            transform_residuals = [
                abs(candidate_scale * x + candidate_offset - y)
                for x, y in seed_pairs
            ]
            image_width = max(
                float(row["x_px"]) for row in extracted_rows
            ) - min(float(row["x_px"]) for row in extracted_rows)
            inlier_ratio = sum(
                residual <= tolerance for residual in transform_residuals
            ) / len(transform_residuals)
            transform_is_plausible = (
                math.isfinite(candidate_scale)
                and math.isfinite(candidate_offset)
                and 0.80 <= candidate_scale <= 1.20
                and abs(candidate_offset) <= max(40.0, image_width * 0.08)
                and float(median(transform_residuals)) <= max(2.5, tolerance * 0.75)
                and inlier_ratio >= 0.75
            )
            if transform_is_plausible:
                candidate_slots = [
                    {
                        **item,
                        "x_px": candidate_scale * float(item["x_px"]) + candidate_offset,
                    }
                    for item in native_slots
                ]
                refined_pairs = match_slots(candidate_slots, tolerance)
                if len(refined_pairs) >= len(hint_pairs):
                    pairs = refined_pairs
                    aligned_native_slots = candidate_slots
                    x_scale, x_offset = candidate_scale, candidate_offset
                    x_refinement_used = True
                    x_refinement_source = "PREEXISTING_SLOT_ID_ANCHORS"

    if not pairs:
        pairs = match_slots(native_slots, tolerance)

    if len(pairs) < 8:
        return fail(
            "INSUFFICIENT_X_MATCHES",
            "Fewer than eight extracted candles align with distinct native MT5 X anchors.",
            matched_candles=len(pairs),
            native_slot_count=n,
            extracted_bar_count=m,
            tolerance_px=round(tolerance, 3),
        )

    matched_native_x = [float(native_slots[a]["x_px"]) for a, _ in pairs]
    native_span = max(float(item["x_px"]) for item in native_slots) - min(
        float(item["x_px"]) for item in native_slots
    )
    coverage = (
        (max(matched_native_x) - min(matched_native_x)) / native_span
        if native_span > 0 else 0.0
    )
    if coverage < 0.25:
        return fail(
            "X_MATCH_COVERAGE_LOW",
            "Native/image X matches do not span at least 25% of the visible native candle range.",
            matched_candles=len(pairs),
            x_coverage_ratio=round(coverage, 4),
            tolerance_px=round(tolerance, 3),
        )

    assigned = [dict(item) if isinstance(item, dict) else item for item in extracted_bars]
    previous_slot_values = [
        item.get("slot_index") if isinstance(item, dict) else None
        for item in extracted_bars
    ]
    cleared_existing_slot_count = sum(value is not None for value in previous_slot_values)
    # Native X anchors supersede any earlier uniform-grid/slot-guided IDs.
    # Clear every old ID first so unmatched bars cannot leave duplicate slots.
    for item in assigned:
        if isinstance(item, dict):
            item.pop("slot_index", None)
            item.pop("slot_assignment_source", None)
            item.pop("native_geometry_x_residual_px", None)
    residuals: list[float] = []
    conflicts = 0
    sample: list[dict[str, Any]] = []
    for native_index, extracted_index in pairs:
        native = native_slots[native_index]
        extracted = extracted_rows[extracted_index]
        original_index = int(extracted["original_index"])
        target = assigned[original_index]
        slot = int(native["slot_index"])
        previous = previous_slot_values[original_index]
        if previous is not None:
            try:
                if int(previous) != slot:
                    conflicts += 1
            except (TypeError, ValueError, OverflowError):
                conflicts += 1
        aligned_x = float(aligned_native_slots[native_index]["x_px"])
        residual = abs(aligned_x - float(extracted["x_px"]))
        target["slot_index"] = slot
        target["native_geometry_x_residual_px"] = round(residual, 3)
        target["slot_assignment_source"] = source
        residuals.append(residual)
        if len(sample) < 8:
            sample.append({
                "slot_index": slot,
                "native_x_px": round(float(native["x_px"]), 3),
                "aligned_native_x_px": round(aligned_x, 3),
                "image_x_px": round(float(extracted["x_px"]), 3),
                "residual_px": round(residual, 3),
            })

    return assigned, {
        "status": "PROVISIONAL_ASSIGNMENT",
        "mapping_verified": False,
        "decision_eligible": False,
        "method": "monotonic_one_to_one_x_match_with_provisional_affine_refinement",
        "x_affine_refinement_used": x_refinement_used,
        "x_affine_refinement_source": x_refinement_source,
        "x_affine_scale": round(x_scale, 8),
        "x_affine_offset_px": round(x_offset, 4),
        "matched_candles": len(pairs),
        "native_slot_count": n,
        "native_slot_x_min_px": round(min(float(item["x_px"]) for item in native_slots), 3),
        "native_slot_x_max_px": round(max(float(item["x_px"]) for item in native_slots), 3),
        "extracted_bar_count": m,
        "x_coverage_ratio": round(coverage, 4),
        "tolerance_px": round(tolerance, 3),
        "median_residual_px": round(float(median(residuals)), 3),
        "maximum_residual_px": round(max(residuals), 3),
        "preexisting_slot_conflicts": conflicts,
        "cleared_existing_slot_count": cleared_existing_slot_count,
        "sample_matches": sample,
        "reason": "Slot IDs are provisional X matches only; exact OHLC fit and independent overlay hold-out remain required.",
    }


def validate_mt5_chart_geometry(
    raw_geometry: Any,
    *,
    bars: list[dict[str, Any]],
    chart: dict[str, Any],
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Validate MT5's native time/price-to-pixel geometry without trusting its claims.

    The returned image coordinates are provisional dimension-ratio transforms.
    They remain ineligible for visual alignment until a separate pixel-overlay
    check verifies the transform against the PNG itself.
    """
    if not isinstance(raw_geometry, dict):
        return {
            "status": "NOT_AVAILABLE",
            "decision_eligible": False,
            "reason": "The capture has no native MT5 pixel-geometry payload.",
            "bars": [],
        }

    if raw_geometry.get("schema") != GEOMETRY_SCHEMA:
        return {
            "status": "SCHEMA_MISMATCH",
            "decision_eligible": False,
            "reason": "The MT5 pixel-geometry schema is missing or unsupported.",
            "bars": [],
        }
    if raw_geometry.get("coordinate_source") != "MQL5_CHART_TIME_PRICE_TO_XY":
        return {
            "status": "SOURCE_MISMATCH",
            "decision_eligible": False,
            "reason": "Pixel coordinates are not identified as native ChartTimePriceToXY output.",
            "bars": [],
        }
    if raw_geometry.get("coordinate_origin") != "MAIN_CHART_WINDOW_TOP_LEFT":
        return {
            "status": "ORIGIN_MISMATCH",
            "decision_eligible": False,
            "reason": "The coordinate origin is not the main chart window's upper-left corner.",
            "bars": [],
        }

    try:
        source_width = int(raw_geometry["source_width_px"])
        source_height = int(raw_geometry["source_height_px"])
        declared_image_width = int(raw_geometry["image_width_px"])
        declared_image_height = int(raw_geometry["image_height_px"])
        declared_total = int(raw_geometry["bars_total"])
        declared_valid = int(raw_geometry["bars_valid"])
        declared_visible = int(raw_geometry["bars_visible"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {
            "status": "INVALID_METADATA",
            "decision_eligible": False,
            "reason": "Native geometry dimensions or counters are incomplete.",
            "bars": [],
        }

    chart_width = int(chart.get("source_width_px", 0) or 0)
    chart_height = int(chart.get("source_main_window_height_px", 0) or 0)
    if (
        source_width <= 0 or source_height <= 0
        or source_width != chart_width or source_height != chart_height
    ):
        return {
            "status": "SOURCE_DIMENSION_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry dimensions do not match the chart manifest dimensions.",
            "bars": [],
        }
    if declared_image_width != int(image_width) or declared_image_height != int(image_height):
        return {
            "status": "IMAGE_DIMENSION_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry dimensions do not match the decoded PNG dimensions.",
            "bars": [],
        }
    if declared_total != len(bars):
        return {
            "status": "BAR_COUNT_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry bar count does not match the CopyRates OHLC array.",
            "bars": [],
        }

    raw_items = raw_geometry.get("bars")
    if not isinstance(raw_items, list) or len(raw_items) != len(bars):
        return {
            "status": "BAR_ARRAY_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry must contain one item for every copied OHLC bar.",
            "bars": [],
        }

    scale_x = image_width / source_width
    scale_y = image_height / source_height
    output: list[dict[str, Any]] = []
    valid_count = 0
    visible_count = 0
    previous_x: float | None = None

    for index, (item, native) in enumerate(zip(raw_items, bars)):
        if not isinstance(item, dict):
            return {
                "status": "INVALID_BAR_GEOMETRY",
                "decision_eligible": False,
                "reason": f"Geometry item {index} is not an object.",
                "bars": output,
            }
        try:
            stamp = int(item["time_server_ms"])
            closed = item["is_closed"]
            item_x = float(item["x_px"])
            valid = item.get("valid") is True
            visible = item.get("visible") is True
        except (KeyError, TypeError, ValueError, OverflowError):
            return {
                "status": "INVALID_BAR_GEOMETRY",
                "decision_eligible": False,
                "reason": f"Geometry item {index} has incomplete identity or validity metadata.",
                "bars": output,
            }

        if stamp != int(native["time_server_ms"]) or closed is not native["is_closed"]:
            return {
                "status": "BAR_IDENTITY_MISMATCH",
                "decision_eligible": False,
                "reason": f"Geometry item {index} does not match its OHLC timestamp/close state.",
                "bars": output,
            }
        if not math.isfinite(item_x):
            return {
                "status": "NON_FINITE_COORDINATE",
                "decision_eligible": False,
                "reason": f"Geometry item {index} has a non-finite X coordinate.",
                "bars": output,
            }

        # ChartTimePriceToXY can legitimately fail for bars whose OHLC points
        # are outside the drawable chart area. MQL5 serializes those points as
        # null and marks the item invalid/invisible. Preserve that fact without
        # discarding the entire geometry sample; visible invalid bars remain a
        # hard failure.
        if not valid:
            if visible:
                return {
                    "status": "VISIBLE_POINT_INVALID",
                    "decision_eligible": False,
                    "reason": f"Geometry item {index} is declared visible but its point set is invalid.",
                    "bars": output,
                }
            output.append({
                "index": index,
                "time_server_ms": stamp,
                "is_closed": closed,
                "valid": False,
                "visible": False,
                "x_source_px": item_x,
                "x_image_px_provisional": None,
                "points_source_px": None,
                "points_image_px_provisional": None,
                "x_alignment_error_px": None,
            })
            continue

        points: dict[str, dict[str, float]] = {}
        try:
            for name in _POINT_FIELDS:
                point = item.get(name)
                if not isinstance(point, dict):
                    raise ValueError(f"{name} point missing")
                points[name] = {
                    "x": float(point["x_px"]),
                    "y": float(point["y_px"]),
                }
        except (KeyError, TypeError, ValueError, OverflowError):
            return {
                "status": "INVALID_BAR_GEOMETRY",
                "decision_eligible": False,
                "reason": f"Valid geometry item {index} has incomplete point coordinates.",
                "bars": output,
            }

        values = [coordinate for point in points.values() for coordinate in point.values()]
        if not all(math.isfinite(value) for value in values) or not math.isfinite(item_x):
            return {
                "status": "NON_FINITE_COORDINATE",
                "decision_eligible": False,
                "reason": f"Geometry item {index} contains a non-finite coordinate.",
                "bars": output,
            }

        x_values = [points[name]["x"] for name in _POINT_FIELDS]
        x_error = max(x_values) - min(x_values)
        if x_error > 1.0:
            return {
                "status": "X_ALIGNMENT_FAILED",
                "decision_eligible": False,
                "reason": f"OHLC points for candle {index} do not share one time coordinate.",
                "bars": output,
            }

        high_y = points["high"]["y"]
        low_y = points["low"]["y"]
        body_top_y = min(points["open"]["y"], points["close"]["y"])
        body_bottom_y = max(points["open"]["y"], points["close"]["y"])
        if high_y > body_top_y + 1.0 or low_y < body_bottom_y - 1.0 or high_y > low_y:
            return {
                "status": "Y_ORDER_FAILED",
                "decision_eligible": False,
                "reason": f"Geometry item {index} has impossible High/Body/Low pixel ordering.",
                "bars": output,
            }

        valid_count += 1
        if previous_x is not None and item_x <= previous_x:
            return {
                "status": "X_SEQUENCE_INVALID",
                "decision_eligible": False,
                "reason": "Native chart X coordinates must increase with chronological OHLC bars.",
                "bars": output,
            }
        previous_x = item_x
        if visible:
            visible_count += 1

        output.append({
            "index": index,
            "time_server_ms": stamp,
            "is_closed": closed,
            "valid": valid,
            "visible": visible,
            "x_source_px": item_x,
            "x_image_px_provisional": item_x * scale_x,
            "points_source_px": points,
            "points_image_px_provisional": {
                name: {
                    "x": points[name]["x"] * scale_x,
                    "y": points[name]["y"] * scale_y,
                }
                for name in _POINT_FIELDS
            },
            "x_alignment_error_px": round(x_error, 4),
        })

    # Counters are audited but not trusted as a substitute for the array itself.
    if declared_valid != valid_count or declared_visible != visible_count:
        return {
            "status": "COUNTER_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry counters do not match the validated items.",
            "bars": output,
            "validated_bars": valid_count,
            "visible_bars": visible_count,
        }

    minimum_visible = max(8, int(chart.get("visible_bars", 0) * 0.50))
    if valid_count < 8 or visible_count < minimum_visible:
        return {
            "status": "PARTIAL",
            "decision_eligible": False,
            "reason": "Too few native OHLC points are visible and valid for pixel alignment.",
            "validated_bars": valid_count,
            "visible_bars": visible_count,
            "minimum_visible_bars": minimum_visible,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "mapping_status": "UNVERIFIED_PROVISIONAL_DIMENSION_RATIO",
            "bars": output,
        }

    return {
        "status": "READY_FOR_PIXEL_ALIGNMENT",
        "decision_eligible": False,
        "source": "MT5_CHART_TIME_PRICE_TO_XY",
        "coordinate_origin": "MAIN_CHART_WINDOW_TOP_LEFT",
        "source_width_px": source_width,
        "source_height_px": source_height,
        "image_width_px": image_width,
        "image_height_px": image_height,
        "validated_bars": valid_count,
        "visible_bars": visible_count,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "mapping_status": "UNVERIFIED_PROVISIONAL_DIMENSION_RATIO",
        "reason": "Native geometry passed structural validation; PNG coordinate alignment still requires an independent visual overlay test.",
        "bars": output,
    }


def validate_mt5_geometry_overlay(
    geometry_validation: dict[str, Any],
    *,
    native_bars: list[dict[str, Any]],
    extracted_bars: list[dict[str, Any]],
    visible_bars: int,
    first_visible_bar_shift: int,
    residual_limit_px: float = 13.5,
    minimum_validation_pass_ratio: float = 0.80,
) -> dict[str, Any]:
    """Validate the affine mapping from native MT5 coordinates to detected PNG candles.

    Fit candles determine the coordinate transform; interleaved hold-out candles
    independently verify it. This function never authorizes a trading decision.
    """
    def fail(status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {"status": status, "mapping_verified": False, "decision_eligible": False,
                "reason": reason, **extra}

    if geometry_validation.get("status") not in {"READY_FOR_PIXEL_ALIGNMENT", "PARTIAL"}:
        return fail("GEOMETRY_NOT_READY", "Native MT5 geometry did not pass structural validation.")
    if visible_bars < 8 or not native_bars or not extracted_bars:
        return fail("INSUFFICIENT_INPUT", "Visible native bars and extracted image candles are required.")
    if not math.isfinite(residual_limit_px) or residual_limit_px <= 0:
        return fail("INVALID_THRESHOLD", "Overlay residual threshold must be positive and finite.")

    geometry_items = geometry_validation.get("bars")
    if not isinstance(geometry_items, list) or len(geometry_items) != len(native_bars):
        return fail("GEOMETRY_BAR_COUNT_MISMATCH", "Validated geometry does not cover the native OHLC array.")

    extracted_by_slot: dict[int, dict[str, Any]] = {}
    for item in extracted_bars:
        if not isinstance(item, dict):
            continue
        try:
            slot = int(item["slot_index"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if slot in extracted_by_slot:
            return fail("DUPLICATE_IMAGE_SLOT", "More than one extracted candle occupies the same image slot.")
        extracted_by_slot[slot] = item

    rightmost_visible_offset = max(0, int(first_visible_bar_shift) - int(visible_bars) + 1)
    matched: list[dict[str, Any]] = []
    for index, (geometry, native) in enumerate(zip(geometry_items, native_bars)):
        if not isinstance(geometry, dict) or geometry.get("valid") is not True or geometry.get("visible") is not True:
            continue
        offset = len(native_bars) - 1 - index
        relative_offset = offset - rightmost_visible_offset
        if not 0 <= relative_offset < visible_bars:
            continue
        slot = visible_bars - 1 - relative_offset
        extracted = extracted_by_slot.get(slot)
        if extracted is None:
            continue
        if int(geometry.get("time_server_ms", -1)) != int(native.get("time_server_ms", -2)):
            return fail("NATIVE_BAR_IDENTITY_MISMATCH", "Geometry timestamp does not match its OHLC source bar.")
        points = geometry.get("points_source_px")
        if not isinstance(points, dict) or any(not isinstance(points.get(name), dict) for name in _POINT_FIELDS):
            continue
        try:
            x_source = float(geometry["x_source_px"])
            x_image = float(extracted["x_px"])
            y_source = {name: float(points[name]["y"]) for name in _POINT_FIELDS}
            y_image = {
                "high": float(extracted["high_y_px"]),
                "low": float(extracted["low_y_px"]),
            }
            open_price, close_price = float(native["open"]), float(native["close"])
            if close_price > open_price:
                y_image["open"] = float(extracted["body_bottom_y_px"])
                y_image["close"] = float(extracted["body_top_y_px"])
            elif close_price < open_price:
                y_image["open"] = float(extracted["body_top_y_px"])
                y_image["close"] = float(extracted["body_bottom_y_px"])
            else:
                midpoint = (float(extracted["body_top_y_px"]) + float(extracted["body_bottom_y_px"])) / 2.0
                y_image["open"] = midpoint
                y_image["close"] = midpoint
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        coordinates = [x_source, x_image, *y_source.values(), *y_image.values()]
        if not all(math.isfinite(value) for value in coordinates):
            continue
        matched.append({
            "slot_index": slot,
            "x_source": x_source,
            "x_image": x_image,
            "y_source": y_source,
            "y_image": y_image,
        })

    matched.sort(key=lambda row: row["slot_index"])

    def coordinate_range(values: list[float]) -> dict[str, float | None]:
        if not values:
            return {"min": None, "max": None, "span": None}
        return {
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "span": round(max(values) - min(values), 3),
        }

    coordinate_diagnostics = {
        "x_source": coordinate_range([row["x_source"] for row in matched]),
        "x_image": coordinate_range([row["x_image"] for row in matched]),
        "y_source": {
            name: coordinate_range([row["y_source"][name] for row in matched])
            for name in _POINT_FIELDS
        },
        "y_image": {
            name: coordinate_range([row["y_image"][name] for row in matched])
            for name in _POINT_FIELDS
        },
        "sample_matches": [
            {
                "slot_index": row["slot_index"],
                "x_source": round(row["x_source"], 3),
                "x_image": round(row["x_image"], 3),
                "y_source": {name: round(row["y_source"][name], 3) for name in _POINT_FIELDS},
                "y_image": {name: round(row["y_image"][name], 3) for name in _POINT_FIELDS},
            }
            for row in matched[:3]
        ],
    }

    if len(matched) < 8:
        return fail("INSUFFICIENT_MATCHED_CANDLES",
                    "At least eight exact-slot native/image candle pairs are required.",
                    matched_candles=len(matched),
                    coordinate_diagnostics=coordinate_diagnostics)

    fit_rows = [row for row in matched if row["slot_index"] % 4 != 0]
    holdout_rows = [row for row in matched if row["slot_index"] % 4 == 0]
    if len(fit_rows) < 5 or len(holdout_rows) < 3:
        return fail("INSUFFICIENT_HOLDOUT", "Affine fit and independent hold-out samples are too small.",
                    matched_candles=len(matched), fit_candles=len(fit_rows),
                    validation_candles=len(holdout_rows))

    def robust_affine(pairs: list[tuple[float, float]]) -> tuple[float, float] | None:
        slopes = [
            (y2 - y1) / (x2 - x1)
            for i, (x1, y1) in enumerate(pairs)
            for x2, y2 in pairs[i + 1:]
            if abs(x2 - x1) >= 2.0
        ]
        if not slopes:
            return None
        slope = float(median(slopes))
        intercept = float(median(y - slope * x for x, y in pairs))
        if not math.isfinite(slope) or not math.isfinite(intercept) or slope <= 0:
            return None
        return slope, intercept

    x_fit = robust_affine([(row["x_source"], row["x_image"]) for row in fit_rows])
    y_fit = robust_affine([
        (row["y_source"][name], row["y_image"][name])
        for row in fit_rows for name in _POINT_FIELDS
    ])
    if x_fit is None or y_fit is None:
        return fail("AFFINE_FIT_FAILED", "Native-to-image coordinates do not produce positive affine transforms.")

    x_scale, x_offset = x_fit
    y_scale, y_offset = y_fit
    validation_rows = []
    for row in holdout_rows:
        x_error = abs(x_scale * row["x_source"] + x_offset - row["x_image"])
        y_errors = {
            name: abs(y_scale * row["y_source"][name] + y_offset - row["y_image"][name])
            for name in _POINT_FIELDS
        }
        maximum = max([x_error, *y_errors.values()])
        validation_rows.append({
            "slot_index": row["slot_index"],
            "x_residual_px": round(x_error, 3),
            "y_residual_px_by_point": {key: round(value, 3) for key, value in y_errors.items()},
            "maximum_residual_px": round(maximum, 3),
            "passed": maximum <= residual_limit_px,
        })

    passed = [row for row in validation_rows if row["passed"]]
    ratio = len(passed) / len(validation_rows)
    median_error = float(median(row["maximum_residual_px"] for row in validation_rows))
    required = max(3, math.ceil(len(validation_rows) * minimum_validation_pass_ratio))
    if len(passed) < required or median_error > residual_limit_px * 0.5:
        return fail(
            "OVERLAY_HOLDOUT_FAILED",
            "Independent native-to-image candle overlay does not meet residual and pass-ratio limits.",
            matched_candles=len(matched), fit_candles=len(fit_rows),
            validation_candles=len(holdout_rows), validation_passed_candles=len(passed),
            validation_pass_ratio=round(ratio, 4),
            validation_median_max_residual_px=round(median_error, 3),
            validation_max_residual_px=max(row["maximum_residual_px"] for row in validation_rows),
            residual_limit_px=residual_limit_px, validation_rows=validation_rows,
            x_scale=round(x_scale, 8), x_offset=round(x_offset, 4),
            y_scale=round(y_scale, 8), y_offset=round(y_offset, 4),
            coordinate_diagnostics=coordinate_diagnostics,
        )

    return {
        "status": "READY",
        "mapping_verified": True,
        "decision_eligible": False,
        "method": "native_mt5_geometry_affine_fit_with_interleaved_image_holdout",
        "matched_candles": len(matched),
        "fit_candles": len(fit_rows),
        "validation_candles": len(holdout_rows),
        "validation_passed_candles": len(passed),
        "validation_pass_ratio": round(ratio, 4),
        "validation_median_max_residual_px": round(median_error, 3),
        "validation_max_residual_px": max(row["maximum_residual_px"] for row in validation_rows),
        "residual_limit_px": residual_limit_px,
        "x_scale": round(x_scale, 8),
        "x_offset": round(x_offset, 4),
        "y_scale": round(y_scale, 8),
        "y_offset": round(y_offset, 4),
        "validation_rows": validation_rows,
        "coordinate_diagnostics": coordinate_diagnostics,
    }


def analyze_native_mt5_ohlc(
    bars: list[dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Run pattern and structure analysis on original MT5 OHLC, not pixel-reconstructed prices."""
    from .chart_pattern_knowledge import analyze_candle_patterns
    from .chart_pattern_reference import analyze_talib_pattern_reference
    from .chart_structure_knowledge import analyze_chart_structure_knowledge

    if not isinstance(bars, list) or not bars:
        return {
            "status": "INSUFFICIENT",
            "source": "MT5_COPYRATES",
            "decision_eligible": False,
            "patterns": {"status": "INSUFFICIENT", "detected": []},
            "reference_patterns": {"status": "INSUFFICIENT", "events": []},
            "structure": {"status": "INSUFFICIENT"},
        }

    if any(not isinstance(bar.get("is_closed"), bool) for bar in bars):
        return {
            "status": "INVALID_BAR_STATE",
            "source": "MT5_COPYRATES",
            "decision_eligible": False,
            "reason": "Every native OHLC bar must carry an explicit closed/forming state.",
        }
    if any(not bar["is_closed"] for bar in bars[:-1]) or bars[-1]["is_closed"]:
        return {
            "status": "INVALID_BAR_SEQUENCE",
            "source": "MT5_COPYRATES",
            "decision_eligible": False,
            "reason": "Only the latest MT5 OHLC bar may be forming.",
        }

    patterns = analyze_candle_patterns(bars, last_candle_closed=False)
    reference_patterns = analyze_talib_pattern_reference(
        bars, last_candle_closed=False
    )
    structure = analyze_chart_structure_knowledge(
        bars, last_candle_closed=False
    )

    def add_times(items: list[dict[str, Any]], start_key: str, end_key: str) -> None:
        for item in items:
            start = item.get(start_key)
            end = item.get(end_key)
            if isinstance(start, int) and 0 <= start < len(bars):
                item["start_time_server_ms"] = bars[start]["time_server_ms"]
            if isinstance(end, int) and 0 <= end < len(bars):
                item["end_time_server_ms"] = bars[end]["time_server_ms"]

    add_times(patterns.get("detected", []), "start_index", "end_index")
    add_times(reference_patterns.get("events", []), "formation_start_index", "formation_end_index")

    for key in ("bos_choch_events", "liquidity_sweeps"):
        for event in structure.get(key, []):
            index = event.get("confirmation_index")
            if isinstance(index, int) and 0 <= index < len(bars):
                event["confirmation_time_server_ms"] = bars[index]["time_server_ms"]

    return {
        "status": "READY" if structure.get("status") in {"READY", "PARTIAL", "INSUFFICIENT"} else "PARTIAL",
        "source": "MT5_COPYRATES",
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_count": len(bars),
        "closed_bar_count": sum(1 for bar in bars if bar["is_closed"]),
        "forming_bar_count": 1,
        "patterns": patterns,
        "reference_patterns": reference_patterns,
        "structure": structure,
        "decision_eligible": False,
        "interpretation": (
            "Native OHLC analysis only. Pattern matches and structure events are evidence, "
            "not probabilities, trade votes, or instructions."
        ),
    }


__all__ = ["analyze_native_mt5_ohlc", "native_geometry_slot_centers", "infer_regular_chart_slot_centers", "assign_native_geometry_slots", "validate_mt5_chart_geometry", "validate_mt5_geometry_overlay"]
