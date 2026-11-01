from __future__ import annotations

import math
from typing import Any

from ..config import RISK_PER_TRADE

TIMEFRAME_WEIGHTS={"1m":1.0,"5m":2.0,"15m":3.0,"1h":4.0,"4h":5.0,"1d":5.0}

def _ema(values:list[float],period:int)->float|None:
    if period<2 or len(values)<period:
        return None
    alpha=2.0/(period+1)
    value=sum(values[:period])/period
    for item in values[period:]:
        value=alpha*item+(1-alpha)*value
    return value

def _rsi(values:list[float],period:int=14)->float|None:
    if period<2 or len(values)<=period:
        return None
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    gains=[max(x,0.0) for x in changes]
    losses=[max(-x,0.0) for x in changes]
    avg_gain=sum(gains[:period])/period
    avg_loss=sum(losses[:period])/period
    for gain,loss in zip(gains[period:],losses[period:]):
        avg_gain=(avg_gain*(period-1)+gain)/period
        avg_loss=(avg_loss*(period-1)+loss)/period
    if avg_loss==0:
        return 50.0 if avg_gain==0 else 100.0
    return 100.0-(100.0/(1.0+avg_gain/avg_loss))

def _atr(candles:list[dict[str,Any]],period:int=14)->float|None:
    if period<2 or len(candles)<=period:
        return None
    ranges=[]
    for previous,current in zip(candles[:-1],candles[1:]):
        ranges.append(max(
            float(current["high"])-float(current["low"]),
            abs(float(current["high"])-float(previous["close"])),
            abs(float(current["low"])-float(previous["close"])),
        ))
    return sum(ranges[-period:])/period

def _timeframe_trend(candles:list[dict[str,Any]])->dict[str,Any]:
    closed=[c for c in candles if c.get("closed")]
    closes=[float(c["close"]) for c in closed]
    fast,slow=_ema(closes,20),_ema(closes,50)
    if fast is None or slow is None or not closes:
        return {"status":"INSUFFICIENT","trend":"UNKNOWN","closed_candles":len(closes)}
    last=closes[-1]
    trend="BULLISH" if fast>slow and last>fast else ("BEARISH" if fast<slow and last<fast else "NEUTRAL")
    return {"status":"READY","trend":trend,"ema20":fast,"ema50":slow,
            "last_close":last,"closed_candles":len(closes)}

def calculate_volume(
    *,equity:float,entry:float,stop_loss:float,tick_size:float,tick_value_loss:float,
    volume_min:float,volume_step:float,volume_max:float,risk_fraction:float=RISK_PER_TRADE,
)->dict[str,Any]:
    values=(equity,entry,stop_loss,tick_size,tick_value_loss,volume_min,volume_step,volume_max,risk_fraction)
    try:
        parsed=[float(v) for v in values]
    except (TypeError,ValueError,OverflowError):
        return {"status":"UNAVAILABLE","reason":"Live account or symbol specifications are not numeric."}
    if any(not math.isfinite(v) for v in parsed):
        return {"status":"UNAVAILABLE","reason":"Live account or symbol specifications contain non-finite values."}
    if equity<=0 or entry<=0 or stop_loss<=0 or tick_size<=0 or tick_value_loss<=0:
        return {"status":"UNAVAILABLE","reason":"Live account or loss-side tick specifications are missing."}
    if not (0<risk_fraction<1):
        return {"status":"UNAVAILABLE","reason":"Configured risk fraction must be between 0 and 1."}
    if volume_min<=0 or volume_step<=0 or volume_max<volume_min:
        return {"status":"UNAVAILABLE","reason":"Broker volume minimum, step or maximum is invalid."}
    risk_cash=equity*risk_fraction
    loss_per_lot=abs(entry-stop_loss)/tick_size*tick_value_loss
    if not math.isfinite(loss_per_lot) or loss_per_lot<=0:
        return {"status":"UNAVAILABLE","reason":"Cannot calculate cash loss per lot."}
    raw_volume=risk_cash/loss_per_lot
    rounded=math.floor((raw_volume+1e-12)/volume_step)*volume_step
    rounded=min(rounded,volume_max)
    rounded=round(rounded,8)
    if rounded<volume_min:
        return {"status":"BLOCKED","reason":"Risk-based size is below broker minimum volume.",
                "risk_cash":round(risk_cash,8),"unrounded_volume":raw_volume}
    estimated_loss=loss_per_lot*rounded
    return {
        "status":"READY","volume":rounded,"risk_cash":round(risk_cash,8),
        "risk_fraction":risk_fraction,"loss_per_lot":round(loss_per_lot,8),
        "estimated_loss":round(estimated_loss,8),"unrounded_volume":raw_volume,
        "tick_value_basis":"broker-reported loss-side tick value in account currency",
    }

