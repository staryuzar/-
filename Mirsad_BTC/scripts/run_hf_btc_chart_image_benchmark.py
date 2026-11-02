from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mirsad.engines.chart import analyze_chart_image

DATASET_ID = "sellestas/btc-candlestick-dataset"
DATASET_URL = "https://huggingface.co/datasets/sellestas/btc-candlestick-dataset"
DATASET_LICENSE = "MIT"
CARD_DECLARED_RECORDS = 13_081
DEFAULT_MAX_IMAGES = 13_081
DEFAULT_MIN_IMAGES = 10_000
DEFAULT_OCR_SAMPLE_LIMIT = 128


def parse_reference_candle(text: Any) -> dict[str, Any]:
    """Parse the dataset's independently supplied last-candle OHLC description."""
    value = str(text or "")
    direction_match = re.search(
        r"\bCandle\s*:\s*(bullish|bearish|doji)\b",
        value,
        flags=re.IGNORECASE,
    )
    number_pattern = r"([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    ohlc: dict[str, float] = {}
    for field in ("open", "high", "low", "close"):
        match = re.search(
            rf"\b{field}\s*:\s*{number_pattern}",
            value,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        try:
            parsed = float(match.group(1).replace(",", ""))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed) and parsed > 0:
            ohlc[field] = parsed

    direction = direction_match.group(1).upper() if direction_match else None
    if direction is None and "open" in ohlc and "close" in ohlc:
        direction = (
            "BULLISH" if ohlc["close"] > ohlc["open"]
            else "BEARISH" if ohlc["close"] < ohlc["open"]
            else "DOJI"
        )
    ohlc_valid = (
        len(ohlc) == 4
        and ohlc["high"] >= max(ohlc["open"], ohlc["close"], ohlc["low"])
        and ohlc["low"] <= min(ohlc["open"], ohlc["close"], ohlc["high"])
    )
    return {
        "direction": direction,
        "close": ohlc.get("close"),
        "ohlc": ohlc if ohlc_valid else None,
        "ohlc_valid": bool(ohlc_valid),
    }


def future_close_direction(current_close: float | None, next_close: Any) -> str | None:
    """Derive one-hour next-close direction without inferring label semantics."""
    try:
        current = float(current_close)
        following = float(next_close)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(current) and math.isfinite(following)):
        return None
    tolerance = max(1e-10, abs(current) * 1e-10)
    if math.isclose(current, following, rel_tol=0.0, abs_tol=tolerance):
        return "FLAT"
    return "BULLISH" if following > current else "BEARISH"


def extracted_bar_direction(bar: dict[str, Any] | None) -> str | None:
    if not isinstance(bar, dict):
        return None
    colour = str(bar.get("colour", "")).strip().upper()
    if colour in {"GREEN", "BLUE", "TEAL"}:
        return "BULLISH"
    if colour in {"RED", "ORANGE", "MAGENTA"}:
        return "BEARISH"
    if "open" in bar and "close" in bar:
        try:
            opened = float(bar["open"])
            closed = float(bar["close"])
        except (TypeError, ValueError, OverflowError):
            return None
        if not (math.isfinite(opened) and math.isfinite(closed)):
            return None
        if math.isclose(opened, closed, rel_tol=0.0, abs_tol=1e-12):
            return "DOJI"
        return "BULLISH" if closed > opened else "BEARISH"
    return None


def _as_pil_image(value: Any) -> Image.Image:
    if isinstance(value, Image.Image):
        return value.convert("RGB")
    if isinstance(value, (bytes, bytearray, memoryview)):
        with Image.open(io.BytesIO(bytes(value))) as opened:
            return opened.convert("RGB")
    if isinstance(value, dict):
        payload = value.get("bytes")
        if payload:
            with Image.open(io.BytesIO(payload)) as opened:
                return opened.convert("RGB")
        path = value.get("path")
        if path:
            with Image.open(str(path)) as opened:
                return opened.convert("RGB")
    raise ValueError("Dataset row does not contain a decodable image value")


def _quality_gate_failures(gates: Any) -> list[str]:
    if not isinstance(gates, dict):
        return ["quality_gates_unavailable"]
    return sorted(key for key, passed in gates.items() if not bool(passed))


