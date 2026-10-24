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


## 7. Independent holdout result for the M1 breakout-buffer experiment

Workflow: https://github.com/staryuzar/-/actions/runs/40104572704

Both variants ran with the same source SHA, same OHLCV history hash, same MT5 model, and same 2026-09-11 through 2026-09-20 window. The formula/data audits passed for both variants, so this is a comparable strategy outcome rather than a data-integrity failure.

| Buffer | Net profit | Profit factor | Max equity DD | Trades | Wins / losses |
|---|---:|---:|---:|---:|---:|
| 0.00 ATR | -$11.41 | 0.43 | 3.39% | 6 | 1 / 5 |
| 0.10 ATR | -$20.19 | 0.00 | 4.04% | 5 | 0 / 5 |

The trade lists show why the candidate lost: the 0.10 ATR threshold removed the **2026-09-18 09:00 buy**, which was the sole winner (+$8.78), while leaving the other five outcomes unchanged, including all five losing outcomes. It did not prevent any loss in this holdout and reduced net performance by $8.78. **Decision: reject 0.10 ATR; keep 0.00 as the baseline pending further strategy research, not as a claim of profitability.**

The buffer-0.00 baseline's loss pattern was 4 losing sells (Sep 14 10:10; Sep 14 10:30; Sep 15 09:11; Sep 15 12:14) plus one losing buy (Sep 18 09:40), offset by the Sep 18 09:00 buy TP. This suggests direction/regime and entry timing need investigation; merely increasing the breakout threshold is not supported by the holdout.

## 8. Official TechnicalRating v3 source cross-check

The MQL5 oscillator rules were inspected against the pinned source snapshot of TradingView's TechnicalRating Pine library v3 (version dated 2024-11-29): https://github.com/Tealstreet/tealchart/blob/800dafe10ebb48b8eeba53a191460d011f40a6ca/packages/tealscript/src/officialTradingViewLibrarySources.ts (see calcRatingAll(), especially lines 663–665 for ADX). That source and the exported Pine benchmark use rising ADX for both +DI and -DI directional branches. TradingView's help page currently describes falling ADX for the sell branch, so the documentation and versioned library source are inconsistent. We retained the versioned TradingView/TechnicalRating/3 library rule rather than silently substituting the help-page wording. The source comparison is an implementation cross-check, not actual chart-export parity; direct parity still requires an actual TradingView CSV for the same symbol/feed and overlapping bars.


## 9. Follow-on investigation — breakout, threshold and re-entry hypotheses

These experiments were kept on separate research branches; none is merged into the candidate branch.

### M1 breakout lookback screening (Sep 14–18; diagnostic, not held out)

- 1 previous bar: -$11.41, PF 0.43, equity DD 3.39%, 6 trades (1 win / 5 losses).
- 3 previous bars: -$7.57, PF 0.54, DD 2.63%, 5 trades (1 / 4).
- 5 previous bars: +$0.82, PF 1.10, DD 1.12%, 3 trades (1 / 2).
- Report: https://github.com/staryuzar/-/blob/tv26-breakout-lookback-study/trading-lab/tv26/TV26_BREAKOUT_LOOKBACK_EXPERIMENT_2026-10-24.md
- Decision: five-bar breakout is a screening candidate only; 3 trades on the same diagnostic window used to investigate the failures is insufficient.

### Entry consensus strength screening (Sep 14–18; diagnostic, not held out)

- Minimum rating 0.50: -$11.41, PF 0.43, DD 3.39%, 6 trades (1 / 5).
- Minimum rating 0.55: +$1.08, PF 1.14, DD 0.90%, 3 trades (1 / 2).
- Minimum rating 0.60: $0.00, 0 trades. This is inconclusive, not a successful result.
- All variants compiled with zero errors/warnings and passed audit (235,300 votes, zero mismatches; clean exported OHLC integrity) on the same source-data hashes.
- Report: https://github.com/staryuzar/-/blob/tv26-consensus-threshold-study/trading-lab/tv26/TV26_CONSENSUS_THRESHOLD_EXPERIMENT_2026-10-24.md
- Decision: do not approve 0.55 based on this in-sample screen; 0.60 is rejected as a useful setting for this short period because it eliminates every trade.

### Post-exit cooldown screening (Sep 11–20)

