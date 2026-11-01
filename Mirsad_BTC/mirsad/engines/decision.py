from __future__ import annotations
import hashlib
import math
from typing import Any
from ..config import RISK_PER_TRADE, MT5_QUOTE_MAX_AGE_SECONDS

TIMEFRAME_WEIGHTS={"1m":1.0,"5m":2.0,"15m":3.0,"1h":4.0,"4h":5.0,"1d":5.0}

def _ema(values:list[float],period:int)->float|None:
    if period<2 or len(values)<period: return None
    alpha=2.0/(period+1); value=sum(values[:period])/period
    for item in values[period:]: value=alpha*item+(1-alpha)*value
    return value

def _rsi(values:list[float],period:int=14)->float|None:
    if period<2 or len(values)<=period: return None
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    gains=[max(x,0.0) for x in changes]; losses=[max(-x,0.0) for x in changes]
    avg_gain=sum(gains[:period])/period; avg_loss=sum(losses[:period])/period
    for gain,loss in zip(gains[period:],losses[period:]):
        avg_gain=(avg_gain*(period-1)+gain)/period
        avg_loss=(avg_loss*(period-1)+loss)/period
    if avg_loss==0: return 50.0 if avg_gain==0 else 100.0
    return 100.0-(100.0/(1.0+avg_gain/avg_loss))

def _atr(candles:list[dict[str,Any]],period:int=14)->float|None:
    if period<2 or len(candles)<=period: return None
    ranges=[]
    for previous,current in zip(candles[:-1],candles[1:]):
        ranges.append(max(float(current["high"])-float(current["low"]),
            abs(float(current["high"])-float(previous["close"])),
            abs(float(current["low"])-float(previous["close"]))))
    return sum(ranges[-period:])/period

def _timeframe_trend(candles:list[dict[str,Any]])->dict[str,Any]:
    closed=[c for c in candles if c.get("closed")]
    closes=[float(c["close"]) for c in closed]
    fast,slow=_ema(closes,20),_ema(closes,50)
    if fast is None or slow is None:
        return {"status":"INSUFFICIENT","trend":"UNKNOWN","closed_candles":len(closes)}
    last=closes[-1]
    trend="BULLISH" if fast>slow and last>fast else ("BEARISH" if fast<slow and last<fast else "NEUTRAL")
    return {"status":"READY","trend":trend,"ema20":fast,"ema50":slow,
            "last_close":last,"closed_candles":len(closes)}

def _aggregate_orderflow(venues:dict[str,Any])->dict[str,Any]:
    buy=0.0; sell=0.0; count=0; contributors=[]
    for name,row in venues.items():
        flow=row.get("orderflow") or {}
        if row.get("status")!="LIVE" or flow.get("unit")!="BTC":
            continue
        b=float(flow.get("taker_buy_quantity",0)); s=float(flow.get("taker_sell_quantity",0))
        if b<0 or s<0 or not math.isfinite(b+s): continue
        buy+=b; sell+=s; count+=int(flow.get("trade_count",0)); contributors.append(name)
    total=buy+sell
    return {"trade_count":count,"taker_buy_quantity":buy,"taker_sell_quantity":sell,
        "signed_quantity_delta":buy-sell,"taker_buy_ratio":buy/total if total else None,
        "unit":"BTC","venues":contributors,"scope":"sum of separate venue spot samples; venues remain identified"}

def calculate_volume(*,equity:float,entry:float,stop_loss:float,tick_size:float,
    tick_value_loss:float,volume_min:float,volume_step:float,volume_max:float,
    risk_fraction:float=RISK_PER_TRADE)->dict[str,Any]:
    values=(equity,entry,stop_loss,tick_size,tick_value_loss,volume_min,volume_step,volume_max,risk_fraction)
    try: nums=[float(v) for v in values]
    except (TypeError,ValueError,OverflowError):
        return {"status":"UNAVAILABLE","reason":"Live account/specification fields are not numeric."}
    if any(not math.isfinite(v) for v in nums):
        return {"status":"UNAVAILABLE","reason":"Live account/specification fields contain a non-finite value."}
    if equity<=0 or entry<=0 or stop_loss<=0 or tick_size<=0 or tick_value_loss<=0:
        return {"status":"UNAVAILABLE","reason":"Live equity or loss-side tick data is missing."}
    if not 0<risk_fraction<1:
        return {"status":"UNAVAILABLE","reason":"Risk fraction must be between 0 and 1."}
    if volume_min<=0 or volume_step<=0 or volume_max<volume_min:
        return {"status":"UNAVAILABLE","reason":"Broker volume limits are inconsistent."}
    risk_cash=equity*risk_fraction
    loss_per_lot=abs(entry-stop_loss)/tick_size*tick_value_loss
    if not math.isfinite(loss_per_lot) or loss_per_lot<=0:
        return {"status":"UNAVAILABLE","reason":"Cannot calculate loss per lot."}
    raw=risk_cash/loss_per_lot
    volume=round(min(math.floor((raw+1e-12)/volume_step)*volume_step,volume_max),8)
    if volume<volume_min:
        return {"status":"BLOCKED","reason":"Risk-calculated volume is below broker minimum.",
                "risk_cash":risk_cash,"unrounded_volume":raw}
    return {"status":"READY","volume":volume,"risk_cash":risk_cash,"risk_fraction":risk_fraction,
            "loss_per_lot":loss_per_lot,"estimated_loss":loss_per_lot*volume,
            "tick_value_basis":"loss-side tick value reported by MT5 in account currency"}

