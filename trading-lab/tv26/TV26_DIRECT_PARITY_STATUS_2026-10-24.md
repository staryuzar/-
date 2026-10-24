# TV26 direct parity — current status (24 October 2026)

## Latest gates

| Gate | Status | Evidence |
|---|---|---|
| Versioned Pine library references and source-level contract | PASS | [Exact v3 contract test](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/tests/test_exact_technicalrating_v3_contract.py) |
| Pine exporters accepted by TradingView compiler | PASS | [CI run 40093365780](https://github.com/staryuzar/-/actions/runs/40093365780) |
| Python comparator/splitter/regression suite | PASS — 53 tests | [CI run 40093365780](https://github.com/staryuzar/-/actions/runs/40093365780) |
| Official MetaEditor compile | PASS | [Run 40093365794](https://github.com/staryuzar/-/actions/runs/40093365794) |
| Cloud MT5 indicator audit on the tested source commit | PASS | [Run 40093365818](https://github.com/staryuzar/-/actions/runs/40093365818); [artifact 12560305327](https://github.com/staryuzar/-/actions/runs/40093365818/artifacts/12560305327) |
| Independent formula reference versus MT5 votes | PASS on recorded MT5 OHLCV feed | 141,232 component votes; zero mismatches |
| Actual TradingView chart-runtime values versus MT5 | **PENDING** | No real TradingView chart-output CSV has been compared |
| EA profitability / robustness | **NOT ESTABLISHED by parity tests** | Separate controlled Strategy Tester evidence is required |

## Source reconciliation

The exact source reconciliation is documented in [TV26_V3_SOURCE_RECONCILIATION_2026-10-24.md](TV26_V3_SOURCE_RECONCILIATION_2026-10-24.md).

Two key clarifications are pinned in regression tests:
- TechnicalRating v3 source uses rising ADX for both the buy and sell branches. This differs from current Help Center wording for sell ADX. The candidate follows the explicitly versioned v3 library it imports.
- TechnicalRating v3 calculates Bulls/Bears Power from EMA(close, 13); the candidate uses period 13.

This means the source-level contract and same-feed independent vote checks are in good shape. They do not, by themselves, establish numerical equality on a separate TradingView chart with a different provider or candle feed.

## Latest MT5 audit evidence

The cloud audit ran from 21–23 October 2026 for XAUUSD on Headway-Demo/Jarocel with trading disabled. Exact latest source-matched results from run 40093365818:
- 5,432 candle groups across M1/M5/M15/M30/H1; every summary row complete.
- 141,232 component votes checked; zero mismatches and zero missing/invalid values against the independent published-formula implementation.
- 16,296 summary aggregate values recalculated; zero arithmetic mismatches.
- 27,160 Ichimoku raw values/offset checks; zero mismatches.
- Audit CSV SHA-256: e92d178246b76d463f366a5057729d5a73abe5d67b2ee6f56278a0fd508593b2.
- OHLCV history SHA-256: a694348596d8ccca2cc82bd7ed5d82844c452656cf12fabdcdb7b27333f6c671.
- [Download the current MT5 cloud audit artifact](https://github.com/staryuzar/-/actions/runs/40093365818/artifacts/12560305327)

These results establish the formula-level match on the audited MT5 feed. They do not prove the live TradingView chart has identical values or establish strategy profitability.

## Important boundary

The repository's Pine diagnostic exporter compares the reconstructed aggregates against TradingView's versioned library outputs and can emit one payload covering M1/M5/M15/M30/H1. The Python comparator is tested synthetically and fails when a component is corrupted. However, a synthetic test is not a real TradingView chart sample, and Pine compilation is not a runtime-value comparison.

No unofficial WebSocket/scraping feed was added. TradingView's current policies restrict machine-driven/non-display processing of its market data for algorithmic decisions. The automated EA should use the versioned published formula source with MT5's own market history, not an unauthorized TradingView data feed.

## Decision

- **Source-level formula contract:** PASS.
- **Pine compiler and 53 deterministic tests:** PASS.
- **Same-feed MT5 formula checks:** PASS, 141,232/141,232 votes.
- **MT5 audit and Ichimoku checks:** PASS.
- **Direct numerical parity with an actual TradingView chart:** PENDING.
- **Live trading approval:** NOT GRANTED by these checks.

## Evidence refresh — 2026-10-24 12:21 UTC

This addendum supersedes the earlier run IDs above where a newer source-matched run is listed.

- Candidate **code commit tested**: `d948bcc89cf6f31796741f31c14d9b53e4f8127d` (the latest branch tip now also contains this report update).
- Comparator/regression suite: [run 40093365780](https://github.com/staryuzar/-/actions/runs/40093365780) — **53 tests passed**.
- MetaEditor package build: [run 40093365794](https://github.com/staryuzar/-/actions/runs/40093365794) — PASS; package version 1.009, EX5 generated (67,422 bytes), uploaded build artifact 12559558694.
- Source-matched cloud MT5 audit: [run 40093365818](https://github.com/staryuzar/-/actions/runs/40093365818) — PASS; [artifact 12560305327](https://github.com/staryuzar/-/actions/runs/40093365818/artifacts/12560305327).
- Latest MT5 audit source SHA-256: `150263920e66781660aa5c01c81272fb39b510fee5428181ff8abc7020f21f55`.
- Audit CSV SHA-256: `e92d178246b76d463f366a5057729d5a73abe5d67b2ee6f56278a0fd508593b2`; OHLCV reference SHA-256: `a694348596d8ccca2cc82bd7ed5d82844c452656cf12fabdcdb7b27333f6c671`.
- Validated output: 146,664 data rows; 5,432 complete candle groups; 141,232 component votes; 16,296 recalculated summary aggregates; zero aggregate mismatches; zero independent formula-vote mismatches; 27,160 raw Ichimoku values checked with zero mismatches. All five frames M1/M5/M15/M30/H1 passed.
- Tester exit code was 0, and the audit explicitly ran with automated trading disabled.

### Current decision — unchanged for direct parity

The new run confirms the audited candidate source and internal formulas on the recorded MT5 feed. It does **not** remove the only external-data blocker: `trading-lab/tv26/parity-input/TV26_AllTF.csv` is not present until an actual TradingView chart export is supplied. Pine compiler acceptance, local synthetic regression tests, and MT5-feed agreement cannot substitute for chart-runtime output from TradingView.

The prepared one-file export script is `trading-lab/tv26/TradingView_Parity_AllTF_Export.pine`; the exact export procedure is in `trading-lab/tv26/DIRECT_TRADINGVIEW_PARITY_GUIDE_AR.md`. Once that real CSV exists at the specified path, the direct comparison workflow will compare all 26 votes plus summary ratings on M1/M5/M15/M30/H1, with strict source matching and candle-alignment gates. No live-trading approval follows from this audit.