- Cooldown 0 bars: -$11.41, PF 0.43, DD 3.39%, 6 trades (1 / 5).
- Cooldown 10 bars: same metrics, 6 trades; four cooldown blocks logged.
- Cooldown 20 bars: -$11.32, PF 0.44, DD 3.38%, same 6 trades; seven cooldown blocks.
- Report: https://github.com/staryuzar/-/blob/tv26-breakout-buffer-study/trading-lab/tv26/TV26_COOLDOWN_EXPERIMENT_2026-10-24.md
- Decision: reject cooldown as a performance fix for this sample; it blocked attempts but did not change the accepted trades in a meaningful way.

### Validation now in progress

- Independent parameter holdout on Sep 1–10, comparing baseline 1-bar/0.50, 5-bar/0.50, 1-bar/0.55, and combined 5-bar/0.55: https://github.com/staryuzar/-/actions/runs/40106562109. Baseline completed at +$3.35, PF 1.23, max equity DD 2.48%, 5 trades (2 wins / 3 losses); the audit checked 371,332 votes with zero mismatches and found no invalid/duplicate/timestamp OHLC issues. The 5-bar/0.50 variant has since completed with the exact same result and trade list as baseline: +$3.35, PF 1.23, DD 2.48%, 5 trades (2 / 3). Input verification confirms the 5-bar setting was applied, and both runs have the same audit/history SHA-256; it did not improve this holdout. The 1-bar/0.55 and 5-bar/0.55 variants were still running at the last check.
- Separate oscillator-agreement holdout on Sep 1–10, comparing no extra oscillator gate with a directional oscillator average minimum of 0.15 on each timeframe: https://github.com/staryuzar/-/actions/runs/40106767960
- The oscillator gate is on a separate research branch and defaults to disabled; it cannot change the existing candidate unless its explicit input is enabled.
- These two holdouts use the same Headway-Demo XAUUSD feed and model 4 tester settings. MT5 may synthesize ticks for gaps in broker real-tick history. They can check reproducibility and whether an entry hypothesis transfers to a different window; they cannot by themselves prove future profitability.


The Sep 1–10 baseline trade list also revealed one immediate re-entry: a sell TP closed on 2026-09-08 at 22:58:59, then another sell opened at 22:59:00 and hit SL at 23:01:22 (-$5.08). This is a specific post-exit re-entry hypothesis, not proof that a cooldown is broadly beneficial; the separate Sep 11–20 test showed 10/20-bar cooldowns did not materially change accepted trades there. Any one-bar pause should be tested across a new period before adoption.


### Oscillator-filter trial infrastructure issue and retry

The first Sep 1–10 trial with `InpMinDirectionalOscillatorRating=0.15` did not produce a valid backtest: MT5 canceled preliminary real-tick history download and logged `no history data, stop testing`. Although MetaEditor compiled the EA with zero errors/warnings, no trades or performance metrics may be inferred from this run. This was an infrastructure failure, not a strategy loss. The workflow was updated to preserve the failed attempt diagnostics and retry once, only when that specific tick-history cancellation is detected. Retry run: https://github.com/staryuzar/-/actions/runs/40107875721. The original 0.00 baseline remains +$3.35 / PF 1.23 / DD 2.48% / 5 trades; no conclusion about the 0.15 filter is valid until a complete comparable tester export and audit exist.


The 1-bar / threshold 0.55 holdout completed with zero trades. Its summary recorded six consensus-signal bars, four blocked by the minimum-lot risk cap and two blocked by M1 close-breakout confirmation; accepted orders = 0. The broker minimum 0.01 lot would exceed the nominal $5 risk budget at 1% for those signals ($5.15–$11.01 minimum-volume loss). This is an inconclusive no-trade result, not success. The risk cap was intentionally retained.


## 10. Independent September holdout update — 2026-10-24

Workflow: https://github.com/staryuzar/-/actions/runs/40106562109

The completed jobs so far use the same Sep 1–10 window, XAUUSD M1, MT5 Model 4, 1% risk, 2 ATR stop, 4 ATR target, and identical audited OHLCV hash. The remaining combined 5-bar/0.55 job was still running when this update was written.

