from __future__ import annotations

import hashlib
import math
import time
import threading
from pathlib import Path
from typing import Any

from .chart_calibration import (
    calibrate_bars,
    calibrate_from_reference_candle,
    calibrate_from_reference_candles,
    resolve_chart_calibration,
    validate_reference_candle_against_calibration,
)
from .chart_pixel_metrics import analyze_pixel_visual_evidence
from .chart_extraction import PALETTE_PRESETS, _extract_bars
from .chart_image import load_chart_image
from .chart_metrics import analyze_calibrated_bars
from .chart_patterns import _body_bounds, _patterns
from .chart_ocr import detect_price_axis_ticks, fit_price_axis, detect_chart_header_metadata
from .chart_pattern_reference import analyze_talib_pattern_reference
from .chart_pattern_knowledge import analyze_candle_patterns
from .chart_structure_knowledge import analyze_chart_structure_knowledge
from .visual_knowledge import (
    seed_visual_knowledge,
    visual_knowledge_summary,
    record_pattern_observations,
    record_structure_observations,
)

_VISUAL_KNOWLEDGE_DB_STATUS: dict[str, Any] | None = None
_VISUAL_KNOWLEDGE_DB_LOCK = threading.Lock()


def _ensure_visual_knowledge_database() -> dict[str, Any]:
    global _VISUAL_KNOWLEDGE_DB_STATUS
    with _VISUAL_KNOWLEDGE_DB_LOCK:
        try:
            if _VISUAL_KNOWLEDGE_DB_STATUS is None:
                seeded = seed_visual_knowledge()
                summary = visual_knowledge_summary()
                _VISUAL_KNOWLEDGE_DB_STATUS = {**seeded, **summary}
            return dict(_VISUAL_KNOWLEDGE_DB_STATUS)
        except Exception as exc:
            return {
                **(_VISUAL_KNOWLEDGE_DB_STATUS or {}),
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "empirical_status": "UNAVAILABLE",
            }


def _refresh_visual_knowledge_summary() -> None:
    global _VISUAL_KNOWLEDGE_DB_STATUS
    try:
        summary = visual_knowledge_summary()
        with _VISUAL_KNOWLEDGE_DB_LOCK:
            _VISUAL_KNOWLEDGE_DB_STATUS = {
                **(_VISUAL_KNOWLEDGE_DB_STATUS or {}),
                **summary,
            }
    except Exception:
        # A display-count refresh must not invalidate a successfully archived chart.
        return

SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d", "1w"})
MIN_CALIBRATED_BARS = 20
MIN_LAST_BAR_X_RATIO = 0.68
MIN_MEAN_COLOUR_PURITY = 0.72



