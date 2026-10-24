# TV26 direct parity — current status (24 October 2026)

## Gate summary

| Gate | Status | Evidence |
|---|---|---|
| Pine exporters accepted by the TradingView compiler | PASS | [Parity CI, 24 Oct](https://github.com/staryuzar/-/actions/runs/40079665993) |
| Python comparator / splitter / regression suite | PASS | [38 deterministic tests and TradingView compiler gate](https://github.com/staryuzar/-/actions/runs/40079367672) |
| MQL5 source compiled by official MetaEditor in cloud | PASS | [MetaEditor compile](https://github.com/staryuzar/-/actions/runs/40079666035) |
| Recent MT5 audit for 21–23 October 2026 | PASS | [Cloud audit](https://github.com/staryuzar/-/actions/runs/40079359327) |
| Independent formula reference vs MT5 audit votes | PASS within the recorded MT5 feed | [Audit evidence artifact](https://github.com/staryuzar/-/actions/runs/40079359327/artifacts/12554097875) |
| Raw Ichimoku values vs OHLC, including 26-bar cloud shift | PASS on the downloaded audit sample: 5,432 candles × 5 raw values, zero mismatches | [Cloud audit artifact](https://github.com/staryuzar/-/actions/runs/40079359327/artifacts/12554097875) |
| Direct actual TradingView chart data vs MT5 | **PENDING — no TradingView CSV uploaded** | Requires `TV26_AllTF.csv` from the Pine exporter below |
| Strategy profitability / real-tick robustness | **NOT TESTED by these parity runs** | Requires separate backtests with trading enabled in a controlled tester |

## Verified recent MT5 audit

- Window: 21–23 October 2026; MT5 tester end date 24 October.
- Symbol/account context: XAUUSD, Headway-Demo / Jarocel (Pty) Ltd.
- Tester: M1, model 1-minute OHLC, 500 USD deposit, 1:1000 leverage.
- Trading intentionally disabled: `InpEnableTrading=false`, `AllowLiveTrading=0`.
- Audit rows: 146,664; 5,432 candle groups; 141,232 component votes.
- Readiness: all 5,432 summary rows complete over M1/M5/M15/M30/H1.
- Internal aggregate arithmetic: 16,296 values checked, zero mismatches.
- Independent implementation of published TechnicalRating v3 expressions vs MT5 votes: 141,232 checked, zero mismatches, zero missing values.
- Source/data fingerprints and all limits are in [TV26_CLOUD_AUDIT_2026-10-24.md](TV26_CLOUD_AUDIT_2026-10-24.md).

The result means that MT5’s recorded votes agree with the independently coded reference on the audited MT5 OHLCV. It does **not** prove that live TradingView chart values are numerically identical.

A separate raw-value validation reconstructed Tenkan, Kijun, Senkou Span A/B shifted back 26 bars, and close from the actual exported OHLC. It checked 27,160 raw values over all five timeframes (5,432 Ichimoku candles) with zero mismatches. This confirms the current MT5 buffer alignment on that audited feed; it still does not substitute for the TradingView CSV comparison.

## Actual TradingView compiler check

Both `TradingView_Parity_AllTF_Export.pine` and `TradingView_Parity_Components_1TF.pine` were sent through the TradingView compiler endpoint as part of GitHub Actions and returned `clean`. The check exposed and fixed a real compile issue before that result: `tvta.wpr(14)` was changed to the built-in `ta.wpr(14)`, and regression tests now prevent the wrong namespace returning.

## Remaining input

Export one CSV from TradingView after adding [TradingView_Parity_AllTF_Export.pine](TradingView_Parity_AllTF_Export.pine) to the XAUUSD chart at M1. Target window: 21–23 October 2026. Use the closest available feed to Headway XAUUSD; if OHLC differs, the report will identify the feed/time alignment issue before blaming the formulas.

Upload the resulting file as:

`trading-lab/tv26/parity-input/TV26_AllTF.csv`

on branch `tv26-five-timeframes-arabic-candidate`.

The automated workflow watches that path and starts on commit. It downloads the matching MT5 audit artifact from run `40079359327`, then produces reports for all five timeframes. Its current default MT5 offset is UTC+3; verify the broker server offset before interpreting timing mismatches.

Official TradingView documentation describes intraday chart limits by plan: 5,000 bars for basic plans, 10,000 for Essential/Plus, 20,000 for Premium, 25,000 for Expert and 40,000 for Ultimate. See [TradingView's historical intraday bars and limits](https://www.tradingview.com/support/solutions/43000480679-historical-intraday-data-bars-and-limits-explained/). A recent three-day interval is deliberately used to improve the chance of overlap on M1 charts.

## Decision rule

Do not mark parity PASS until all five frames have at least 10 common closed candles, the matched candles cover at least 80% of MT5 audit candles for each frame, OHLC matches within 0.01, all three aggregate ratings are within 0.0011, formula aggregates agree with the official library, and all 26 component votes match without missing values. The 80% coverage gate prevents a misleading PASS based on a tiny overlap. Do not infer profitability from this check.
