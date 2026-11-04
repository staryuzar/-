from __future__ import annotations
import argparse, json, math, sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any
from mirsad.config import DECISION_CALIBRATION_DB_PATH

M1_MS=60_000

@dataclass(frozen=True)
class SplitWindow:
    name: str
    start_ms: int
    end_ms: int

def parse_horizons(value: str) -> tuple[int,...]:
    parts=[x.strip() for x in str(value).split(",")]
    if not parts or any(not x for x in parts):
        raise ValueError("horizons must be comma-separated positive integers")
    try: values=tuple(sorted(int(x) for x in parts))
    except ValueError as exc: raise ValueError("horizons must contain integers only") from exc
    if any(x<=0 for x in values): raise ValueError("horizons must be positive")
    if len(set(values))!=len(values): raise ValueError("horizons must be unique")
    return values

def validate_split_windows(windows: list[SplitWindow], *, max_horizon: int, embargo_bars: int)->None:
    if max_horizon<=0 or embargo_bars<0: raise ValueError("invalid max horizon or embargo")
    if [x.name for x in windows]!=["train","validation","test"]:
        raise ValueError("splits must be supplied in train, validation, test order")
    for x in windows:
        if x.start_ms<=0 or x.end_ms<=x.start_ms: raise ValueError(f"{x.name} split bounds must be increasing and positive")
        if x.end_ms-x.start_ms <= (max_horizon+embargo_bars+1)*M1_MS:
            raise ValueError(f"{x.name} split is too short for its forward horizon and embargo")
    min_gap=(max_horizon+embargo_bars)*M1_MS
    for previous,current in zip(windows,windows[1:]):
        if current.start_ms-previous.end_ms<min_gap:
            raise ValueError(f"{current.name} must begin at least {min_gap} ms after {previous.name} ends")

def forward_markout_bps(*,signal_bar_time_ms:int,action:str,candles_by_open_ms:dict[int,dict[str,float]],
                        horizon:int,fee_bps_per_side:float,slippage_bps_per_side:float,
                        spread_pct:float|None)->dict[str,float]|None:
    direction=1.0 if action=="BUY" else -1.0 if action=="SELL" else 0.0
    if direction==0 or horizon<=0 or spread_pct is None: return None
    assumptions=(fee_bps_per_side,slippage_bps_per_side,float(spread_pct))
    if not all(math.isfinite(x) and x>=0 for x in assumptions): return None
    entry_time=signal_bar_time_ms+M1_MS
    future=[candles_by_open_ms.get(entry_time+i*M1_MS) for i in range(horizon)]
    if any(not isinstance(x,dict) for x in future): return None
    try: entry=float(future[0]["open"]); exit_price=float(future[-1]["close"])
    except (KeyError,TypeError,ValueError,OverflowError): return None
    if not all(math.isfinite(x) and x>0 for x in (entry,exit_price)): return None
    gross=direction*(exit_price/entry-1)*10_000.0
    # Stored spread is percentage points: 0.08 means 0.08%.
    costs=2*fee_bps_per_side+2*slippage_bps_per_side+float(spread_pct)*100.0
    return {"gross_bps":gross,"cost_bps":costs,"net_bps":gross-costs,
            "entry_price":entry,"exit_price":exit_price}

def summarize(rows:list[dict[str,Any]])->dict[str,Any]:
    net=[float(x["net_bps"]) for x in rows]; gross=[float(x["gross_bps"]) for x in rows]
    if not net: return {"sample_count":0,"gross_mean_bps":None,"net_mean_bps":None,
                        "net_median_bps":None,"net_win_rate":None,"profit_factor":None,
                        "max_drawdown_bps":None}
    gains=sum(x for x in net if x>0); losses=-sum(x for x in net if x<0)
    equity=peak=drawdown=0.0
    for value in net:
        equity+=value; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    return {"sample_count":len(net),"gross_mean_bps":round(mean(gross),4),
            "net_mean_bps":round(mean(net),4),"net_median_bps":round(median(net),4),
            "net_win_rate":round(sum(x>0 for x in net)/len(net),4),
            "profit_factor":round(gains/losses,4) if losses else None,
            "max_drawdown_bps":round(drawdown,4)}

def read_calibration_rows(db_path:Path,windows:list[SplitWindow]):
    if not db_path.is_file(): raise FileNotFoundError(f"Calibration archive does not exist: {db_path}")
    low=min(x.start_ms for x in windows); high=max(x.end_ms for x in windows)
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory=sqlite3.Row
        samples=conn.execute("""SELECT sample_key,signal_bar_time_ms,symbol,profile_version,final_action,broker_spread_pct
          FROM decision_calibration_samples WHERE signal_bar_time_ms>=? AND signal_bar_time_ms<?
          ORDER BY signal_bar_time_ms,sample_key""",(low,high)).fetchall()
        symbols=sorted({str(x["symbol"]) for x in samples})
        if len(symbols)>1: raise ValueError("Run one symbol per study.")
        candles={}
        if symbols:
            rows=conn.execute("""SELECT open_time_ms,open,high,low,close FROM decision_calibration_candles
              WHERE symbol=? AND timeframe='1m' AND open_time_ms>? AND open_time_ms<=? ORDER BY open_time_ms""",
              (symbols[0],low,high)).fetchall()
            for row in rows:
                try:
                    stamp=int(row["open_time_ms"]); item={k:float(row[k]) for k in ("open","high","low","close")}
                except (TypeError,ValueError,OverflowError): continue
                if (stamp<=0 or not all(math.isfinite(v) and v>0 for v in item.values())
                    or item["high"]<max(item["open"],item["close"],item["low"])
                    or item["low"]>min(item["open"],item["close"],item["high"])): continue
                candles[stamp]=item
    return [dict(x) for x in samples],candles