class DecisionEngine:
    """Conservative rules-only multi-timeframe decision engine; risk stays in the program."""
    def analyze(self,market:dict[str,Any],chart:dict[str,Any]|None,
                mt5_state:dict[str,Any]|None)->dict[str,Any]:
        base={"engine":"decision_and_risk","risk_owner":"Mirsad_BTC_program","method":"rules_only"}
        if market.get("status") not in {"LIVE","PARTIAL"} or not market.get("primary_venue"):
            return {**base,"status":"NOT_READY","action":"WAIT","reason":"No current market feed is available."}
        primary=market["venues"][market["primary_venue"]]
        candle_sets=primary.get("candles_by_tf") or {"1m":primary.get("candles",[])}
        timeframe_analysis={tf:_timeframe_trend(candle_sets.get(tf,[])) for tf in TIMEFRAME_WEIGHTS}
        required=("1m","5m","15m")
        missing=[tf for tf in required if timeframe_analysis[tf]["status"]!="READY"]
        if missing:
            return {**base,"status":"NOT_READY","action":"WAIT",
                    "timeframes":timeframe_analysis,
                    "reason":"Missing closed candles for required timeframes: "+", ".join(missing)}
        one_minute=[c for c in candle_sets.get("1m",[]) if c.get("closed")]
        five_minute=[c for c in candle_sets.get("5m",[]) if c.get("closed")]
        closes=[float(c["close"]) for c in one_minute]
        if len(closes)<55:
            return {**base,"status":"NOT_READY","action":"WAIT","timeframes":timeframe_analysis,
                    "reason":"At least 55 completed one-minute candles are required."}
        fast,slow=_ema(closes,20),_ema(closes,50)
        rsi,atr1m=_rsi(closes),_atr(one_minute)
        atr5m=_atr(five_minute)
        if None in (fast,slow,rsi,atr1m,atr5m) or atr5m<=0:
            return {**base,"status":"NOT_READY","action":"WAIT","timeframes":timeframe_analysis,
                    "reason":"Indicator calculation lacks sufficient completed candle history."}
        score=0.0
        available_weight=0.0
        for tf,weight in TIMEFRAME_WEIGHTS.items():
            item=timeframe_analysis[tf]
            if item["status"]!="READY":
                continue
            available_weight+=weight
            if item["trend"]=="BULLISH":
                score+=weight
            elif item["trend"]=="BEARISH":
                score-=weight
        trend_score=score/available_weight if available_weight else 0.0
        one_trend=timeframe_analysis["1m"]["trend"]
        five_trend=timeframe_analysis["5m"]["trend"]
        fifteen_trend=timeframe_analysis["15m"]["trend"]
        orderflow=primary.get("orderflow") or {}
        buy_ratio=orderflow.get("taker_buy_ratio")
        action="WAIT"
        if (one_trend=="BULLISH" and five_trend=="BULLISH" and fifteen_trend=="BULLISH"
            and trend_score>=0.35 and 50<rsi<72 and buy_ratio is not None and buy_ratio>=0.52):
            action="BUY"
        elif (one_trend=="BEARISH" and five_trend=="BEARISH" and fifteen_trend=="BEARISH"
            and trend_score<=-0.35 and 28<rsi<50 and buy_ratio is not None and buy_ratio<=0.48):
            action="SELL"
        entry=float(market["price"])
        stop_loss=take_profit=None
        if action=="BUY":
            stop_loss=entry-1.5*atr5m
            take_profit=entry+3.0*atr5m
        elif action=="SELL":
            stop_loss=entry+1.5*atr5m
            take_profit=entry-3.0*atr5m

        size_plan:dict[str,Any]={"status":"WAITING_FOR_LIVE_MT5_SPECS",
            "reason":"Waiting for live MT5 equity and symbol specifications."}
        if action in {"BUY","SELL"} and stop_loss is not None and mt5_state:
            account=mt5_state.get("account",{})
            specs=mt5_state.get("symbol_spec",{})
            required_account=("equity",)
            required_specs=("tick_size","tick_value_loss","volume_min","volume_step","volume_max")
            if (mt5_state.get("status")=="CONNECTED"
                and all(k in account for k in required_account)
                and all(k in specs for k in required_specs)):
                size_plan=calculate_volume(
                    equity=account["equity"],entry=entry,stop_loss=stop_loss,
                    tick_size=specs["tick_size"],tick_value_loss=specs["tick_value_loss"],
                    volume_min=specs["volume_min"],volume_step=specs["volume_step"],
                    volume_max=specs["volume_max"])
        chart_note="not_used_for_direction_until_price_axis_and_symbol_are_calibrated"
        if chart and chart.get("status")=="READY":
            chart_note="visual candidates recorded separately; not used to vote until chart symbol and price scale are verified"
        return {
            **base,"status":"READY","action":action,"as_of_ms":market["captured_at_ms"],
            "symbol":market["symbol"],"entry_reference":entry,"stop_loss":stop_loss,
            "take_profit":take_profit,"trend_score":round(trend_score,4),
            "timeframes":timeframe_analysis,
            "indicators":{"ema20_1m":fast,"ema50_1m":slow,"rsi14_1m":rsi,
                          "atr14_1m":atr1m,"atr14_5m":atr5m},
            "orderflow":orderflow,"risk_plan":size_plan,"chart_context":chart_note,
            "reason":"Requires aligned 1m/5m/15m completed-candle trends and taker-flow confirmation. It is not a certainty or a broker order.",
        }
