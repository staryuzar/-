# TV26 — Follow-up validation and gate corrections (2026-10-24)

## Scope and safety
All results below are isolated MT5 Strategy Tester simulations on XAUUSD M1, using Headway-Demo/Jarocel data and Model 4 (Every tick based on real ticks). The broker/terminal may synthesize ticks where real-tick history is absent. Tester-only and demo guards were enabled. These results are not live trading and do not establish future profitability.

## 1. Completed 2026-10-01 through 2026-10-23 parameter matrix

| Risk | Stop | Target | Net profit | Profit factor | Max equity DD | Trades | Wins | Losses |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.00% | 2.0 ATR | 2.5 ATR | -$9.14 | 0.82 | 5.46% | 22 | 8 | 14 |
| 1.00% | 2.0 ATR | 4.0 ATR | +$12.51 | 1.27 | 4.77% | 20 | 7 | 13 |
| 1.00% | 1.5 ATR | 3.0 ATR | -$45.83 | 0.39 | 13.26% | 24 | 4 | 20 |
| 0.50% | 2.0 ATR | 3.0 ATR | +$3.67 | 1.41 | 0.79% | 8 | 4 | 4 |

Interpretation:
- The 2 ATR stop / 4 ATR target variant is the strongest result by net profit on this particular 23-day sample, but 20 trades is still a small sample and PF 1.27 is not a deployment pass.
- The 0.5% risk result has lower drawdown but only eight trades; it is not enough evidence to claim a robust edge.
- The 1.5 ATR stop / 3 ATR target variant is rejected on this sample.
- A target of 2.5 ATR under the 1% risk setting lost money; do not choose it based on a desire for more frequent target hits.

## 2. One-day screening result and correction
The 2026-10-23 single-day run produced **zero trades** (zero profit, zero loss, zero drawdown; two all-timeframe consensus signal bars and one minimum-volume risk-cap block). Zero trades must not be counted as a “no-loss pass”.

The first version of the conditional workflow incorrectly extended this zero-trade day to 2026-10-21 through 2026-10-23. That three-day run recorded one trade, +$7.48, and zero losses. One trade is insufficient evidence; the profit factor is not meaningful when there are no losing trades. The run's overall job also reported failure during expanded audit validation due Windows console encoding / audit reporting, not because of a detected vote mismatch.

The workflow gate has been corrected to extend only if **at least one trade and zero losing trades** occur. Zero trades now produce an inconclusive/stop-and-diagnose outcome. Python audit output is forced to UTF-8 to prevent Arabic report text from failing under the Windows console code page.

## 3. Indicator formula/data checks
On the 2026-10-23 single-day run:
- 47,164 component votes compared against an independent implementation of the published TradingView TechnicalRating v3 rules.
- Zero vote mismatches; zero missing/invalid comparisons.
- 5,442 aggregate summary values re-calculated; zero aggregate mismatches.
- 1,814 OHLC candles checked; zero invalid rows, duplicate rows, timestamp errors, or incomplete timeframe groups.
- Five overlapping reference bars matched OHLC exactly.

This verifies the exported MT5 vote calculations against the independent reference formulas on the tested feed. It does **not** prove numerical parity with a live TradingView chart/runtime, because a direct comparison of actual TradingView-exported outputs on the same symbol/feed/session is still required. It does not prove profitability.

## 4. Next controlled experiment
The follow-up one-day workflow is now configured to test 2026-10-22 with the currently best-performing candidate settings (1% risk, 2 ATR stop, 4 ATR target, M1 close-breakout enabled). If it produces at least one trade and zero losing trades, it extends to 2026-10-20 through 2026-10-22. If it produces a loss, stop and diagnose; if it produces zero trades, treat as inconclusive and inspect signal/entry blockers.

Do not merge this candidate into main or use it for live trading on the strength of these preliminary results.


## 5. Fresh one-day gate and conditional three-day retest (run 40104226409)

Workflow: https://github.com/staryuzar/-/actions/runs/40104226409

The revised gate behaved as intended:
- **2026-10-22 one-day screen:** +$10.60, 1 trade, 1 win / 0 losses, max equity drawdown 0.74%. One trade is still not statistically meaningful; PF is shown as 0.00 by MT5 because there were no losing trades.
- **2026-10-20 through 2026-10-22 conditional extension:** +$2.74, PF 1.40, max equity drawdown 1.72%, 3 trades, 1 win / 2 losses. This is mixed evidence and not a pass.
- **One-day formula audit:** 47,164 component votes, zero vote mismatches; 1,814 OHLC candles checked with zero invalid/duplicate/timestamp errors.
- **Expanded formula audit:** 141,232 component votes, zero vote mismatches; 5,432 OHLC candles checked with zero invalid/duplicate/timestamp errors.

The expanded HTML trade table attributes both losing trades to sell entries on 2026-10-20: entry 11:08, SL exit at 11:11:38 (-$3.81), then re-entry 11:30, SL exit at 11:32:19 (-$3.07). The later sell on 2026-10-22 reached its 4 ATR target (+$9.62). This points to a possible repeated-entry/choppy-market loss cluster, but two losses are too few to establish that a cooldown fixes the problem. A cooldown variant should be tested against the unchanged baseline on a separate date window; it must not simply be selected because it suppresses trades.

The logs also document minimum-volume risk-cap blocks when the broker's 0.01 lot would exceed the $5 risk budget at 1% risk on the $500 test balance. Keep this protection intact.

## 6. ATR-scaled breakout-buffer matrix (separate branch; run 40102196337)

Workflow and artifacts: https://github.com/staryuzar/-/actions/runs/40102196337

Using the 2026-10-01 through 2026-10-23 sample, risk 1%, SL 2 ATR, TP 4 ATR, and M1 close-breakout enabled:
- 0.00 ATR buffer: +$12.51; PF 1.27; max equity DD 4.77%; 20 trades (7 wins / 13 losses).
- 0.05 ATR buffer: identical metrics to 0.00 ATR; the added distance did not change outcomes.
- 0.10 ATR buffer: +$19.92; PF 1.47; max equity DD 4.54%; 19 trades (7 wins / 12 losses).
- 0.20 ATR buffer: +$18.94; PF 1.45; max equity DD 4.54%; 19 trades (7 wins / 12 losses).

All four matrix variants passed their exported-data and formula-level audits. These are in-sample results and have not been merged into the main candidate; 0.10 ATR is only the provisional holdout candidate. An independent-window comparison of 0.00 vs 0.10 ATR is being run on 2026-09-11 through 2026-09-20. A successful technical audit is not a profitability pass, and a better in-sample net profit is not enough to select a production setting.
