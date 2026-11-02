from __future__ import annotations

from typing import Any

import numpy as np


def analyze_calibrated_bars(
    calibrated: list[dict[str, Any]], *, top_price: float, bottom_price: float
) -> dict[str, Any]:
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
    if len(calibrated)>=6:
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
        trend_strength=min(1.0,abs(net_change)/max(visible_range*0.08,1e-12))
        if structure_score is None:
            structure_alignment=0.50
        elif trend_score == 0 or structure_score == 0:
            structure_alignment=0.50
        elif (trend_score > 0) == (structure_score > 0):
            structure_alignment=1.0
        else:
            structure_alignment=0.0
        # This is a deterministic evidence-quality index, not a calibrated
        # probability that the next market move will be correct.
        confidence_components={
            "sample_completeness":round(sample_quality,4),
            "direction_consistency":round(direction_ratio,4),
            "swing_structure_completeness":round(pivot_quality,4),
            "colour_purity":round(colour_quality,4),
            "net_move_strength":round(trend_strength,4),
            "trend_structure_alignment":round(structure_alignment,4),
        }
        analysis_confidence=float(np.clip(
            0.25*sample_quality
            +0.20*direction_ratio
            +0.15*pivot_quality
            +0.15*colour_quality
            +0.15*trend_strength
            +0.10*structure_alignment,
            0,1
        ))
        if structure_score is None:
            analysis_confidence=min(analysis_confidence,0.69)
        if analysis_score>=0.20:
            bias="BULLISH"
        elif analysis_score<=-0.20:
            bias="BEARISH"
    return {
        "visual_bias": bias,
        "visual_trend": visual_trend,
        "market_structure": market_structure,
        "momentum": momentum,
        "pattern_score": pattern_score,
        "analysis_score": analysis_score,
        "analysis_confidence": analysis_confidence,
        "confidence_components": confidence_components if len(calibrated) >= 6 else {},
        "confidence_kind": "heuristic_evidence_quality_not_probability",
    }
