# TV26 source reconciliation — 24 October 2026

## Purpose and boundary

This is a source-level reconciliation of the EA, Pine diagnostic exporter, and an independent Python implementation against the versioned TradingView TechnicalRating library. It is not a claim that chart values have been compared against a real TradingView chart export.

Primary references:
- TradingView TechnicalRating library: https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/
- Public source snapshot of the v3 implementation (version comment: 2024-11-29): https://github.com/Tealstreet/tealchart/blob/800dafe10ebb48b8eeba53a191460d011f40a6ca/packages/tealscript/src/officialTradingViewLibrarySources.ts
- TradingView help page: https://www.tradingview.com/support/solutions/43000614331-technical-ratings/
- Current TradingView policies: https://www.tradingview.com/policies/

## Findings that affect the formulas

| Item | Versioned TechnicalRating v3 implementation | TV26 candidate | Decision |
|---|---|---|---|
| ADX sell vote | ADX must be above 20 and rising; DI− must exceed DI+ | Same rule in Pine, MQL5, and Python reference | Keep. The Help Center page describes falling ADX for sell, so it conflicts with the versioned v3 code. For this project the explicitly imported library version is the specification. |
| Bulls/Bears Power | EMA(close, 13) for both power series | MQL5 iBullsPower/iBearsPower period 13; Pine/Python use EMA 13 | Keep period 13. Do not substitute the different high-level description without evidence from the actual library implementation. |
| Ichimoku | Senkou spans are read at [26], while Tenkan, Kijun and close conditions use the current evaluated bar | Pine uses the source expression; MQL5 uses its corrected buffer mapping | Previous cloud audit checked 27,160 raw values/alignment with zero mismatches on the recorded MT5 feed. |
| MACD | MACD line vs signal together with histogram sign | Pine uses both checks; source line/signal ordering and closed-bar shift are contract-tested | Keep the dual condition; do not simplify without preserving the same histogram rule. |
| Summary aggregation | Library returns total, oscillator, MA ratings in that order | Exporter explicitly emits total, MA, oscillator and checks reconstructed values against the library values | Keep output ordering; comparator checks the three fields separately. |
| Candle timing | Ratings are evaluated on confirmed, completed bars for the requested timeframe | Exporter shifts all payload fields and timestamps together; five timeframe requests are pinned by tests | Keep the shift; it prevents comparing an MT5 closed candle against a forming TradingView candle. |

The formula specification is 15 moving-average/filters plus 11 oscillators. Current candidate and formula reference retain all 26 component names and the five frames M1/M5/M15/M30/H1.

## Verification performed in this change

- New regression suite: trading-lab/tv26/tests/test_exact_technicalrating_v3_contract.py. It pins the ADX rule, BBP period, five timeframe requests, closed-bar timestamp shift, and checks against the library-returned aggregate ratings.
- Python/CSV comparator tests plus Pine compiler validation: PASS, 50 tests. Run: https://github.com/staryuzar/-/actions/runs/40092639470
- Official MetaEditor candidate compile: PASS. Run: https://github.com/staryuzar/-/actions/runs/40092639481
- A fresh cloud MT5 indicator audit was started after the regression tests were added; result must be read from run https://github.com/staryuzar/-/actions/runs/40092639444 before marking that new audit as passed.
- Previous successful formula audit checked 141,232 component votes on the recorded MT5 OHLCV feed with zero vote mismatches. This establishes agreement of the candidate with an independent implementation of the published expressions on that feed, not chart-runtime equality with TradingView.

## Remaining gap — do not overstate parity

Actual TradingView chart-runtime values have not been compared to this EA: the repository still has no real TV26_AllTF.csv chart output. Pine compilation confirms syntax, not runtime values. A synthetic CSV pass confirms the comparator, not the real indicator values.

We deliberately did not substitute an unofficial WebSocket/scraping feed. TradingView's current policies restrict machine-driven/non-display processing of platform market data for algorithmic decision-making; this is not a suitable way to obtain a hidden feed for the EA. The technically sound work completed here is based on the public, versioned formula expressions and the user's broker's own MT5 history. If a direct chart-runtime comparison is conducted under the applicable TradingView terms, it must be clearly distinguished from this source-level audit.

## Acceptance

- Source-level formula contract: PASS.
- Pine compiler and deterministic comparator suite: PASS.
- Previous same-feed MT5 formula parity: PASS (141,232/141,232 votes).
- New MT5 audit for the current commit: PENDING until run 40092639444 finishes.
- Direct actual TradingView chart-runtime parity: PENDING.
- Profitability: not established by any indicator-parity result.