def _safe_id(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    if raw:
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return fallback


def run_benchmark(
    *,
    max_images: int = DEFAULT_MAX_IMAGES,
    ocr_sample_limit: int = DEFAULT_OCR_SAMPLE_LIMIT,
    dataset_id: str = DATASET_ID,
) -> dict[str, Any]:
    if max_images < 1:
        raise ValueError("max_images must be positive")
    if ocr_sample_limit < 0:
        raise ValueError("ocr_sample_limit cannot be negative")

    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            "The 'datasets' package is required. Install datasets>=3,<5."
        ) from exc

    started = time.perf_counter()
    dataset = load_dataset(dataset_id, streaming=True)
    if hasattr(dataset, "items"):
        split_items: Iterable[tuple[str, Any]] = sorted(dataset.items(), key=lambda item: item[0])
    else:
        split_items = [("train", dataset)]

    records_seen = 0
    images_attempted = 0
    images_analysed = 0
    image_decode_failures = 0
    analysis_errors = 0
    duplicate_paths_skipped = 0
    ocr_attempted = 0

    split_records: Counter[str] = Counter()
    split_analysed: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    gate_failure_counts: Counter[str] = Counter()
    direction_cases = 0
    direction_matches = 0
    direction_confusion: Counter[str] = Counter()
    future_direction_cases = 0
    future_direction_matches = 0
    future_confusion: Counter[str] = Counter()
    eligible_images = 0
    axis_calibrated_images = 0
    detected_bar_total = 0
    detected_bar_counts: list[int] = []
    calibrated_bar_total = 0
    confirmed_bar_total = 0
    calibrated_bar_counts: list[int] = []
    calibration_source_counts: Counter[str] = Counter()
    reference_calibration_status_counts: Counter[str] = Counter()
    reference_anchored_images = 0
    reference_ohlc_override_images = 0
    images_with_20plus_bars = 0
    sample_errors: list[dict[str, Any]] = []
    sample_results: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="mirsad-hf-btc-chart-") as temp_name:
        temp_dir = Path(temp_name)
        stop = False
        for split_name, split_dataset in split_items:
            for row_index, row in enumerate(split_dataset):
                if images_attempted >= max_images:
                    stop = True
                    break
                records_seen += 1
                split_records[split_name] += 1

                source_path = str(row.get("image_path", "") or "").strip()
                if source_path and source_path in seen_paths:
                    duplicate_paths_skipped += 1
                    continue
                if source_path:
                    seen_paths.add(source_path)

                label = str(row.get("label", "UNKNOWN"))
                label_counts[label] += 1
                fallback = f"{split_name}:{row_index}"
                file_id = _safe_id(source_path, fallback)

                try:
                    image = _as_pil_image(row.get("image"))
                    image_path = temp_dir / f"{file_id}.png"
                    image.save(image_path, format="PNG")
                except Exception as exc:
                    image_decode_failures += 1
                    if len(sample_errors) < 50:
                        sample_errors.append({
                            "split": split_name,
                            "record_index": row_index,
                            "stage": "image_decode",
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                    continue

                images_attempted += 1
                use_ocr = (
                    ocr_sample_limit > 0
                    and images_attempted % max(1, max_images // ocr_sample_limit) == 0
                    and ocr_attempted < ocr_sample_limit
                )
                if use_ocr:
                    ocr_attempted += 1

                reference = parse_reference_candle(row.get("text"))
                metadata = {
                    "symbol": "BTCUSDT",
                    "timeframe": "1h",
                    "price_scale_type": "linear",
                    "plot_left_px": 0,
                    "plot_top_px": 0,
                    "plot_bottom_px": image.height,
                    "expected_candle_count": 30,
                    "auto_axis_ocr": bool(use_ocr),
                    "reference_last_candle_ohlc": reference.get("ohlc"),
                    "last_candle_closed": True,
                    "persist_knowledge_observations": False,
                }

                try:
                    result = analyze_chart_image(
                        image_path,
                        metadata,
                        expected_symbol="BTCUSDT",
                    )
                except Exception as exc:
                    analysis_errors += 1
                    status_counts["BENCHMARK_EXCEPTION"] += 1
                    if len(sample_errors) < 50:
                        sample_errors.append({
                            "split": split_name,
                            "record_index": row_index,
                            "image_id": file_id,
                            "stage": "engine_analysis",
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                    continue

                status = str(result.get("status", "UNKNOWN"))
                status_counts[status] += 1
                if status == "ERROR":
                    analysis_errors += 1
                    if len(sample_errors) < 50:
                        sample_errors.append({
                            "split": split_name,
                            "record_index": row_index,
                            "image_id": file_id,
                            "stage": "engine_result",
                            "error": result.get("error"),
                        })
                else:
                    images_analysed += 1
                    split_analysed[split_name] += 1

                bars = result.get("bars") or []
                detected = int(result.get("detected_bar_count", len(bars)) or 0)
                detected_bar_total += detected
                detected_bar_counts.append(detected)
                calibrated_count = int(result.get("calibrated_bar_count", 0) or 0)
                confirmed_count = int(result.get("confirmed_bar_count", 0) or 0)
                calibrated_bar_total += calibrated_count
                confirmed_bar_total += confirmed_count
                calibrated_bar_counts.append(calibrated_count)
                calibration_result = result.get("calibration") or {}
                calibration_source = str(calibration_result.get("source", "unavailable"))
                calibration_source_counts[calibration_source] += 1
                reference_calibration = result.get("reference_calibration") or {}
                reference_calibration_status = str(reference_calibration.get("status", "NOT_REPORTED"))
                reference_calibration_status_counts[reference_calibration_status] += 1
                reference_anchored_images += int(calibration_source == "reference_last_candle_ohlc")
                reference_ohlc_override_images += int(bool(result.get("reference_ohlc_override_applied")))
                if detected >= 20:
                    images_with_20plus_bars += 1

                latest_direction = extracted_bar_direction(bars[-1] if bars else None)
                expected_direction = reference.get("direction")
                if latest_direction and expected_direction in {"BULLISH", "BEARISH", "DOJI"}:
                    direction_cases += 1
                    matched = latest_direction == expected_direction
                    direction_matches += int(matched)
                    direction_confusion[f"{expected_direction}->{latest_direction}"] += 1

                future_direction = future_close_direction(
                    reference.get("close"),
                    row.get("next_close"),
                )
                decision_eligible = bool(result.get("decision_eligible", False))
                calibration = result.get("calibration") or {}
                if calibration.get("price_scale_valid") and calibration_source in {"manual", "ocr"}:
                    axis_calibrated_images += 1
                if decision_eligible:
                    eligible_images += 1
                    visual_bias = str(result.get("visual_bias", "NEUTRAL")).upper()
                    if future_direction in {"BULLISH", "BEARISH"} and visual_bias in {"BULLISH", "BEARISH"}:
                        future_direction_cases += 1
                        matched = visual_bias == future_direction
                        future_direction_matches += int(matched)

                gates = result.get("quality_gates") or {}
                for failed in _quality_gate_failures(gates):
                    gate_failure_counts[failed] += 1

                if len(sample_results) < 40 and (
                    images_attempted <= 10 or images_attempted % max(1, max_images // 30) == 0
                ):
                    sample_results.append({
                        "split": split_name,
                        "image_path": source_path or None,
                        "label_value_uninterpreted": label,
                        "status": status,
                        "detected_bar_count": detected,
                        "calibrated_bar_count": calibrated_count,
                        "confirmed_bar_count": confirmed_count,
                        "calibration_source": calibration_source,
                        "reference_calibration_status": reference_calibration_status,
                        "reference_calibration_reason": reference_calibration.get("reason"),
                        "reference_calibration_max_residual_fraction": reference_calibration.get("maximum_residual_fraction"),
                        "reference_calibration_pixel_rows": reference_calibration.get("reference_pixel_rows"),
                        "reference_ohlc_override_applied": bool(result.get("reference_ohlc_override_applied")),
                        "segmentation_mode": (result.get("extraction_diagnostics") or {}).get("segmentation_mode"),
                        "last_bar_x_ratio": result.get("last_bar_x_ratio"),
                        "last_extracted_candle_direction": latest_direction,
                        "reference_last_candle_direction": expected_direction,
                        "last_candle_direction_match": (
                            latest_direction == expected_direction
                            if latest_direction and expected_direction else None
                        ),
                        "axis_ocr_attempted": use_ocr,
                        "axis_ocr_status": (result.get("axis_ocr") or {}).get("status"),
                        "decision_eligible": decision_eligible,
                        "visual_bias": result.get("visual_bias"),
                        "failed_quality_gates": _quality_gate_failures(gates),
                        "future_close_direction": future_direction,
                    })

            if stop:
                break

    elapsed = time.perf_counter() - started
    count = len(detected_bar_counts)
    mean_bars = round(detected_bar_total / count, 3) if count else None
    sorted_bars = sorted(detected_bar_counts)
    median_bars = (
        float(sorted_bars[count // 2])
        if count and count % 2
        else (round((sorted_bars[count // 2 - 1] + sorted_bars[count // 2]) / 2, 3) if count else None)
    )

    return {
        "benchmark": "mirsad_engine_2_huggingface_btc_chart_image_benchmark",
        "schema_version": 1,
        "dataset": {
            "id": dataset_id,
            "url": DATASET_URL if dataset_id == DATASET_ID else None,
            "license_reported_by_huggingface": DATASET_LICENSE if dataset_id == DATASET_ID else None,
            "card_declared_total_records": CARD_DECLARED_RECORDS if dataset_id == DATASET_ID else None,
            "sampling_mode": "streaming_all_available_splits_until_max_images",
            "max_images_requested": max_images,
            "ocr_sample_limit": ocr_sample_limit,
        },
        "records_seen": records_seen,
        "images_attempted": images_attempted,
        "images_analysed": images_analysed,
        "image_decode_failures": image_decode_failures,
        "analysis_errors": analysis_errors,
        "duplicate_paths_skipped": duplicate_paths_skipped,
        "splits_seen": dict(split_records),
        "analysed_by_split": dict(split_analysed),
        "source_label_histogram_uninterpreted": dict(label_counts),
        "status_counts": dict(status_counts),
        "detected_bar_statistics": {
            "images_with_20_or_more_detected_bars": images_with_20plus_bars,
            "mean_detected_bars": mean_bars,
            "median_detected_bars": median_bars,
            "total_detected_bars": detected_bar_total,
            "mean_calibrated_bars": (
                round(calibrated_bar_total / len(calibrated_bar_counts), 3)
                if calibrated_bar_counts else None
            ),
            "total_calibrated_bars": calibrated_bar_total,
            "total_confirmed_bars": confirmed_bar_total,
        },
        "last_candle_colour_reference": {
            "cases": direction_cases,
            "matches": direction_matches,
            "accuracy_pct": round(100.0 * direction_matches / direction_cases, 3) if direction_cases else None,
            "confusion": dict(direction_confusion),
            "meaning": "Pixel-extracted last candle colour versus the dataset's textual last-candle description; not a trade-signal metric.",
        },
        "price_calibration_and_decision_gates": {
            "ocr_attempted_images": ocr_attempted,
            "axis_calibrated_images": axis_calibrated_images,
            "reference_anchored_images": reference_anchored_images,
            "reference_ohlc_override_images": reference_ohlc_override_images,
            "calibration_source_counts": dict(calibration_source_counts),
            "reference_calibration_status_counts": dict(reference_calibration_status_counts),
            "decision_eligible_images": eligible_images,
            "quality_gate_failure_counts": dict(gate_failure_counts),
            "meaning": "Axis OCR and reference-candle anchoring are reported separately. Reference-assisted calibration requires validated last-candle OHLC plus matching extracted candle colour and a bounded pixel-fit residual; it is not the autonomous live image path. No Engine 2 quality gate is relaxed.",
        },
        "one_step_forward_close_diagnostic": {
            "cases": future_direction_cases,
            "matches": future_direction_matches,
            "directional_match_pct": (
                round(100.0 * future_direction_matches / future_direction_cases, 3)
                if future_direction_cases else None
            ),
            "confusion": dict(future_confusion),
            "meaning": "Diagnostic only, restricted to decision-eligible charts; compares visible chart bias with the next close direction, not a backtest or profitability result.",
        },
        "elapsed_seconds": round(elapsed, 3),
        "errors_sample": sample_errors,
        "representative_results": sample_results,
        "limitations": [
            "The dataset card declares 13,081 BTCUSDT records, 30 candles per image, a 1h interval, and next_close labels. The script reports actual rows consumed and does not assume label integer meanings.",
            "Text descriptions provide the last-candle OHLC reference for an explicitly tagged reference-assisted pixel calibration. The anchored candle is not an independent OHLC-accuracy test; the benchmark reports calibration provenance and rejects direction conflicts.",
            "An image without readable price-axis calibration must remain ineligible for a live Engine 4 decision, even if candle pixels can be extracted.",
            "This benchmark tests Engine 2 image ingestion and visual extraction. It does not test Engine 4 decisions, risk sizing, MT5 execution, or profitability.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stream and benchmark Engine 2 against a public 13,081-record BTCUSDT chart-image dataset."
    )
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES)
    parser.add_argument("--min-images", type=int, default=DEFAULT_MIN_IMAGES)
    parser.add_argument("--ocr-sample-limit", type=int, default=DEFAULT_OCR_SAMPLE_LIMIT)
    parser.add_argument("--dataset-id", default=DATASET_ID)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports" / "hf_btc_chart_image_benchmark.json",
    )
    args = parser.parse_args()

    if args.min_images < 1 or args.min_images > args.max_images:
        parser.error("--min-images must be >= 1 and <= --max-images")

    try:
        report = run_benchmark(
            max_images=args.max_images,
            ocr_sample_limit=args.ocr_sample_limit,
            dataset_id=args.dataset_id,
        )
    except Exception as exc:
        print(f"Benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)

    if report["images_attempted"] < args.min_images:
        print(
            f"Only {report['images_attempted']} images were processed; "
            f"minimum required is {args.min_images}.",
            file=sys.stderr,
        )
        return 3
    if report["images_analysed"] == 0:
        print("Engine 2 did not analyse any dataset image.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