| Variant | Net profit | Profit factor | Max equity DD | Trades | Wins / losses | Decision |
|---|---:|---:|---:|---:|---:|---|
| Baseline: 1-bar breakout, 0.50 rating | +$3.35 | 1.23 | 2.48% | 5 | 2 / 3 | Reference only; too few trades |
| 5-bar breakout, 0.50 rating | +$3.35 | 1.23 | 2.48% | 5 | 2 / 3 | No improvement; same outcomes and trade list |
| 1-bar breakout, 0.55 rating | $0.00 | 0.00 | 0.00% | 0 | 0 / 0 | Inconclusive; do not call it a pass |

For the 5-bar variant, input verification confirms that the five-bar setting was applied, while audit and OHLCV history hashes match the baseline. It did not improve the accepted trades. The 0.55 threshold generated only six consensus signal bars and four minimum-volume risk-cap blocks, but no accepted orders. The $5 risk budget at 1% of the $500 balance remains a valid protection; do not weaken it merely to create trades.

The baseline's five trades comprised three losses and two wins. One specific failure was an immediate sell re-entry one second after a sell TP on 2026-09-08 22:58:59, followed by an SL at 23:01:22 (-$5.08). This is a concrete timing hypothesis, but a single case does not establish that a one-bar pause generalizes. The separate 10/20-bar cooldown experiment on Sep 11–20 did not materially change accepted trades. Any new re-entry rule must be compared with the unchanged baseline on a separate window, with trade count and lost winners explicitly reported.

The oscillator-confirmation retry is tracked separately at https://github.com/staryuzar/-/actions/runs/40107875721. Its earlier 0.15 attempt failed before a valid tester export due to canceled MT5 history download, so no performance conclusion is valid until the retry completes with a complete audit. Formula-level audit PASS continues to mean consistency with the independent published-formula implementation on MT5 data; actual live TradingView chart-runtime parity remains pending.


## 11. Completed oscillator-confirmation diagnostic — Sep 1–10

Retry workflow completed successfully: https://github.com/staryuzar/-/actions/runs/40107875721

| Variant | Net profit | Profit factor | Max equity DD | Trades | Wins / losses |
|---|---:|---:|---:|---:|---:|
| Oscillator gate disabled (0.00) | +$3.35 | 1.23 | 2.48% | 5 | 2 / 3 |
| Minimum directional oscillator rating 0.15 on every timeframe | +$3.93 | 1.77 | 1.54% | 2 | 1 / 1 |

The 0.15 variant compiled with zero errors/warnings, completed the real-tick tester, and passed the formula/data audit: 371,332 votes, zero mismatches, no missing comparisons, and no OHLC integrity failures. The bounded retry recovered from the prior canceled history-download attempt; the earlier failed run was infrastructure-only and is not counted as a strategy outcome.

Interpretation: on this short diagnostic window, the gate changed the trade list and produced +$0.58 more net profit with lower equity drawdown. It also removed three of five trades, including one winner and two losers. Only two accepted trades remain, one win and one loss; the result is **promising enough to test again, not enough to approve**. Treat this as an in-sample screening result because this September window was already being used to investigate the baseline. A cross-window replication with the same 0.00 vs 0.15 settings is required before retaining the filter. The gate remains disabled by default in the candidate.

## 12. Completed consensus/lookback holdout — full matrix result

Workflow: https://github.com/staryuzar/-/actions/runs/40106562109

The final 5-bar / 0.55 job completed with the following result:

| Variant | Net profit | Profit factor | Max equity DD | Trades | Wins / losses |
|---|---:|---:|---:|---:|---:|
| 1-bar breakout / 0.50 baseline | +$3.35 | 1.23 | 2.48% | 5 | 2 / 3 |
| 5-bar breakout / 0.50 | +$3.35 | 1.23 | 2.48% | 5 | 2 / 3 |
| 1-bar breakout / 0.55 | $0.00 | 0.00 | 0.00% | 0 | 0 / 0 |
| 5-bar breakout / 0.55 | $0.00 | 0.00 | 0.00% | 0 | 0 / 0 |

The 5-bar / 0.50 variant used the configured input but produced the same five accepted entries and same deal list as baseline; it reduced the minimum-volume blocks from 27 to 15 without improving outcomes. Both 0.55 variants produced zero accepted orders. Decision: reject these settings as performance improvements. The baseline remains a reference for comparisons only, not a production pass.
