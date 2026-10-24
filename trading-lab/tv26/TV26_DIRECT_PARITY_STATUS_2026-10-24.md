# TV26 direct parity — current status (24 October 2026)

## Gate summary

| Gate | Status | Latest evidence |
|---|---|---|
| Pine exporters accepted by the TradingView compiler | PASS | [Parity CI, TradingView compiler + regressions](https://github.com/staryuzar/-/actions/runs/40083533515) |
| Python comparator, splitter and regression suite | PASS — 41 deterministic tests | [CI run](https://github.com/staryuzar/-/actions/runs/40083533515) |
| MQL5 source compiled by official MetaEditor in cloud | PASS | [MetaEditor compile](https://github.com/staryuzar/-/actions/runs/40083533537) |
| Recent MT5 audit for 21–23 October 2026 | PASS | [Cloud audit](https://github.com/staryuzar/-/actions/runs/40083533466); [artifact 12556177506](https://github.com/staryuzar/-/actions/runs/40083533466/artifacts/12556177506) |
| Independent formula reference versus MT5 audit votes | PASS on the recorded MT5 feed | [Audit job and evidence](https://github.com/staryuzar/-/actions/runs/40083533466) |
| Raw Ichimoku values and 26-bar cloud alignment | PASS: 27,160 values, zero mismatches | [Cloud audit artifact](https://github.com/staryuzar/-/actions/runs/40083533466/artifacts/12556177506) |
| Direct actual TradingView chart data versus MT5 | **PENDING — no real TradingView CSV in the repository** | Requires `TV26_AllTF.csv` from the Pine exporter |
| EA strategy profitability / real-tick robustness | **NOT TESTED by parity runs** | Requires a separate Strategy Tester campaign with trading enabled only in a controlled tester |

## Verified latest MT5 audit

- Window: 21–23 October 2026; Strategy Tester end date 24 October.
- Symbol/broker: XAUUSD, Headway-Demo / Jarocel (Pty) Ltd.
- Tester model: M1, 1-minute OHLC, not Real Ticks; deposit 500 USD; leverage 1:1000.
- Trading was intentionally disabled: `InpEnableTrading=false`, `AllowLiveTrading=0`.
- Audit CSV: 146,664 data rows; 5,432 candle groups; 141,232 component votes.
- All 5,432 summary rows were complete on M1/M5/M15/M30/H1.
- Aggregate arithmetic checks: 16,296 values, zero mismatches.
- Independent implementation of the published TechnicalRating v3 rules versus MT5 votes: 141,232 checked, zero mismatches, zero missing/invalid values.
- Raw Ichimoku validation: 27,160 values checked, zero mismatches/missing, including Tenkan, Kijun and Senkou spans shifted 26 bars.
- Audit SHA-256: `e92d178246b76d463f366a5057729d5a73abe5d67b2ee6f56278a0fd508593b2`.
- OHLCV history SHA-256: `a694348596d8ccca2cc82bd7ed5d82844c452656cf12fabdcdb7b27333f6c671`.
- Full detailed record: [TV26_CLOUD_AUDIT_2026-10-24.md](TV26_CLOUD_AUDIT_2026-10-24.md).

These results establish that the recorded MT5 votes agree with an independent implementation of the published rules on the audited MT5 feed. They do **not** show that the live TradingView chart has identical values, and do not establish strategy profitability.

## Compiler and comparison pipeline checks

Both `TradingView_Parity_AllTF_Export.pine` and `TradingView_Parity_Components_1TF.pine` passed the TradingView compiler endpoint as part of CI. The 41-test Python suite includes the CSV splitter, repeated-higher-timeframe-row validation, timestamp handling, formula contract tests, and an end-to-end synthetic comparison across all five timeframes. Its negative test deliberately corrupts one M15 RSI14 vote and confirms that the comparator returns FAIL and identifies RSI14.

- [Latest parity CI and compiler gate — run 40083533515](https://github.com/staryuzar/-/actions/runs/40083533515)
- [Latest official MetaEditor compile — run 40083533537](https://github.com/staryuzar/-/actions/runs/40083533537)
- [Latest cloud MT5 audit — run 40083533466](https://github.com/staryuzar/-/actions/runs/40083533466)
- [Latest audit artifact — 12556177506](https://github.com/staryuzar/-/actions/runs/40083533466/artifacts/12556177506)

The synthetic end-to-end pass is a software integration test only. It cannot replace live chart data or Pine runtime output from the user’s TradingView chart.

## Remaining input: one TradingView export

1. Open XAUUSD on TradingView at M1 and add `TradingView_Parity_AllTF_Export.pine`.
2. Export chart data, preserving the raw CSV at full precision; use the 21–23 October 2026 window where available and select the closest available XAUUSD feed to Headway-Demo.
3. Commit the single file as `trading-lab/tv26/parity-input/TV26_AllTF.csv` on branch `tv26-five-timeframes-arabic-candidate`.

The workflow automatically triggers when that exact file is committed. It now searches recent successful cloud-audit runs and selects the newest one whose EA source, audit workflow, formula reference and validation scripts have the same Git blob IDs as the checked-out branch. It relies on exact Git blob IDs to prove the EA and audit scripts match the tested commit, verifies the downloaded audit CSV against its embedded SHA-256 digest, requires Strategy Tester exit code 0, and requires the explicit `InpEnableTrading=false` marker. The CSV digest is checked byte-for-byte; source identity is checked through Git objects, avoiding false mismatches caused by Windows/Linux line-ending conversion. A stale or altered artifact is rejected instead of being compared silently. For a manual run, `mt5_audit_run_id` is optional; leaving it blank enables automatic selection. The latest matching evidence before these new gates were added is run `40083533466`; the stricter workflow must pass its next CI run before its new guards are considered tested. Default MT5 server offset is UTC+3; confirm this against the broker’s actual server time before interpreting timestamps.

Do not use another symbol such as a futures contract or a composite gold index as a substitute for spot XAUUSD. Similar ticker labels do not guarantee identical OHLC bars. If prices do not agree, the diagnostics prioritize `PRICE_FEED_OR_CANDLE_ALIGNMENT` before recommending formula changes.

## Direct parity acceptance gates

Do not mark direct parity PASS until every timeframe has at least 10 common closed bars, the matched bars cover at least 80% of the MT5 audit bars for that timeframe, OHLC differs by no more than 0.01, all three aggregate ratings are within 0.0011, the Pine-reconstructed aggregates agree with the official TradingView library, and all 26 component votes match without missing values.

This stage must remain marked **PENDING** until the real `TV26_AllTF.csv` is supplied and the workflow produces actual results. Do not infer profitability from these parity checks or enable live trading based on them.
