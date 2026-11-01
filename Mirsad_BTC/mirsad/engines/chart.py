from __future__ import annotations
import math
import time
from pathlib import Path
from typing import Any
import cv2
import numpy as np

def _groups(columns:np.ndarray,gap:int=2)->list[tuple[int,int]]:
    indices=np.flatnonzero(columns)
    if len(indices)==0:
        return []
    result=[]
    start=previous=int(indices[0])
    for value in indices[1:]:
        current=int(value)
        if current-previous>gap+1:
            result.append((start,previous))
            start=current
        previous=current
    result.append((start,previous))
    return result

PALETTE_PRESETS: dict[str, dict[str, list[tuple[int, int]]]] = {
    "auto": {"bullish": [(34, 96), (97, 140)], "bearish": [(0, 30), (160, 179)]},
    "green_red": {"bullish": [(34, 96)], "bearish": [(0, 12), (165, 179)]},
    "blue_orange": {"bullish": [(97, 140)], "bearish": [(8, 30), (165, 179)]},
    "teal_magenta": {"bullish": [(75, 110)], "bearish": [(135, 179)]},
}


def _hue_mask(hsv: np.ndarray, ranges: list[tuple[int, int]]) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in ranges:
        part = cv2.inRange(
            hsv,
            np.array([lower, 45, 35], dtype=np.uint8),
            np.array([upper, 255, 255], dtype=np.uint8),
        )
        mask = cv2.bitwise_or(mask, part)
    return mask


