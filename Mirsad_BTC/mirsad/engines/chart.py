from __future__ import annotations
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

def _extract_bars(image:np.ndarray,meta:dict[str,Any])->list[dict[str,Any]]:
    height,width=image.shape[:2]
    left=max(0,min(width-1,int(meta.get("plot_left_px",0))))
    right_value=int(meta.get("plot_right_px",0) or 0)
    right=width if right_value<=0 else max(left+1,min(width,right_value))
    top=max(0,min(height-1,int(meta.get("plot_top_px",0))))
    bottom_value=int(meta.get("plot_bottom_px",0) or 0)
    bottom=height if bottom_value<=0 else max(top+1,min(height,bottom_value))
    area=image[top:bottom,left:right]
    if area.size==0:
        return []
    hsv=cv2.cvtColor(area,cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,np.array([32,45,40]),np.array([95,255,255]))
    red_a=cv2.inRange(hsv,np.array([0,55,45]),np.array([12,255,255]))
    red_b=cv2.inRange(hsv,np.array([168,55,45]),np.array([180,255,255]))
    red=cv2.bitwise_or(red_a,red_b)
    mask=cv2.bitwise_or(green,red)
    activity=(mask>0).sum(axis=0)
    groups=_groups(activity>max(2,int(area.shape[0]*0.0025)),gap=2)
    bars=[]
    for x0,x1 in groups:
        if x1-x0>18:
            continue
        roi_g=green[:,x0:x1+1]>0
        roi_r=red[:,x0:x1+1]>0
        roi=roi_g|roi_r
        ys,_=np.where(roi)
        if len(ys)<4:
            continue
        y_high=int(ys.min())
        y_low=int(ys.max())
        row_width=roi.sum(axis=1)
        strongest=int(row_width.max())
        if strongest<=0:
            continue
        body_rows=np.flatnonzero(row_width>=max(1,int(strongest*0.55)))
        if len(body_rows)==0:
            continue
        body_top=int(body_rows.min())
        body_bottom=int(body_rows.max())
        total_h=max(1,y_low-y_high+1)
        body_h=max(1,body_bottom-body_top+1)
        green_pixels,red_pixels=int(roi_g.sum()),int(roi_r.sum())
        if green_pixels==red_pixels:
            continue
        colour="GREEN" if green_pixels>red_pixels else "RED"
        upper=max(0,body_top-y_high)
        lower=max(0,y_low-body_bottom)
        ratio=min(1.0,body_h/total_h)
        shape="normal"
        if ratio<=0.12:
            shape="doji_candidate"
        elif lower>=2*body_h and upper<=body_h:
            shape="hammer_candidate"
        elif upper>=2*body_h and lower<=body_h:
            shape="shooting_star_candidate"
        bar={
            "x_px":int((x0+x1)/2)+left,
            "high_y_px":y_high+top,"low_y_px":y_low+top,
            "body_top_y_px":body_top+top,"body_bottom_y_px":body_bottom+top,
            "colour":colour,"shape":shape,"body_ratio":round(ratio,3),
        }
        bars.append(bar)
    return sorted(bars,key=lambda item:item["x_px"])

def _patterns(bars:list[dict[str,Any]])->list[dict[str,Any]]:
    patterns=[]
    for i,bar in enumerate(bars):
        if bar["shape"]!="normal":
            patterns.append({"index":i,"pattern":bar["shape"],"colour":bar["colour"],"confidence":"LOW"})
        if i==0:
            continue
        prev=bars[i-1]
        prev_top=min(prev["body_top_y_px"],prev["body_bottom_y_px"])
        prev_bottom=max(prev["body_top_y_px"],prev["body_bottom_y_px"])
        curr_top=min(bar["body_top_y_px"],bar["body_bottom_y_px"])
        curr_bottom=max(bar["body_top_y_px"],bar["body_bottom_y_px"])
        if prev["colour"]=="RED" and bar["colour"]=="GREEN" and curr_top<=prev_top and curr_bottom>=prev_bottom:
            patterns.append({"index":i,"pattern":"bullish_engulfing_candidate","confidence":"LOW"})
        elif prev["colour"]=="GREEN" and bar["colour"]=="RED" and curr_top<=prev_top and curr_bottom>=prev_bottom:
            patterns.append({"index":i,"pattern":"bearish_engulfing_candidate","confidence":"LOW"})
    return patterns[-30:]

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
    bars=_extract_bars(image,meta)
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

    top_price=meta.get("price_top")
    bottom_price=meta.get("price_bottom")
    plot_top=meta.get("plot_top_px")
    plot_bottom=meta.get("plot_bottom_px")
    scale_valid=False
    try:
        top_price=float(top_price); bottom_price=float(bottom_price)
        plot_top=int(plot_top); plot_bottom_value=int(plot_bottom)
        plot_bottom=height if plot_bottom_value<=0 else plot_bottom_value
        scale_valid=(top_price>bottom_price>0 and 0<=plot_top<plot_bottom<=height)
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

    # Use a short, calibrated close-price sequence as visual trend evidence.
    # Require both a meaningful net move relative to the visible axis range and
    # directional consistency across most adjacent closes to avoid colour-count
    # false positives.
    if scale_valid and len(calibrated)>=6:
        recent=calibrated[-8:]
        closes=np.asarray([float(bar["close"]) for bar in recent],dtype=float)
        steps=np.diff(closes)
        rising=int(np.count_nonzero(steps>0))
        falling=int(np.count_nonzero(steps<0))
        net_change=float(closes[-1]-closes[0])
        visible_range=float(top_price-bottom_price)
        minimum_move=max(abs(float(closes[0]))*0.0002,visible_range*0.015)
        required=int(np.ceil(len(steps)*0.60))
        visual_trend={
            "sample_bars":len(recent),
            "net_change":round(net_change,8),
            "net_change_pct":round((net_change/abs(float(closes[0])))*100,6) if closes[0] else None,
            "visible_range_fraction":round(net_change/visible_range,6) if visible_range>0 else None,
            "rising_close_steps":rising,
            "falling_close_steps":falling,
            "required_directional_steps":required,
            "minimum_move":round(minimum_move,8),
        }
        if net_change>=minimum_move and rising>=required:
            bias="BULLISH"
        elif net_change<=-minimum_move and falling>=required:
            bias="BEARISH"

    symbol_matches=bool(expected_symbol and meta.get("symbol")==expected_symbol)
    timeframe=meta.get("timeframe")
    timeframe_valid=timeframe in {"1m","5m","15m","1h","4h","1d"}
    eligible=bool(scale_valid and symbol_matches and timeframe_valid and len(calibrated)>=20)
    state="READY" if eligible else ("DETECTED_UNCALIBRATED" if len(bars)>=5 else "LOW_DETECTION")
    return {
        **result,"status":state,"image_width":width,"image_height":height,
        "detected_bar_count":len(bars),"calibrated_bar_count":len(calibrated),
        "colour_counts":counts,"visual_bias":bias,"visual_trend":visual_trend,
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
