from __future__ import annotations

import json

import cv2
import numpy as np

from mirsad.engines.chart_ocr import detect_price_axis_ticks, fit_price_axis


def main() -> int:
    width, height = 1280, 720
    plot_left, plot_right = 80, 1120
    plot_top, plot_bottom = 60, 620
    image = np.full((height, width, 3), 255, dtype=np.uint8)

    values = [
        (120, 120000),
        (250, 100000),
        (380, 80000),
        (510, 60000),
    ]
    for y, price in values:
        cv2.line(image, (plot_left, y), (plot_right, y), (220, 220, 220), 1)
        text = f"{price:,}"
        cv2.putText(
            image,
            text,
            (plot_right + 12, y + 7),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (20, 20, 20),
            2,
            cv2.LINE_AA,
        )

    detected = detect_price_axis_ticks(
        image,
        plot_top_px=plot_top,
        plot_bottom_px=plot_bottom,
        plot_right_px=plot_right,
        minimum_score=0.25,
    )
    fitted = fit_price_axis(
        detected.get("ticks", []),
        plot_top_px=plot_top,
        plot_bottom_px=plot_bottom,
        scale_type="linear",
    )
    report = {
        "detected_status": detected.get("status"),
        "tick_count": len(detected.get("ticks", [])),
        "ticks": [
            {"text": tick["text"], "price": tick["price"], "y_px": round(tick["y_px"], 2)}
            for tick in detected.get("ticks", [])
        ],
        "fit_status": fitted.get("status"),
        "fit_confidence": fitted.get("confidence"),
        "price_top": fitted.get("price_top"),
        "price_bottom": fitted.get("price_bottom"),
        "residual_px": fitted.get("rms_residual_px"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if detected.get("status") != "TICKS_FOUND":
        raise SystemExit("RapidOCR did not read numeric price-axis labels.")
    if fitted.get("status") != "READY":
        raise SystemExit("OCR ticks did not produce a reliable linear price-axis fit.")
    if len(detected.get("ticks", [])) < 4:
        raise SystemExit("Fewer than four distinct OCR price ticks were detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
