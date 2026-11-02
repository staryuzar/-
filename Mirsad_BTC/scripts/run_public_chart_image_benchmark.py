from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from mirsad.engines.chart import analyze_chart_image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "tests" / "data" / "public_chart_manifest.json"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_IMAGE_HOSTS = {"itbfx.com", "img.bgstatic.com", "s3.tradingview.com"}


def _crop_box(
    width: int,
    height: int,
    crop: list[float] | tuple[float, ...] | None,
    *,
    preserve_right_axis: bool = False,
) -> tuple[int, int, int, int]:
    if crop is None:
        return 0, 0, width, height
    if len(crop) != 4:
        raise ValueError("crop must contain [left, top, right, bottom] fractions")
    left, top, right, bottom = (float(value) for value in crop)
    if not all(math.isfinite(value) for value in (left, top, right, bottom)):
        raise ValueError("crop fractions must be finite")
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("crop fractions must define a non-empty rectangle inside the image")
    # The manifest's right edge marks the plot area. Keep the axis labels beyond
    # that boundary so Engine 2 can calibrate from labels actually present.
    if preserve_right_axis:
        right = 1.0
    box = (
        max(0, min(width, round(left * width))),
        max(0, min(height, round(top * height))),
        max(0, min(width, round(right * width))),
        max(0, min(height, round(bottom * height))),
    )
    if box[2] - box[0] < 64 or box[3] - box[1] < 64:
        raise ValueError("cropped chart region is too small for reliable analysis")
    return box


