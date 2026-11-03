from __future__ import annotations

import math
import re
import statistics
from typing import Any

import cv2
import numpy as np

_NUMERIC_TOKEN = re.compile(
    r"(?<![A-Za-z])(?:[$€£]\s*)?([0-9][0-9.,\s]*)\s*([KMB])?(?![A-Za-z])",
    re.IGNORECASE,
)
_OCR_ENGINE: Any | None = None
_OCR_ERROR: str | None = None


def _normalize_price_number(raw: str) -> str | None:
    """Normalize decimal/thousands separators without guessing malformed groups."""
    value = str(raw).strip()
    if not value or not re.fullmatch(r"[0-9][0-9.,\s]*", value):
        return None

    # A chart locale normally uses either spaces or punctuation for grouping.
    # Mixed space/punctuation grouping is rejected to avoid silently changing scale.
    has_space = bool(re.search(r"\s", value))
    has_dot = "." in value
    has_comma = "," in value

    def grouped_integer(part: str, separator: str | None) -> str | None:
        if not part or not re.fullmatch(r"[0-9][0-9.,\s]*", part):
            return None
        if has_space and ("," in part or "." in part):
            return None
        if separator:
            groups = part.split(separator)
            if (
                len(groups) < 2
                or not 1 <= len(groups[0]) <= 3
                or not groups[0].isdigit()
                or any(len(group) != 3 or not group.isdigit() for group in groups[1:])
            ):
                return None
            return "".join(groups)
        if has_space:
            groups = re.split(r"\s+", part.strip())
            if (
                len(groups) < 2
                or not 1 <= len(groups[0]) <= 3
                or not groups[0].isdigit()
                or any(len(group) != 3 or not group.isdigit() for group in groups[1:])
            ):
                return None
            return "".join(groups)
        return part if part.isdigit() else None

    if has_dot and has_comma:
        decimal_separator = "." if value.rfind(".") > value.rfind(",") else ","
        grouping_separator = "," if decimal_separator == "." else "."
        if has_space:
            return None
        integer_part, fraction = value.rsplit(decimal_separator, 1)
        if not fraction.isdigit():
            return None
        integer_digits = grouped_integer(integer_part, grouping_separator)
        if integer_digits is None:
            return None
        return integer_digits + "." + fraction

    separator = "," if has_comma else "." if has_dot else None
    if separator is None:
        return grouped_integer(value, None)

    if value.count(separator) > 1:
        if has_space:
            return None
        return grouped_integer(value, separator)

    integer_part, tail = value.split(separator, 1)
    if not integer_part or not tail.isdigit():
        return None
    if has_space:
        integer_digits = grouped_integer(integer_part, None)
        return integer_digits + "." + tail if integer_digits is not None else None

    # With one punctuation mark, one or two trailing digits are decimal.
    # Three trailing digits are treated as grouping for 1-3 digit leading groups
    # (69.500 -> 69500); a leading zero remains decimal (0.125 -> 0.125).
    if len(tail) in (1, 2) or integer_part == "0":
        return integer_part + "." + tail
    if len(tail) == 3 and 1 <= len(integer_part) <= 3:
        return integer_part + tail
    return integer_part + "." + tail


def parse_price_label(text: str) -> float | None:
    """Parse axis labels with conservative US/EU separators and K/M/B suffixes."""
    if not text:
        return None
    normalized = str(text).translate(
        str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    )
    normalized = normalized.replace("٬", ",").replace("٫", ".")
    if re.search(r"\b(?:RSI|MACD|EMA|SMA|ATR|ADX|CCI|STOCH(?:ASTIC)?|WPR|WILLIAMS|BOLLINGER|BBANDS|VOLUME|VOL)\b", normalized, re.IGNORECASE):
        return None
    for match in _NUMERIC_TOKEN.finditer(normalized):
        # Percent labels and malformed separator groups are not price ticks.
        end = match.end()
        if end < len(normalized) and normalized[end:].lstrip().startswith("%"):
            continue
        number = _normalize_price_number(match.group(1))
        if number is None:
            continue
        suffix = (match.group(2) or "").upper()
        try:
            value = float(number)
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


