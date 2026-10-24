# TV26 direct parity — current status (24 October 2026)

## Latest gates

| Gate | Status | Evidence |
|---|---|---|
| Versioned Pine library references and source-level contract | PASS | [Exact v3 contract test](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/tests/test_exact_technicalrating_v3_contract.py) |
| Pine exporters accepted by TradingView compiler | PASS | [CI run 40092639470](https://github.com/staryuzar/-/actions/runs/40092639470) |
| Python comparator/splitter/regression suite | PASS — 50 tests | [CI run 40092639470](https://github.com/staryuzar/-/actions/runs/40092639470) |
| Official MetaEditor compile | PASS | [Run 40092639481](https://github.com/staryuzar/-/actions/runs/40092639481) |
| New cloud MT5 indicator audit after the tests were added | PENDING while workflow runs | [Run 40092639444](https://github.com/staryuzar/-/actions/runs/40092639444) |
| Previous independent formula reference versus MT5 votes | PASS on recorded MT5 OHLCV feed | 141,232 component votes; zero mismatches in [prior audit run 40091850456](https://github.com/staryuzar/-/actions/runs/40091850456) |
| Actual TradingView chart-runtime values versus MT5 | **PENDING** | No real TradingView chart-output CSV has been compared |
| EA profitability / robustness | **NOT ESTABLISHED by parity tests** | Separate controlled Strategy Tester evidence is required |

## New source reconciliation

The exact source reconciliation is documented in [TV26_V3_SOURCE_RECONCILIATION_2026-10-24.md](TV26_V3_SOURCE_RECONCILIATION_2026-10-24.md).

Two key clarifications are pinned in regression tests:
- TechnicalRating v3 source uses rising ADX for both the buy and sell branches. This differs from the current Help Center wording for sell ADX. The candidate follows the explicitly versioned v3 library it imports.
- TechnicalRating v3 calculates Bulls/Bears Power from EMA(close, 13); the candidate uses period 13.

This means the source-level contract and same-feed independent vote checks are in good shape. They do not, by themselves, establish numerical equality on a separate TradingView chart with a different provider or candle feed.

## Latest known MT5 audit scope

The previous successful audit covered 21–23 October 2026, XAUUSD on Headway-Demo/Jarocel, with trading disabled. It contained 146,664 data rows, 5,432 candle groups and 141,232 component votes. Aggregate arithmetic checks and the independent formula-level vote check passed; the Ichimoku raw-value and 26-bar alignment check covered 27,160 values with zero mismatches. See [TV26_CLOUD_AUDIT_2026-10-24.md](TV26_CLOUD_AUDIT_2026-10-24.md).

A newer cloud audit is running for the latest test commit. Do not call it passed until its actual conclusion and logs are checked:
https://github.com/staryuzar/-/actions/runs/40092639444

## Important boundary

The repository's Pine diagnostic exporter compares the reconstructed aggregates against TradingView's versioned library outputs and can emit one payload covering M1/M5/M15/M30/H1. The Python comparator is tested synthetically and fails when a component is corrupted. However, a synthetic test is not a real TradingView chart sample, and Pine compilation is not a runtime-value comparison.

No unofficial WebSocket/scraping feed was added. TradingView's current policies restrict machine-driven/non-display processing of its market data for algorithmic decisions. Use the versioned published formula source and MT5's own market history for automated computation; do not treat unauthorized scraping as a way to certify TradingView parity.

## Decision

- **Source-level formula contract:** PASS.
- **Pine compiler and 50 deterministic tests:** PASS.
- **Same-feed MT5 formula checks:** previously PASS, 141,232/141,232 votes.
- **New MT5 cloud audit:** PENDING until run 40092639444 finishes.
- **Direct numerical parity with an actual TradingView chart:** PENDING.
- **Live trading approval:** NOT GRANTED by these checks.
