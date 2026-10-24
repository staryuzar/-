# TV26 direct TradingView parity — current state (24 October 2026)

## Verified

| Check | State | Evidence |
|---|---|---|
| Published TechnicalRating v3 formula/source contract | PASS | Version-pinned Pine reference and regression tests |
| Pine visual dashboard compile | PASS | [Earlier compiler/regression run](https://github.com/staryuzar/-/actions/runs/40096465363) |
| MetaEditor build of candidate | PASS | [Run 40117459680](https://github.com/staryuzar/-/actions/runs/40117459680) |
| Independent formula checks against recorded MT5 feed | PASS for audited feed | Latest completed audit checked 141,232 component votes with zero mismatches; this is not a live TradingView sample |
| Real-time chart value match between MT5 and a separate TradingView chart | **PENDING manual visual comparison** | No matching-bar visual review has been recorded |
| EA profitability/robustness | **NOT ESTABLISHED** | [Three-day progressive run](https://github.com/staryuzar/-/actions/runs/40115334971) stopped at +$2.74 versus required +$7.50 |

## Safe verification workflow

The automated TradingView CSV-export/processing workflow has been retired. This is deliberate: TradingView's current market-data policy restricts non-display processing. Do not export chart prices/ratings into CSV for automated GitHub processing, do not scrape TradingView, and do not feed TradingView data to an EA.

The remaining supported visual route:
- Pine dashboard: [TradingView_Visual_Parity_5TF.pine](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TradingView_Visual_Parity_5TF.pine)
- Arabic instructions: [TV26_VISUAL_PARITY_GUIDE_AR.md](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TV26_VISUAL_PARITY_GUIDE_AR.md)
- Official policy: https://www.tradingview.com/policies/
- Official Technical Ratings definition: https://www.tradingview.com/support/solutions/43000614331-technical-ratings/

Compare the closed-bar timestamp first, then O/H/L/C, then the official total/MA/oscillator ratings and 26 component votes by eye. If timestamps or OHLC differ, the chart/feed is not aligned and an indicator-formula mismatch is not established. The MT5 audit is from Headway-Demo/Jarocel; using a different XAUUSD source on TradingView can naturally produce different bars.

## Historical CSV tools

TradingView_Parity_AllTF_Export.pine, TradingView_Parity_Components_1TF.pine, the CSV decoder, and the CSV comparator are retained as legacy formula-contract and synthetic-test references. The Pine export scripts are visibly marked legacy; the automated direct TradingView data-processing workflow is now only a display-only guard with manual dispatch and no CSV processing step. Do not use the legacy scripts to export real TradingView market data.

## Decision

- Source-level formula contract and same-feed MT5 formula checks: PASS on the recorded input.
- Direct per-bar comparison against an actual TradingView chart: pending until a human checks matching timestamps/OHLC and visible values.
- Strategy robustness: not established; the three-day gate failed.
- No live-use or main-branch merge approval follows from these checks.


## Follow-up: MACD formula discrepancy in the visual dashboard

Audit found that the display-only formula reconstruction in `TradingView_Visual_Parity_5TF.pine` added a histogram-sign condition to its MACD vote:

- Old dashboard formula: `macdLine > macdSignal and macdHist > 0` / `macdLine < macdSignal and macdHist < 0`.
- Pinned TechnicalRating v3 source at lines 670–672 compares only `macd > signal` / `macd < signal`; it does not add a histogram-sign condition.
- Corrected formula in commit [`fe8cea60`](https://github.com/staryuzar/-/commit/fe8cea60a6188354878d088b93c569152f4462c8): `float rMacd = f_calcRating(macdSignal, macdLine > macdSignal, macdLine < macdSignal)`.
- Added regression assertion in [`e33917a8`](https://github.com/staryuzar/-/commit/e33917a8c175b410652acad5aaa1aa532d074854). The first CI run then surfaced a separate stale contract assertion expecting a 0.50% risk default while the candidate's source default is 1.00%. The test was corrected to expect `InpRiskPercent=1.00` while retaining the hard `InpRiskPercent>2.0` safety-ceiling assertion in [`f9738c7c`](https://github.com/staryuzar/-/commit/f9738c7cd5650d13f313ae2da5b36012a5078157).

Verification:
- [Parity/comparator tests on `f9738c7c`](https://github.com/staryuzar/-/actions/runs/40141782024): passed, including the pinned Pine linter, TradingView compiler endpoint validation, Python syntax checks and deterministic formula tests.
- Official MetaEditor compile on the MACD-corrected candidate commit [run 40141707334](https://github.com/staryuzar/-/actions/runs/40141707334): success. The current source still uses the same MQL5 version; the MACD correction was in the diagnostic dashboard, not a change to the EA's order logic.
- The dedicated tester audit is tracked in [run 40141714585](https://github.com/staryuzar/-/actions/runs/40141714585); do not record its result before it completes.

This closes a false discrepancy in the **formula-side Pine dashboard**. It does not prove live same-bar parity with the user's TradingView chart. Actual per-bar comparison remains pending against the same ticker/feed, closed-candle timestamp and OHLC, and the official library values shown by the dashboard.