def infer_plot_bottom_from_axis_ticks(
    ticks: list[dict[str, Any]],
    *,
    plot_top_px: int,
    current_plot_bottom_px: int,
    minimum_ticks: int = 8,
) -> dict[str, Any]:
    """Exclude an unlabelled bottom overlay band when dense, fitted axis ticks end well above it."""
    top = int(plot_top_px)
    current_bottom = int(current_plot_bottom_px)
    plot_height = current_bottom - top
    if plot_height < 64:
        return {
            "status": "UNCHANGED",
            "plot_bottom_px": current_bottom,
            "reason": "Plot height is too small for bottom-band inference.",
        }

    y_values: list[float] = []
    for tick in ticks:
        if not isinstance(tick, dict) or tick.get("inlier") is False:
            continue
        try:
            y = float(tick["y_px"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(y) and top <= y < current_bottom:
            y_values.append(y)
    y_values = sorted(set(round(value, 2) for value in y_values))
    if len(y_values) < max(8, int(minimum_ticks)):
        return {
            "status": "UNCHANGED",
            "plot_bottom_px": current_bottom,
            "tick_count": len(y_values),
            "reason": "Too few inlier axis ticks to infer the price-pane boundary.",
        }

    spacings = [
        right - left
        for left, right in zip(y_values, y_values[1:])
        if 2.0 <= right - left <= plot_height * 0.20
    ]
    if len(spacings) < 5:
        return {
            "status": "UNCHANGED",
            "plot_bottom_px": current_bottom,
            "tick_count": len(y_values),
            "reason": "Axis tick spacing is too sparse or irregular for safe bottom-band inference.",
        }

    median_spacing = float(statistics.median(spacings))
    tick_bottom = float(y_values[-1])
    bottom_gap = float(current_bottom) - tick_bottom
    minimum_gap = max(18.0, median_spacing * 1.25)
    maximum_gap = plot_height * 0.18
    if bottom_gap < minimum_gap or bottom_gap > maximum_gap:
        return {
            "status": "UNCHANGED",
            "plot_bottom_px": current_bottom,
            "tick_count": len(y_values),
            "tick_bottom_y_px": round(tick_bottom, 2),
            "median_tick_spacing_px": round(median_spacing, 2),
            "bottom_gap_px": round(bottom_gap, 2),
            "reason": "The lowest fitted axis tick is not separated from the image bottom by a reliable overlay-band gap.",
        }

    padding = int(round(max(4.0, min(12.0, median_spacing * 0.45))))
    candidate_bottom = min(current_bottom, int(math.ceil(tick_bottom + padding)))
    if candidate_bottom - top < 32 or candidate_bottom >= current_bottom - 8:
        return {
            "status": "UNCHANGED",
            "plot_bottom_px": current_bottom,
            "tick_count": len(y_values),
            "tick_bottom_y_px": round(tick_bottom, 2),
            "median_tick_spacing_px": round(median_spacing, 2),
            "bottom_gap_px": round(bottom_gap, 2),
            "padding_px": padding,
            "reason": "The inferred crop would be too small to improve the price plot safely.",
        }

    return {
        "status": "REFINED",
        "plot_bottom_px": candidate_bottom,
        "tick_count": len(y_values),
        "tick_bottom_y_px": round(tick_bottom, 2),
        "median_tick_spacing_px": round(median_spacing, 2),
        "bottom_gap_px": round(bottom_gap, 2),
        "padding_px": padding,
        "excluded_bottom_band_px": current_bottom - candidate_bottom,
        "reason": "A dense, consistent price-axis tick run ends above an unlabelled bottom overlay band.",
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



_HEADER_TIMEFRAME_RE = re.compile(
    r"(?<![A-Za-z0-9.])(\d{1,3}\s*[smhdwSMHDW])(?![A-Za-z0-9])"
)
_HEADER_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z0-9]{2,12})\s*[/\-]\s*(USDT|USDC|USD|BTC|ETH)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_HEADER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z0-9]{5,16})(?![A-Za-z0-9])")
_HEADER_EXCHANGES = (
    "BINANCE", "BYBIT", "OKX", "COINBASE", "KRAKEN",
    "BITGET", "GATEIO", "KUCOIN", "MEXC",
)
_HEADER_SYMBOL_SUFFIXES = ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH")


