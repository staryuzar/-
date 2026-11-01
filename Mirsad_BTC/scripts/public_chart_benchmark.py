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
    result = {
        "project": "Mirsad BTC",
        "benchmark": "public_chart_image_robustness",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "image_count": len(rows),
        "successful_analyses": successful,
        "failed_downloads_or_analyses": len(rows) - successful,
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
        "",
        "| Image | Engine | Bars | Bias | Score | Confidence | Comparison |",
        "|---|---:|---:|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {id} | {status} | {bars} | {bias} | {score} | {confidence} | {comparison} |".format(
                id=row.get("id", "unknown"),
                status=row.get("engine_status", "ERROR"),
                bars=row.get("detected_bars", 0),
                bias=row.get("visual_bias", "—"),
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