def _persist_visual_observations(
    image_path: Path,
    symbol: str,
    timeframe: str,
    candle_knowledge: dict[str, Any],
    structure_knowledge: dict[str, Any],
) -> dict[str, Any]:
    """Archive deterministic observations for an explicitly enabled chart sample."""
    try:
        fingerprint = hashlib.sha256(image_path.read_bytes()).hexdigest()
        pattern_events = candle_knowledge.get("detected", [])
        pattern_count = record_pattern_observations(
            fingerprint, symbol, timeframe, pattern_events
        )

        structural_events: list[dict[str, Any]] = []
        for scale_name, scale in (structure_knowledge.get("scales") or {}).items():
            for key, structure_id in (("swing_highs", "pivot_high"), ("swing_lows", "pivot_low")):
                for pivot in scale.get(key, []):
                    index = int(pivot["index"])
                    structural_events.append({
                        "structure_id": structure_id,
                        "start_index": index, "end_index": index,
                        "confirmed": bool(pivot.get("confirmed")),
                        "level_price": pivot.get("price"),
                        "scope": scale_name,
                        "confirmation_index": pivot.get("confirmation_index"),
                        "evidence": pivot,
                    })

        mapping = {
            "BOS_BULLISH": "bos_bullish",
            "BOS_BEARISH": "bos_bearish",
            "CHOCH_BULLISH": "choch_bullish",
            "CHOCH_BEARISH": "choch_bearish",
        }
        for block in structure_knowledge.get("order_block_candidates", []):
            structure_id = block.get("structure_id")
            if structure_id not in {"bullish_order_block", "bearish_order_block"}:
                continue
            source_index = int(block.get("source_candle_index", block.get("break_index", 0)))
            break_index = int(block.get("break_index", source_index))
            structural_events.append({
                "structure_id": structure_id,
                "start_index": source_index, "end_index": break_index,
                "confirmed": True, "zone_low": block.get("zone_low"),
                "zone_high": block.get("zone_high"),
                "scope": "swing", "evidence": block,
            })

        for event in structure_knowledge.get("bos_choch_events", []):
            structure_id = mapping.get(event.get("event"))
            if structure_id:
                index = int(event.get("confirmation_index", event.get("pivot_index", 0)))
                structural_events.append({
                    "structure_id": structure_id,
                    "start_index": int(event.get("pivot_index", index)),
                    "end_index": index, "confirmed": True,
                    "level_price": event.get("level"),
                    "scope": "swing", "evidence": event,
                })

        sweep_mapping = {
            "HIGH_LIQUIDITY_SWEEP": "high_liquidity_sweep",
            "LOW_LIQUIDITY_SWEEP": "low_liquidity_sweep",
        }
        for event in structure_knowledge.get("liquidity_sweeps", []):
            structure_id = sweep_mapping.get(event.get("event"))
            if structure_id:
                index = int(event.get("confirmation_index", 0))
                structural_events.append({
                    "structure_id": structure_id,
                    "start_index": int(event.get("pivot_index", index)),
                    "end_index": index, "confirmed": True,
                    "level_price": event.get("level"),
                    "scope": "swing", "evidence": event,
                })

        for key, structure_id in (("equal_highs", "equal_highs"), ("equal_lows", "equal_lows")):
            for zone in structure_knowledge.get(key, []):
                indices = [int(x) for x in zone.get("pivot_indices", [])]
                if indices:
                    structural_events.append({
                        "structure_id": structure_id,
                        "start_index": min(indices), "end_index": max(indices),
                        "confirmed": True, "level_price": zone.get("level"),
                        "scope": "swing", "evidence": zone,
                    })

        for gap in structure_knowledge.get("fair_value_gaps", []):
            index = int(gap.get("index", 0))
            structural_events.append({
                "structure_id": gap["structure_id"],
                "start_index": max(0, index - 2), "end_index": index,
                "confirmed": True, "zone_low": gap.get("zone_low"),
                "zone_high": gap.get("zone_high"),
                "scope": "single_timeframe", "evidence": gap,
            })

        for pattern in structure_knowledge.get("classical_patterns", []):
            pattern_id = str(pattern.get("pattern_id", ""))
            pivot_indices = [int(value) for value in pattern.get("pivot_indices", [])]
            start_index = min(pivot_indices or [int(pattern.get("formation_start_index", 0))])
            end_index = int(
                pattern.get("breakout_index")
                or pattern.get("confirmation_index")
                or pattern.get("end_index")
                or start_index
            )
            pattern_status = str(pattern.get("status", "CANDIDATE"))
            structural_events.append({
                "structure_id": pattern_id,
                "start_index": start_index,
                "end_index": end_index,
                "confirmed": pattern_status in {"CONFIRMED", "BREAKOUT_UP", "BREAKOUT_DOWN"},
                "level_price": pattern.get("breakout_level", pattern.get("neckline_break_level")),
                "zone_low": pattern.get("lower_line_end"),
                "zone_high": pattern.get("upper_line_end"),
                "scope": "single_timeframe",
                "evidence": pattern,
            })

        structure_count = record_structure_observations(
            fingerprint, symbol, timeframe, structural_events
        )
        _refresh_visual_knowledge_summary()
        return {
            "status": "READY",
            "sample_fingerprint": fingerprint,
            "pattern_observations_written": pattern_count,
            "structure_observations_written": structure_count,
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "pattern_observations_written": 0,
            "structure_observations_written": 0,
        }

