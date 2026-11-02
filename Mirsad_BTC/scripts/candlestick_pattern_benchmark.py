from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import math
import re
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

DATASET = "rohanjain2312/candlestick-pattern-recognition-system-data"
REVISION = "805d2686883bca7e1b98f870a253c2a998e9c6d3"
USER_AGENT = "MirsadBTC-PatternBenchmark/1.0 (held-out-pattern-audit; no trading)"
CLASS_NAMES = [
    "Hammer",
    "ShootingStar",
    "BullishEngulfing",
    "BearishEngulfing",
    "MorningStar",
    "EveningStar",
    "Doji",
    "Harami",
]
CANDIDATE_NAMES = {
    0: "hammer_candidate",
    1: "shooting_star_candidate",
    2: "bullish_engulfing_candidate",
    3: "bearish_engulfing_candidate",
    4: "morning_star_candidate",
    5: "evening_star_candidate",
    6: "doji_candidate",
    7: "harami_candidate",
}
IMAGE_KEY = re.compile(r"^SPY_\d{8}$")


def request_bytes(url: str, maximum_bytes: int = 120 * 1024 * 1024, timeout: int = 90) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/gzip,application/octet-stream,*/*",
        },
    )
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(maximum_bytes + 1)
                if not payload:
                    raise ValueError("empty archive response")
                if len(payload) > maximum_bytes:
                    raise ValueError(f"archive exceeds {maximum_bytes} bytes")
                return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            retry_after = 0.0
            try:
                retry_after = float(exc.headers.get("Retry-After", "0"))
            except (TypeError, ValueError):
                pass
            time.sleep(max(retry_after, min(30.0, 2.0 ** (attempt + 1))))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(min(2.0 ** (attempt + 1), 20.0))
    raise RuntimeError(f"dataset download failed after retries: {last_error}")


def request_json(url: str) -> Any:
    data = request_bytes(url, maximum_bytes=16 * 1024 * 1024, timeout=35)
    return json.loads(data.decode("utf-8"))


def find_test_archive() -> tuple[str, str]:
    api = (
        f"https://huggingface.co/api/datasets/{DATASET}/tree/"
        f"{REVISION}?recursive=true&expand=false"
    )
    entries = request_json(api)
    if isinstance(entries, dict):
        entries = entries.get("files", entries.get("tree", []))
    if not isinstance(entries, list):
        raise RuntimeError("Hugging Face tree API returned an unexpected format")

    files = [
        str(entry.get("path", ""))
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") == "file"
    ]
    candidates = [
        path for path in files
        if path.lower().endswith((".tar.gz", ".tgz", ".tar"))
        and "test" in Path(path).name.lower()
    ]
    if not candidates:
        candidates = [
            path for path in files
            if Path(path).name.lower() in {"test.tar.gz", "test.tgz", "test.tar"}
        ]
    if len(candidates) != 1:
        available = [p for p in files if p.lower().endswith((".tar.gz", ".tgz", ".tar"))]
        raise RuntimeError(
            f"Could not identify one held-out test archive. "
            f"Candidates={candidates}; archives={available}"
        )
    path = candidates[0]
    url = (
        f"https://huggingface.co/datasets/{DATASET}/resolve/"
        f"{REVISION}/{urllib.parse.quote(path, safe='/')}?download=true"
    )
    return path, url


def parse_yolo_labels(data: bytes) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        try:
            cls = int(parts[0])
            cx, cy, width, height = (float(v) for v in parts[1:])
        except (TypeError, ValueError):
            continue
        if cls not in range(len(CLASS_NAMES)):
            continue
        if not all(math.isfinite(v) for v in (cx, cy, width, height)):
            continue
        if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < width <= 1 and 0 < height <= 1):
            continue
        rows.append({"class_id": cls, "cx": cx, "cy": cy, "width": width, "height": height})
    return rows


def load_archive(payload: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    image_entries: dict[str, bytes] = {}
    label_entries: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        members = [m for m in archive.getmembers() if m.isfile()]
        for member in members:
            name = member.name.replace("\\", "/")
            base = Path(name).name
            stem = Path(base).stem
            if not IMAGE_KEY.match(stem):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read()
            if name.lower().endswith(".png"):
                image_entries[stem] = raw
            elif name.lower().endswith(".txt"):
                label_entries[stem] = raw

    common = sorted(set(image_entries) & set(label_entries))
    if not common:
        raise RuntimeError(
            "The test archive did not contain paired SPY PNG images and YOLO TXT labels. "
            f"images={len(image_entries)}, labels={len(label_entries)}"
        )
    rows = [
        {
            "sample_id": stem,
            "image_bytes": image_entries[stem],
            "labels": parse_yolo_labels(label_entries[stem]),
        }
        for stem in common
    ]
    return rows, {
        "image_files": len(image_entries),
        "label_files": len(label_entries),
        "paired_samples": len(rows),
    }


def _match_class(
    predicted_x: list[float],
    truth_x: list[float],
    tolerance_px: float,
) -> dict[str, int]:
    pairs = sorted(
        (abs(px - tx), pi, ti)
        for pi, px in enumerate(predicted_x)
        for ti, tx in enumerate(truth_x)
        if abs(px - tx) <= tolerance_px
    )
    used_predictions: set[int] = set()
    used_truths: set[int] = set()
    for _, pi, ti in pairs:
        if pi not in used_predictions and ti not in used_truths:
            used_predictions.add(pi)
            used_truths.add(ti)
    tp = len(used_predictions)
    return {
        "tp": tp,
        "fp": len(predicted_x) - tp,
        "fn": len(truth_x) - tp,
        "predicted": len(predicted_x),
        "ground_truth": len(truth_x),
    }


def analyze_sample(row: dict[str, Any], index: int, temp_dir: Path) -> dict[str, Any]:
    from mirsad.engines.chart import analyze_chart_image

    stem = str(row["sample_id"])
    image = cv2.imdecode(
        np.frombuffer(row["image_bytes"], dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    if image is None:
        return {
            "sample_index": index,
            "sample_id": stem,
            "status": "IMAGE_DECODE_ERROR",
            "ground_truth": row["labels"],
            "predictions": [],
        }

    height, width = image.shape[:2]
    image_path = temp_dir / f"{stem}.png"
    if not cv2.imwrite(str(image_path), image):
        return {
            "sample_index": index,
            "sample_id": stem,
            "status": "IMAGE_WRITE_ERROR",
            "ground_truth": row["labels"],
            "predictions": [],
        }

    metadata = {
        "symbol": "SPY",
        "timeframe": "1d",
        # These charts have no numeric axis. This positive virtual scale is
        # used only to order candles vertically, never as recovered market prices.
        "price_top": 2.0,
        "price_bottom": 1.0,
        "plot_left_px": 0,
        "plot_right_px": width,
        "plot_top_px": 0,
        "plot_bottom_px": height,
        "expected_candle_count": 20,
        "palette_mode": "auto",
    }
    try:
        result = analyze_chart_image(image_path, metadata, expected_symbol="SPY")
        bars = result.get("bars", []) or []
        predictions_by_class: dict[int, list[float]] = defaultdict(list)
        for candidate in result.get("pattern_candidates", []) or []:
            name = str(candidate.get("pattern", ""))
            if name.endswith("_candidate"):
                name = name[:-10]
            class_id = next(
                (k for k, v in CANDIDATE_NAMES.items() if v[:-10] == name),
                None,
            )
            if class_id is None:
                continue
            start = int(candidate.get("start_index", candidate.get("index", 0)))
            end = int(candidate.get("index", start))
            if 0 <= start < len(bars) and 0 <= end < len(bars) and start <= end:
                centre_x = (
                    float(bars[start]["x_px"]) + float(bars[end]["x_px"])
                ) / 2.0
                predictions_by_class[class_id].append(centre_x)

        truths_by_class: dict[int, list[float]] = defaultdict(list)
        for label in row["labels"]:
            truths_by_class[int(label["class_id"])].append(float(label["cx"]) * width)

        tolerance = width / 20.0 * 0.72
        matches = {
            str(class_id): _match_class(
                predictions_by_class.get(class_id, []),
                truths_by_class.get(class_id, []),
                tolerance,
            )
            for class_id in range(len(CLASS_NAMES))
        }
        candle_geometry = [
            {
                "index": bar_index,
                "x_px": int(bar["x_px"]),
                "high_y_px": int(bar["high_y_px"]),
                "low_y_px": int(bar["low_y_px"]),
                "body_top_y_px": int(bar["body_top_y_px"]),
                "body_bottom_y_px": int(bar["body_bottom_y_px"]),
                "body_size_px": round(abs(float(bar["body_bottom_y_px"]) - float(bar["body_top_y_px"])), 3),
                "range_size_px": round(float(bar["low_y_px"]) - float(bar["high_y_px"]), 3),
                "upper_shadow_px": round(float(bar["body_top_y_px"]) - float(bar["high_y_px"]), 3),
                "lower_shadow_px": round(float(bar["low_y_px"]) - float(bar["body_bottom_y_px"]), 3),
                "colour": bar.get("colour"),
            }
            for bar_index, bar in enumerate(bars)
        ]
        return {
            "sample_index": index,
            "sample_id": stem,
            "image_width": width,
            "image_height": height,
            "status": result.get("status"),
            "detected_bars": result.get("detected_bar_count", 0),
            "decision_eligible": bool(result.get("decision_eligible")),
            "calibrated_bars": result.get("calibrated_bar_count", 0),
            "analysis_confidence": result.get("analysis_confidence"),
            "pattern_matches": matches,
            "ground_truth": row["labels"],
            "candle_geometry": candle_geometry,
            "predictions": [
                {"class_id": cls, "x_px": round(x, 2)}
                for cls, xs in predictions_by_class.items()
                for x in xs
            ],
            "extraction_diagnostics": result.get("extraction_diagnostics"),
        }
    except Exception as exc:
        return {
            "sample_index": index,
            "sample_id": stem,
            "status": "ANALYSIS_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "ground_truth": row["labels"],
            "predictions": [],
        }
    finally:
        image_path.unlink(missing_ok=True)


def _end_candle_index(center_px: float, image_width: int, span: int) -> float:
    # The external renderer uses mplfinance x limits [-0.8, 19.8] for
    # 20 candles, so candle centres are affine in image pixels.
    x_margin = 0.8
    window = 20
    slot = image_width / (window - 1 + 2 * x_margin)
    first_center = image_width * x_margin / (window - 1 + 2 * x_margin)
    center_index = (center_px - first_center) / slot
    return center_index + (span - 1) / 2.0


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    per_class: dict[str, dict[str, float | int | None]] = {}
    reference_per_class: dict[str, dict[str, float | int | None]] = {}
    spans = {0: 1, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 1, 7: 2}
    required_history = {0: 10, 1: 10, 2: 1, 3: 1, 4: 12, 5: 12, 6: 10, 7: 11}

    for class_id, class_name in enumerate(CLASS_NAMES):
        tp = fp = fn = predicted = truth = 0
        context_tp = context_fp = context_fn = 0
        context_predicted = context_truth = unseen_truth = 0

        for row in results:
            match = (row.get("pattern_matches") or {}).get(str(class_id), {})
            tp += int(match.get("tp", 0))
            fp += int(match.get("fp", 0))
            fn += int(match.get("fn", 0))
            predicted += int(match.get("predicted", 0))
            truth += int(match.get("ground_truth", 0))

            image_width = int(row.get("image_width", 640) or 640)
            min_history = required_history[class_id]
            span = spans[class_id]
            tolerance = image_width / 20.6 * 0.72

            all_truth_x = [
                float(gt["cx"]) * image_width
                for gt in row.get("ground_truth", [])
                if int(gt.get("class_id", -1)) == class_id
            ]
            available_truth_x = [
                x for x in all_truth_x
                if round(_end_candle_index(x, image_width, span)) >= min_history
            ]
            unseen_truth += len(all_truth_x) - len(available_truth_x)
            context_truth += len(available_truth_x)

            all_prediction_x = [
                float(pred["x_px"])
                for pred in row.get("predictions", [])
                if int(pred.get("class_id", -1)) == class_id
            ]
            available_prediction_x = [
                x for x in all_prediction_x
                if round(_end_candle_index(x, image_width, span)) >= min_history
            ]
            context_predicted += len(available_prediction_x)
            context_match = _match_class(
                available_prediction_x,
                available_truth_x,
                tolerance,
            )
            context_tp += context_match["tp"]
            context_fp += context_match["fp"]
            context_fn += context_match["fn"]

        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall > 0
            else None
        )
        context_precision = (
            context_tp / (context_tp + context_fp)
            if context_tp + context_fp else None
        )
        context_recall = (
            context_tp / (context_tp + context_fn)
            if context_tp + context_fn else None
        )
        context_f1 = (
            2 * context_precision * context_recall / (context_precision + context_recall)
            if context_precision is not None and context_recall is not None
            and context_precision + context_recall > 0
            else None
        )
        per_class[class_name] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "predicted_instances": predicted,
            "ground_truth_instances": truth,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
            "context_required_prior_bars": min_history,
            "context_predicted_instances": context_predicted,
            "context_ground_truth_instances": context_truth,
            "context_unavailable_ground_truth_instances": unseen_truth,
            "context_tp": context_tp,
            "context_fp": context_fp,
            "context_fn": context_fn,
            "context_precision": round(context_precision, 4) if context_precision is not None else None,
            "context_recall": round(context_recall, 4) if context_recall is not None else None,
            "context_f1": round(context_f1, 4) if context_f1 is not None else None,
        }

    # Separate score for TA-Lib applied to image-derived OHLC. Ground truth is
    # itself TA-Lib-generated, so this measures OHLC reconstruction/definition
    # agreement, not human validation or future-price prediction.
    for class_id, class_name in enumerate(CLASS_NAMES):
        tp = fp = fn = predicted = truth = 0
        context_tp = context_fp = context_fn = 0
        context_predicted = context_truth = unseen_truth = 0
        for row in results:
            match = (row.get("reference_pattern_matches") or {}).get(str(class_id), {})
            tp += int(match.get("tp", 0))
            fp += int(match.get("fp", 0))
            fn += int(match.get("fn", 0))
            predicted += int(match.get("predicted", 0))
            truth += int(match.get("ground_truth", 0))

            image_width = int(row.get("image_width", 640) or 640)
            min_history = required_history[class_id]
            span = spans[class_id]
            tolerance = image_width / 20.6 * 0.72
            truth_x = [
                float(gt["cx"]) * image_width
                for gt in row.get("ground_truth", [])
                if int(gt.get("class_id", -1)) == class_id
            ]
            available_truth_x = [
                x for x in truth_x
                if round(_end_candle_index(x, image_width, span)) >= min_history
            ]
            unseen_truth += len(truth_x) - len(available_truth_x)
            context_truth += len(available_truth_x)

            reference_x = [
                float(pred["x_px"])
                for pred in row.get("reference_predictions", [])
                if int(pred.get("class_id", -1)) == class_id
            ]
            available_reference_x = [
                x for x in reference_x
                if round(_end_candle_index(x, image_width, span)) >= min_history
            ]
            context_predicted += len(available_reference_x)
            context_match = _match_class(
                available_reference_x, available_truth_x, tolerance
            )
            context_tp += context_match["tp"]
            context_fp += context_match["fp"]
            context_fn += context_match["fn"]

        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall > 0
            else None
        )
        context_precision = (
            context_tp / (context_tp + context_fp)
            if context_tp + context_fp else None
        )
        context_recall = (
            context_tp / (context_tp + context_fn)
            if context_tp + context_fn else None
        )
        context_f1 = (
            2 * context_precision * context_recall / (context_precision + context_recall)
            if context_precision is not None and context_recall is not None
            and context_precision + context_recall > 0 else None
        )
        reference_per_class[class_name] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "predicted_instances": predicted,
            "ground_truth_instances": truth,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
            "context_required_prior_bars": min_history,
            "context_predicted_instances": context_predicted,
            "context_ground_truth_instances": context_truth,
            "context_unavailable_ground_truth_instances": unseen_truth,
            "context_tp": context_tp,
            "context_fp": context_fp,
            "context_fn": context_fn,
            "context_precision": round(context_precision, 4) if context_precision is not None else None,
            "context_recall": round(context_recall, 4) if context_recall is not None else None,
            "context_f1": round(context_f1, 4) if context_f1 is not None else None,
        }

    ready = sum(int(row.get("detected_bars", 0)) >= 18 for row in results)
    analyzed = sum(row.get("status") not in {"ANALYSIS_ERROR", "IMAGE_DECODE_ERROR", "IMAGE_WRITE_ERROR"} for row in results)
    return {
        "images": len(results),
        "analyzed_images": analyzed,
        "images_with_at_least_18_bars": ready,
        "bar_detection_coverage_pct": round(ready / len(results) * 100, 2) if results else 0.0,
        "context_method": (
            "Context-adjusted metrics exclude labels whose TA-Lib rule needs more prior candles "
            "than are visible in the 20-candle image. Required prior bars: 10 for Hammer, "
            "ShootingStar and Doji; 1 for Engulfing; 11 for Harami; 12 for Morning/Evening Star."
        ),
        "per_class": per_class,
        "talib_reference_per_class": reference_per_class,
        "reference_status_counts": dict(Counter(str(row.get("reference_pattern_status", "UNAVAILABLE")) for row in results)),
        "reference_method": (
            "TA-Lib pattern recognition applied to image-extracted calibrated OHLC. "
            "Ground-truth annotations were generated from source OHLC by TA-Lib; this is a parser/geometry "
            "reconstruction diagnostic, not human-verified pattern accuracy."
        ),
        "status_counts": dict(Counter(str(row.get("status")) for row in results)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Mirsad visual candle-pattern candidates on a held-out SPY chart set."
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-images", type=int, default=0, help="0 means the full held-out test split.")
    parser.add_argument("--output", default="mirsad-candlestick-pattern-benchmark.json")
    args = parser.parse_args()

    if args.batch_size < 1 or args.workers < 1:
        raise ValueError("--batch-size and --workers must be at least 1")

    archive_path, archive_url = find_test_archive()
    print(f"Dataset: {DATASET}@{REVISION}", flush=True)
    print(f"Test archive: {archive_path}", flush=True)
    archive_payload = request_bytes(archive_url)
    dataset_rows, archive_info = load_archive(archive_payload)
    if args.max_images > 0:
        dataset_rows = dataset_rows[:args.max_images]
    total = len(dataset_rows)
    total_batches = math.ceil(total / args.batch_size)
    print(
        f"Paired held-out chart images: {total} | "
        f"archive bytes={len(archive_payload)} | batches={total_batches}",
        flush=True,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    batch_history: list[dict[str, Any]] = []

    def persist(complete: bool) -> dict[str, Any]:
        ordered = sorted(results, key=lambda r: int(r.get("sample_index", 0)))
        metrics = aggregate(ordered)
        document = {
            "project": "Mirsad BTC",
            "benchmark": "held_out_visual_and_talib_reference_pattern_benchmark",
            "dataset": DATASET,
            "dataset_revision": REVISION,
            "split": "test",
            "dataset_role": (
                "External SPY chart-pattern diagnostic. The visual pixel-geometry detector and the "
                "TA-Lib-on-image-OHLC reference are scored separately against TA-Lib-generated source-OHLC "
                "labels. Labels are not human annotation. This is not a BTC outcome or profitability test."
            ),
            "archive": archive_path,
            "archive_info": archive_info,
            "progress": {
                "completed_batches": len(batch_history),
                "total_batches": total_batches,
                "batch_size": args.batch_size,
                "images_completed": len(ordered),
                "images_total": total,
                "is_complete": complete,
            },
            "batch_history": batch_history,
            "metrics": metrics,
            "results": ordered,
            "limitations": [
                "Ground-truth boxes are TA-Lib heuristic outputs, not human-verified chart interpretation.",
                "Metrics measure pattern candidate agreement by class and horizontal candle-span centre, not object-detection IoU.",
                "SPY chart style and stock instrument differ from live BTC screenshots; this is a geometry-pattern stress test only.",
                "Pattern candidates remain LOW confidence diagnostics and never add directional weight to Engine 4.",
                "No future-return label is read or evaluated in this benchmark.",
            ],
        }
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output_path)

        lines = [
            "# Mirsad held-out candlestick-pattern benchmark",
            "",
            f"- Dataset: {DATASET}@{REVISION}",
            f"- Images tested: {len(ordered)}/{total}",
            f"- Batches: {len(batch_history)}/{total_batches}",
            f"- Images with at least 18 detected bars: {metrics['images_with_at_least_18_bars']}",
            f"- Bar-detection coverage: {metrics['bar_detection_coverage_pct']}%",
            "",
            "| Pattern | TP | FP | FN | P | R | F1 | Context GT | Unseen GT | Context P | Context R | Context F1 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, m in metrics["per_class"].items():
            lines.append(
                f"| {name} | {m['tp']} | {m['fp']} | {m['fn']} | "
                f"{m['precision']} | {m['recall']} | {m['f1']} | "
                f"{m['context_ground_truth_instances']} | {m['context_unavailable_ground_truth_instances']} | "
                f"{m['context_precision']} | {m['context_recall']} | {m['context_f1']} |"
            )
        lines.extend([
            "",
            "## TA-Lib reference applied to OHLC reconstructed from the image",
            "",
            "| Pattern | TP | FP | FN | P | R | F1 | Context P | Context R | Context F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for name, m in metrics["talib_reference_per_class"].items():
            lines.append(
                f"| {name} | {m['tp']} | {m['fp']} | {m['fn']} | "
                f"{m['precision']} | {m['recall']} | {m['f1']} | "
                f"{m['context_precision']} | {m['context_recall']} | {m['context_f1']} |"
            )
        lines.extend([
            "",
            f"- TA-Lib reference statuses: {metrics['reference_status_counts']}",
            "- Interpretation: the reference uses image-reconstructed OHLC and source annotations were generated by TA-Lib; it measures OHLC reconstruction agreement, not independent human-labelled pattern accuracy.",
            "",
            "| Batch | Range | Images with 18+ bars | Pattern TPs | Pattern FPs |",
            "|---:|---:|---:|---:|---:|",
        ])
        for item in batch_history:
            bm = item["metrics"]
            tp = sum(int(m["tp"]) for m in bm["per_class"].values())
            fp = sum(int(m["fp"]) for m in bm["per_class"].values())
            lines.append(
                f"| {item['batch_number']} | {item['sample_start']}-{item['sample_end']} | "
                f"{bm['images_with_at_least_18_bars']} | {tp} | {fp} |"
            )
        lines.extend([
            "",
            f"- Complete: {complete}",
            "> Scores measure agreement with a TA-Lib-generated label set, not human truth or trading edge.",
        ])
        summary_path = Path("mirsad-candlestick-pattern-benchmark-summary.md")
        summary_tmp = summary_path.with_suffix(".md.tmp")
        summary_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary_tmp.replace(summary_path)
        return metrics

    with tempfile.TemporaryDirectory(prefix="mirsad_pattern_eval_") as temp:
        temp_dir = Path(temp)
        for offset in range(0, total, args.batch_size):
            batch_number = len(batch_history) + 1
            batch = dataset_rows[offset:offset + args.batch_size]
            batch_results: list[dict[str, Any]] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, 8)) as pool:
                futures = [
                    pool.submit(analyze_sample, row, offset + i, temp_dir)
                    for i, row in enumerate(batch)
                ]
                for future in concurrent.futures.as_completed(futures):
                    batch_results.append(future.result())
            batch_results.sort(key=lambda r: int(r.get("sample_index", 0)))
            results.extend(batch_results)

            batch_metric = aggregate(batch_results)
            batch_history.append({
                "batch_number": batch_number,
                "sample_start": offset + 1,
                "sample_end": offset + len(batch),
                "image_count": len(batch_results),
                "metrics": batch_metric,
            })
            for row in batch_results:
                print(
                    f"IMAGE {int(row['sample_index']) + 1}/{total} | {row['sample_id']} | "
                    f"bars={row.get('detected_bars', 0)} | status={row.get('status')} | "
                    f"patterns={len(row.get('predictions', []))}",
                    flush=True,
                )
            current = persist(complete=(len(results) == total))
            print(
                f"BATCH {batch_number}/{total_batches} | "
                f"images={len(results)}/{total} | "
                f"bar_coverage={current['bar_detection_coverage_pct']}% | "
                f"class_count={len(current['per_class'])}",
                flush=True,
            )

    final_metrics = persist(complete=True)
    print(f"PATTERN BENCHMARK COMPLETE: {total} images / {total_batches} batches", flush=True)
    print(f"RESULT_JSON={output_path.resolve()}", flush=True)
    return 0 if final_metrics["analyzed_images"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
