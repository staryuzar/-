#!/usr/bin/env python3
"""Compare TradingView TV26 Pine chart-data exports against the MT5 component audit.

Export one TradingView_Parity_Components_1TF.pine CSV per timeframe.
The TradingView export must contain TV26.bar_open_time, TV26.open/high/low/close,
TV26.<component> vote columns. MT5 CSV is the EA's detailed audit export.
This is a direct numeric comparison only where candle identity can be established.
"""
from __future__ import annotations
import argparse, csv, json, math
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TV_TO_MT5 = {
    "SMA10":"متوسط بسيط 10", "SMA20":"متوسط بسيط 20", "SMA30":"متوسط بسيط 30",
    "SMA50":"متوسط بسيط 50", "SMA100":"متوسط بسيط 100", "SMA200":"متوسط بسيط 200",
    "EMA10":"متوسط أسي 10", "EMA20":"متوسط أسي 20", "EMA30":"متوسط أسي 30",
    "EMA50":"متوسط أسي 50", "EMA100":"متوسط أسي 100", "EMA200":"متوسط أسي 200",
    "HMA9":"متوسط هال 9", "VWMA20":"متوسط مرجّح بالحجم", "Ichimoku":"إيشيموكو - خط الأساس",
    "RSI14":"القوة النسبية RSI", "Stochastic":"ستوكاستك", "CCI20":"قناة السلع CCI",
    "ADX":"مؤشر الاتجاه ADX", "AO":"المذبذب الرائع AO", "Momentum10":"الزخم Momentum",
    "MACD":"تقارب/تباعد المتوسطات MACD", "StochRSI":"ستوكاستك RSI",
    "WilliamsR":"ويليامز %R", "BullBearPower":"قوة الثيران والدببة",
    "UltimateOscillator":"المذبذب النهائي",
}
TV_FIELDS = {"open":"TV26.open","high":"TV26.high","low":"TV26.low","close":"TV26.close"}
def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
def num(x):
    try:
        v=float(str(x).strip())
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):
        return None
def tv_epoch(row):
    raw=num(row.get("TV26.bar_open_time",""))
    if raw is None: return None
    # Pine time is UNIX milliseconds; tolerate seconds in manually transformed exports.
    seconds=raw/1000 if raw>10_000_000_000 else raw
    return datetime.fromtimestamp(seconds, timezone.utc)
def mt5_stamp(raw, offset):
    # MT5 audit records broker-server wall time. Offset is supplied by the operator
    # for the tested dates; DST changes should be split into separate runs.
    try:
        dt=datetime.strptime(raw,"%Y.%m.%d %H:%M")
        return (dt-timedelta(hours=offset)).replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):
        return None