def parse_chart_header_text(
    texts: list[str],
    scores: list[float] | None = None,
    *,
    expected_symbol: str | None = None,
) -> dict[str, Any]:
    """Turn OCR header fragments into suggestions without overriding user metadata."""
    clean_texts = [str(item).strip() for item in texts if str(item).strip()]
    combined = " ".join(clean_texts)
    upper = combined.upper()
    normalised = re.sub(r"[^A-Z0-9]", "", upper)

    expected = re.sub(r"[^A-Z0-9]", "", str(expected_symbol or "").upper())
    expected_match: bool | None = None

    timeframe_suggestion = None
    timeframe_match = _HEADER_TIMEFRAME_RE.search(combined)
    if timeframe_match:
        token = re.sub(r"\s+", "", timeframe_match.group(1))
        number = re.match(r"\d+", token)
        unit = token[len(number.group(0)):] if number else ""
        if number and unit:
            numeric_part = int(number.group(0))
            if unit == "M":
                valid_value = numeric_part in {1, 3, 6, 12}
                normalised_unit = "M"
            elif unit.lower() == "m":
                valid_value = numeric_part in {1, 3, 5, 10, 15, 30, 45, 60, 90, 120, 180, 240, 360, 480, 720}
                normalised_unit = "m"
            elif unit.lower() == "h":
                valid_value = numeric_part in {1, 2, 3, 4, 6, 8, 12, 16, 24}
                normalised_unit = "h"
            elif unit.lower() == "d":
                valid_value = 1 <= numeric_part <= 365
                normalised_unit = "d"
            elif unit.lower() == "w":
                valid_value = 1 <= numeric_part <= 52
                normalised_unit = "w"
            else:
                valid_value = False
                normalised_unit = unit.lower()
            if valid_value:
                timeframe_suggestion = f"{numeric_part}{normalised_unit}"

    symbol_suggestion = None
    pair_match = _HEADER_PAIR_RE.search(combined)
    if pair_match:
        symbol_suggestion = (
            pair_match.group(1).upper() + pair_match.group(2).upper()
        )
    else:
        for token in _HEADER_TOKEN_RE.findall(upper):
            if token.endswith(_HEADER_SYMBOL_SUFFIXES):
                symbol_suggestion = token
                break

    exchange_suggestion = next(
        (exchange for exchange in _HEADER_EXCHANGES if exchange in upper),
        None,
    )
    if expected:
        if symbol_suggestion:
            expected_match = re.sub(
                r"[^A-Z0-9]", "", symbol_suggestion.upper()
            ) == expected
        else:
            expected_match = expected in normalised
    numeric_scores: list[float] = []
    for value in scores or []:
        try:
            score = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(score) and 0 <= score <= 1:
            numeric_scores.append(score)

    suggestions_found = any((
        symbol_suggestion,
        timeframe_suggestion,
        exchange_suggestion,
    ))
    return {
        "status": "SUGGESTIONS_FOUND" if suggestions_found else "NO_METADATA",
        "symbol_suggestion": symbol_suggestion,
        "timeframe_suggestion": timeframe_suggestion,
        "exchange_suggestion": exchange_suggestion,
        "expected_symbol": expected_symbol,
        "expected_symbol_match": expected_match,
        "ocr_fragment_count": len(clean_texts),
        "mean_ocr_score": (
            round(sum(numeric_scores) / len(numeric_scores), 4)
            if numeric_scores else None
        ),
        "raw_text": clean_texts,
        "overrides_input_metadata": False,
        "used_for_price_calibration": False,
        "used_for_decision": False,
        "interpretation": "METADATA_SUGGESTIONS_ONLY_NOT_USED_FOR_PRICE_CALIBRATION_OR_DECISION",
    }


def detect_chart_header_metadata(
    image_bgr: np.ndarray,
    *,
    expected_symbol: str | None = None,
    header_height_fraction: float = 0.22,
) -> dict[str, Any]:
    """Optionally OCR the chart header strip to suggest symbol/timeframe/exchange."""
    if (
        image_bgr is None
        or image_bgr.ndim != 3
        or image_bgr.shape[2] != 3
    ):
        return {
            "status": "INVALID_IMAGE",
            "overrides_input_metadata": False,
            "used_for_price_calibration": False,
            "used_for_decision": False,
            "interpretation": "METADATA_SUGGESTIONS_ONLY_NOT_USED_FOR_PRICE_CALIBRATION_OR_DECISION",
        }
    if not math.isfinite(float(header_height_fraction)) or not (
        0.05 <= float(header_height_fraction) <= 0.40
    ):
        return {
            "status": "INVALID_HEADER_REGION",
            "overrides_input_metadata": False,
            "used_for_price_calibration": False,
            "used_for_decision": False,
            "interpretation": "METADATA_SUGGESTIONS_ONLY_NOT_USED_FOR_PRICE_CALIBRATION_OR_DECISION",
        }
    height, width = image_bgr.shape[:2]
    crop_height = max(32, min(height, int(round(height * header_height_fraction))))
    crop = image_bgr[:crop_height, :width]
    try:
        engine = _get_ocr_engine()
        output = engine(crop)
        raw_texts = getattr(output, "txts", None)
        raw_scores = getattr(output, "scores", None)
        texts = [] if raw_texts is None else list(raw_texts)
        scores = [] if raw_scores is None else list(raw_scores)
    except Exception as exc:
        return {
            "status": "OCR_UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {exc}",
            "crop_height_px": crop_height,
            "overrides_input_metadata": False,
            "used_for_price_calibration": False,
            "used_for_decision": False,
            "interpretation": "METADATA_SUGGESTIONS_ONLY_NOT_USED_FOR_PRICE_CALIBRATION_OR_DECISION",
        }
    parsed = parse_chart_header_text(
        texts,
        scores,
        expected_symbol=expected_symbol,
    )
    return {
        **parsed,
        "crop_height_px": crop_height,
        "ocr_backend": "RapidOCR",
        "overrides_input_metadata": False,
        "used_for_price_calibration": False,
        "used_for_decision": False,
        "interpretation": "METADATA_SUGGESTIONS_ONLY_NOT_USED_FOR_PRICE_CALIBRATION_OR_DECISION",
    }


__all__ = ["parse_price_label", "fit_price_axis", "detect_price_axis_ticks", "parse_chart_header_text", "detect_chart_header_metadata"]