def analyze_chart_image(
    image_path: str | Path,
    metadata: dict[str, Any] | None = None,
    expected_symbol: str | None = None,
) -> dict[str, Any]:
    """Run Engine 2's staged chart-image analysis and emit its stable contract."""
    path = Path(image_path)
    meta = metadata if isinstance(metadata, dict) else {}
    result: dict[str, Any] = {
        "engine": "engine_2_chart_visual_analysis",
        "method": "OpenCV computer vision, optional local RapidOCR axis reading and explicit candle rules",
        "ai_used": False,
        "ocr_model_used": False,
        "image": path.name,
        "analyzed_at_ms": int(time.time() * 1000),
        "symbol": meta.get("symbol"),
        "timeframe": meta.get("timeframe"),
    }

    image, image_error = load_chart_image(path)
    if image_error or image is None:
        return {
            **result,
            "status": "ERROR",
            "error": "The image could not be read or decoded: " + str(image_error or "unknown image error"),
            "decision_eligible": False,
        }

    image_height, image_width = image.shape[:2]
    header_ocr: dict[str, Any] = {"status": "DISABLED"}
    if bool(meta.get("auto_header_ocr", False)):
        header_ocr = detect_chart_header_metadata(
            image,
            expected_symbol=expected_symbol,
        )
    try:
        calibration = resolve_chart_calibration(meta, image_width=image_width, image_height=image_height)
        axis_ocr: dict[str, Any] = {"status": "SKIPPED_MANUAL" if calibration["price_scale_valid"] else "DISABLED"}
        calibration_source = "manual" if calibration["price_scale_valid"] else "unavailable"

        # Manual axis values always take precedence. OCR is a fallback only,
        # and must pass a robust multi-tick fit before becoming price data.
        if not calibration["price_scale_valid"] and bool(meta.get("auto_axis_ocr", False)):
            axis_ocr = detect_price_axis_ticks(
                image,
                plot_top_px=calibration["plot_top_px"],
                plot_bottom_px=calibration["plot_bottom_px"],
                plot_right_px=calibration["plot_right_px"],
            )
            if axis_ocr.get("ticks"):
                axis_fit = fit_price_axis(
                    axis_ocr["ticks"],
                    plot_top_px=calibration["plot_top_px"],
                    plot_bottom_px=calibration["plot_bottom_px"],
                    scale_type=calibration["price_scale_type"],
                )
                axis_ocr["fit"] = axis_fit
                if axis_fit.get("status") == "READY":
                    proposed_right = axis_ocr.get("candidate_plot_right_px")
                    explicit_right = int(meta.get("plot_right_px", 0) or 0)
                    if not explicit_right and proposed_right is not None:
                        proposed_right = int(proposed_right)
                        if calibration["plot_left_px"] + 32 < proposed_right <= image_width:
                            meta = {**meta, "plot_right_px": proposed_right}
                    meta = {
                        **meta,
                        "price_top": float(axis_fit["price_top"]),
                        "price_bottom": float(axis_fit["price_bottom"]),
                        "price_scale_type": calibration["price_scale_type"],
                    }
                    calibration = resolve_chart_calibration(
                        meta, image_width=image_width, image_height=image_height
                    )
                    calibration_source = "ocr" if calibration["price_scale_valid"] else "unavailable"
            elif axis_ocr.get("status") == "OCR_UNAVAILABLE":
                calibration_source = "unavailable"

        extraction_metadata = {
            **meta,
            "plot_left_px": calibration["plot_left_px"],
            "plot_top_px": calibration["plot_top_px"],
            "plot_right_px": calibration["plot_right_px"],
            "plot_bottom_px": calibration["plot_bottom_px"],
        }
        extraction_diagnostics: dict[str, Any] = {}
        bars = _extract_bars(image, extraction_metadata, diagnostics=extraction_diagnostics)
        reference_calibration: dict[str, Any] = {"status": "NOT_REQUESTED"}
        reference_axis_validation: dict[str, Any] = {"status": "NOT_REQUESTED"}
        reference_anchor_verified = False
        require_multi_reference_validation = bool(meta.get("require_multi_reference_validation", False))
        reference_multi_calibration: dict[str, Any] = {"status": "NOT_REQUESTED"}
        reference_pair_candidates: list[dict[str, Any]] = []
        selected_reference_bar: dict[str, Any] | None = None
        selected_reference_ohlc: dict[str, Any] | None = None
        selected_reference_candidate: dict[str, Any] | None = None
        reference_candidates_raw = meta.get("reference_candle_candidates")
        reference_candidates: list[dict[str, Any]] = []
        if isinstance(reference_candidates_raw, list):
            for item in reference_candidates_raw[:256]:
                if not isinstance(item, dict) or not isinstance(item.get("ohlc"), dict):
                    continue
                try:
                    offset = int(item.get("offset_from_right", -1))
                except (TypeError, ValueError, OverflowError):
                    continue
                if offset >= 0:
                    reference_candidates.append({**item, "offset_from_right": offset})
        if not reference_candidates:
            legacy_reference = meta.get("reference_last_candle_ohlc")
            try:
                legacy_offset = int(meta.get("reference_candle_offset_from_right", 0))
            except (TypeError, ValueError, OverflowError):
                legacy_offset = -1
            if isinstance(legacy_reference, dict) and legacy_offset >= 0:
                reference_candidates.append({
                    "offset_from_right": legacy_offset,
                    "ohlc": legacy_reference,
                    "time_server_ms": None,
                    "closed": None,
                })

        try:
            expected_count = int(meta.get("expected_candle_count", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            expected_count = 0
        has_slot_indices = any(
            isinstance(item, dict) and "slot_index" in item for item in bars
        )
        last_reference_failure: dict[str, Any] | None = None

        def find_reference_pixel_bar(offset_from_right: int) -> dict[str, Any] | None:
            if offset_from_right < 0:
                return None
            if expected_count > 0:
                if has_slot_indices:
                    target_slot = expected_count - 1 - offset_from_right
                    if target_slot < 0:
                        return None
                    matches = [
                        item for item in bars
                        if isinstance(item, dict) and item.get("slot_index") == target_slot
                    ]
                    return matches[0] if len(matches) == 1 else None
                # Without explicit slot IDs, order is safe only when every
                # expected visible slot was recovered. Missing bars make an
                # ordinal guess ambiguous, so block this reference candidate.
                if len(bars) != expected_count:
                    return None
            index = len(bars) - 1 - offset_from_right
            return bars[index] if 0 <= index < len(bars) else None

        for candidate in reference_candidates:
            offset = int(candidate["offset_from_right"])
            if candidate.get("closed") is False:
                continue
            if expected_count > 0 and offset >= expected_count:
                continue
            reference_bar = find_reference_pixel_bar(offset)
            if reference_bar is None:
                last_reference_failure = {
                    "status": "REFERENCE_BAR_NOT_DETECTED",
                    "reason": "The extracted chart image has no candle in the exact MT5 reference slot.",
                    "offset_from_right": offset,
                    "target_slot_index": expected_count - 1 - offset if expected_count > 0 else None,
                }
                continue

            reference_ohlc_candidate = candidate["ohlc"]
            target_slot = (
                expected_count - 1 - offset
                if expected_count > 0
                else int(reference_bar.get("slot_index", len(bars) - 1 - offset))
            )
            reference_pair_candidates.append({
                "slot_index": reference_bar.get("slot_index", target_slot),
                "bar": reference_bar,
                "ohlc": reference_ohlc_candidate,
                "closed": candidate.get("closed"),
            })
            candidate_calibration = calibrate_from_reference_candle(
                reference_bar,
                reference_ohlc_candidate,
                image_width=image_width,
                image_height=image_height,
                plot_left_px=calibration["plot_left_px"],
                plot_top_px=calibration["plot_top_px"],
                plot_right_px=calibration["plot_right_px"],
                plot_bottom_px=calibration["plot_bottom_px"],
                scale_type=calibration["price_scale_type"],
            )
            if candidate_calibration.get("status") != "READY":
                last_reference_failure = {
                    **candidate_calibration,
                    "offset_from_right": offset,
                    "slot_index": reference_bar.get("slot_index"),
                }
                continue

            candidate_axis_validation: dict[str, Any]
            candidate_calibration_map = calibration
            replace_ocr_axis = False
            if not calibration["price_scale_valid"]:
                candidate_axis_validation = {
                    "status": "READY",
                    "method": "reference_candle_slot_ohlc_pixel_fit",
                    "maximum_residual_fraction": candidate_calibration.get("maximum_residual_fraction"),
                }
                candidate_calibration_map = candidate_calibration["calibration"]
            else:
                candidate_axis_validation = validate_reference_candle_against_calibration(
                    reference_bar, reference_ohlc_candidate, calibration
                )
                if candidate_axis_validation.get("status") != "READY":
                    if calibration_source == "ocr" and bool(meta.get("allow_reference_anchor_override", False)):
                        ocr_axis_validation = candidate_axis_validation
                        candidate_axis_validation = {
                            "status": "READY",
                            "method": "native_ohlc_anchor_replaced_inconsistent_ocr",
                            "ocr_axis_validation": ocr_axis_validation,
                            "independent_reference_fit_status": "READY",
                            "maximum_residual_fraction": candidate_calibration.get("maximum_residual_fraction"),
                        }
                        candidate_calibration_map = candidate_calibration["calibration"]
                        replace_ocr_axis = True
                    else:
                        last_reference_failure = {
                            **candidate_axis_validation,
                            "offset_from_right": offset,
                            "slot_index": reference_bar.get("slot_index"),
                            "independent_reference_fit_status": "READY",
                        }
                        continue

            reference_calibration = candidate_calibration
            reference_axis_validation = {
                **candidate_axis_validation,
                "offset_from_right": offset,
                "slot_index": reference_bar.get("slot_index"),
                "reference_time_server_ms": candidate.get("time_server_ms"),
                "reference_candle_closed": candidate.get("closed"),
            }
            selected_reference_bar = reference_bar
            selected_reference_ohlc = reference_ohlc_candidate
            selected_reference_candidate = candidate
            reference_anchor_verified = True
            if not calibration["price_scale_valid"] or replace_ocr_axis:
                calibration = candidate_calibration_map
                calibration_source = "reference_last_candle_ohlc"
            break

        if not reference_anchor_verified and reference_candidates:
            reference_axis_validation = last_reference_failure or {
                "status": "REFERENCE_NOT_VERIFIED",
                "reason": "No recent MT5 native candle matched a detected visual chart slot.",
            }
            if last_reference_failure and last_reference_failure.get("status"):
                reference_calibration = dict(last_reference_failure)
            else:
                reference_calibration = {"status": "REFERENCE_NOT_VERIFIED"}

        if require_multi_reference_validation and reference_candidates:
            reference_multi_calibration = calibrate_from_reference_candles(
                reference_pair_candidates,
                image_width=image_width,
                image_height=image_height,
                plot_left_px=calibration["plot_left_px"],
                plot_top_px=calibration["plot_top_px"],
                plot_right_px=calibration["plot_right_px"],
                plot_bottom_px=calibration["plot_bottom_px"],
                scale_type=calibration["price_scale_type"],
            )
            reference_calibration = reference_multi_calibration
            reference_axis_validation = reference_multi_calibration
            if reference_multi_calibration.get("status") == "READY":
                calibration = reference_multi_calibration["calibration"]
                calibration_source = "reference_multi_candle_ohlc"
                reference_anchor_verified = True
            else:
                # A single candle remains diagnostic only; it cannot qualify
                # a live observer chart or establish the full price axis.
                reference_anchor_verified = False
    except (TypeError, ValueError, OverflowError) as exc:
        return {
            **result,
            "status": "ERROR",
            "error": f"Invalid chart crop metadata or extraction settings: {exc}",
            "decision_eligible": False,
        }

    last_candle_closed = bool(meta.get("last_candle_closed", False))
    pattern_candidates = _patterns(bars, last_candle_closed=last_candle_closed)
    calibrated = calibrate_bars(bars, calibration)
    reference_ohlc_override_applied = False
    if (
        reference_anchor_verified
        and not require_multi_reference_validation
        and isinstance(selected_reference_ohlc, dict)
        and selected_reference_bar
    ):
        reference_x = selected_reference_bar.get("x_px")
        for index in range(len(calibrated) - 1, -1, -1):
            if calibrated[index].get("x_px") == reference_x:
                calibrated[index] = {**calibrated[index], **selected_reference_ohlc}
                reference_ohlc_override_applied = True
                break
    # The live/current candle remains visible in the result, but only closed
    # candles may contribute to confirmed visual evidence.
    confirmed_calibrated = calibrated if last_candle_closed else calibrated[:-1]
    pixel_visual_evidence = analyze_pixel_visual_evidence(bars)

    knowledge_database = _ensure_visual_knowledge_database()
    observation_archive: dict[str, Any] = {"status": "DISABLED"}
    if calibration["price_scale_valid"]:
        try:
            candle_knowledge = analyze_candle_patterns(
                calibrated, last_candle_closed=last_candle_closed
            )
            advanced_structure = analyze_chart_structure_knowledge(
                calibrated, last_candle_closed=last_candle_closed
            )
        except (TypeError, ValueError, OverflowError) as exc:
            candle_knowledge = {
                "status": "ERROR", "count": 0, "detected": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            advanced_structure = {
                "status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
                "bos_choch_events": [], "liquidity_sweeps": [],
            }
        if (
            bool(meta.get("persist_knowledge_observations", False))
            and candle_knowledge.get("status") not in {"ERROR", "SKIPPED_UNCALIBRATED"}
            and advanced_structure.get("status") not in {"ERROR", "SKIPPED_UNCALIBRATED"}
            and str(meta.get("symbol", "")).strip()
            and str(meta.get("timeframe", "")).strip()
        ):
            observation_archive = _persist_visual_observations(
                path, str(meta["symbol"]), str(meta["timeframe"]),
                candle_knowledge, advanced_structure,
            )
    else:
        candle_knowledge = {
            "status": "SKIPPED_UNCALIBRATED", "count": 0, "detected": [],
            "reason": "Validated price calibration is required for OHLC candle knowledge.",
        }
        advanced_structure = {
            "status": "SKIPPED_UNCALIBRATED",
            "reason": "Validated price calibration is required for price-structure analysis.",
            "bos_choch_events": [], "liquidity_sweeps": [],
        }
    if calibration["price_scale_valid"]:
        try:
            reference_patterns = analyze_talib_pattern_reference(
                calibrated,
                last_candle_closed=last_candle_closed,
            )
        except Exception as exc:
            # Keep the visual analyst operational if its independent reference
            # scanner fails; the failure is exposed rather than hidden.
            reference_patterns = {
                "status": "ERROR",
                "source": "TA-Lib",
                "events": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        reference_patterns = {
            "status": "SKIPPED_UNCALIBRATED",
            "source": "TA-Lib",
            "events": [],
            "error": "Calibrated OHLC is required before reference pattern scanning.",
        }
    if calibration["price_scale_valid"]:
        analysis = analyze_calibrated_bars(
            confirmed_calibrated,
            top_price=float(calibration["price_top"]),
            bottom_price=float(calibration["price_bottom"]),
        )
    else:
        analysis = {
            "visual_bias": "NEUTRAL",
            "visual_trend": {
                "sample_bars": 0, "net_change": None, "net_change_pct": None,
                "visible_range_fraction": None, "rising_close_steps": 0,
                "falling_close_steps": 0, "required_directional_steps": 0,
                "minimum_move": None, "score": 0.0, "direction_consistency": 0.0,
            },
            "market_structure": {
                "status": "INSUFFICIENT", "direction": "UNKNOWN", "score": None,
                "swing_highs": [], "swing_lows": [], "higher_highs": False,
                "higher_lows": False, "lower_highs": False, "lower_lows": False,
                "support": None, "resistance": None,
                "distance_to_support_pct": None, "distance_to_resistance_pct": None,
            },
            "momentum": {"status": "INSUFFICIENT", "score": None, "change": None, "change_pct": None},
            "pattern_score": 0.0, "analysis_score": 0.0, "analysis_confidence": 0.0,
            "confidence_components": {},
            "confidence_kind": "heuristic_evidence_quality_not_probability",
        }

    symbol_value = str(meta.get("symbol", "")).strip().upper()
    expected_value = str(expected_symbol or "").strip().upper()
    symbol_matches = bool(expected_value and symbol_value == expected_value)
    timeframe = str(meta.get("timeframe", "")).strip().lower()
    timeframe_valid = timeframe in SUPPORTED_TIMEFRAMES

    plot_left = int(calibration["plot_left_px"])
    plot_right = int(calibration["plot_right_px"])
    plot_width = max(1, plot_right - plot_left)
    last_bar_x_ratio = (
        (float(bars[-1]["x_px"]) - plot_left) / plot_width if bars else None
    )
    quality_bars = bars if last_candle_closed else bars[:-1]
    mean_colour_purity = (
        float(sum(float(bar.get("colour_purity", 0.0)) for bar in quality_bars[-24:]) / min(len(quality_bars), 24))
        if quality_bars else 0.0
    )

    quality_gates = {
        "price_axis_calibrated": bool(calibration["price_scale_valid"]),
        "market_symbol_matches": symbol_matches,
        "timeframe_supported": timeframe_valid,
        "minimum_candle_count": len(confirmed_calibrated) >= MIN_CALIBRATED_BARS,
        "latest_candle_near_right_edge": (
            last_bar_x_ratio is not None and last_bar_x_ratio >= MIN_LAST_BAR_X_RATIO
        ),
        "candle_colour_purity": mean_colour_purity >= MIN_MEAN_COLOUR_PURITY,
    }
    if isinstance(meta.get("reference_last_candle_ohlc"), dict) or isinstance(meta.get("reference_candle_candidates"), list):
        quality_gates["native_reference_candle_verified"] = bool(
            reference_multi_calibration.get("status") == "READY"
            if require_multi_reference_validation
            else reference_anchor_verified
        )
    eligible = all(quality_gates.values())
    if eligible:
        state = "READY"
    elif len(confirmed_calibrated) < 5:
        state = "LOW_DETECTION"
    elif not calibration["price_scale_valid"]:
        state = "DETECTED_UNCALIBRATED"
    else:
        state = "BLOCKED_QUALITY_GATE"

    score = float(analysis["analysis_score"])
    confidence = float(analysis["analysis_confidence"])
    if not math.isfinite(score):
        score = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0

    output_bars = calibrated[-250:] if calibration["price_scale_valid"] else bars[-80:]
    output_bars = [
        {
            **bar,
            "candle_state": (
                "CLOSED" if last_candle_closed or index < len(output_bars) - 1
                else "FORMING_OR_UNVERIFIED"
            ),
        }
        for index, bar in enumerate(output_bars)
    ]

    return {
        **result,
        "status": state,
        "image_width": image_width,
        "image_height": image_height,
        "detected_bar_count": len(bars),
        "calibrated_bar_count": len(calibrated),
        "confirmed_bar_count": len(confirmed_calibrated),
        "last_candle_closed": last_candle_closed,
        "latest_candle_state": "CLOSED" if last_candle_closed else "FORMING_OR_UNVERIFIED",
        "last_bar_x_ratio": round(last_bar_x_ratio, 4) if last_bar_x_ratio is not None else None,
        "mean_colour_purity": round(mean_colour_purity, 4),
        "palette_mode": extraction_diagnostics.get(
            "selected_palette_mode", str(meta.get("palette_mode", "auto"))
        ),
        "palette_mode_requested": str(meta.get("palette_mode", "auto")),
        "palette_inference": extraction_diagnostics.get(
            "palette_inference", {"status": "UNAVAILABLE"}
        ),
        "extraction_diagnostics": extraction_diagnostics,
        "colour_counts": {
            "GREEN": sum(bar.get("colour") == "GREEN" for bar in bars),
            "RED": sum(bar.get("colour") == "RED" for bar in bars),
        },
        "visual_bias": analysis["visual_bias"],
        "visual_trend": analysis["visual_trend"],
        "pixel_visual_evidence": pixel_visual_evidence,
        "market_structure": analysis["market_structure"],
        "momentum": analysis["momentum"],
        "analysis_score": round(max(-1.0, min(1.0, score)), 4),
        "analysis_confidence": round(max(0.0, min(1.0, confidence)), 4),
        "confidence_kind": analysis.get("confidence_kind", "heuristic_evidence_quality_not_probability"),
        "confidence_components": analysis.get("confidence_components", {}),
        "analysis_components": {
            "trend": analysis["visual_trend"].get("score"),
            "structure": analysis["market_structure"].get("score"),
            "momentum": analysis["momentum"].get("score"),
            "patterns": 0.0,
        },
        "pattern_candidates": pattern_candidates,
        "reference_patterns": reference_patterns,
        "candle_knowledge": candle_knowledge,
        "advanced_structure_knowledge": advanced_structure,
        "visual_knowledge_database": knowledge_database,
        "visual_observation_archive": observation_archive,
        "bars": output_bars,
        "decision_eligible": eligible,
        "quality_gates": quality_gates,
        "axis_ocr": axis_ocr,
        "reference_calibration": (
            reference_calibration
            if "reference_calibration" in locals()
            else {"status": "NOT_REQUESTED"}
        ),
        "reference_multi_calibration": reference_multi_calibration,
        "reference_ohlc_override_applied": reference_ohlc_override_applied,
        "reference_anchor": ({
            "status": "READY",
            "offset_from_right": selected_reference_candidate.get("offset_from_right"),
            "slot_index": selected_reference_bar.get("slot_index") if selected_reference_bar else None,
            "bar_index": next((index for index, item in enumerate(bars) if item is selected_reference_bar), None),
            "time_server_ms": selected_reference_candidate.get("time_server_ms"),
            "closed": selected_reference_candidate.get("closed"),
        } if reference_anchor_verified and selected_reference_candidate else {
            "status": reference_axis_validation.get("status", "NOT_REQUESTED"),
            "reason": reference_axis_validation.get("reason"),
        }),
        "reference_axis_validation": (
            reference_axis_validation
            if "reference_axis_validation" in locals()
            else {"status": "NOT_REQUESTED"}
        ),
        "header_ocr": header_ocr,
        "ocr_model_used": (
            axis_ocr.get("ocr_backend") == "RapidOCR"
            or header_ocr.get("ocr_backend") == "RapidOCR"
        ),
        "ai_used": axis_ocr.get("ocr_backend") == "RapidOCR",
        "calibration": {
            "source": calibration_source,
            "price_scale_valid": bool(calibration["price_scale_valid"]),
            "price_scale_type": calibration["price_scale_type"],
            "symbol_matches": symbol_matches,
            "timeframe_valid": timeframe_valid,
            "plot_top_px": calibration["plot_top_px"],
            "plot_bottom_px": calibration["plot_bottom_px"],
            "plot_left_px": calibration["plot_left_px"],
            "plot_right_px": calibration["plot_right_px"],
            "price_top": calibration["price_top"],
            "price_bottom": calibration["price_bottom"],
        },
        "limitations": [
            "The price axis depends on user-supplied top/bottom prices and the exact plot rectangle; reference-assisted calibration is separately tagged and requires a trusted OHLC anchor for the last candle.",
            "The selected linear/logarithmic scale type must match the displayed chart axis.",
            "Candle colours depend on the selected palette and chart theme.",
            "Visual pattern candidates and TA-Lib reference candidates are separate observations; neither is a probability or an independent directional vote.",
            "The visual confidence index is heuristic evidence quality, not a statistical probability.",
            "The latest candle is treated as forming/unverified unless last_candle_closed is explicitly true; it is visible but excluded from confirmed trend and structure metrics.",
            "Engine 2 uses deterministic computer vision; it does not use a trained AI vision model.",
            "The candle and structure knowledge modules are independent evidence reports; they do not change the existing decision score.",
            "Pattern definitions are documented rules with UNVALIDATED empirical status until BTC-specific labelled evaluation exists.",
            "Internal/swing/external pivot scales in the advanced structure report are scales within the supplied timeframe, not true multi-timeframe confluence.",
        ],
    }


__all__ = [
    "PALETTE_PRESETS", "_body_bounds", "_extract_bars", "_patterns", "analyze_chart_image"
]