def price_key(row, prefix, tick):
    vals=[]
    for name in ("open","high","low","close"):
        v=num(row.get(prefix[name],""))
        if v is None: return None
        vals.append(round(v/tick))
    return tuple(vals)
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--tv-csv",required=True)
    ap.add_argument("--mt5-csv",required=True)
    ap.add_argument("--timeframe",required=True,choices=["M1","M5","M15","M30","H1"])
    ap.add_argument("--mt5-utc-offset-hours",type=float,default=0.0,
                    help="Broker server wall-clock offset from UTC during the tested dates")
    ap.add_argument("--tick-size",type=float,default=0.01)
    ap.add_argument("--report",default="tv26-direct-parity-report.md")
    ap.add_argument("--json",default="tv26-direct-parity-report.json")
    args=ap.parse_args()
    tv_rows=read_csv(args.tv_csv); mt_rows=read_csv(args.mt5_csv)
    if not tv_rows: raise SystemExit("TradingView CSV has no data rows.")
    if not mt_rows: raise SystemExit("MT5 audit CSV has no data rows.")
    if "TV26.bar_open_time" not in tv_rows[0]:
        raise SystemExit("Missing TV26.bar_open_time. Export chart data from the diagnostic Pine script, not a screenshot.")
    tf_map={"M1":"د1","M5":"د5","M15":"د15","M30":"د30","H1":"س1"}
    mt=[r for r in mt_rows if r.get("timeframe")==tf_map[args.timeframe]]
    mt_by_stamp=defaultdict(list); mt_by_ohlc=defaultdict(list)
    for r in mt:
        stamp=mt5_stamp(r.get("bar_open_time_server",""),args.mt5_utc_offset_hours)
        if stamp: mt_by_stamp[stamp].append(r)
        k=price_key(r,{"open":"candle_open","high":"candle_high","low":"candle_low","close":"candle_close"},args.tick_size)
        if k: mt_by_ohlc[k].append(r)
    tv_component_cols={}
    for col in tv_rows[0]:
        name=col.removeprefix("TV26.")
        if name in TV_TO_MT5: tv_component_cols[name]=col
    if len(tv_component_cols)<20:
        raise SystemExit(f"Only {len(tv_component_cols)} recognized component columns found; expected 26. Check that the Pine export includes all TV26 plots.")
    component_stats={name:Counter() for name in tv_component_cols}
    matched=unmatched=ambiguous=ohlc_mismatch=0
    examples=[]
    seen=set()
    for tr in tv_rows:
        tstamp=tv_epoch(tr)
        k=price_key(tr,TV_FIELDS,args.tick_size)
        candidates=[]
        # Prefer exact timestamp after configured timezone normalization; use OHLC as
        # an independent guard against accidental same-time/different-feed comparisons.
        if tstamp and tstamp in mt_by_stamp:
            candidates=mt_by_stamp[tstamp]
            if k:
                exact=[r for r in candidates if price_key(r,{"open":"candle_open","high":"candle_high","low":"candle_low","close":"candle_close"},args.tick_size)==k]
                if exact: candidates=exact
                else:
                    ohlc_mismatch+=1
                    candidates=[]
        if not candidates and k:
            # Fallback only when the OHLC fingerprint uniquely identifies one MT5 bar.
            unique={(r.get("bar_open_time_server","")) for r in mt_by_ohlc.get(k,[])}
            if len(unique)==1:
                stamp=next(iter(unique))
                candidates=[r for r in mt_by_ohlc[k] if r.get("bar_open_time_server")==stamp]
        if not candidates:
            unmatched+=1
            continue
        stamps={r.get("bar_open_time_server","") for r in candidates}
        if len(stamps)!=1:
            ambiguous+=1
            continue
        stamp=next(iter(stamps))
        if (stamp,k) in seen:
            continue
        seen.add((stamp,k)); matched+=1
        by_comp={r.get("component"):r for r in candidates}
        for tv_name,tv_col in tv_component_cols.items():
            mt_name=TV_TO_MT5[tv_name]
            mr=by_comp.get(mt_name)
            tv_vote=num(tr.get(tv_col,""))
            if not mr or tv_vote is None or mr.get("readiness")!="OK":
                component_stats[tv_name]["not_comparable"]+=1; continue
            mv=num(mr.get("vote",""))
            if mv is None:
                component_stats[tv_name]["not_comparable"]+=1; continue
            component_stats[tv_name]["compared"]+=1
            if int(round(tv_vote))==int(round(mv)):
                component_stats[tv_name]["equal"]+=1
            else:
                component_stats[tv_name]["different"]+=1
                if len(examples)<50:
                    examples.append({"timeframe":args.timeframe,"mt5_time":stamp,"component":tv_name,
                                     "tradingview_vote":tv_vote,"mt5_vote":mv,
                                     "tv_close":tr.get("TV26.close",""),"mt5_close":mr.get("candle_close","")})
    all_compared=sum(v["compared"] for v in component_stats.values())
    all_diff=sum(v["different"] for v in component_stats.values())
    all_equal=sum(v["equal"] for v in component_stats.values())
    result={"timeframe":args.timeframe,"tv_rows":len(tv_rows),"mt5_rows_for_timeframe":len(mt),
      "matched_candles":matched,"unmatched_tv_rows":unmatched,"ambiguous_candles":ambiguous,
      "timestamp_matches_with_ohlc_mismatch":ohlc_mismatch,"components_exported":len(tv_component_cols),
      "component_votes_compared":all_compared,"equal_votes":all_equal,"different_votes":all_diff,
      "match_rate_percent":round(100*matched/max(1,len(tv_rows)),4),
      "vote_agreement_percent":round(100*all_equal/max(1,all_compared),4),
      "components":{k:dict(v) for k,v in component_stats.items()},"first_differences":examples,
      "limits":["Feed equality is checked by candle OHLC to tick-size precision; bars from different price feeds are not treated as valid same-candle comparisons.",
      "The MT5 UTC offset must be correct for the test dates. Split the comparison if broker DST offset changes.",
      "This report validates exported indicator votes only, not trade profitability or execution."]}
    lines=["# TV26 direct TradingView ↔ MT5 component parity", "",
      f"- Timeframe: **{args.timeframe}**",
      f"- TradingView rows: {len(tv_rows)}",
      f"- MT5 rows in selected timeframe: {len(mt)}",
      f"- Candles matched: {matched}; unmatched TV rows: {unmatched}; ambiguous: {ambiguous}",
      f"- Timestamp-matched candles rejected due to OHLC mismatch: {ohlc_mismatch}",
      f"- Components exported: {len(tv_component_cols)} / 26",
      f"- Component votes compared: {all_compared}",
      f"- Equal votes: {all_equal}; different votes: {all_diff}",
      f"- Vote agreement: **{result['vote_agreement_percent']:.4f}%**",
      "", "## Per-component results", "", "| Pine component | Compared | Equal | Different | Not comparable |",
      "|---|---:|---:|---:|---:|"]
    for name,stats in component_stats.items():
      lines.append(f"| {name} | {stats['compared']} | {stats['equal']} | {stats['different']} | {stats['not_comparable']} |")
    lines += ["","## First differences",""]
    if examples:
      lines += ["| MT5 bar time | Component | TradingView | MT5 | TV close | MT5 close |","|---|---|---:|---:|---:|---:|"]
      for e in examples:
        lines.append(f"| {e['mt5_time']} | {e['component']} | {e['tradingview_vote']} | {e['mt5_vote']} | {e['tv_close']} | {e['mt5_close']} |")
    else: lines.append("No vote differences were observed among the component votes that could be compared.")
    lines += ["","## Interpretation","",
      "A component-level match is accepted only on bars whose OHLC fingerprints agree to the configured tick size. If the match rate is low, first resolve the chart symbol/feed, history range, and broker UTC offset; do not change indicator formulas to compensate for different price data.",
      ""]
    Path(args.report).write_text("\n".join(lines),encoding="utf-8")
    Path(args.json).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("\n".join(lines[:18]))
if __name__=="__main__": main()
