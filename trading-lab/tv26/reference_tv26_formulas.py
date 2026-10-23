#!/usr/bin/env python3
"""Independent formula-level audit of TV26 votes from OHLCV warmup and MT5 audit CSV.

The rules follow the published TradingView TechnicalRating v3 expression reference
and TradingView ta-library definitions. This is not a live TradingView chart export.
Requires numpy and pandas.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

TF_LABEL = {"M1":"د1", "M5":"د5", "M15":"د15", "M30":"د30", "H1":"س1"}
MIN_BARS = {"M1":1000, "M5":200, "M15":60, "M30":30, "H1":15}
KEY_TO_LABEL = {
 "SMA10":"متوسط بسيط 10", "SMA20":"متوسط بسيط 20", "SMA30":"متوسط بسيط 30",
 "SMA50":"متوسط بسيط 50", "SMA100":"متوسط بسيط 100", "SMA200":"متوسط بسيط 200",
 "EMA10":"متوسط أسي 10", "EMA20":"متوسط أسي 20", "EMA30":"متوسط أسي 30",
 "EMA50":"متوسط أسي 50", "EMA100":"متوسط أسي 100", "EMA200":"متوسط أسي 200",
 "HMA9":"متوسط هال 9", "VWMA20":"متوسط مرجّح بالحجم",
 "Ichimoku":"إيشيموكو - خط الأساس", "RSI14":"القوة النسبية RSI",
 "Stochastic":"ستوكاستك", "CCI20":"قناة السلع CCI", "ADX":"مؤشر الاتجاه ADX",
 "AO":"المذبذب الرائع AO", "Momentum10":"الزخم Momentum",
 "MACD":"تقارب/تباعد المتوسطات MACD", "StochRSI":"ستوكاستك RSI",
 "WilliamsR":"ويليامز %R", "BullBearPower":"قوة الثيران والدببة",
 "UltimateOscillator":"المذبذب النهائي",
}
LABEL_TO_KEY = {v:k for k,v in KEY_TO_LABEL.items()}
MA_KEYS = ("SMA10","SMA20","SMA30","SMA50","SMA100","SMA200",
           "EMA10","EMA20","EMA30","EMA50","EMA100","EMA200",
           "HMA9","VWMA20","Ichimoku")
OSC_KEYS = ("RSI14","Stochastic","CCI20","ADX","AO","Momentum10","MACD",
            "StochRSI","WilliamsR","BullBearPower","UltimateOscillator")
ALL_KEYS = MA_KEYS + OSC_KEYS
EPS = 1.0e-10

class FormulaAuditError(ValueError): pass

def read_csv(path: str | Path) -> tuple[list[str], list[dict[str,str]]]:
    p=Path(path)
    if not p.is_file(): raise FormulaAuditError(f"Input file missing: {p}")
    with p.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames: raise FormulaAuditError(f"No header row in {p}")
        rows=[{str(k).strip(): (v or "").strip() for k,v in r.items() if k is not None} for r in reader]
        return list(reader.fieldnames), rows

def require_columns(headers: list[str], required: tuple[str,...], source: str) -> None:
    missing=[x for x in required if x not in headers]
    if missing: raise FormulaAuditError(f"{source} missing columns: {', '.join(missing)}")

def ema(s: pd.Series, n: int) -> pd.Series:
    # Pine ta.ema recurrence: alpha=2/(n+1), recursively seeded from first source value.
    return s.ewm(span=n, adjust=False, min_periods=1).mean()

def rma(s: pd.Series, n: int) -> pd.Series:
    # Wilder RMA seeded by the first SMA over n non-NA values, then recursive smoothing.
    x=np.asarray(s,dtype=float); out=np.full(len(x),np.nan)
    valid=np.flatnonzero(np.isfinite(x))
    if len(valid)<n: return pd.Series(out,index=s.index)
    seed_pos=int(valid[n-1]); out[seed_pos]=float(np.mean(x[valid[:n]])); alpha=1.0/n
    for i in range(seed_pos+1,len(x)):
        if np.isfinite(x[i]): out[i]=alpha*x[i]+(1-alpha)*out[i-1]
        else: out[i]=out[i-1]
    return pd.Series(out,index=s.index)

def wma(s: pd.Series, n: int) -> pd.Series:
    weights=np.arange(1,n+1,dtype=float); denom=float(weights.sum())
    return s.rolling(n,min_periods=n).apply(lambda a: float(np.dot(a,weights)/denom),raw=True)

def sign(a: pd.Series, b: pd.Series) -> pd.Series:
    diff=a-b; out=pd.Series(np.nan,index=diff.index,dtype=float)
    valid=a.notna()&b.notna()
    out.loc[valid]=np.sign(diff.loc[valid])
    return out

# Match the EA's tiny price/MA equality tolerance to avoid binary-float artifacts.
# XAUUSD tick size is 0.01 in this lab, so tick_size * 1e-7 = 1e-9.
PRICE_COMPARE_EPS = 1.0e-9

def sign_price_level(source: pd.Series, level: pd.Series) -> pd.Series:
    diff=source-level
    out=pd.Series(np.nan,index=diff.index,dtype=float)
    valid=source.notna() & level.notna()
    values=diff.loc[valid]
    out.loc[valid]=np.where(values.abs()<=PRICE_COMPARE_EPS,0.0,np.sign(values))
    return out

def rsi(close: pd.Series, n: int=14) -> pd.Series:
    delta=close.diff(); up=delta.clip(lower=0); down=(-delta).clip(lower=0)
    au=rma(up,n); ad=rma(down,n); rs=au/ad
    out=100-(100/(1+rs))
    out.loc[(ad==0)&(au>0)]=100
    out.loc[(au==0)&(ad>0)]=0
    out.loc[(au==0)&(ad==0)]=50
    return out

def compute_votes(df: pd.DataFrame) -> dict[str,pd.Series]:
    o,h,l,c,v=(df[k].astype(float) for k in ("open","high","low","close","volume"))
    votes: dict[str,pd.Series]={}
    for n in (10,20,30,50,100,200):
        votes[f"SMA{n}"]=sign_price_level(c,c.rolling(n,min_periods=n).mean())
        votes[f"EMA{n}"]=sign_price_level(c,ema(c,n))
    votes["HMA9"]=sign_price_level(c,wma(2*wma(c,4)-wma(c,9),3))
    denom=v.rolling(20,min_periods=20).sum()
    vwma=(c*v).rolling(20,min_periods=20).sum()/denom.replace(0,np.nan)
    votes["VWMA20"]=sign_price_level(c,vwma)
    tenkan=(h.rolling(9,min_periods=9).max()+l.rolling(9,min_periods=9).min())/2
    kijun=(h.rolling(26,min_periods=26).max()+l.rolling(26,min_periods=26).min())/2
    span_a=(tenkan+kijun)/2
    span_b=(h.rolling(52,min_periods=52).max()+l.rolling(52,min_periods=52).min())/2
    lead_a=span_a.shift(26); lead_b=span_b.shift(26)
    ichi=np.where((lead_a>lead_b)&(kijun>lead_a)&(tenkan>kijun)&(c>tenkan),1,
         np.where((lead_a<lead_b)&(kijun<lead_a)&(tenkan<kijun)&(c<tenkan),-1,0))
    votes["Ichimoku"]=pd.Series(ichi,index=df.index,dtype=float).where(lead_a.notna()&lead_b.notna()&kijun.notna()&tenkan.notna())
    R=rsi(c,14)
    rv=np.where((R<30)&(R.shift(1)<R),1,np.where((R>70)&(R.shift(1)>R),-1,0))
    votes["RSI14"]=pd.Series(rv,index=df.index,dtype=float).where(R.notna()&R.shift(1).notna())
    lo14=l.rolling(14,min_periods=14).min(); hi14=h.rolling(14,min_periods=14).max()
    raw_k=100*(c-lo14)/(hi14-lo14).replace(0,np.nan)
    k=raw_k.rolling(3,min_periods=3).mean(); d=k.rolling(3,min_periods=3).mean()
    sv=np.where((k<20)&(d<20)&(k>d+EPS),1,np.where((k>80)&(d>80)&(k<d-EPS),-1,0))
    votes["Stochastic"]=pd.Series(sv,index=df.index,dtype=float).where(d.shift(1).notna())
    sma20=c.rolling(20,min_periods=20).mean()
    mean_dev=c.rolling(20,min_periods=20).apply(lambda a: float(np.mean(np.abs(a-np.mean(a))),),raw=True)
    cci=(c-sma20)/(0.015*mean_dev.replace(0,np.nan))
    ccv=np.where((cci<-100)&(cci>cci.shift(1)),1,np.where((cci>100)&(cci<cci.shift(1)),-1,0))
    votes["CCI20"]=pd.Series(ccv,index=df.index,dtype=float).where(cci.notna()&cci.shift(1).notna())
    up=h.diff(); down=-l.diff()
    plus_dm=pd.Series(np.where((up>down)&(up>0),up,0.0),index=df.index)
    minus_dm=pd.Series(np.where((down>up)&(down>0),down,0.0),index=df.index)
    tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    tr.iloc[0]=h.iloc[0]-l.iloc[0]
    atr=rma(tr,14); plus=100*rma(plus_dm,14)/atr; minus=100*rma(minus_dm,14)/atr
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,1)
    adx=rma(dx,14)
    ax=np.where((adx>20)&(adx>adx.shift(1))&(plus>minus),1,
       np.where((adx>20)&(adx>adx.shift(1))&(plus<minus),-1,0))
    votes["ADX"]=pd.Series(ax,index=df.index,dtype=float).where(adx.notna()&adx.shift(1).notna()&plus.notna()&minus.notna())
    hl2=(h+l)/2; ao=hl2.rolling(5,min_periods=5).mean()-hl2.rolling(34,min_periods=34).mean()
    up_cross=(ao>0)&(ao.shift(1)<=0); down_cross=(ao<0)&(ao.shift(1)>=0)
    up_saucer=(ao>0)&(ao.shift(1)>0)&(ao>ao.shift(1))&(ao.shift(2)>ao.shift(1))
    down_saucer=(ao<0)&(ao.shift(1)<0)&(ao<ao.shift(1))&(ao.shift(2)<ao.shift(1))
    aov=np.where(up_cross|up_saucer,1,np.where(down_cross|down_saucer,-1,0))
    votes["AO"]=pd.Series(aov,index=df.index,dtype=float).where(ao.shift(1).notna()&ao.shift(2).notna())
    mom=c-c.shift(10); momv=np.where(mom>mom.shift(1),1,np.where(mom<mom.shift(1),-1,0))
    votes["Momentum10"]=pd.Series(momv,index=df.index,dtype=float).where(mom.notna()&mom.shift(1).notna())
    macd=ema(c,12)-ema(c,26); macd_signal=ema(macd,9)
    votes["MACD"]=sign(macd,macd_signal).where(macd_signal.notna())
    rsi_lo=R.rolling(14,min_periods=14).min(); rsi_hi=R.rolling(14,min_periods=14).max()
    raw_sr=100*(R-rsi_lo)/(rsi_hi-rsi_lo).replace(0,np.nan)
    ksr=raw_sr.rolling(3,min_periods=3).mean(); dsr=ksr.rolling(3,min_periods=3).mean()
    ema50=ema(c,50); downtrend=c<ema50; uptrend=c>ema50
    srs=np.where(downtrend&(ksr<20)&(dsr<20)&(ksr>dsr+EPS),1,
         np.where(uptrend&(ksr>80)&(dsr>80)&(ksr<dsr-EPS),-1,0))
    votes["StochRSI"]=pd.Series(srs,index=df.index,dtype=float).where(ksr.notna()&dsr.notna()&ema50.notna())
    hh=h.rolling(14,min_periods=14).max(); ll=l.rolling(14,min_periods=14).min()
    wr=-100*(hh-c)/(hh-ll).replace(0,np.nan)
    wrv=np.where((wr<-80)&(wr>wr.shift(1)),1,np.where((wr>-20)&(wr<wr.shift(1)),-1,0))
    votes["WilliamsR"]=pd.Series(wrv,index=df.index,dtype=float).where(wr.notna()&wr.shift(1).notna())
    bull=h-ema(c,13); bear=l-ema(c,13)
    bbv=np.where(uptrend&(bear<0)&(bear>bear.shift(1)),1,
         np.where(downtrend&(bull>0)&(bull<bull.shift(1)),-1,0))
    votes["BullBearPower"]=pd.Series(bbv,index=df.index,dtype=float).where(ema50.notna()&bear.notna()&bear.shift(1).notna()&bull.notna()&bull.shift(1).notna())
    tmax=pd.concat([h,c.shift(1)],axis=1).max(axis=1); tmin=pd.concat([l,c.shift(1)],axis=1).min(axis=1)
    tr_uo=tmax-tmin; bp=c-tmin
    a7=bp.rolling(7,min_periods=7).sum()/tr_uo.rolling(7,min_periods=7).sum().replace(0,np.nan)
    a14=bp.rolling(14,min_periods=14).sum()/tr_uo.rolling(14,min_periods=14).sum().replace(0,np.nan)
    a28=bp.rolling(28,min_periods=28).sum()/tr_uo.rolling(28,min_periods=28).sum().replace(0,np.nan)
    uo=100*(4*a7+2*a14+a28)/7
    uov=np.where(uo>70,1,np.where(uo<30,-1,0))
    votes["UltimateOscillator"]=pd.Series(uov,index=df.index,dtype=float).where(uo.notna())
    return votes

def run_audit(audit_path: str | Path, history_path: str | Path,
              min_bars: dict[str,int] | None=None) -> tuple[dict[str,Any], list[dict[str,str]], str]:
    ah,ar=read_csv(audit_path); hh,hr=read_csv(history_path)
    require_columns(ah,('bar_open_time_server','timeframe','component','readiness','vote','candle_open','candle_high','candle_low','candle_close','tick_volume'),'MT5 audit')
    require_columns(hh,('bar_open_time_server','timeframe','symbol','broker_company','broker_server','candle_open','candle_high','candle_low','candle_close','tick_volume'),'OHLCV history')
    minima=dict(MIN_BARS); minima.update(min_bars or {})
    rows_detail=[]; per_tf={}; all_mismatches=0; all_checked=0; all_missing=0; overlap_mismatches=0; overlap_pairs=0
    seen_metadata=set()
    for tf, label in TF_LABEL.items():
        history=[r for r in hr if r.get('timeframe')==label]
        aud=[r for r in ar if r.get('timeframe')==label]
        summaries={r['bar_open_time_server']:r for r in aud if r.get('component')=='SUMMARY'}
        records=[r for r in aud if r.get('component')!='SUMMARY']
        record_counts=Counter(r['bar_open_time_server'] for r in records)
        components_by_time=defaultdict(set)
        for component_row in records: components_by_time[component_row['bar_open_time_server']].add(component_row['component'])
        if not summaries: raise FormulaAuditError(f'No SUMMARY candles found for {tf}')
        combined={}; history_by_time={}
        for r in history:
            history_by_time[r['bar_open_time_server']]={
                'time':r['bar_open_time_server'],'open':float(r['candle_open']),'high':float(r['candle_high']),
                'low':float(r['candle_low']),'close':float(r['candle_close']),'volume':float(r['tick_volume'])}
            combined[r['bar_open_time_server']]=history_by_time[r['bar_open_time_server']]
            seen_metadata.add((r['symbol'],r['broker_company'],r['broker_server']))
        for r in summaries.values():
            stamp=r['bar_open_time_server']
            current={'time':stamp,'open':float(r['candle_open']),'high':float(r['candle_high']),
                'low':float(r['candle_low']),'close':float(r['candle_close']),'volume':float(r['tick_volume'])}
            if stamp in history_by_time:
                overlap_pairs+=1
                if any(abs(current[k]-history_by_time[stamp][k])>1e-8 for k in ('open','high','low','close')):
                    overlap_mismatches+=1
            combined[stamp]=current
            seen_metadata.add((r['symbol'],r['broker_company'],r['broker_server']))
        df=pd.DataFrame(combined.values())
        df=df.sort_values('time').drop_duplicates('time',keep='last').reset_index(drop=True)
        df['datetime']=pd.to_datetime(df['time'],format='%Y.%m.%d %H:%M',errors='raise')
        votes=compute_votes(df)
        ix={stamp:i for i,stamp in enumerate(df['time'])}
        errors=[]; checked=0; mismatches=0; missing=0
        for row in records:
            stamp=row['bar_open_time_server']; label_name=row['component']
            key=LABEL_TO_KEY.get(label_name)
            if key is None:
                missing+=1; all_missing+=1
                rows_detail.append({'timeframe':tf,'time':stamp,'component':label_name,'reference_vote':'','mt5_vote':row.get('vote',''),'state':'UNKNOWN_COMPONENT','note':'Not one of the published 26 components'})
                continue
            pos=ix.get(stamp)
            calc=float(votes[key].iloc[pos]) if pos is not None and pd.notna(votes[key].iloc[pos]) else float('nan')
            mt=float(row['vote']) if row.get('readiness')=='OK' and row.get('vote','')!='' else float('nan')
            if not math.isfinite(calc) or not math.isfinite(mt):
                missing+=1; all_missing+=1
                rows_detail.append({'timeframe':tf,'time':stamp,'component':key,'reference_vote':str(calc),'mt5_vote':str(mt),'state':'MISSING_VALUE','note':'Formula calculation or MT5 vote is not ready'})
                continue
            checked+=1; all_checked+=1
            state='MATCH' if calc==mt else 'MISMATCH'
            if state!='MATCH':
                mismatches+=1; all_mismatches+=1
                if len(errors)<100: errors.append({'time':stamp,'component':key,'formula_vote':int(calc),'mt5_vote':int(mt)})
            rows_detail.append({'timeframe':tf,'time':stamp,'component':key,'reference_vote':str(int(calc)),'mt5_vote':str(int(mt)),'state':state,'note':'Published TechnicalRating formula reimplementation'})
        candles=len(summaries)
        by_tf_checked=sum(1 for x in rows_detail if x['timeframe']==tf and x.get('state') in ('MATCH','MISMATCH'))
        by_tf_mismatch=sum(1 for x in rows_detail if x['timeframe']==tf and x.get('state')=='MISMATCH')
        by_tf_missing=sum(1 for x in rows_detail if x['timeframe']==tf and x.get('state') not in ('MATCH','MISMATCH'))
        coverage=candles>=minima[tf]
        expected_labels=set(KEY_TO_LABEL.values())
        candle_complete=all(s.get('readiness')=='OK' for s in summaries.values()) and all(record_counts.get(stamp,0)==26 and components_by_time.get(stamp,set())==expected_labels for stamp in summaries)
        passed=coverage and candle_complete and by_tf_checked==candles*26 and by_tf_mismatch==0 and by_tf_missing==0
        per_tf[tf]={'summary_candles':candles,'component_rows':len(records),'formula_votes_checked':by_tf_checked,
                    'mismatches':by_tf_mismatch,'missing_or_invalid':by_tf_missing,'minimum_candles':minima[tf],
                    'coverage_pass':coverage,'complete_26_vote_bundles':candle_complete,'status':'PASS' if passed else 'FAIL',
                    'mismatch_examples':errors[:20]}
    metadata=[{'symbol':x[0],'broker_company':x[1],'broker_server':x[2]} for x in sorted(seen_metadata)]
    enough_metadata=len(metadata)==1
    passed=(all(p['status']=='PASS' for p in per_tf.values()) and all_mismatches==0 and all_missing==0 and overlap_mismatches==0 and enough_metadata)
    result={'status':'PASS' if passed else 'FAIL','scope':'formula-level reference vs MT5 recorded votes; not live TradingView export',
            'audit_file':str(audit_path),'audit_sha256':hashlib.sha256(Path(audit_path).read_bytes()).hexdigest(),
            'history_file':str(history_path),'history_sha256':hashlib.sha256(Path(history_path).read_bytes()).hexdigest(),
            'feed_metadata':metadata,'per_timeframe':per_tf,'history_overlap_pairs_checked':overlap_pairs,
            'history_overlap_price_mismatches':overlap_mismatches,'total_formula_votes_checked':all_checked,
            'total_vote_mismatches':all_mismatches,'total_missing_or_invalid':all_missing,
            'all_components_26':list(KEY_TO_LABEL.keys()),'source_reference':'TradingView TechnicalRating v3 and TradingView ta-library public expressions'}
    return result,rows_detail,make_report(result)

def make_report(r: dict[str,Any]) -> str:
    lines=['# TV26 Formula-Level Audit — '+r['status'],'',
      '**Scope:** independent Python implementation of the published TradingView TechnicalRating v3 rules, evaluated on exported MT5 OHLCV, compared against the MT5 audit votes. This is not an export from the live TradingView chart.',
      '', '- MT5 audit SHA-256: '+r['audit_sha256'], '- OHLCV history SHA-256: '+r['history_sha256'],
      '- Feed metadata entries: '+str(len(r['feed_metadata'])), '- Total votes compared: '+str(r['total_formula_votes_checked']),
      '- Vote mismatches: '+str(r['total_vote_mismatches']), '- Missing/invalid comparisons: '+str(r['total_missing_or_invalid']),
      '- Overlapping history bars checked: '+str(r['history_overlap_pairs_checked']), '- OHLC mismatches on overlapping history bars: '+str(r['history_overlap_price_mismatches']), '',
      '| Timeframe | Candles | Formula votes checked | Mismatches | Missing | Minimum | Result |', '|---|---:|---:|---:|---:|---:|---|']
    for tf,p in r['per_timeframe'].items():
        lines.append(f"| {tf} | {p['summary_candles']} | {p['formula_votes_checked']} | {p['mismatches']} | {p['missing_or_invalid']} | {p['minimum_candles']} | {p['status']} |")
    lines += ['', '## Interpretation', '',
      '- PASS establishes agreement on recorded votes between this independent public-formula implementation and MT5 for the candles and feed hashes listed above.',
      '- It does not prove that the live TradingView chart used the same symbol/feed, session settings, volume semantics, warmup history, or library runtime; that requires exporting the actual TradingView Pine outputs and running the separate CSV comparator.',
      '- It does not establish strategy profitability or real-tick execution behavior.', '', '## Feed identity', '']
    for item in r['feed_metadata']:
        lines.append('- Symbol: '+item['symbol']+'; broker: '+item['broker_company']+'; server: '+item['broker_server'])
    issues=[]
    for tf,p in r['per_timeframe'].items(): issues.extend((tf,x) for x in p['mismatch_examples'])
    lines += ['', '## First mismatch examples', '']
    if issues:
        for tf,x in issues[:50]: lines.append(f"- {tf} {x['time']} {x['component']}: formula={x['formula_vote']} vs MT5={x['mt5_vote']}")
    else: lines.append('No vote mismatches detected.')
    return '\n'.join(lines)+'\n'

def write_details(path: str|Path, rows: list[dict[str,str]]) -> None:
    fields=('timeframe','time','component','reference_vote','mt5_vote','state','note')
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main(argv: list[str]|None=None) -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit',required=True,help='MT5 TV26_Audit_*.csv')
    ap.add_argument('--history',required=True,help='TV26_OHLC_History_*.csv')
    ap.add_argument('--report',default='tv26-formula-audit.md')
    ap.add_argument('--details',default='tv26-formula-audit-details.csv')
    ap.add_argument('--json',default='tv26-formula-audit.json')
    for tf in ('M1','M5','M15','M30','H1'): ap.add_argument('--min-'+tf.lower(),type=int,default=MIN_BARS[tf])
    args=ap.parse_args(argv)
    mins={tf:getattr(args,'min_'+tf.lower()) for tf in TF_LABEL}
    if any(v<1 for v in mins.values()): ap.error('minimum candle counts must be positive')
    try:
        result,details,report=run_audit(args.audit,args.history,mins)
        Path(args.report).write_text(report,encoding='utf-8')
        Path(args.json).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        write_details(args.details,details)
        print(report); print('Details CSV: '+args.details); print('JSON: '+args.json)
        return 0 if result['status']=='PASS' else 1
    except (FormulaAuditError,OSError,ValueError,KeyError,IndexError) as exc:
        print('Formula audit could not run: '+str(exc),file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