def evaluate_database(db_path:Path,*,windows:list[SplitWindow],horizons:tuple[int,...],
                      embargo_bars:int,fee_bps_per_side:float,slippage_bps_per_side:float)->dict[str,Any]:
    if not horizons or tuple(sorted(set(horizons)))!=horizons: raise ValueError("horizons must be sorted, unique, and non-empty")
    validate_split_windows(windows,max_horizon=max(horizons),embargo_bars=embargo_bars)
    if not all(math.isfinite(x) and x>=0 for x in (fee_bps_per_side,slippage_bps_per_side)):
        raise ValueError("fee and slippage must be finite and non-negative")
    samples,candles=read_calibration_rows(db_path,windows); reports={}
    for window in windows:
        eligible=[x for x in samples if window.start_ms+embargo_bars*M1_MS<=int(x["signal_bar_time_ms"])
                  and int(x["signal_bar_time_ms"])+(max(horizons)+1)*M1_MS<=window.end_ms]
        directional=[x for x in eligible if str(x["final_action"]).upper() in {"BUY","SELL"}]
        metrics={}
        for horizon in horizons:
            rows=[]; skipped=0
            for sample in directional:
                result=forward_markout_bps(signal_bar_time_ms=int(sample["signal_bar_time_ms"]),
                    action=str(sample["final_action"]).upper(),candles_by_open_ms=candles,horizon=horizon,
                    fee_bps_per_side=fee_bps_per_side,slippage_bps_per_side=slippage_bps_per_side,
                    spread_pct=sample.get("broker_spread_pct"))
                if result is None: skipped+=1
                else: rows.append(result)
            metrics[str(horizon)]={**summarize(rows),"skipped_missing_spread_or_future_bars":skipped}
        reports[window.name]={"start_ms":window.start_ms,"end_ms":window.end_ms,
            "eligible_samples":len(eligible),"directional_signals":len(directional),
            "wait_signals":sum(str(x["final_action"]).upper()=="WAIT" for x in eligible),
            "horizons":metrics}
    return {"schema":"MIRSAD-DECISION-FORWARD-MARKOUT-STUDY-1","status":"UNVALIDATED",
        "profile_versions":sorted({str(x["profile_version"]) for x in samples}),
        "fee_bps_per_side":fee_bps_per_side,"slippage_bps_per_side":slippage_bps_per_side,
        "embargo_bars":embargo_bars,"horizons":list(horizons),"costs_applied":True,"splits":reports,
        "method":"Closed M1 signal -> next M1 open -> Nth consecutive future M1 close; round-trip costs include two-sided fees, slippage and recorded broker spread.",
        "limitations":["Forward markout only; not a portfolio backtest or execution simulator.",
          "Does not replay stops, targets, partial exits, funding, latency or queue position.",
          "No weights are optimized or changed by this script.",
          "Results remain UNVALIDATED until sample sufficiency, regime coverage, costs and untouched test data are independently reviewed.",
          "Overlapping horizons/signals are correlated; results are descriptive, not independent-trade confidence intervals."]}

def build_parser():
    parser=argparse.ArgumentParser(description="Cost-aware chronological evaluation of stored Mirsad decision signals.")
    parser.add_argument("--db-path",type=Path,default=DECISION_CALIBRATION_DB_PATH)
    for split in ("train","validation","test"):
        parser.add_argument(f"--{split}-start-ms",type=int,required=True)
        parser.add_argument(f"--{split}-end-ms",type=int,required=True)
    parser.add_argument("--embargo-bars",type=int,default=20)
    parser.add_argument("--horizons",default="1,3,5,10,20")
    parser.add_argument("--fee-bps-per-side",type=float,required=True)
    parser.add_argument("--slippage-bps-per-side",type=float,required=True)
    parser.add_argument("--output-json",type=Path,default=None)
    return parser

def main()->int:
    parser=build_parser(); args=parser.parse_args()
    try:
        windows=[SplitWindow(name,getattr(args,f"{name}_start_ms"),getattr(args,f"{name}_end_ms"))
                 for name in ("train","validation","test")]
        result=evaluate_database(args.db_path,windows=windows,horizons=parse_horizons(args.horizons),
            embargo_bars=args.embargo_bars,fee_bps_per_side=args.fee_bps_per_side,
            slippage_bps_per_side=args.slippage_bps_per_side)
        if args.output_json:
            args.output_json.parent.mkdir(parents=True,exist_ok=True)
            args.output_json.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    except Exception as exc:
        parser.exit(2,f"Calibration study failed: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0

if __name__=="__main__":
    raise SystemExit(main())