def _extract_bars(
    image: np.ndarray, meta: dict[str, Any], diagnostics: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    height, width = image.shape[:2]
    left = int(meta.get("plot_left_px", 0) or 0)
    right_value = int(meta.get("plot_right_px", 0) or 0)
    right = width if right_value <= 0 else right_value
    top = int(meta.get("plot_top_px", 0) or 0)
    bottom_value = int(meta.get("plot_bottom_px", 0) or 0)
    bottom = height if bottom_value <= 0 else bottom_value
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("plot bounds must be inside the image and have positive width/height")

    area = image[top:bottom, left:right]
    if area.size == 0:
        return []
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    palette_mode = str(meta.get("palette_mode", "auto")).strip().lower()
    if palette_mode not in PALETTE_PRESETS:
        raise ValueError(f"Unsupported palette_mode: {palette_mode}")
    palette = PALETTE_PRESETS[palette_mode]
    bullish = _hue_mask(hsv, palette["bullish"]) > 0
    bearish = _hue_mask(hsv, palette["bearish"]) > 0
    mask = bullish | bearish

    # Moving-average curves and other colored indicators can run across nearly
    # every x-column. Retain vertically persistent candle cores/wicks for the
    # column projection; use the original color masks below for OHLC geometry.
    desired_kernel_height = max(3, int(round(area.shape[0] * 0.015)))
    if desired_kernel_height % 2 == 0:
        desired_kernel_height += 1
    largest_odd_height = area.shape[0] if area.shape[0] % 2 else max(1, area.shape[0] - 1)
    vertical_kernel_height = max(1, min(desired_kernel_height, largest_odd_height))
    vertical_kernel = np.ones((vertical_kernel_height, 1), dtype=np.uint8)
    candle_core = cv2.morphologyEx(
        mask.astype(np.uint8) * 255,
        cv2.MORPH_OPEN,
        vertical_kernel,
    ) > 0
    # Expand the candle core only along y to restore the original wick/body
    # edges; indicator lines removed by opening stay excluded from OHLC geometry.
    candle_support = cv2.dilate(
        candle_core.astype(np.uint8) * 255,
        vertical_kernel,
    ) > 0
    candle_bullish = bullish & candle_support
    candle_bearish = bearish & candle_support

    activity = candle_core.sum(axis=0)
    minimum_activity = max(1, int(np.ceil(area.shape[0] * 0.0008)))
    # Allow tiny anti-alias gaps between wick/body pixels, as seen in resized web charts.
    groups = _groups(activity >= minimum_activity, gap=2)
    bars: list[dict[str, Any]] = []
    # Public chart images vary significantly in resolution and candle thickness.
    # A 1.2% / 18 px cap discarded valid ~19 px candles on high-resolution charts.
    max_bar_width = max(6, min(32, int(round(area.shape[1] * 0.02))))
    try:
        expected_candle_count = int(meta.get("expected_candle_count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        expected_candle_count = 0
    if expected_candle_count > 0:
        # Fixed-window educational renders have known candle slots. Use the
        # slot geometry so thick bodies are not mistaken for overlays.
        slot_width = area.shape[1] / expected_candle_count
        max_bar_width = max(max_bar_width, min(48, int(round(slot_width * 1.05))))
    rejection_counts = {"wide_group": 0, "low_pixel_count": 0, "mixed_palette": 0, "short_component": 0, "no_body": 0}
    if diagnostics is not None:
        diagnostics.update({
            "palette_mode": palette_mode,
            "bullish_palette_pixels": int(bullish.sum()),
            "bearish_palette_pixels": int(bearish.sum()),
            "raw_active_columns": int(np.count_nonzero(mask.sum(axis=0) >= minimum_activity)),
            "active_columns": int(np.count_nonzero(activity >= minimum_activity)),
            "vertical_kernel_height": vertical_kernel_height,
            "indicator_pixels_suppressed": int(
                mask.sum() - np.count_nonzero(candle_bullish | candle_bearish)
            ),
            "projection_groups": len(groups),
            "projection_group_widths": [int(x1 - x0 + 1) for x0, x1 in groups[:500]],
            "minimum_activity_per_column": minimum_activity,
            "maximum_bar_width": max_bar_width,
        })

    for x0, x1 in groups:
        group_width = x1 - x0 + 1
        if group_width > max_bar_width:
            rejection_counts["wide_group"] += 1
            continue
        bull_roi = candle_bullish[:, x0:x1 + 1]
        bear_roi = candle_bearish[:, x0:x1 + 1]
        bull_pixels = int(bull_roi.sum())
        bear_pixels = int(bear_roi.sum())
        total_pixels = bull_pixels + bear_pixels
        if total_pixels < max(8, int(area.shape[0] * 0.008)) or bull_pixels == bear_pixels:
            rejection_counts["low_pixel_count"] += 1
            continue
        colour_purity = max(bull_pixels, bear_pixels) / total_pixels
        if colour_purity < 0.68:
            rejection_counts["mixed_palette"] += 1
            continue
        colour = "GREEN" if bull_pixels > bear_pixels else "RED"
        roi = bull_roi | bear_roi
        ys, _ = np.where(roi)
        if len(ys) < 5:
            rejection_counts["short_component"] += 1
            continue
        y_high, y_low = int(ys.min()), int(ys.max())
        row_width = roi.sum(axis=1)
        strongest = int(row_width.max())
        if strongest <= 0:
            continue
        body_rows = np.flatnonzero(row_width >= max(1, int(np.ceil(strongest * 0.48))))
        if len(body_rows) == 0:
            rejection_counts["no_body"] += 1
            continue
        body_top, body_bottom = int(body_rows.min()), int(body_rows.max())
        total_h = max(1, y_low - y_high + 1)
        body_h = max(1, body_bottom - body_top + 1)
        upper, lower = max(0, body_top - y_high), max(0, y_low - body_bottom)
        ratio = min(1.0, body_h / total_h)

        shape = "normal"
        if ratio <= 0.16:
            shape = "doji_candidate"
        elif lower >= 2.2 * body_h and upper <= body_h * 0.8:
            shape = "hammer_candidate"
        elif upper >= 2.2 * body_h and lower <= body_h * 0.8:
            shape = "shooting_star_candidate"

        bars.append({
            "x_px": int((x0 + x1) / 2) + left,
            "width_px": group_width,
            "high_y_px": y_high + top,
            "low_y_px": y_low + top,
            "body_top_y_px": body_top + top,
            "body_bottom_y_px": body_bottom + top,
            "colour": colour,
            "shape": shape,
            "body_ratio": round(ratio, 3),
            "colour_purity": round(colour_purity, 4),
            "bullish_colour_pixels": bull_pixels,
            "bearish_colour_pixels": bear_pixels,
            "palette_mode": palette_mode,
        })
    if diagnostics is not None:
        diagnostics["accepted_bars"] = len(bars)
        diagnostics["rejected_groups"] = rejection_counts
    return sorted(bars, key=lambda item: item["x_px"])

def _body_bounds(bar: dict[str, Any]) -> tuple[float, float]:
    top = float(min(bar["body_top_y_px"], bar["body_bottom_y_px"]))
    bottom = float(max(bar["body_top_y_px"], bar["body_bottom_y_px"]))
    return top, bottom


def _patterns(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return low-confidence visual pattern candidates; never directional votes.

    The rules use only visible candle geometry. They are intentionally
    conservative and remain diagnostics until compared with labelled,
    out-of-sample chart images.
    """
    patterns: list[dict[str, Any]] = []

    def add(index: int, start_index: int, name: str, colour: str | None = None) -> None:
        item: dict[str, Any] = {
            "index": index,
            "start_index": start_index,
            "pattern": name,
            "confidence": "LOW",
        }
        if colour is not None:
            item["colour"] = colour
        patterns.append(item)

    for i, bar in enumerate(bars):
        if bar.get("shape", "normal") != "normal":
            add(i, i, str(bar["shape"]), str(bar.get("colour", "UNKNOWN")))
        if i >= 1:
            previous = bars[i - 1]
            prev_top, prev_bottom = _body_bounds(previous)
            curr_top, curr_bottom = _body_bounds(bar)
            prev_size = max(1.0, prev_bottom - prev_top)
            curr_size = max(1.0, curr_bottom - curr_top)
            opposite_colours = previous.get("colour") != bar.get("colour")

            if (
                previous.get("colour") == "RED"
                and bar.get("colour") == "GREEN"
                and curr_top <= prev_top
                and curr_bottom >= prev_bottom
            ):
                add(i, i - 1, "bullish_engulfing_candidate")
            elif (
                previous.get("colour") == "GREEN"
                and bar.get("colour") == "RED"
                and curr_top <= prev_top
                and curr_bottom >= prev_bottom
            ):
                add(i, i - 1, "bearish_engulfing_candidate")

            # Harami: a materially smaller opposite-colour body contained
            # inside the preceding real body.
            if (
                opposite_colours
                and curr_size <= prev_size * 0.75
                and curr_top >= prev_top
                and curr_bottom <= prev_bottom
            ):
                add(i, i - 1, "harami_candidate")

        if i >= 2:
            first, middle, last = bars[i - 2], bars[i - 1], bar
            first_top, first_bottom = _body_bounds(first)
            middle_top, middle_bottom = _body_bounds(middle)
            last_top, last_bottom = _body_bounds(last)
            first_size = max(1.0, first_bottom - first_top)
            middle_size = max(1.0, middle_bottom - middle_top)
            last_size = max(1.0, last_bottom - last_top)
            first_mid = (first_top + first_bottom) / 2.0
            middle_mid = (middle_top + middle_bottom) / 2.0
            last_mid = (last_top + last_bottom) / 2.0
            large_first_and_last = (
                first_size >= middle_size * 1.4
                and last_size >= middle_size * 1.4
            )

            # Pixel y increases downwards. A morning star falls, pauses low,
            # then a bullish third body recovers above the first body's midpoint.
            if (
                first.get("colour") == "RED"
                and last.get("colour") == "GREEN"
                and large_first_and_last
                and middle_mid >= first_mid
                and last_mid < first_mid
            ):
                add(i, i - 2, "morning_star_candidate")
            elif (
                first.get("colour") == "GREEN"
                and last.get("colour") == "RED"
                and large_first_and_last
                and middle_mid <= first_mid
                and last_mid > first_mid
            ):
                add(i, i - 2, "evening_star_candidate")

    return patterns[-60:]

def analyze_chart_image(image_path:str|Path,metadata:dict[str,Any]|None=None,expected_symbol:str|None=None)->dict[str,Any]:
    path=Path(image_path)
    meta=metadata or {}
    result={
        "engine":"engine_2_chart_visual_analysis",
        "method":"OpenCV classical computer vision and explicit candle rules",
        "ai_used":False,"image":path.name,"analyzed_at_ms":int(time.time()*1000),
        "symbol":meta.get("symbol"),"timeframe":meta.get("timeframe"),
    }
    image=cv2.imread(str(path),cv2.IMREAD_COLOR)
    if image is None:
        return {**result,"status":"ERROR","error":"The image could not be read."}
    height,width=image.shape[:2]
    try:
        crop_left=int(meta.get("plot_left_px",0) or 0)
        crop_right_value=int(meta.get("plot_right_px",0) or 0)
        crop_right=width if crop_right_value<=0 else crop_right_value
        crop_top=int(meta.get("plot_top_px",0) or 0)
        crop_bottom_value=int(meta.get("plot_bottom_px",0) or 0)
        crop_bottom=height if crop_bottom_value<=0 else crop_bottom_value
        if not (0<=crop_left<crop_right<=width and 0<=crop_top<crop_bottom<=height):
            raise ValueError("plot bounds must be inside the image and have positive width/height")
        extraction_diagnostics: dict[str, Any] = {}
        bars=_extract_bars(image,meta,diagnostics=extraction_diagnostics)
    except (TypeError,ValueError,OverflowError) as exc:
        return {**result,"status":"ERROR","error":f"Invalid chart crop metadata: {exc}"}
    patterns=_patterns(bars)
    counts={"GREEN":sum(b["colour"]=="GREEN" for b in bars),
            "RED":sum(b["colour"]=="RED" for b in bars)}
    # Direction must come from calibrated price movement, not candle colours alone.
    # A sequence of green candles can still form lower closes (and vice versa).
    bias="NEUTRAL"
    visual_trend={
        "sample_bars":0,"net_change":None,"net_change_pct":None,
        "visible_range_fraction":None,"rising_close_steps":0,
        "falling_close_steps":0,"required_directional_steps":0,
        "minimum_move":None,
    }

    top_price=0.0
    bottom_price=0.0
    plot_left=0
    plot_right=width
    plot_top=0
    plot_bottom=height
    scale_valid=False
    try:
        top_price=float(meta.get("price_top"))
        bottom_price=float(meta.get("price_bottom"))
        plot_left=int(meta.get("plot_left_px",0) or 0)
        plot_right_value=int(meta.get("plot_right_px",0) or 0)
        plot_right=width if plot_right_value<=0 else plot_right_value
        plot_top=int(meta.get("plot_top_px",0) or 0)
        plot_bottom_value=int(meta.get("plot_bottom_px",0) or 0)
        plot_bottom=height if plot_bottom_value<=0 else plot_bottom_value
        scale_valid=(
            math.isfinite(top_price) and math.isfinite(bottom_price)
            and top_price>bottom_price>0
            and 0<=plot_left<plot_right<=width
            and 0<=plot_top<plot_bottom<=height
        )
    except (TypeError,ValueError,OverflowError):
        scale_valid=False
    calibrated=[]
    if scale_valid:
        span=top_price-bottom_price
        pixel_span=plot_bottom-plot_top
        for bar in bars:
            def price_at(y:int)->float:
                return top_price-((y-plot_top)/pixel_span)*span
            if bar["colour"]=="GREEN":
                open_price=price_at(bar["body_bottom_y_px"])
                close_price=price_at(bar["body_top_y_px"])
            else:
                open_price=price_at(bar["body_top_y_px"])
                close_price=price_at(bar["body_bottom_y_px"])
            calibrated.append({
                **bar,"open":open_price,"close":close_price,
                "high":price_at(bar["high_y_px"]),"low":price_at(bar["low_y_px"]),
            })

    # Core visual analysis: trend, swing structure, short momentum and candlestick patterns.
    # All price-based measurements are made only after the image axis is calibrated.
    visual_trend={
        "sample_bars":0,"net_change":None,"net_change_pct":None,
        "visible_range_fraction":None,"rising_close_steps":0,
        "falling_close_steps":0,"required_directional_steps":0,
        "minimum_move":None,"score":0.0,
    }
    market_structure={
        "status":"INSUFFICIENT","direction":"UNKNOWN","score":None,
        "swing_highs":[],"swing_lows":[],"higher_highs":False,
        "higher_lows":False,"lower_highs":False,"lower_lows":False,
        "support":None,"resistance":None,
        "distance_to_support_pct":None,"distance_to_resistance_pct":None,
    }
    momentum={"status":"INSUFFICIENT","score":None,"change":None,"change_pct":None}
    pattern_score=0.0
    analysis_score=0.0
    analysis_confidence=0.0
    if scale_valid and len(calibrated)>=6:
        recent=calibrated[-30:]
        closes=np.asarray([float(bar["close"]) for bar in recent],dtype=float)
        highs=np.asarray([float(bar["high"]) for bar in recent],dtype=float)
        lows=np.asarray([float(bar["low"]) for bar in recent],dtype=float)
        steps=np.diff(closes)
        rising=int(np.count_nonzero(steps>0))
        falling=int(np.count_nonzero(steps<0))
        net_change=float(closes[-1]-closes[0])
        visible_range=float(top_price-bottom_price)
        required=int(np.ceil(len(steps)*0.60))
        direction_ratio=max(rising,falling)/max(1,len(steps))
        minimum_move=max(abs(float(closes[0]))*0.0002,visible_range*0.012)
        trend_magnitude=min(1.0,abs(net_change)/max(visible_range*0.08,1e-12))
        trend_score=(1.0 if net_change>0 else -1.0 if net_change<0 else 0.0)*trend_magnitude*direction_ratio
        visual_trend={
            "sample_bars":len(recent),
            "net_change":round(net_change,8),
            "net_change_pct":round((net_change/abs(float(closes[0])))*100,6) if closes[0] else None,
            "visible_range_fraction":round(net_change/visible_range,6) if visible_range>0 else None,
            "rising_close_steps":rising,
            "falling_close_steps":falling,
            "required_directional_steps":required,
            "minimum_move":round(minimum_move,8),
            "score":round(float(np.clip(trend_score,-1,1)),4),
            "direction_consistency":round(direction_ratio,4),
        }

        # Swing highs/lows are local extrema with a two-candle shoulder on each side.
        swing_highs=[]
        swing_lows=[]
        for index in range(2,len(recent)-2):
            high_window=highs[index-2:index+3]
            low_window=lows[index-2:index+3]
            if highs[index]>=np.max(high_window) and highs[index]>max(highs[index-2:index]) and highs[index]>=max(highs[index+1:index+3]):
                swing_highs.append({"index":index,"price":float(highs[index])})
            if lows[index]<=np.min(low_window) and lows[index]<min(lows[index-2:index]) and lows[index]<=min(lows[index+1:index+3]):
                swing_lows.append({"index":index,"price":float(lows[index])})
        higher_highs=bool(len(swing_highs)>=2 and swing_highs[-1]["price"]>swing_highs[-2]["price"])
        lower_highs=bool(len(swing_highs)>=2 and swing_highs[-1]["price"]<swing_highs[-2]["price"])
        higher_lows=bool(len(swing_lows)>=2 and swing_lows[-1]["price"]>swing_lows[-2]["price"])
        lower_lows=bool(len(swing_lows)>=2 and swing_lows[-1]["price"]<swing_lows[-2]["price"])
        structure_score=None
        if len(swing_highs)>=2 and len(swing_lows)>=2:
            high_direction=1.0 if higher_highs else -1.0 if lower_highs else 0.0
            low_direction=1.0 if higher_lows else -1.0 if lower_lows else 0.0
            structure_score=(high_direction+low_direction)/2.0
        current_price=float(closes[-1])
        supports=[x["price"] for x in swing_lows if x["price"]<=current_price]
        resistances=[x["price"] for x in swing_highs if x["price"]>=current_price]
        support=max(supports) if supports else (float(np.min(lows)) if len(lows) else None)
        resistance=min(resistances) if resistances else (float(np.max(highs)) if len(highs) else None)
        market_structure={
            "status":"READY" if structure_score is not None else "PARTIAL",
            "direction":"BULLISH" if structure_score==1 else "BEARISH" if structure_score==-1 else "MIXED_OR_UNKNOWN",
            "score":round(structure_score,4) if structure_score is not None else None,
            "swing_highs":swing_highs[-6:],"swing_lows":swing_lows[-6:],
            "higher_highs":higher_highs,"higher_lows":higher_lows,
            "lower_highs":lower_highs,"lower_lows":lower_lows,
            "support":round(support,8) if support is not None else None,
            "resistance":round(resistance,8) if resistance is not None else None,
            "distance_to_support_pct":round((current_price-support)/current_price*100,5) if support is not None and current_price>0 else None,
            "distance_to_resistance_pct":round((resistance-current_price)/current_price*100,5) if resistance is not None and current_price>0 else None,
        }

        if len(closes)>=6:
            momentum_change=float(closes[-1]-closes[-6])
            momentum_direction=1.0 if momentum_change>0 else -1.0 if momentum_change<0 else 0.0
            momentum_consistency=max(
                np.count_nonzero(np.diff(closes[-6:])>0),
                np.count_nonzero(np.diff(closes[-6:])<0),
            )/5.0
            momentum_score=momentum_direction*min(1.0,abs(momentum_change)/max(visible_range*0.025,1e-12))*momentum_consistency
            momentum={"status":"READY","score":round(float(np.clip(momentum_score,-1,1)),4),
                      "change":round(momentum_change,8),
                      "change_pct":round(momentum_change/abs(float(closes[-6]))*100,6) if closes[-6] else None}

        # Pattern candidates are diagnostic only until contextually validated.
        # Low-confidence shape candidates never steer the analyst's direction.
        pattern_score=0.0
        components=[(trend_score,0.65)]
        if structure_score is not None:
            components.append((structure_score,0.25))
        if momentum.get("score") is not None:
            components.append((float(momentum["score"]),0.10))
        weight_sum=sum(weight for _,weight in components)
        analysis_score=float(np.clip(sum(score*weight for score,weight in components)/weight_sum,-1,1))
        sample_quality=min(1.0,len(recent)/24.0)
        pivot_quality=min(1.0,min(len(swing_highs),len(swing_lows))/2.0)
        colour_quality=float(np.mean([float(bar.get("colour_purity",0.0)) for bar in calibrated[-24:]]))
        analysis_confidence=float(np.clip(
            0.40*sample_quality+0.25*direction_ratio+0.20*pivot_quality+0.15*colour_quality,0,1
        ))
        if structure_score is None:
            analysis_confidence=min(analysis_confidence,0.69)
        if analysis_score>=0.20:
            bias="BULLISH"
        elif analysis_score<=-0.20:
            bias="BEARISH"

    symbol_matches=bool(expected_symbol and meta.get("symbol")==expected_symbol)
    timeframe=meta.get("timeframe")
    timeframe_valid=timeframe in {"1m","5m","15m","1h","4h","1d"}
    plot_width=max(1,plot_right-plot_left)
    last_bar_x_ratio=((float(bars[-1]["x_px"])-plot_left)/plot_width) if bars else None
    mean_colour_purity=(float(np.mean([bar.get("colour_purity",0.0) for bar in bars[-24:]])) if bars else 0.0)
    eligible=bool(
        scale_valid and symbol_matches and timeframe_valid and len(calibrated)>=20
        and last_bar_x_ratio is not None and last_bar_x_ratio>=0.68
        and mean_colour_purity>=0.72
    )
    state="READY" if eligible else ("DETECTED_UNCALIBRATED" if len(bars)>=5 else "LOW_DETECTION")
    return {
        **result,"status":state,"image_width":width,"image_height":height,
        "detected_bar_count":len(bars),"calibrated_bar_count":len(calibrated),
        "last_bar_x_ratio":round(last_bar_x_ratio,4) if last_bar_x_ratio is not None else None,
        "mean_colour_purity":round(mean_colour_purity,4),
        "palette_mode":str(meta.get("palette_mode","auto")),
        "extraction_diagnostics":extraction_diagnostics,
        "colour_counts":counts,"visual_bias":bias,"visual_trend":visual_trend,
        "market_structure":market_structure,"momentum":momentum,
        "analysis_score":round(analysis_score,4),
        "analysis_confidence":round(analysis_confidence,4),
        "analysis_components":{
            "trend":round(float(visual_trend["score"]),4),
            "structure":market_structure["score"],
            "momentum":momentum["score"],
            "patterns":round(pattern_score,4),
        },
        "pattern_candidates":patterns,
        "bars":calibrated[-80:] if scale_valid else bars[-80:],
        "decision_eligible":eligible,
        "calibration":{
            "price_scale_valid":scale_valid,"symbol_matches":symbol_matches,
            "timeframe_valid":timeframe_valid,"plot_top_px":plot_top,"plot_bottom_px":plot_bottom,
            "price_top":top_price,"price_bottom":bottom_price,
        },
        "limitations":[
            "The price scale depends on the user-supplied chart top/bottom values and plot pixel bounds.",
            "Colour recognition depends on chart theme; inspect chart metadata before trusting visual evidence.",
            "Pattern candidates are classical rules-based observations, not certainty or standalone signals.",
        ],
    }