class DecisionEngine:
    """Engine 4: signal evidence comes only from Engines 1 and 2.
    Engine 3 supplies live account/specification data for program-side sizing
    and carries the final MIR1 command; it never votes on direction.
    """
    def analyze(self,market:dict[str,Any],chart:dict[str,Any]|None,
                bridge:dict[str,Any]|None)->dict[str,Any]:
        base={"engine":"engine_4_decision_and_risk","method":"rules_only",
              "direction_inputs":["engine_1_market","engine_2_chart"],
              "bridge_role":"engine_3 transports commands and supplies live account/specification fields for risk sizing only",
              "risk_owner":"Mirsad_BTC_program"}
        if market.get("status") not in {"LIVE","PARTIAL"} or not market.get("primary_venue"):
            return {**base,"status":"NOT_READY","action":"WAIT","candidate_action":"WAIT",
                    "reason":"Engine 1 has no current public market feed."}
        primary=market["venues"][market["primary_venue"]]
        candle_sets=primary.get("candles_by_tf") or {"1m":primary.get("candles",[])}
        tf_data={tf:_timeframe_trend(candle_sets.get(tf,[])) for tf in TIMEFRAME_WEIGHTS}
        required=("1m","5m","15m")
        missing=[tf for tf in required if tf_data[tf]["status"]!="READY"]
        if missing:
            return {**base,"status":"NOT_READY","action":"WAIT","candidate_action":"WAIT",
                "timeframes":tf_data,"reason":"Engine 1 lacks completed candles for "+", ".join(missing)}
        one=[c for c in candle_sets.get("1m",[]) if c.get("closed")]
        five=[c for c in candle_sets.get("5m",[]) if c.get("closed")]
        closes=[float(c["close"]) for c in one]
        fast,slow=_ema(closes,20),_ema(closes,50)
        rsi,atr1,atr5=_rsi(closes),_atr(one),_atr(five)
        if None in (fast,slow,rsi,atr1,atr5) or atr5<=0:
            return {**base,"status":"NOT_READY","action":"WAIT","candidate_action":"WAIT",
                "timeframes":tf_data,"reason":"Completed candle data is insufficient for technical calculations."}
        weighted=0.0; weight_total=0.0
        for tf,weight in TIMEFRAME_WEIGHTS.items():
            item=tf_data[tf]
            if item["status"]!="READY": continue
            weight_total+=weight
            weighted+=weight*(1 if item["trend"]=="BULLISH" else -1 if item["trend"]=="BEARISH" else 0)
        trend_score=weighted/weight_total if weight_total else 0.0
        flow=_aggregate_orderflow(market.get("venues",{}))
        ratio=flow.get("taker_buy_ratio")
        candidate="WAIT"
        if (tf_data["1m"]["trend"]=="BULLISH" and tf_data["5m"]["trend"]=="BULLISH"
            and tf_data["15m"]["trend"]=="BULLISH" and trend_score>=0.35
            and 50<rsi<72 and ratio is not None and ratio>=0.52):
            candidate="BUY"
        elif (tf_data["1m"]["trend"]=="BEARISH" and tf_data["5m"]["trend"]=="BEARISH"
            and tf_data["15m"]["trend"]=="BEARISH" and trend_score<=-0.35
            and 28<rsi<50 and ratio is not None and ratio<=0.48):
            candidate="SELL"

        chart=chart or {}
        chart_eligible=bool(chart.get("decision_eligible")) and chart.get("status")=="READY"
        visual_bias=chart.get("visual_bias","NEUTRAL")
        action=candidate
        chart_gate="NOT_CALIBRATED"
        if not chart_eligible:
            action="WAIT"
            chart_gate="WAITING_FOR_ENGINE_2_CALIBRATION"
        elif candidate in {"BUY","SELL"}:
            expected="BULLISH" if candidate=="BUY" else "BEARISH"
            if visual_bias!=expected:
                action="WAIT"
                chart_gate="VISUAL_CONFLICT_OR_NEUTRAL"
            else:
                chart_gate="CONFIRMED"
        else:
            chart_gate="NO_MARKET_SETUP"

        market_entry=float(market["price"])
        sl=tp=None
        bridge=bridge or {}
        account=bridge.get("account",{})
        specs=bridge.get("symbol_spec",{})
        quote=bridge.get("quote",{})
        broker_symbol=str(bridge.get("symbol",""))
        mapped_market_symbol=str(bridge.get("market_symbol",""))
        try:
            bid=float(quote.get("bid",0))
            ask=float(quote.get("ask",0))
            quote_age=float(bridge.get("quote_age_seconds",float("inf")))
            tick_age=float(quote.get("tick_age_seconds",float("inf")))
            quote_ok=(bridge.get("status")=="CONNECTED"
                and mapped_market_symbol.upper()==str(market.get("symbol","")).upper()
                and bool(broker_symbol) and 0<bid<=ask
                and math.isfinite(bid) and math.isfinite(ask)
                and math.isfinite(quote_age) and math.isfinite(tick_age)
                and 0<=quote_age<=MT5_QUOTE_MAX_AGE_SECONDS
                and 0<=tick_age<=MT5_QUOTE_MAX_AGE_SECONDS)
        except (TypeError,ValueError,OverflowError):
            quote_ok=False
            bid=ask=0.0
            quote_age=None

        if action=="BUY" and quote_ok:
            entry=ask
        elif action=="SELL" and quote_ok:
            entry=bid
        else:
            entry=market_entry
        if action=="BUY":
            sl=entry-1.5*atr5
            tp=entry+3.0*atr5
        elif action=="SELL":
            sl=entry+1.5*atr5
            tp=entry-3.0*atr5

        size={"status":"WAITING_FOR_ENGINE_3_QUOTE",
              "reason":"Engine 3 must provide a fresh broker quote mapped to the market symbol."}
        if action in {"BUY","SELL"} and sl is not None:
            account_fields=("equity",)
            spec_fields=("tick_size","tick_value_loss","volume_min","volume_step","volume_max")
            if not quote_ok:
                size={"status":"BLOCKED","reason":"No fresh MT5 quote or broker symbol mapping does not match the market instrument."}
            elif not all(k in account for k in account_fields) or not all(k in specs for k in spec_fields):
                size={"status":"UNAVAILABLE","reason":"Engine 3 account equity or loss/volume symbol specifications are incomplete."}
            else:
                size=calculate_volume(equity=account["equity"],entry=entry,stop_loss=sl,
                    tick_size=specs["tick_size"],tick_value_loss=specs["tick_value_loss"],
                    volume_min=specs["volume_min"],volume_step=specs["volume_step"],
                    volume_max=specs["volume_max"])
        command_ready=bool(action in {"BUY","SELL"} and size.get("status")=="READY"
            and quote_ok and bridge.get("status")=="CONNECTED")
        last_closed=one[-1].get("open_time_ms") if one else 0
        signal_source=f"{market.get('symbol')}|{action}|{last_closed}|{chart.get('image','')}"
        signal_id=("MIR-"+hashlib.sha256(signal_source.encode("utf-8")).hexdigest()[:24]
                   if action in {"BUY","SELL"} else None)
        return {
            **base,"status":"READY" if chart_eligible else "WAITING_FOR_ENGINE_2",
            "action":action,"candidate_action":candidate,"signal_id":signal_id,"command_ready":command_ready,
            "chart_gate":chart_gate,"chart_visual_bias":visual_bias,
            "as_of_ms":market.get("captured_at_ms"),"market_symbol":market.get("symbol"),
            "symbol":broker_symbol if quote_ok else market.get("symbol"),
            "market_price_reference":market_entry,"broker_quote":quote if quote_ok else None,
            "entry_reference":entry,"stop_loss":sl,"take_profit":tp,
            "trend_score":round(trend_score,4),"timeframes":tf_data,
            "indicators":{"ema20_1m":fast,"ema50_1m":slow,"rsi14_1m":rsi,"atr14_1m":atr1,"atr14_5m":atr5},
            "orderflow":flow,"risk_plan":size,
            "engine_inputs":{"direction_from_engine_1_market":market.get("status"),
                "direction_from_engine_2_chart":"READY" if chart_eligible else chart.get("status","NOT_READY"),
                "engine_3_bridge_for_quote_risk_specs_and_transport":(bridge or {}).get("status","NOT_CONFIGURED"),
                "engine_3_market_symbol_mapping":mapped_market_symbol,
                "engine_3_quote_fresh":quote_ok},
            "reason":"Engine 4 requires agreement between closed-candle market rules, public taker flow and a calibrated chart screenshot. No AI or certainty is claimed.",
        }
