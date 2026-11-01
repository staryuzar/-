from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import sys
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

DATASET = "sogosonnet/Crypto-Chart-Dataset"
VIEWER = "https://datasets-server.huggingface.co"
USER_AGENT = "MirsadBTC-Research-Benchmark/1.0 (chart-image-evaluation; no trades)"
LABEL_NAMES = {
    0: "down_7plus",
    1: "down_5_7",
    2: "down_3_5",
    3: "up_3_5",
    4: "up_5_7",
    5: "up_7plus",
}


def request_bytes(url: str, timeout: int = 45, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/png,image/jpeg,image/webp,application/json,*/*",
        },
    )
    last_error: Exception | None = None
    for attempt in range(7):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise ValueError(f"payload exceeds {max_bytes} bytes")
                if not payload:
                    raise ValueError("empty HTTP response")
                return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            retry_after = 0.0
            try:
                retry_after = float(exc.headers.get("Retry-After", "0"))
            except (TypeError, ValueError):
                retry_after = 0.0
            delay = max(retry_after, min(60.0, 2.0 ** (attempt + 1)))
            print(f"HTTP {exc.code}; backing off {delay:.1f}s (attempt {attempt + 1}/7)", flush=True)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(min(2.0 ** (attempt + 1), 30.0))
    raise RuntimeError(f"download failed after retries: {last_error}")


def request_json(url: str, timeout: int = 40) -> dict[str, Any]:
    payload = request_bytes(url, timeout=timeout, max_bytes=20 * 1024 * 1024)
    return json.loads(payload.decode("utf-8"))


def build_page_url(split: str, offset: int, length: int, ticker: str | None) -> str:
    params = {
        "dataset": DATASET,
        "config": "default",
        "split": split,
        "offset": str(offset),
        "length": str(length),
    }
    if ticker:
        params["where"] = f'"ticker"={ticker!r}'
        return f"{VIEWER}/filter?{urllib.parse.urlencode(params)}"
    return f"{VIEWER}/rows?{urllib.parse.urlencode(params)}"


def fetch_dataset_rows(split: str, ticker: str | None, max_images: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # The HF /filter endpoint is faster, but may return transient 5xx responses
    # for some image datasets. Fall back to /rows and filter locally so the test
    # is not lost because the metadata index is temporarily unavailable.
    used_fallback = False
    try:
        first = request_json(build_page_url(split, 0, 100, ticker))
        api_ticker_filter = ticker is not None
    except Exception as filter_error:
        if ticker is None:
            raise
        print(
            f"HF filter endpoint unavailable ({type(filter_error).__name__}: {filter_error}); "
            "falling back to paginated /rows and local ticker selection.",
            flush=True,
        )
        first = request_json(build_page_url(split, 0, 100, None))
        api_ticker_filter = False
        used_fallback = True

    total = int(first.get("num_rows_total", 0))
    partial = bool(first.get("partial", False))
    if total <= 0:
        raise RuntimeError(f"Hugging Face returned no rows for split={split}, ticker={ticker!r}")

    target = total if max_images <= 0 else min(total, max_images)
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < target:
        if offset == 0:
            page = first
        else:
            # Hugging Face viewer API enforces per-client request limits.
            # Keep pagination below its typical 30-requests/minute threshold.
            time.sleep(2.2)
            page = request_json(build_page_url(split, offset, 100, ticker if api_ticker_filter else None))
        page_rows = page.get("rows", [])
        if not page_rows:
            break
        for wrapper in page_rows:
            row = wrapper.get("row", wrapper)
            if ticker and row.get("ticker") != ticker:
                continue
            rows.append(row)
            if max_images > 0 and len(rows) >= max_images:
                break
        offset += len(page_rows)
        if offset % 500 == 0 or offset >= target:
            print(f"Fetched metadata rows: {min(offset, target)}/{target}; selected images: {len(rows)}", flush=True)
        if max_images > 0 and len(rows) >= max_images:
            break
    if not rows:
        raise RuntimeError("Dataset rows were returned, but no image rows matched the requested ticker.")
    return rows, {
        "dataset": DATASET,
        "split": split,
        "ticker_filter": ticker,
        "reported_rows_total": total,
        "partial_index": partial,
        "filter_fallback_to_rows": used_fallback,
        "metadata_rows_selected": len(rows),
    }


def unpack_image_info(row: dict[str, Any]) -> tuple[str, int | None, int | None]:
    image = row.get("image")
    if isinstance(image, str):
        return image, None, None
    if not isinstance(image, dict):
        raise ValueError("row.image is not an image URL object")
    src = image.get("src") or image.get("url")
    if not src:
        raise ValueError("row.image has no src URL")
    return str(src), image.get("width"), image.get("height")


def decode_and_analyze(
    row: dict[str, Any],
    index: int,
    temp_dir: Path,
    crop: tuple[float, float, float, float],
) -> dict[str, Any]:
    from mirsad.engines.chart import analyze_chart_image

    date = str(row.get("end_date", ""))
    ticker = str(row.get("ticker", ""))
    label_value = row.get("label")
    try:
        label_number = int(label_value)
        label_name = LABEL_NAMES.get(label_number, str(label_value))
    except (TypeError, ValueError):
        label_number = None
        label_name = str(label_value)

    future_return = row.get("pct_return")
    try:
        future_return = float(future_return)
    except (TypeError, ValueError, OverflowError):
        future_return = None
    target_direction = (
        "BULLISH" if future_return is not None and future_return > 0
        else "BEARISH" if future_return is not None and future_return < 0
        else "NEUTRAL"
    )

    try:
        image_url, expected_width, expected_height = unpack_image_info(row)
        payload = request_bytes(image_url, timeout=40, max_bytes=8 * 1024 * 1024)
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("OpenCV could not decode the downloaded image")
        height, width = image.shape[:2]
        left, top, right, bottom = crop
        metadata = {
            "symbol": ticker,
            "timeframe": "1d",
            # Dataset charts are percentage-normalized and omit numeric axes.
            # A positive virtual scale from 2 to 1 preserves direction without claiming real price values.
            "price_top": 2.0,
            "price_bottom": 1.0,
            "plot_left_px": int(round(left * width)),
            "plot_right_px": int(round(right * width)),
            "plot_top_px": int(round(top * height)),
            "plot_bottom_px": int(round(bottom * height)),
            "palette_mode": "auto",
            "expected_candle_count": 20,
        }
        image_path = temp_dir / f"crypto_chart_{index:06d}.png"
        if not cv2.imwrite(str(image_path), image):
            raise RuntimeError("could not save temporary decoded image")
        result = analyze_chart_image(image_path, metadata, expected_symbol=ticker)
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            pass

        bias = str(result.get("visual_bias", "NEUTRAL")).upper()
        eligible = bool(result.get("decision_eligible"))
        confidence = float(result.get("analysis_confidence") or 0.0)
        predicted_direction = bias if eligible and bias in {"BULLISH", "BEARISH"} else "ABSTAIN"
        scored = predicted_direction in {"BULLISH", "BEARISH"} and target_direction in {"BULLISH", "BEARISH"}
        correct = predicted_direction == target_direction if scored else None
        return {
            "sample_index": index,
            "ticker": ticker,
            "end_date": date,
            "image_width": width,
            "image_height": height,
            "label_id": label_number,
            "label_name": label_name,
            "future_return_pct": future_return,
            "target_direction": target_direction,
            "engine_status": result.get("status"),
            "detected_bars": result.get("detected_bar_count", 0),
            "calibrated_bars": result.get("calibrated_bar_count", 0),
            "decision_eligible": eligible,
            "predicted_direction": predicted_direction,
            "visual_bias": bias,
            "analysis_score": result.get("analysis_score"),
            "analysis_confidence": confidence,
            "correct_direction": correct,
            "last_bar_x_ratio": result.get("last_bar_x_ratio"),
            "mean_colour_purity": result.get("mean_colour_purity"),
            "extraction_diagnostics": result.get("extraction_diagnostics"),
            "analysis_components": result.get("analysis_components"),
            "market_structure": result.get("market_structure"),
            "momentum": result.get("momentum"),
            "patterns": result.get("pattern_candidates", []),
            "expected_image_width": expected_width,
            "expected_image_height": expected_height,
            "download_bytes": len(payload),
        }
    except Exception as exc:
        return {
            "sample_index": index,
            "ticker": ticker,
            "end_date": date,
            "label_id": label_number,
            "label_name": label_name,
            "future_return_pct": future_return,
            "target_direction": target_direction,
            "engine_status": "DOWNLOAD_OR_ANALYSIS_ERROR",
            "predicted_direction": "ABSTAIN",
            "correct_direction": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_ticker[str(row.get("ticker", "UNKNOWN"))].append(row)

    def metrics(group: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(group)
        analyzed = sum(r.get("engine_status") != "DOWNLOAD_OR_ANALYSIS_ERROR" for r in group)
        eligible = [r for r in group if r.get("decision_eligible")]
        predictions = [r for r in group if r.get("predicted_direction") in {"BULLISH", "BEARISH"}]
        scored = [r for r in predictions if r.get("correct_direction") is not None]
        correct = sum(bool(r["correct_direction"]) for r in scored)
        bullish_targets = [r for r in group if r.get("target_direction") == "BULLISH"]
        bearish_targets = [r for r in group if r.get("target_direction") == "BEARISH"]
        tp_bull = sum(r.get("predicted_direction") == "BULLISH" for r in bullish_targets)
        tp_bear = sum(r.get("predicted_direction") == "BEARISH" for r in bearish_targets)
        conf_metrics = {}
        for threshold in (0.50, 0.60, 0.70, 0.80):
            selected = [r for r in predictions if float(r.get("analysis_confidence") or 0) >= threshold]
            selected_scored = [r for r in selected if r.get("correct_direction") is not None]
            conf_metrics[str(threshold)] = {
                "count": len(selected_scored),
                "accuracy": round(sum(bool(r["correct_direction"]) for r in selected_scored) / len(selected_scored), 4)
                if selected_scored else None,
            }
        return {
            "total_images": total,
            "analyzed_images": analyzed,
            "decision_eligible_images": len(eligible),
            "directional_predictions": len(predictions),
            "directional_coverage_pct": round(len(predictions) / total * 100, 2) if total else 0,
            "accuracy_on_directional_predictions_pct": round(correct / len(scored) * 100, 2) if scored else None,
            "correct_predictions": correct,
            "scored_predictions": len(scored),
            "bullish_target_count": len(bullish_targets),
            "bearish_target_count": len(bearish_targets),
            "bullish_recall_pct": round(tp_bull / len(bullish_targets) * 100, 2) if bullish_targets else None,
            "bearish_recall_pct": round(tp_bear / len(bearish_targets) * 100, 2) if bearish_targets else None,
            "accuracy_by_confidence": conf_metrics,
        }

    return {
        "overall": metrics(rows),
        "by_ticker": {ticker: metrics(group) for ticker, group in sorted(by_ticker.items())},
        "status_counts": dict(Counter(str(r.get("engine_status")) for r in rows)),
        "prediction_counts": dict(Counter(str(r.get("predicted_direction")) for r in rows)),
        "target_counts": dict(Counter(str(r.get("target_direction")) for r in rows)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mirsad Engine 2 across a held-out cryptocurrency chart-image dataset.")
    parser.add_argument("--split", default="test", choices=("train", "test"))
    parser.add_argument("--ticker", default="BTC-USD", help="Dataset ticker such as BTC-USD; use 'all' for all 15 crypto tickers.")
    parser.add_argument("--max-images", type=int, default=0, help="0 means all matching images.")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=25, help="Number of images per audited batch; a checkpoint is written after every batch.")
    parser.add_argument("--crop", default="0.03,0.04,0.97,0.78", help="left,top,right,bottom fractions")
    parser.add_argument("--output", default="mirsad-crypto-chart-benchmark.json")
    args = parser.parse_args()

    crop_values = tuple(float(x) for x in args.crop.split(","))
    if len(crop_values) != 4 or not (0 <= crop_values[0] < crop_values[2] <= 1 and 0 <= crop_values[1] < crop_values[3] <= 1):
        raise ValueError("--crop must be left,top,right,bottom fractions in [0,1]")
    ticker_filter = None if args.ticker.lower() == "all" else args.ticker

    print(f"Dataset: {DATASET} | split={args.split} | ticker={args.ticker} | max_images={args.max_images}", flush=True)
    dataset_rows, source_info = fetch_dataset_rows(args.split, ticker_filter, args.max_images)
    print(f"Selected {len(dataset_rows)} held-out image records.", flush=True)

    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")

    results: list[dict[str, Any]] = []
    batch_history: list[dict[str, Any]] = []
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_images = len(dataset_rows)
    total_batches = math.ceil(total_images / args.batch_size)

    def persist_checkpoint(complete: bool) -> dict[str, Any]:
        ordered_results = sorted(results, key=lambda r: int(r.get("sample_index", 0)))
        current_stats = aggregate(ordered_results)
        progress = {
            "completed_batches": len(batch_history),
            "total_batches": total_batches,
            "batch_size": args.batch_size,
            "images_completed": len(ordered_results),
            "images_total": total_images,
            "is_complete": complete,
            "next_sample_index": len(ordered_results),
        }
        output = {
            "project": "Mirsad BTC",
            "benchmark": "huggingface_crypto_chart_dataset",
            "dataset": DATASET,
            "dataset_license": "CC-BY-4.0",
            "split": args.split,
            "ticker_filter": ticker_filter or "ALL_CRYPTO",
            "source": source_info,
            "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "progress": progress,
            "image_count": len(ordered_results),
            "batch_history": batch_history,
            "label_semantics": (
                "The future-return label and pct_return are evaluation-only ground truth. "
                "Neither is passed to the visual analyzer. Direction is scored by the sign of pct_return."
            ),
            "important_limitations": [
                "The chart images are percentage-normalized and omit numeric price axes; a virtual positive scale is used only to preserve visual direction.",
                "This measures future-direction agreement on the dataset label, not trading profitability, fees, slippage, risk-adjusted return, or live execution.",
                "The dataset documents a held-out test split; evaluation should not be confused with training or tuning on those labels.",
                "The first run is an audit of the current analyzer, not a claim of validated predictive performance.",
            ],
            "metrics": current_stats,
            "results": ordered_results,
        }
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(output_path)

        overall = current_stats["overall"]
        lines = [
            "# Mirsad - Crypto chart image benchmark",
            "",
            f"- Dataset: {DATASET}",
            f"- Split: {args.split}",
            f"- Ticker filter: {ticker_filter or 'all crypto'}",
            f"- Progress: {len(ordered_results)}/{total_images} images",
            f"- Batches: {len(batch_history)}/{total_batches} (size {args.batch_size})",
            f"- Decision-eligible: {overall['decision_eligible_images']}",
            f"- Directional predictions: {overall['directional_predictions']}",
            f"- Directional coverage: {overall['directional_coverage_pct']}%",
            f"- Directional accuracy: {overall['accuracy_on_directional_predictions_pct']}%",
            "",
            "| Batch | Samples | Eligible | Predictions | Coverage | Accuracy |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
        for item in batch_history:
            metric = item["metrics"]
            lines.append(
                f"| {item['batch_number']} | {item['sample_start']}-{item['sample_end']} | "
                f"{metric['decision_eligible_images']} | {metric['directional_predictions']} | "
                f"{metric['directional_coverage_pct']}% | {metric['accuracy_on_directional_predictions_pct']}% |"
            )
        lines.extend([
            "",
            "| Ticker | Images | Eligible | Predictions | Coverage | Accuracy |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for ticker, metric in current_stats["by_ticker"].items():
            lines.append(
                f"| {ticker} | {metric['total_images']} | {metric['decision_eligible_images']} | "
                f"{metric['directional_predictions']} | {metric['directional_coverage_pct']}% | "
                f"{metric['accuracy_on_directional_predictions_pct']}% |"
            )
        lines.extend([
            "",
            "## Confidence audit",
            "",
            "| Confidence threshold | Predictions | Accuracy |",
            "|---|---:|---:|",
        ])
        for threshold, metric in overall["accuracy_by_confidence"].items():
            lines.append(f"| {threshold} | {metric['count']} | {metric['accuracy']} |")
        lines.extend([
            "",
            f"- Complete: {complete}",
            "> Future-return labels are evaluation-only and never enter the analyzer. Accuracy is not trading profitability.",
            "> Full diagnostics and per-image decisions are stored in the JSON artifact.",
        ])
        summary_tmp = Path("mirsad-crypto-chart-benchmark-summary.md.tmp")
        summary_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary_tmp.replace(Path("mirsad-crypto-chart-benchmark-summary.md"))
        return current_stats

    with tempfile.TemporaryDirectory(prefix="mirsad_crypto_dataset_") as temp:
        temp_dir = Path(temp)
        # Analyze small, auditable batches. Persist the cumulative results after
        # each batch so an interrupted Actions job still retains completed work.
        for batch_offset in range(0, total_images, args.batch_size):
            batch_number = len(batch_history) + 1
            batch = dataset_rows[batch_offset:batch_offset + args.batch_size]
            batch_results: list[dict[str, Any]] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, 24)) as pool:
                futures = [
                    pool.submit(decode_and_analyze, row, batch_offset + i, temp_dir, crop_values)
                    for i, row in enumerate(batch)
                ]
                for future in concurrent.futures.as_completed(futures):
                    batch_results.append(future.result())

            batch_results.sort(key=lambda r: int(r.get("sample_index", 0)))
            results.extend(batch_results)
            batch_metric = aggregate(batch_results)["overall"]
            sample_start = batch_offset + 1
            sample_end = batch_offset + len(batch)
            batch_history.append({
                "batch_number": batch_number,
                "sample_start": sample_start,
                "sample_end": sample_end,
                "image_count": len(batch_results),
                "metrics": batch_metric,
            })

            print(
                f"\n=== BATCH {batch_number}/{total_batches} | images {sample_start}-{sample_end} "
                f"of {total_images} ===",
                flush=True,
            )
            for row in batch_results:
                confidence = float(row.get("analysis_confidence") or 0.0)
                correct = row.get("correct_direction")
                verdict = "CORRECT" if correct is True else "WRONG" if correct is False else "UNSCORED"
                print(
                    f"IMAGE {int(row.get('sample_index', 0)) + 1}/{total_images} | "
                    f"{row.get('ticker', '?')} | {row.get('end_date', '?')} | "
                    f"bars={row.get('detected_bars', 0)} calibrated={row.get('calibrated_bars', 0)} | "
                    f"eligible={bool(row.get('decision_eligible'))} | "
                    f"prediction={row.get('predicted_direction', 'ABSTAIN')} | "
                    f"target={row.get('target_direction', 'UNKNOWN')} | "
                    f"confidence={confidence:.3f} | {verdict} | "
                    f"status={row.get('engine_status', 'UNKNOWN')}"
                    + (f" | error={row['error']}" if row.get("error") else ""),
                    flush=True,
                )

            current_stats = persist_checkpoint(complete=(len(results) == total_images))
            overall = current_stats["overall"]
            print(
                f"BATCH SUMMARY {batch_number}/{total_batches}: "
                f"coverage={batch_metric['directional_coverage_pct']}% "
                f"accuracy={batch_metric['accuracy_on_directional_predictions_pct']}% "
                f"eligible={batch_metric['decision_eligible_images']}/{len(batch_results)}; "
                f"CUMULATIVE={len(results)}/{total_images} "
                f"coverage={overall['directional_coverage_pct']}% "
                f"accuracy={overall['accuracy_on_directional_predictions_pct']}%",
                flush=True,
            )

    stats = persist_checkpoint(complete=True)
    print(
        f"\nBENCHMARK COMPLETE: {len(results)} images in {total_batches} batches "
        f"of at most {args.batch_size}.",
        flush=True,
    )
    print(f"RESULT_JSON={output_path.resolve()}", flush=True)
    return 0 if stats["overall"]["analyzed_images"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
