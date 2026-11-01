from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "data" / "public_chart_manifest.json"
USER_AGENT = "MirsadBTC-ChartResearch/0.3 (public-image-evaluation; no trading)"

def download_image(url: str, timeout: int = 25, maximum_bytes: int = 12 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "image/" not in content_type:
            raise ValueError(f"URL did not return an image (Content-Type={content_type!r})")
        payload = response.read(maximum_bytes + 1)
    if not payload or len(payload) > maximum_bytes:
        raise ValueError(f"Image payload is empty or exceeds {maximum_bytes} bytes")
    return payload

def palette_profile(image: np.ndarray, crop: list[float]) -> dict[str, Any]:
    height, width = image.shape[:2]
    left, top, right, bottom = [float(v) for v in crop]
    x0, x1 = int(left * width), int(right * width)
    y0, y1 = int(top * height), int(bottom * height)
    roi = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    selected = (saturation > 35) & (value > 45)
    total = int(selected.sum())
    if total == 0:
        return {"saturated_pixels": 0, "dominant_hues": [], "hue_families": {}}
    hist = np.bincount(hue[selected].astype(np.int32), minlength=180)
    top_hues = np.argsort(hist)[::-1][:8]
    families = {
        "red": int(hist[:13].sum() + hist[168:].sum()),
        "orange": int(hist[13:25].sum()),
        "yellow": int(hist[25:36].sum()),
        "green": int(hist[36:86].sum()),
        "cyan": int(hist[86:106].sum()),
        "blue": int(hist[106:136].sum()),
        "purple": int(hist[136:168].sum()),
    }
    return {
        "saturated_pixels": total,
        "dominant_hues": [{"hue": int(v), "pixels": int(hist[v])} for v in top_hues if hist[v] > 0],
        "hue_families": families,
    }


def analyze_sample(sample: dict[str, Any]) -> dict[str, Any]:
    from mirsad.engines.chart import analyze_chart_image

    started = time.monotonic()
    payload = download_image(sample["image_url"])
    array = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Downloaded payload could not be decoded as an image")
    height, width = image.shape[:2]
    left, top, right, bottom = [float(v) for v in sample["crop"]]
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("Crop fractions must be inside [0,1] with positive area")

    metadata = {
        "symbol": sample["symbol"],
        "timeframe": sample["timeframe"],
        "price_top": float(sample["price_top"]),
        "price_bottom": float(sample["price_bottom"]),
        "plot_left_px": int(round(left * width)),
        "plot_right_px": int(round(right * width)),
        "plot_top_px": int(round(top * height)),
        "plot_bottom_px": int(round(bottom * height)),
    }
    with tempfile.TemporaryDirectory(prefix="mirsad_public_chart_") as temp:
        image_path = Path(temp) / "public_chart_image.png"
        if not cv2.imwrite(str(image_path), image):
            raise RuntimeError("Could not write decoded image for the analyzer")
        result = analyze_chart_image(
            image_path,
            metadata,
            expected_symbol=sample["symbol"],
        )

    extracted_bars = result.get("bars", []) or []
    last_bar = extracted_bars[-1] if extracted_bars else {}
    last_direction = None
    if last_bar.get("open") is not None and last_bar.get("close") is not None:
        last_direction = "BULLISH" if float(last_bar["close"]) > float(last_bar["open"]) else (
            "BEARISH" if float(last_bar["close"]) < float(last_bar["open"]) else "DOJI"
        )
    expected_last = sample.get("expected_last_candle_direction")
    last_match = (
        "MATCH" if expected_last and last_direction == expected_last
        else "MISMATCH" if expected_last and last_direction is not None
        else "NOT_TESTED"
    )
    palette = palette_profile(image, sample["crop"])

    reference = str(sample.get("reference_bias", "UNKNOWN")).upper()
    actual = str(result.get("visual_bias", "NEUTRAL")).upper()
    if reference in {"BULLISH", "BEARISH"} and actual in {"BULLISH", "BEARISH"}:
        agreement = "AGREES_WITH_PUBLISHED_CONTEXT" if reference == actual else "DIFFERS_FROM_PUBLISHED_CONTEXT"
    elif reference == actual:
        agreement = "AGREES_WITH_NEUTRAL_OR_MIXED_CONTEXT"
    else:
        agreement = "NOT_COMPARABLE_OR_NO_CLEAR_ENGINE_SIGNAL"

    return {
        "id": sample["id"],
        "title": sample["title"],
        "source_url": sample["source_url"],
        "image_url": sample["image_url"],
        "symbol": sample["symbol"],
        "timeframe": sample["timeframe"],
        "snapshot_date": sample.get("snapshot_date"),
        "downloaded_bytes": len(payload),
        "image_width": width,
        "image_height": height,
        "engine_status": result.get("status"),
        "decision_eligible": result.get("decision_eligible"),
        "last_bar_x_ratio": result.get("last_bar_x_ratio"),
        "mean_colour_purity": result.get("mean_colour_purity"),
        "palette_mode": result.get("palette_mode"),
        "detected_bars": result.get("detected_bar_count", 0),
        "calibrated_bars": result.get("calibrated_bar_count", 0),
        "visual_bias": actual,
        "analysis_score": result.get("analysis_score"),
        "analysis_confidence": result.get("analysis_confidence"),
        "visual_trend": result.get("visual_trend"),
        "market_structure": result.get("market_structure"),
        "momentum": result.get("momentum"),
        "analysis_components": result.get("analysis_components"),
        "patterns": result.get("pattern_candidates", []),
        "last_detected_candle": last_bar,
        "last_detected_candle_direction": last_direction,
        "expected_last_candle_direction": expected_last,
        "last_candle_direction_match": last_match,
        "expected_last_candle_ohlc": sample.get("expected_last_candle_ohlc"),
        "palette_profile": palette,
        "reference_bias": reference,
        "reference_note": sample.get("reference_note"),
        "published_context_comparison": agreement,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Mirsad chart analysis on public Bitcoin chart screenshots.")
    parser.add_argument("--output", default="public-chart-benchmark.json")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for sample in manifest:
        try:
            rows.append(analyze_sample(sample))
        except Exception as exc:
            rows.append({
                "id": sample.get("id"),
                "title": sample.get("title"),
                "source_url": sample.get("source_url"),
                "image_url": sample.get("image_url"),
                "engine_status": "DOWNLOAD_OR_ANALYSIS_ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            })

    successful = sum(1 for row in rows if row.get("engine_status") not in {"DOWNLOAD_OR_ANALYSIS_ERROR", "ERROR"})
    eligible_count = sum(1 for row in rows if row.get("decision_eligible"))
    last_candle_checks = sum(1 for row in rows if row.get("last_candle_direction_match") in {"MATCH", "MISMATCH"})
    last_candle_matches = sum(1 for row in rows if row.get("last_candle_direction_match") == "MATCH")
    result = {
        "project": "Mirsad BTC",
        "benchmark": "public_chart_image_robustness",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "image_count": len(rows),
        "successful_analyses": successful,
        "failed_downloads_or_analyses": len(rows) - successful,
        "decision_eligible_images": eligible_count,
        "last_candle_checks": last_candle_checks,
        "last_candle_direction_matches": last_candle_matches,
        "important_note": (
            "Agreement with an article's written interpretation is not proof that a trade would be profitable. "
            "True outcome validation requires an exact chart cutoff timestamp, the same market/instrument, "
            "and future OHLC data that was not visible in the screenshot."
        ),
        "results": rows,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "## Mirsad public chart image benchmark",
        "",
        f"- Images in manifest: {len(rows)}",
        f"- Successful downloads and analyses: {successful}",
        f"- Failed downloads/analyses: {len(rows) - successful}",
        f"- Images eligible for decision: {eligible_count}",
        f"- Last-candle direction checks: {last_candle_matches}/{last_candle_checks}",
        "",
        "| Image | Engine | Bars | Bias | Last candle | Right-edge | Purity | Score | Confidence | Comparison |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {id} | {status} | {bars} | {bias} | {last} ({match}) | {right} | {purity} | {score} | {confidence} | {comparison} |".format(
                id=row.get("id", "unknown"),
                status=row.get("engine_status", "ERROR"),
                bars=row.get("detected_bars", 0),
                bias=row.get("visual_bias", "—"),
                last=row.get("last_detected_candle_direction", "—"),
                match=row.get("last_candle_direction_match", "—"),
                hue=(row.get("palette_profile", {}).get("dominant_hues") or [{}])[0].get("hue", "—"),
                right=row.get("last_bar_x_ratio", "—"),
                purity=row.get("mean_colour_purity", "—"),
                score=row.get("analysis_score", "—"),
                confidence=row.get("analysis_confidence", "—"),
                comparison=row.get("published_context_comparison", "—"),
            )
        )
    lines.extend([
        "",
        "> A comparison with the publisher's text is a diagnostic reference only, not market-outcome accuracy.",
        "> The downloaded source images are temporary and are not redistributed in the artifact.",
    ])
    summary = Path("public-chart-benchmark-summary.md")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"RESULT_JSON={output_path.resolve()}")
    if successful == 0:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
