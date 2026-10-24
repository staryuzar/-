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


## Source-level discrepancies found during the latest audit

A source-to-document comparison found two descriptions that should not be treated as the implementation contract when the target is the live TechnicalRating v3 library:

1. The Help Center describes the ADX sell rule as requiring ADX to fall versus the prior bar ([TradingView Help Center](https://www.tradingview.com/support/solutions/43000614331-technical-ratings/), ADX section). The pinned public source snapshot used by the Pine dashboard requires `adx > adx[1]` for **both** bullish and bearish ADX cases. TV26 currently follows that library-source expression in MQL5 and in the Pine formula-side diagnostic.
2. The library page's prose lists Bull Bear Power with “a period of 50”, while the Help Center says 13. The pinned source snapshot calculates bull/bear power with EMA(13) and applies a separate EMA(50) trend gate. TV26 follows that split: BBP values from EMA(13), trend direction from EMA(50).

Reference snapshot (third-party public mirror, pinned commit): https://github.com/Tealstreet/tealchart/blob/800dafe10ebb48b8eeba53a191460d011f40a6ca/packages/tealscript/src/officialTradingViewLibrarySources.ts (TechnicalRating source begins near line 568). The Pine visual dashboard also directly calls `TradingView/TechnicalRating/3` and shows library aggregate ratings beside formula-recalculated aggregates, so it can expose a source-level difference on chart without exporting market data.

This resolves which formula contract the candidate is intentionally reproducing; it does **not** prove same-bar numeric parity with the user's live TradingView symbol/feed. That still needs manual comparison of closed-bar timestamp, OHLC, total rating, MA rating, oscillator rating, and component votes on the on-chart display.