def _download_image(url: str, destination: Path) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_IMAGE_HOSTS:
        raise ValueError(f"Unapproved public chart image host: {parsed.hostname or 'missing'}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mirsad-Public-Chart-Benchmark/1.0"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https":
            raise ValueError("Image source redirected to a non-HTTPS URL")
        declared_length = response.headers.get("Content-Length")
        if declared_length and int(declared_length) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Chart image exceeds the 20 MB benchmark download limit")
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    if not payload:
        raise ValueError("Downloaded chart image is empty")
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Chart image exceeds the 20 MB benchmark download limit")
    destination.write_bytes(payload)


def _bar_direction(bar: dict[str, Any] | None) -> str | None:
    if not isinstance(bar, dict):
        return None
    if "open" in bar and "close" in bar:
        try:
            opened = float(bar["open"])
            closed = float(bar["close"])
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(opened) or not math.isfinite(closed):
            return None
        if math.isclose(opened, closed, rel_tol=0.0, abs_tol=1e-12):
            return "DOJI"
        return "BULLISH" if closed > opened else "BEARISH"
    colour = str(bar.get("colour", "")).upper()
    if colour in {"GREEN", "BLUE", "TEAL"}:
        return "BULLISH"
    if colour in {"RED", "ORANGE", "MAGENTA"}:
        return "BEARISH"
    return None


def _ohlc_comparison(
    actual: dict[str, Any] | None,
    expected: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return None
    errors: dict[str, float] = {}
    for field in ("open", "high", "low", "close"):
        try:
            observed = float(actual[field])
            reference = float(expected[field])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(observed) or not math.isfinite(reference) or reference <= 0:
            continue
        errors[field] = round(abs(observed - reference) / reference * 100.0, 4)
    if not errors:
        return None
    maximum = max(errors.values())
    return {
        "absolute_error_pct_by_field": errors,
        "maximum_absolute_error_pct": maximum,
        "within_3pct_tolerance": maximum <= 3.0,
    }


def _analyse_entry(entry: dict[str, Any], temp_dir: Path) -> dict[str, Any]:
    chart_id = str(entry.get("id", "unknown"))
    image_url = str(entry.get("image_url", "")).strip()
    if not image_url:
        raise ValueError("Manifest entry is missing image_url")
    downloaded_path = temp_dir / f"{chart_id}_source"
    cropped_path = temp_dir / f"{chart_id}.png"
    _download_image(image_url, downloaded_path)

    with Image.open(downloaded_path) as opened:
        source = opened.convert("RGB")
        source_width, source_height = source.size
        crop_box = _crop_box(
            source_width,
            source_height,
            entry.get("crop"),
            preserve_right_axis=True,
        )
        chart = source.crop(crop_box)
        chart.save(cropped_path, format="PNG")
        width, height = chart.size

    metadata = {
        "symbol": entry.get("symbol"),
        "timeframe": entry.get("timeframe"),
        "price_scale_type": entry.get("price_scale_type", "linear"),
        "plot_left_px": 0,
        "plot_top_px": 0,
        "plot_bottom_px": height,
        # Price calibration must be derived from the right-hand axis OCR.
        # Manifest price bounds are reference context, not input ground truth.
        "auto_axis_ocr": True,
        "palette_mode": entry.get("palette_mode", "auto"),
        # The manifest does not establish that the rightmost candle is closed.
        "last_candle_closed": bool(entry.get("last_candle_closed", False)),
    }
    result = analyze_chart_image(
        cropped_path,
        metadata,
        expected_symbol=str(entry.get("symbol", "")),
    )
    bars = result.get("bars") or []
    latest_bar = bars[-1] if bars else None
    actual_direction = _bar_direction(latest_bar)
    expected_direction = entry.get("expected_last_candle_direction")
    reference_bias = str(entry.get("reference_bias", "UNSPECIFIED")).upper()
    visual_bias = str(result.get("visual_bias", "UNKNOWN")).upper()
    bias_match = (
        visual_bias == reference_bias
        if reference_bias in {"BULLISH", "BEARISH"}
        else None
    )
    latest_ohlc = (
        {key: latest_bar.get(key) for key in ("open", "high", "low", "close")}
        if latest_bar and all(key in latest_bar for key in ("open", "high", "low", "close"))
        else None
    )
    axis_ocr = result.get("axis_ocr") or {}

    return {
        "id": chart_id,
        "title": entry.get("title"),
        "source_url": entry.get("source_url"),
        "snapshot_date": entry.get("snapshot_date"),
        "source_image_size": [source_width, source_height],
        "analysed_crop_size": [width, height],
        "status": result.get("status"),
        "decision_eligible": result.get("decision_eligible", False),
        "quality_gates": result.get("quality_gates", {}),
        "detected_bar_count": result.get("detected_bar_count", 0),
        "calibrated_bar_count": result.get("calibrated_bar_count", 0),
        "confirmed_bar_count": result.get("confirmed_bar_count", 0),
        "latest_candle_closed": result.get("last_candle_closed", False),
        "latest_candle_direction": actual_direction,
        "expected_last_candle_direction": expected_direction,
        "last_candle_direction_match": (
            actual_direction == str(expected_direction).upper()
            if expected_direction else None
        ),
        "visual_bias": visual_bias,
        "reference_bias": reference_bias,
        "bias_agreement": bias_match,
        "analysis_score": result.get("analysis_score"),
        "analysis_confidence": result.get("analysis_confidence"),
        "confidence_kind": result.get("confidence_kind"),
        "calibration": result.get("calibration", {}),
        "axis_ocr_status": axis_ocr.get("status"),
        "axis_ocr_tick_count": len(axis_ocr.get("ticks", [])),
        "axis_ocr_fit": axis_ocr.get("fit"),
        "colour_counts": result.get("colour_counts", {}),
        "extraction_diagnostics": result.get("extraction_diagnostics", {}),
        "latest_bar_ohlc": latest_ohlc,
        "latest_bar_ohlc_reference_check": _ohlc_comparison(
            latest_ohlc,
            entry.get("expected_last_candle_ohlc"),
        ),
        "error": result.get("error"),
        "note": (
            "Engine 2 visual evidence only; reference_bias is analyst context, "
            "not a ground-truth label or an Engine 4 trade instruction."
        ),
    }


def run_benchmark(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Public chart manifest must be a non-empty JSON array")
    reports: list[dict[str, Any]] = []
    for entry in manifest:
        chart_id = str(entry.get("id", "unknown")) if isinstance(entry, dict) else "invalid"
        try:
            with tempfile.TemporaryDirectory(prefix="mirsad-chart-") as directory:
                reports.append(_analyse_entry(entry, Path(directory)))
        except Exception as exc:
            reports.append({
                "id": chart_id,
                "status": "BENCHMARK_ERROR",
                "decision_eligible": False,
                "error": f"{type(exc).__name__}: {exc}",
            })

    attempted = len(reports)
    analysed = sum(item.get("status") not in {"BENCHMARK_ERROR", "ERROR"} for item in reports)
    expected = [item for item in reports if item.get("last_candle_direction_match") is not None]
    direction_matches = sum(bool(item["last_candle_direction_match"]) for item in expected)
    eligible = sum(bool(item.get("decision_eligible")) for item in reports)
    ohlc_checks = [
        item["latest_bar_ohlc_reference_check"]
        for item in reports
        if item.get("latest_bar_ohlc_reference_check") is not None
    ]
    return {
        "benchmark": "mirsad_public_chart_image_smoke_test",
        "schema_version": 1,
        "manifest": str(manifest_path.name),
        "images_attempted": attempted,
        "images_analysed": analysed,
        "decision_eligible_images": eligible,
        "last_candle_reference_cases": len(expected),
        "last_candle_direction_matches": direction_matches,
        "last_candle_direction_accuracy_pct": (
            round(100.0 * direction_matches / len(expected), 2) if expected else None
        ),
        "ohlc_reference_cases": len(ohlc_checks),
        "ohlc_cases_within_3pct_tolerance": sum(
            bool(item["within_3pct_tolerance"]) for item in ohlc_checks
        ),
        "results": reports,
        "interpretation": (
            "This is an image-extraction and visual-evidence smoke test. It does not "
            "validate profitability, establish analyst bias as truth, or test Engine 4."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Engine 2 against public BTC chart images in the manifest."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, help="Optional path for the JSON benchmark report.")
    args = parser.parse_args()

    if not args.manifest.is_file():
        parser.error(f"Manifest does not exist: {args.manifest}")
    report = run_benchmark(args.manifest)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if report["images_analysed"] == 0:
        print("No public chart image could be analysed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
