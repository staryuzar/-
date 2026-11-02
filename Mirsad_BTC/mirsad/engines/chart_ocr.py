from __future__ import annotations

import math
import re
import statistics
from typing import Any

import cv2
import numpy as np

_NUMERIC_TOKEN = re.compile(
    r"(?<![A-Za-z])(?:[$€£]\s*)?([0-9][0-9,\s]*(?:\.[0-9]+)?)\s*([KMB])?(?![A-Za-z])",
    re.IGNORECASE,
)
_OCR_ENGINE: Any | None = None
_OCR_ERROR: str | None = None


def parse_price_label(text: str) -> float | None:
    """Parse one numeric axis label, including separators and K/M/B suffixes."""
    if not text:
        return None
    normalized = str(text).translate(
        str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    )
    normalized = normalized.replace("٬", ",").replace("٫", ".")
    if re.search(r"\b(?:RSI|MACD|EMA|SMA|ATR|ADX|CCI|STOCH(?:ASTIC)?|WPR|WILLIAMS|BOLLINGER|BBANDS|VOLUME|VOL)\b", normalized, re.IGNORECASE):
        return None
    normalized = normalized.replace("٬", ",").replace("٫", ".")
    for match in _NUMERIC_TOKEN.finditer(normalized):
        raw = re.sub(r"[\s,]", "", match.group(1))
        suffix = (match.group(2) or "").upper()
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        multiplier = {"": 1.0, "K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}[suffix]
        value *= multiplier
        if math.isfinite(value) and value > 0:
            return value
    return None


def fit_price_axis(
    ticks: list[dict[str, Any]],
    *,
    plot_top_px: int,
    plot_bottom_px: int,
    scale_type: str = "linear",
) -> dict[str, Any]:
    """Robustly fit price-to-y mapping from OCR tick labels using Theil-Sen median slopes."""
    scale = str(scale_type).strip().lower()
    if scale not in {"linear", "logarithmic"}:
        return {"status": "INVALID_SCALE", "reason": "Unsupported price scale type."}
    plot_height = int(plot_bottom_px) - int(plot_top_px)
    if plot_height < 32:
        return {"status": "INVALID_PLOT", "reason": "Plot height is too small."}

    clean: list[dict[str, float]] = []
    for tick in ticks:
        try:
            y = float(tick["y_px"])
            price = float(tick["price"])
            score = float(tick.get("score", 0.0))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not (math.isfinite(y) and math.isfinite(price) and price > 0 and math.isfinite(score)):
            continue
        if y < plot_top_px - 0.04 * plot_height or y > plot_bottom_px + 0.04 * plot_height:
            continue
        value = math.log(price) if scale == "logarithmic" else price
        clean.append({"y": y, "price": price, "value": value, "score": score})
    clean.sort(key=lambda item: item["y"])

    # Collapse repeated OCR lines that point to nearly the same tick.
    deduped: list[dict[str, float]] = []
    for item in clean:
        if deduped and abs(item["y"] - deduped[-1]["y"]) < max(3.0, plot_height * 0.008):
            if item["score"] > deduped[-1]["score"]:
                deduped[-1] = item
        else:
            deduped.append(item)
    if len(deduped) < 4:
        return {
            "status": "INSUFFICIENT_TICKS",
            "reason": "At least four distinct numeric axis labels are required for automatic calibration.",
            "tick_count": len(deduped),
            "ticks": deduped,
        }

    pairs = [
        (right["value"] - left["value"]) / (right["y"] - left["y"])
        for index, left in enumerate(deduped)
        for right in deduped[index + 1 :]
        if abs(right["y"] - left["y"]) >= 2.0
    ]
    if not pairs:
        return {"status": "INSUFFICIENT_TICKS", "reason": "Axis labels have no usable vertical spacing."}
    slope = float(statistics.median(pairs))
    intercept = float(statistics.median(item["value"] - slope * item["y"] for item in deduped))
    if not math.isfinite(slope) or slope >= 0:
        return {"status": "NON_MONOTONIC_AXIS", "reason": "Higher prices were not consistently located above lower prices."}

    residual_limit = max(4.0, plot_height * 0.0125)

    def y_residual(item: dict[str, float], a: float, b: float) -> float:
        return abs(item["y"] - (item["value"] - a) / b)

    inliers = [item for item in deduped if y_residual(item, intercept, slope) <= residual_limit]
    if len(inliers) >= 3:
        inlier_pairs = [
            (right["value"] - left["value"]) / (right["y"] - left["y"])
            for index, left in enumerate(inliers)
            for right in inliers[index + 1 :]
            if abs(right["y"] - left["y"]) >= 2.0
        ]
        if inlier_pairs:
            slope = float(statistics.median(inlier_pairs))
            intercept = float(statistics.median(item["value"] - slope * item["y"] for item in inliers))
    residuals = [y_residual(item, intercept, slope) for item in inliers]
    rms_px = math.sqrt(sum(value * value for value in residuals) / len(residuals)) if residuals else float("inf")
    inlier_ratio = len(inliers) / len(deduped)
    if len(inliers) < 3 or inlier_ratio < 0.75 or rms_px > residual_limit:
        return {
            "status": "LOW_CONFIDENCE",
            "reason": "OCR ticks do not form a sufficiently consistent price axis.",
            "tick_count": len(deduped),
            "inlier_count": len(inliers),
            "inlier_ratio": round(inlier_ratio, 4),
            "rms_residual_px": round(rms_px, 3) if math.isfinite(rms_px) else None,
            "ticks": deduped,
        }

    top_value = intercept + slope * float(plot_top_px)
    bottom_value = intercept + slope * float(plot_bottom_px)
    if scale == "logarithmic":
        top_price = math.exp(top_value)
        bottom_price = math.exp(bottom_value)
    else:
        top_price = top_value
        bottom_price = bottom_value
    if not (
        math.isfinite(top_price)
        and math.isfinite(bottom_price)
        and top_price > bottom_price > 0
    ):
        return {
            "status": "INVALID_FIT",
            "reason": "The fitted axis produced an invalid positive price range.",
            "tick_count": len(deduped),
            "inlier_count": len(inliers),
        }

    confidence = max(0.0, min(1.0, inlier_ratio * (1.0 - rms_px / residual_limit)))
    return {
        "status": "READY",
        "scale_type": scale,
        "price_top": top_price,
        "price_bottom": bottom_price,
        "plot_top_px": int(plot_top_px),
        "plot_bottom_px": int(plot_bottom_px),
        "tick_count": len(deduped),
        "inlier_count": len(inliers),
        "inlier_ratio": round(inlier_ratio, 4),
        "rms_residual_px": round(rms_px, 3),
        "confidence": round(confidence, 4),
        "ticks": [
            {
                "y_px": round(item["y"], 2),
                "price": item["price"],
                "score": round(item["score"], 4),
                "inlier": item in inliers,
            }
            for item in deduped
        ],
    }


def _get_ocr_engine() -> Any:
    global _OCR_ENGINE, _OCR_ERROR
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    if _OCR_ERROR is not None:
        raise RuntimeError(_OCR_ERROR)
    try:
        from rapidocr import RapidOCR

        _OCR_ENGINE = RapidOCR(params={"Global.text_score": 0.25, "Global.use_cls": False})
        return _OCR_ENGINE
    except Exception as exc:
        _OCR_ERROR = f"RapidOCR initialization failed: {type(exc).__name__}: {exc}"
        raise RuntimeError(_OCR_ERROR) from exc


def detect_price_axis_ticks(
    image_bgr: np.ndarray,
    *,
    plot_top_px: int = 0,
    plot_bottom_px: int | None = None,
    plot_right_px: int | None = None,
    minimum_score: float = 0.30,
) -> dict[str, Any]:
    """Read numbers from the chart's right-hand price axis without changing chart pixels."""
    if image_bgr is None or image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        return {"status": "INVALID_IMAGE", "ticks": [], "reason": "Expected a BGR colour image."}
    height, width = image_bgr.shape[:2]
    y_top = max(0, int(plot_top_px))
    y_bottom = min(height, int(plot_bottom_px if plot_bottom_px is not None else height))
    explicit_right = int(plot_right_px or 0)
    if y_top >= y_bottom:
        return {"status": "INVALID_PLOT", "ticks": [], "reason": "Invalid vertical plot bounds."}

    if 0 < explicit_right < width - 12:
        axis_left = explicit_right
    else:
        axis_left = int(round(width * 0.82))
    axis_left = max(0, min(axis_left, width - 12))
    axis_crop = image_bgr[y_top:y_bottom, axis_left:width]
    if axis_crop.size == 0:
        return {"status": "NO_AXIS_CROP", "ticks": [], "reason": "The right-axis crop is empty."}
    try:
        ocr = _get_ocr_engine()
        output = ocr(axis_crop)
        raw_texts = getattr(output, "txts", None)
        raw_scores = getattr(output, "scores", None)
        raw_boxes = getattr(output, "boxes", None)
        # RapidOCR 3.x exposes boxes as a NumPy array; boolean evaluation is ambiguous.
        texts = [] if raw_texts is None else list(raw_texts)
        scores = [] if raw_scores is None else list(raw_scores)
        boxes = [] if raw_boxes is None else list(raw_boxes)
    except Exception as exc:
        return {
            "status": "OCR_UNAVAILABLE",
            "ticks": [],
            "reason": f"{type(exc).__name__}: {exc}",
            "axis_crop_left_px": axis_left,
        }

    ticks: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        try:
            score = float(scores[index]) if index < len(scores) else 0.0
            box = np.asarray(boxes[index], dtype=float)
            if box.shape != (4, 2) or not np.isfinite(box).all():
                continue
            y_center = float(np.mean(box[:, 1])) + y_top
            x_left = float(np.min(box[:, 0])) + axis_left
        except (IndexError, TypeError, ValueError, OverflowError):
            continue
        if score < minimum_score or y_center < y_top or y_center > y_bottom:
            continue
        price = parse_price_label(str(text))
        if price is None:
            continue
        ticks.append({
            "text": str(text),
            "price": price,
            "y_px": y_center,
            "x_left_px": x_left,
            "score": score,
        })
    ticks.sort(key=lambda tick: tick["y_px"])
    return {
        "status": "TICKS_FOUND" if ticks else "NO_NUMERIC_TICKS",
        "ticks": ticks,
        "axis_crop_left_px": axis_left,
        "axis_crop_right_px": width,
        "candidate_plot_right_px": (
            max(0, int(round(min(tick["x_left_px"] for tick in ticks) - 5)))
            if ticks else None
        ),
        "ocr_backend": "RapidOCR",
        "ocr_version_required": ">=3.10,<4",
    }


__all__ = ["parse_price_label", "fit_price_axis", "detect_price_axis_ticks"]
