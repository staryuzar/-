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


## 13. Trade-list inspection and cross-experiment interpretation

### What the oscillator gate actually changed

The trade-by-trade HTML reports show that the September 1–10 oscillator-gate variant at 0.15 retained only the two September 8 sells: the 22:20 sell TP (+$9.01) and the 22:59 sell SL (-$5.08). Relative to the five-trade baseline, it removed:
- September 7 sell SL (-$5.17),
- September 10 buy SL (-$4.40),
- September 10 sell TP (+$8.99).

So the gate excluded two losses and one near-$9 winner, while retaining the immediate same-direction re-entry loss. Its net improvement was only $0.58. This makes it a weak screening lead, not an identified solution to the re-entry problem.

### M15 buy-rating gate: no transfer observed in the tested holdout

The M15 buy-only rating gate at 0.58 improved the October 1–23 training result from +$19.92 / PF 1.47 / 19 trades to +$30.67 / PF 1.98 / 16 trades (7 wins / 9 losses). However, on September 11–20, the 0.50 baseline and 0.58 gate had the same result: -$20.19, five trades, all five losses. This holdout did not establish an improvement. Do not promote the gate from the in-sample profit increase.

### Sell-only directional check

- October 1–10: allowing buys and sells produced -$6.57, PF 0.78, 12 trades (4 wins / 8 losses); sell-only produced +$0.79, PF 1.04, 10 trades (4 / 6).
- October 14–23: allowing buys and sells produced -$1.40, PF 0.93, 9 trades (3 / 6); sell-only produced +$3.26, PF 1.31, 5 trades (2 / 3).

Although the sell-only subset did better on both short windows, it reduces trade opportunities and has not been validated across a clean independent market regime. It is a diagnostic, not approval to permanently disable buys.

### Next immediate test — post-exit cooldown around the October 20–22 loss cluster

Workflow: https://github.com/staryuzar/-/actions/runs/40109199896

The three-day base result was +$2.74 / PF 1.40 / max equity DD 1.72% on three trades (one win, two losses). The diagnostic matrix fixes risk at 1%, stop at 2 ATR, target at 4 ATR, M1 close breakout on, and compares cooldowns of 0, 10, and 20 M1 bars on the same three dates. This is intentionally a diagnostic because the suspected cluster was observed on these dates. Any favourable outcome must then be replicated on a separate window; a lower trade count alone is not considered improvement.


## 14. Signal-latch state fix prepared for isolated validation

Source inspection found a direct state-machine concern in the current candidate: the neutral-signal branch calls RememberSignal(0) before checking whether this EA still has an open position. Thus, a neutral period during a position can erase the last executed direction and re-arm a same-side entry. This is consistent with the logged Sep 8 sell TP at 22:58:59 followed by a new sell at 22:59:00, but the exact preceding neutral bar was not logged in the old build, so the causal path remains a testable hypothesis rather than a proven explanation.

A research-only change has been committed on the separate branch:
https://github.com/staryuzar/-/blob/tv26-reentry-latch-preservation-study/trading-lab/tv26/TV26_FiveTF_Arabic_CANDIDATE.mq5
Commit: f0f915f6c4234d5bdb090075d5fbc7da3eb1959b

Change scope: on a neutral consensus, preserve the last executed direction while this EA has a position open; clear/re-arm the latch only while flat. A diagnostic message records when the latch is held/reset. This does not change indicator formulas, ATR stop/target, risk percentage, spread limits, order sizing, or cooldown. The branch is not merged, and this source change is **not yet compiled/tested by MT5**. The intended first validation is the same Sep 1–10 setup as the source-matched five-trade baseline, then an independent-window replication only if the trade-list effect is supported. Do not infer performance from the code change itself.

The current Oct 20–22 cooldown matrix remains a separate experiment. Its zero-cooldown control has completed and reproduced the earlier result (+$2.74, PF 1.40, 1 win / 2 losses, 3 trades). The 10- and 20-bar variants are still being run; do not mix these results with the latch-source experiment.


## 15. Progressive one-day-first validation workflow

Workflow commit: `30516b4fe771d6f1ae5fce7bfd856fe9199517ed`
Run: https://github.com/staryuzar/-/actions/runs/40110879062

The previous conditional one-day/three-day workflow has been replaced by a sequential daily gate runner. The first window is October 22, 2026; if it passes, the runner replays October 21–22, then October 20–22, and so on, up to ten days ending on the same date. It does not launch later windows unless the previous stage passes.

Promotion criteria are explicit:
- One day: net profit at least $5.00, at least one trade, zero losing trades, max equity drawdown no more than 1.00%.
- Two days and beyond: cumulative net profit at least $2.50 per tested day on average; at least one trade; if any losses occur, PF at least 1.15; max equity drawdown limited to 1% per day, capped at 5%.
- Every stage must pass both OHLC integrity validation and the independent published TechnicalRating formula audit. Zero trades or an audit/metric failure stops expansion rather than being treated as success.

Each stage gets a unique magic number and its own artifact folder, retaining the tester summary, trade report, logs, CSV exports, formula report, and stage decision. MT5's explicit canceled tick-history failure is retried once; a second or non-transient failure stops the progression. The run was in progress when this entry was written, so no result from the new progressive sequence is asserted here. These thresholds are screening rules selected for the $500 lab account, not general investment guidance or evidence of a robust edge.


## 16. Progressive runner infrastructure repair — 2026-10-24

- First progressive run: https://github.com/staryuzar/-/actions/runs/40110879062.
- Stage 1 did complete and pass its configured screen: October 22, +$10.60 net, PF reported as 0.00 with no losses, max equity DD 0.74%, one winning trade, and both audits passed.
- Stage 2 did **not** run: the shared tester script clears the MT5 credential environment variable after a run. The progressive orchestrator initially failed to restore it, so stage 2 reported “Missing secret mt5; no tester run attempted.” This was an orchestration failure, not a strategy result. No claim is made about the two-day strategy outcome from this failed attempt.
- Fix committed: `2b400508d0ccac05f03fdb41a18a5df7f4bad03c` restores the in-memory credential value before each tester attempt and fixes literal USD text in the generated gate report. The secret is not written to source files or artifacts.
- Rerun triggered: https://github.com/staryuzar/-/actions/runs/40111025063. This rerun starts the progression over with a clean one-day test; two-day and longer windows are only reached if the preceding gate passes.


The completed one-day evidence for run 40110879062 records 47,164 component votes checked, zero vote mismatches, zero missing/invalid comparisons, 5,442 aggregate values with zero aggregate mismatches, and 1,814 OHLC candle groups with zero integrity errors. This validates the first stage's data/formula checks on the recorded Headway-Demo MT5 feed; it does not mean the whole progressive sequence passed.

## 17. Completed progressive daily-to-multi-day gate — run 40111025063

Workflow: https://github.com/staryuzar/-/actions/runs/40111025063

The corrected sequential runner completed successfully. All stages used XAUUSD M1, USD 500 initial deposit, MT5 Model 4, 1% risk, stop 2 ATR, target 4 ATR, M1 close-breakout enabled, a tester-only guard, and unique magic numbers. A stage ran only after its predecessor passed.

| Stage | Tested window | Net profit | PF | Max equity DD | Trades | Wins / losses | Decision |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 day | Oct 22, 2026 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Pass screen; expand |
| 2 days | Oct 21–22, 2026 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Pass screen; expand |
| 3 days | Oct 20–22, 2026 | +$2.74 | 1.40 | 1.72% | 3 | 1 / 2 | Stop |

*MT5 reports PF as 0.00 when there are no losing trades; with a single trade, this is not evidence of a stable edge.

The one- and two-day windows both contain only the October 22 winning sell, so the second day contributed no additional trades. The three-day window added two losing sells on October 20. Because the required three-day profit was at least $7.50, the recorded +$2.74 failed the profit gate and the runner correctly stopped; no 4–10-day windows were run.

### Integrity and formula audits by stage

| Stage | Component votes checked | Vote mismatches | Recalculated aggregates | OHLC candle groups | Invalid / duplicate / timestamp issues |
|---:|---:|---:|---:|---:|---:|
| 1 day | 47,164 | 0 | 5,442 | 1,814 | 0 / 0 / 0 |
| 2 days | 94,198 | 0 | 10,869 | 3,623 | 0 / 0 / 0 |
| 3 days | 141,232 | 0 | 16,296 | 5,432 | 0 / 0 / 0 |

Each stage compiled the EX5 in MetaEditor with zero reported errors/warnings and completed the MT5 Strategy Tester process with exit code 0. The audit hashes and reports are retained in artifact tv26-progressive-daily-gate-40111025063 (artifact ID 12567295356). As before, these formula-level audits compare MT5 votes to an independent implementation of the published TechnicalRating rules; direct runtime parity against a CSV exported from the user's actual TradingView chart remains pending.

### Trade-level diagnosis of the three-day failure

The two losing sells occurred on October 20:
- 11:08:00: sell 0.01 XAUUSD at 4119.61, SL 4123.36; stop loss triggered at 11:11:38.
- 11:30:00: sell 0.01 at 4119.34, SL 4122.38; stop loss triggered at 11:32:19.

The October 22 sell was a winner. Combined gross profit was $9.62 and gross loss was -$6.88, leaving +$2.74 net. The failures are therefore not caused by audit/formula mismatches in the captured data; this short sample shows two same-direction sell stop-outs on October 20, with a later winning sell on October 22.

## 18. Cooldown interpretation after the progressive result

The completed diagnostic matrix for October 20–22 is available in workflow https://github.com/staryuzar/-/actions/runs/40109199896. All three arms used the same source/data and settings (1% risk, SL 2 ATR, TP 4 ATR, M1 close-breakout, Model 4); only post-exit cooldown changed:

| Cooldown | Net profit | PF | Max equity DD | Trades | Wins / losses | Cooldown blocks |
|---:|---:|---:|---:|---:|---:|---:|
| 0 bars | +$2.74 | 1.40 | 1.72% | 3 | 1 / 2 | 0 |
| 10 bars | +$2.74 | 1.40 | 1.72% | 3 | 1 / 2 | 0 |
| 20 bars | +$6.79 | 2.78 | 1.13% | 2 | 1 / 1 | 1 |

On this diagnostic three-day window, 20 bars blocked the second October 20 stop-out and improved net profit by $4.05. This is a specific lead, not permission to adopt 20 bars: a separate October 1–10 holdout used a 3 ATR target and did not show a general improvement:
- 0 bars: -$6.57, PF 0.78, DD 3.78%, 12 trades (4 wins / 8 losses).
- 10 bars: -$9.10, PF 0.64, DD 3.00%, 10 trades (3 / 7).
- 20 bars: -$6.47, PF 0.75, DD 2.98%, 10 trades (3 / 7).

The Sep 11–20 20-bar result was also still losing (-$11.32, PF 0.44, six trades), barely different from the zero-bar baseline (-$11.41, PF 0.43, six trades). Conclusion: do not enable cooldown globally as a claimed profit fix. The October 20–22 gain came from avoiding one observed loss in the same window that motivated the test; it must be treated as overfit-prone until independently replicated.

## 19. Next isolated experiment — preserve signal latch during open position

The next test addresses a separate state-machine hypothesis, not another cooldown tweak. The research-only branch tv26-reentry-latch-preservation-study changes the neutral-signal path so it preserves the last executed direction while an EA position is still open; it only clears/re-arms when flat. This is intended to prevent a neutral candle during an open trade from resetting the latch and enabling same-direction immediate re-entry after exit.

Validation was activated on that branch (push-triggered run): https://github.com/staryuzar/-/actions/runs/40111570530. The planned windows are September 1–10 and October 20–22, with the same 1% risk / 2 ATR stop / 4 ATR target / M1 close-breakout / zero cooldown baseline settings. The September window has a previously measured baseline of +$3.35, PF 1.23, five trades (two wins / three losses), including a September 8 same-direction sell re-entry one second after TP which then hit SL at -$5.08. No performance conclusion about the latch fix is valid until its two strategy-tester runs and both audits complete.

No research-only fix has been merged into the candidate or main branch, and no live trading has been enabled.

## 20. Signal-latch preservation — first controlled comparison (Sep 1–10)

Research-only workflow: https://github.com/staryuzar/-/actions/runs/40111570530  
Sep artifact: https://github.com/staryuzar/-/actions/runs/40111570530/artifacts/12566902328

The baseline and latch-preservation build were tested on the **same date range, same broker feed, same OHLCV reference hash, same MT5 audit CSV hash, same model and risk/exit settings**. Only the signal-latch code differs. Both exported audits passed:
- 371,332 component votes compared; 0 formula mismatches and 0 missing/invalid comparisons.
- 42,846 summary aggregates recalculated; 0 aggregate mismatches.
- 14,282 OHLC candle groups checked; 0 invalid rows, duplicates, or timestamp errors.
- MetaEditor produced the EX5 with 0 errors and 0 warnings; Strategy Tester exit code 0.

| Sep 1–10 variant | Net | PF | Max equity DD | Trades | Wins / losses |
|---|---:|---:|---:|---:|---:|
| Baseline latch | +$3.35 | 1.23 | 2.48% | 5 | 2 / 3 |
| Preserve latch while a position is open | +$8.43 | 1.88 | 2.35% | 4 | 2 / 2 |

The MT5 HTML trade tables confirm the four remaining trades and their outcomes are unchanged. The only removed trade was the same-direction sell opened at 22:59:00 on Sep 8, one second after the prior sell TP at 22:58:59; it hit SL at 23:01:22 for -$5.08. In the modified build, the log explicitly records SAME_SIGNAL_LATCH at 22:59:00. Gross profit therefore remains $18.00 while gross loss falls from -$14.65 to -$9.57, improving the net by exactly $5.08. Audit CSV hash and OHLCV history hash are identical to the baseline; this is a controlled change in the entry state, not changed prices or indicator votes.

**Interpretation:** this is stronger evidence than the prior cooldown experiment because the exact suspected bad re-entry disappeared while the other four trades remained intact. It is still only a four-trade test over one already-investigated window; the change is not approved for the main candidate until the predeclared Oct 20–22 cross-window check completes. That independent window is currently running in the same workflow. No live trading or merge has been enabled.

## 21. Diagnostic log isolation improvement — progressive runner retest

After reviewing the completed progressive artifact, the tester report's actual deal table showed three trades in the three-day window while the aggregate diagnostic event count included an extra accepted-order event from a previous stage's terminal log. The financial metrics and per-stage audit CSVs were separate and remain the basis for the stage decisions, but the cross-stage log contamination makes those diagnostic counters unsuitable for attribution.

The shared progressive helper now uses a separate portable MT5 installation/log root for each stage, keyed by that stage's unique magic number. The progressive workflow path filter was updated so the isolation change triggers a new sequential run. Retest: https://github.com/staryuzar/-/actions/runs/40111786286

The rerun must reproduce the strategy metrics and demonstrate that each stage's diagnostic events match only that stage's trades before the log counters are reused. The previously completed run remains historical evidence for its Strategy Tester reports and formula/data audits; no inflated diagnostic counter is treated as a strategy fact.

## 22. Progressive daily gate — completed strategy screen and runner isolation correction

Completed sequential tester run: https://github.com/staryuzar/-/actions/runs/40111025063  
Artifact: https://github.com/staryuzar/-/actions/runs/40111025063/artifacts/12567295356

The corrected credential handling allowed the progressive gate to complete three sequential stages. It used XAUUSD M1, MT5 Model 4, $500 deposit, 1% risk, 2 ATR stop, 4 ATR target, M1 close-breakout, demo guard and tester-only guard. Each stage completed its formula and OHLC integrity audits.

| Days | Window | Net | PF | Max equity DD | Trades | Wins / losses | Gate |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | Oct 22 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Pass screen |
| 2 | Oct 21–22 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Pass screen |
| 3 | Oct 20–22 | +$2.74 | 1.40 | 1.72% | 3 | 1 / 2 | Stop |

*MT5 reports PF 0.00 when gross losses are zero; it is not a negative PF reading. The one-day and two-day runs each produced the same single trade on Oct 22. The three-day run did not meet the predeclared $7.50 minimum net profit for three days, so the workflow correctly stopped without running longer windows.

Formula audits passed at all three stages: 47,164, 94,198 and 141,232 component votes checked respectively; zero mismatches or missing/invalid votes. Summary aggregate checks passed; OHLC integrity audits reported zero invalid rows, duplicates or timestamp errors. Five overlapping reference bars were checked with no price mismatches at each stage. This confirms the candidate's exported calculations against the independent formula reference on the tested Headway-Demo feed, not direct parity with a live TradingView chart. MT5 can synthesize ticks where broker real-tick history is absent.

A follow-up isolation attempt (https://github.com/staryuzar/-/actions/runs/40111786286) failed before a tester run because a code-edit operation corrupted the shared PowerShell helper's quoting/structure. This is a runner/script failure, not a strategy result; that attempt produced no valid trades or audit. The helper has now been restored from the previously successful version and the per-stage portable-terminal/log-root change applied as a minimal top-of-file edit. A fresh sequential rerun should confirm that isolation fix before relying on per-stage diagnostic counters.

Decision: the current candidate has **not passed multi-day profitability screening**. Keep it in research only; do not merge to main or use live. Continue with the re-entry-latch hypothesis as a separate research branch, while preserving baseline comparisons and rejecting any change that merely suppresses trades without improving held-out outcomes.


## 23. Final progressive-runner isolation retest and current-candidate cross-check

Completed runner retest: https://github.com/staryuzar/-/actions/runs/40112081270  
Artifact: https://github.com/staryuzar/-/actions/runs/40112081270/artifacts/12567257003

The per-stage terminal/log isolation fix is now confirmed by a clean full run. The stage-specific portable MT5 roots and unique magic numbers were used, and each stage's accepted-order diagnostic count matches the Strategy Tester trade count. All three tests and audits completed without the earlier cross-stage log contamination.

| Days | Window | Net | PF | Equity DD | Trades | Wins / losses | Decision |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | Oct 22 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Expand |
| 2 | Oct 21–22 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Expand |
| 3 | Oct 20–22 | +$2.74 | 1.40 | 1.72% | 3 | 1 / 2 | Stop |

*PF is displayed as 0.00 by MT5 when no losing trades exist. The first two windows still contain only one trade; this is not evidence of robust profitability. The three-day stage failed the required $7.50 net-profit gate and correctly stopped progression. The stage-specific audit vote counts remain 47,164 / 94,198 / 141,232 with zero formula mismatches, and all OHLC audits passed.

## 24. Signal-latch change — independent October cross-check complete

Research comparison workflow: https://github.com/staryuzar/-/actions/runs/40111570530  
October artifact: https://github.com/staryuzar/-/actions/runs/40111570530/artifacts/12567026082

The Sep 1–10 comparison previously showed a favorable but small effect: baseline +$3.35 / PF 1.23 / DD 2.48% / five trades (2 wins, 3 losses) versus latch-preservation +$8.43 / PF 1.88 / DD 2.35% / four trades (2 wins, 2 losses). It removed only the identified same-direction sell re-entry that lost $5.08. This outcome is promising but remains a four-trade observation on the period that motivated the hypothesis.

On the predeclared October 20–22 cross-window check, the latch-preservation build did **not** change the result: +$2.74, PF 1.40, equity DD 1.72%, three sells (one win, two losses). The audit passed with 141,232 vote comparisons and zero formula mismatches; OHLC integrity checks also passed. The October logs show no same-signal-latch blocks, so this window does not independently demonstrate a performance gain or a loss.

Implementation note: the latch-preservation source was subsequently committed to the active candidate branch at commit 12fb2fab17c6c5f2c7d715ef0645ae009ec84787; it has not been merged into the repository default/main branch. The result should remain a candidate-branch change, not a production-performance claim. Keep it under observation and retain the baseline as a comparator.

## 25. Ten-day cooldown diagnostic and independent holdout

Diagnostic workflow: https://github.com/staryuzar/-/actions/runs/40112056560  
10-bar artifact: https://github.com/staryuzar/-/actions/runs/40112056560/artifacts/12567072288  
20-bar artifact: https://github.com/staryuzar/-/actions/runs/40112056560/artifacts/12567177171

On Oct 14–23, XAUUSD M1, Model 4, $500, 1% risk, SL 2 ATR, TP 3 ATR, M1 close-breakout enabled:

| Cooldown after exit | Net | PF | Max equity DD | Trades | Wins / losses |
|---:|---:|---:|---:|---:|---:|
| 10 M1 bars | +$3.13 | 1.19 | 2.24% | 8 | 3 / 5 |
| 20 M1 bars | +$6.20 | 1.46 | 2.24% | 7 | 3 / 4 |

Compared with the historical zero-cooldown M1-breakout result on this window (-$1.40 / PF 0.93 / DD 2.72% / nine trades), these variants are better screening outcomes. However, the zero-cooldown baseline was measured earlier in the development sequence, so it is not a strict same-commit A/B. More importantly, a prior September 11–20 test showed no general benefit from cooldowns. Do not turn cooldown on globally based on this single window.

A stricter same-source Oct 1–10 holdout is underway in workflow https://github.com/staryuzar/-/actions/runs/40112056553. The zero-bar control has completed and the 10-/20-bar variants were still queued/running at the last status check; no holdout conclusion is claimed until all arms and audits complete.

## 26. MT5 indicator audit — all five timeframes and Ichimoku raw values

Trading-disabled audit workflow: https://github.com/staryuzar/-/actions/runs/40112682884  
Artifact: https://github.com/staryuzar/-/actions/runs/40112682884/artifacts/12567441591

With EA trading disabled, the Oct 21–23 M1-chart diagnostic completed under MT5 Model 1 and passed:
- 141,232 indicator votes compared with the independent published TechnicalRating v3 formula implementation; zero mismatches or missing/invalid comparisons.
- 16,296 summary aggregate values recalculated; zero mismatches.
- 5,432 OHLC candle groups checked; zero invalid rows, duplicates, or timestamp errors.
- 27,160 Ichimoku raw fields checked across M1/M5/M15/M30/H1 (Tenkan, Kijun, shifted Span A, shifted Span B and close); zero mismatches and zero missing values.
- MetaEditor compile: zero errors and zero warnings.

This is stronger coverage of the internal indicator implementation, particularly the 26-bar Ichimoku cloud alignment, but remains a reference-formula check on the Headway-Demo feed. A direct numerical export from the actual TradingView chart on matching symbol/feed/session is still required for the final chart-parity claim.

## 27. Regression-test harness repair

The parity/comparator workflow exposed a test-harness defect after the latch test was added: one assertion referenced an undefined local variable (branch) instead of the fixture's extracted neutral branch. That caused a Python NameError; it was not a failing TradingView formula, MT5 indicator, or EA compilation result.

Fixed in commit 614afebc8998cc4e5351fb1bdbe41bb3d7ce1ca3 by asserting against self.neutral_branch. The follow-up comparator workflow passed all 70 Python tests and its TradingView compiler-status gate: https://github.com/staryuzar/-/actions/runs/40112887150. MetaEditor compile also passed: https://github.com/staryuzar/-/actions/runs/40112887163. The separately launched cloud MT5 audit at https://github.com/staryuzar/-/actions/runs/40112887198 was still queued at last check.

## Current decision

The formula implementations and data-audit tooling now have multiple clean MT5 runs, the progressive runner's isolation is validated, and the signal-latch change has one favorable diagnostic period but no lift in the October cross-check. The candidate still fails the three-day profitability gate, and the direct TradingView chart-export comparison remains open. Keep the work on the candidate/research branches; do not claim the EA is production-ready or enable live use on this evidence.


## 28. October 1–10 same-source cooldown holdout — two arms completed

Holdout workflow: https://github.com/staryuzar/-/actions/runs/40112056553  
0-bar artifact: https://github.com/staryuzar/-/actions/runs/40112056553/artifacts/12567650766  
10-bar artifact: https://github.com/staryuzar/-/actions/runs/40112056553/artifacts/12567186919

The 0-bar and 10-bar arms completed on the same EA source hash and identical market/audit hashes. Both used XAUUSD M1, MT5 Model 4, 1% risk, 2 ATR stop, 3 ATR target, M1 close-breakout enabled, and a $500 deposit. Results were identical:

| Cooldown | Net | PF | Max equity DD | Trades | Wins / losses | Cooldown blocks |
|---:|---:|---:|---:|---:|---:|---:|
| 0 M1 bars | -$9.10 | 0.64 | 3.00% | 10 | 3 / 7 | 0 |
| 10 M1 bars | -$9.10 | 0.64 | 3.00% | 10 | 3 / 7 | 0 |

Both runs had the same MT5 audit SHA-256 `699e66d4e046c9e9df8195f793aab3d195dcf988dd0fa734f58aafc773fc0d26` and history SHA-256 `db0447bee35ea1d59e4ad10c8c96709ca539a459d329a5bcd140ee03bf573005`. The 10-bar arm recorded zero cooldown blocks and kept the same accepted-order/trade counts. I also compared the Strategy Tester HTML order/deal tables directly: all 41 table rows (including the 10 entries, 10 exits, and balance row) are identical between 0 and 10 bars, not merely the headline metrics. Its complete formula audit checked 329,368 votes with zero mismatches; OHLC integrity checks passed. Decision: **no evidence of benefit from 10 bars on this holdout**.

At the time of this original section the 20-bar arm was still in progress; its completed result is now recorded in section 32.

## 29. Separate three-day risk diagnostic — technical history failure, not a result

Workflow: https://github.com/staryuzar/-/actions/runs/40112056555  
Diagnostic artifact: https://github.com/staryuzar/-/actions/runs/40112056555/artifacts/12567211453

A separate three-day diagnostic using a 3 ATR target did not yield a valid MT5 result because the terminal reported `preliminary downloading of history ticks canceled` / `no history data, stop testing`. The workflow produced no tester trade summary and skipped the data/formula audits. Therefore it contributes **no profit, loss, or trade-count evidence** and must be treated as an infrastructure failure rather than a strategy loss. A clean completed rerun is required before using that period for conclusions.

## 30. Updated CI status after regression-test repair

Following the correction to the signal-latch test assertion, the current comparator suite passed all 70 Python tests and the TradingView compiler-status gate (workflow 40112887150). MetaEditor compilation also passed (workflow 40112887163). The source-matched trading-disabled cloud audit completed in workflow 40112887198: 141,232 vote comparisons with zero formula mismatches, 16,296 summary aggregate values with zero mismatch, 5,432 OHLC candle groups with no data-quality issues, and 27,160 Ichimoku raw fields with zero mismatch or missing values.

These technical passes strengthen the implementation checks; they do not override the failed three-day profitability gate or establish direct numerical parity against an actual TradingView chart export.


## 31. Trade-level diagnosis — same-source October cooldown holdout

The exact Strategy Tester deal rows for the 0-bar and 10-bar arms are identical. The ten closed trades (same list in both arms) break down by date as follows:

| Date | Entries / direction | Net contribution | Detail |
|---|---|---:|---|
| Oct 2 | 1 sell | +$6.08 | TP |
| Oct 5 | 3 sells | -$12.00 | Three SL exits: -$4.13, -$3.09, -$4.78 |
| Oct 7 | 4 sells | +$4.18 | Two TP wins (+$5.80, +$4.47) and two SL losses (-$3.03, -$3.06) |
| Oct 9 | 2 buys | -$7.36 | Two SL exits: -$4.76, -$2.60 |
| Total | 8 sells, 2 buys | -$9.10 | 3 wins, 7 losses |

The main concentration is the three losing sells on October 5 and the two losing buys on October 9. The 10-bar setting failed to block them because the accepted entries were not within ten M1 bars of the previous exit; the entry/deal table and diagnostic counter confirm no cooldown block occurred.

The October 7 12:20 sell was a winner (+$4.47) entered 10 minutes 27 seconds after the prior sell's SL exit at 12:09:33. The completed 20-bar arm blocked that entry but allowed a later sell at 12:31 to reach TP for +$7.10, replacing the earlier +$4.47 outcome (+$2.63 improvement). This timing change did not reduce the seven losing trades. The full result and its limits are recorded in section 32; do not generalize it from one affected entry.


## 32. October 1–10 cooldown holdout — all arms completed

Completed workflow: https://github.com/staryuzar/-/actions/runs/40112056553  
0-bar artifact: https://github.com/staryuzar/-/actions/runs/40112056553/artifacts/12567650766  
10-bar artifact: https://github.com/staryuzar/-/actions/runs/40112056553/artifacts/12567186919  
20-bar artifact: https://github.com/staryuzar/-/actions/runs/40112056553/artifacts/12567173668

All three arms used the same current EA source SHA, the same October 1–10 window, identical MT5 audit CSV hash and identical OHLCV history hash. Settings: XAUUSD M1, Model 4, $500 balance, 1% risk, SL 2 ATR, TP 3 ATR, M1 close-breakout on. All three audits passed; 329,368 component votes were checked with zero formula mismatches and no OHLC integrity issues.

| Cooldown | Net | PF | Max equity DD | Trades | Wins / losses | Cooldown blocks |
|---:|---:|---:|---:|---:|---:|---:|
| 0 bars | -$9.10 | 0.64 | 3.00% | 10 | 3 / 7 | 0 |
| 10 bars | -$9.10 | 0.64 | 3.00% | 10 | 3 / 7 | 0 |
| 20 bars | -$6.47 | 0.75 | 2.98% | 10 | 3 / 7 | 1 |

The 0-bar and 10-bar HTML order/deal tables matched exactly. In the 20-bar arm, one re-entry at 12:20 on October 7 was blocked after an SL exit at 12:09:33; a subsequent sell was accepted at 12:31 and reached TP at 13:02:38. This shifted entry timing and improved the net result by $2.63 while leaving the seven losses and overall trade count unchanged. It did **not** make the strategy profitable: net remains negative and PF remains below 1.0.

Decision: the 20-bar rule is a modest holdout improvement for this particular 3-ATR-target setup, not a general fix. Keep the default cooldown at 0 until the same rule is replicated on another clean window with matched settings; the earlier Sep 11–20 comparison showed almost no benefit (−$11.32 vs −$11.41), and the Oct 20–22 diagnostic that motivated the idea was not independent. Do not merge a global cooldown or describe the candidate as profitable from these results.


## 33. Next independent cooldown cross-check launched

Workflow: https://github.com/staryuzar/-/actions/runs/40113501784  
Workflow file: `.github/workflows/tv26-strategy-cooldown-sep21-30.yml`  
Commit: `5b1ad32f804e1f1137fdc569d831fcb0557db08e`

To test whether the October 1–10 20-bar timing improvement transfers, a new source-matched 0/10/20-bar matrix was launched for **September 21–30, 2026** using XAUUSD M1, Model 4, $500 balance, 1% risk, 2 ATR stop, 3 ATR target and M1 close-breakout. The three arms are serialized and have the same formula/OHLC audits; the existing demo and tester-only guards remain in place. No outcome is inferred until each arm and audit completes. This is a cross-check, not permission to adopt a global cooldown.


## 34. September 21–30 cooldown cross-check — completed

Workflow: https://github.com/staryuzar/-/actions/runs/40113501784  
0-bar artifact: https://github.com/staryuzar/-/actions/runs/40113501784/artifacts/12567164341  
10-bar artifact: https://github.com/staryuzar/-/actions/runs/40113501784/artifacts/12566854212  
20-bar artifact: https://github.com/staryuzar/-/actions/runs/40113501784/artifacts/12567199994

The source-matched 0/10/20-bar matrix completed on Sep 21–30 with XAUUSD M1, MT5 Model 4, $500 deposit, 1% risk, 2 ATR stop, 3 ATR target, M1 close-breakout enabled. All three arms had identical code source SHA `1448c417b458b78f7d69225801b44949cefb8b960bbe2a07eb68b719d64dde87`, audit SHA `323581c3a518b2c968a5a96223584b76174c2035430204563e268d9ab7b0f8d3` and history SHA `1e5831d3f58937bcf401822e82541aed0f53318ea238e84be816b1157af023dc`. Audits passed on all arms, with no formula vote mismatches or OHLC integrity errors.

| Cooldown | Net | PF | Max equity DD | Trades | Wins / losses | Cooldown blocks |
|---:|---:|---:|---:|---:|---:|---:|
| 0 bars | +$0.67 | 1.17 | 0.99% | 2 | 1 / 1 | 0 |
| 10 bars | +$0.67 | 1.17 | 0.99% | 2 | 1 / 1 | 0 |
| 20 bars | +$4.50 | 0.00* | 0.99% | 1 | 1 / 0 | 1 |

*PF 0.00 indicates there were no losing trades in the single-trade 20-bar sample; it is not a useful estimate of profitability. As on Oct 1–10, the 10-bar arm had no effect. The 20-bar arm blocked one potential re-entry and removed one loss from this two-trade sample. This is directionally consistent with its modest improvement on Oct 1–10, but one blocked trade across a two-trade window is still far too small to approve a general cooldown. The September 11–20 window previously showed almost no change. Keep the default cooldown at 0 until it is replicated on longer, unseen data without a material loss of winners.

## 35. M1/M5 oscillator confirmation — research implementation and gate semantics

Created an isolated branch, `tv26-m1m5-oscillator-gate-study`, adding the optional input `InpMinM1M5DirectionalOscillatorRating` (valid range 0–1; default 0.00 means disabled). It is a strategy entry filter only: it requires the directional oscillator average on both M1 and M5 to meet the threshold, but it does not modify `AlignedSignal()`, the 26-component formula values, or the five-timeframe panel's Strong Buy/Strong Sell classification.

The gate emits a specific diagnostic with M1/M5 raw and directional oscillator ratings, the threshold, and a pass/fail flag for each timeframe. It is ordered after already-open same-side position, same-signal latch, and post-exit cooldown checks so it only diagnoses a plausible new entry; the existing risk, demo and tester-only guards remain intact. This reduces misleading filter counts and ensures the filter does not reset signal memory.

A September 21–30 source-matched real-tick comparison was prepared for threshold 0.00 versus 0.15 using 1% risk, 2 ATR stop, 3 ATR target, M1 close-breakout, zero cooldown, and the same Headway-Demo feed. The first CI attempts exposed test-harness/environment problems before Strategy Tester: (1) an assertion used the wrong `DetailSignal` signature, and (2) the test called a Windows Store WSL shim named `bash` rather than Git Bash, which returned “Windows Subsystem for Linux has no installed distributions.” These are not strategy results. The test was corrected to use Git for Windows' Bash executable explicitly, to parse the block from a UTF-8 temporary file, and to assert the new entry-gate ordering. No performance outcome should be recorded until the current workflow completes compiler, regression, tester and audit gates.

Research holdout workflow: https://github.com/staryuzar/-/actions/runs/40114435807


## 36. Targeted post-TP same-direction cooldown — research branch started

Research-only branch: `tv26-post-tp-same-direction-cooldown-study`  
EA source commit: `5c422c17083eff82b0cb5271c26c2228df01eceb`  
Tester harness commit: `6e7f2cc5f3dd22598fb79db5f1fd374318920efa`  
Contract-test commit: `6780c6a5dabdc2e70e3461afa0bc830fb2cfaf8f`

This is a narrower hypothesis than a global after-exit cooldown, based on two observed same-direction re-entries after take-profit that subsequently hit SL:
- Sep 8: sell TP at 22:58:59, same-direction sell re-entered at 22:59:00, then SL -$5.08.
- Sep 23: sell TP +$4.50 at 10:59:34, same-direction sell re-entered at 11:10, then SL -$3.83.

A different pattern argues against a global cooldown: on Oct 7, a sell opened at 12:20 after a prior SL at 12:09:33 was a winner (+$4.47). A 20-bar global cooldown delayed it until 12:31; it later won +$7.10, changing profit by +$2.63, but this timing outcome is not evidence the global rule should be adopted.

The research build adds `InpSameDirectionCooldownAfterProfitBars`, default 0 (disabled), capped at 720 bars. It checks the direction of the last closed position and only pauses a new same-direction entry after the complete position lifecycle had positive net profit; it should not pause after an SL/loss or an opposite-direction signal. To account for entry commission, swap and fees, the implementation uses `HistorySelectByPosition` and totals BUY/SELL deal profit, swap, commission and fee across the full position history; if that history cannot be verified, the profit-based gate remains off. Official reference: https://www.mql5.com/en/docs/trading/historyselectbyposition.

The change is isolated to its research branch, and its two-window, source-matched MT5 matrix is being prepared for Sep 21–30 and Oct 1–10 with values 0/10/20 bars, global cooldown fixed at zero, 1% risk, 2 ATR SL, 3 ATR TP, M1 close-breakout and Model 4. **No strategy result is claimed for this new rule until MetaEditor compilation, all regression contracts, the six tester arms and audits pass.** It has not been merged into the candidate or default branch.


## 37. Progressive gate rerun after PowerShell helper restoration — 2026-10-24

Workflow: https://github.com/staryuzar/-/actions/runs/40115334971  
Artifact: https://github.com/staryuzar/-/actions/runs/40115334971/artifacts/12568635764

The repaired progressive workflow completed successfully at the infrastructure/audit level and stopped at the 3-day profitability gate, as designed. Settings were XAUUSD M1, MT5 Model 4, $500 deposit, risk 1%, SL 2 ATR, TP 4 ATR, M1 close-breakout enabled, demo/tester-only guards, and distinct Magic IDs for each stage.

| Window | Net | PF | Max equity DD | Trades | Wins / losses | Gate |
|---|---:|---:|---:|---:|---:|---|
| Oct 22 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Pass one-day screen only |
| Oct 21–22 | +$10.60 | 0.00* | 0.74% | 1 | 1 / 0 | Continue to 3 days, still one trade total |
| Oct 20–22 | +$2.74 | 1.40 | 1.72% | 3 | 1 / 2 | STOP: below required +$7.50 |

*MT5 reports PF 0.00 with no losing trades; this is not a meaningful PF estimate. One winning trade is not evidence of robust profitability. At three days, the accepted trades were two losing sells on Oct 20 (-$3.81 and -$3.07) and one winning sell on Oct 22 (+$9.62). The runner therefore stopped before longer windows. The 3-day audit checked 141,232 component votes with zero independent-formula mismatches; all 5,432 candle groups and aggregate checks passed. The one- and two-day audits also passed. These are broker-feed formula/data audits, not direct TradingView chart-runtime parity. No live trading or main-branch merge is authorized by these results.

## 38. Signal-latch fix diagnostic — latest fixed-source runs

Workflow: https://github.com/staryuzar/-/actions/runs/40115390637  
September artifact: https://github.com/staryuzar/-/actions/runs/40115390637/artifacts/12568391392  
October artifact: https://github.com/staryuzar/-/actions/runs/40115390637/artifacts/12568651534

The fixed-source diagnostic completed both windows using source SHA-256 `1448c417b458b78f7d69225801b44949cefb8b960bbe2a07eb68b719d64dde87`, 1% risk, SL 2 ATR, TP 4 ATR, M1 close-breakout enabled, global cooldown 0, and Model 4. The source preserves the last executed signal while a matching position is still open and only clears/re-arms once neutral and flat.

| Window | Net | PF | Max equity DD | Trades | Wins / losses | Same-signal latch blocks |
|---|---:|---:|---:|---:|---:|---:|
| Sep 1–10 | +$8.43 | 1.88 | 2.35% | 4 | 2 / 2 | 2 |
| Oct 20–22 | +$2.74 | 1.40 | 1.72% | 3 | 1 / 2 | 0 |

Audits passed: 371,332 component votes on Sep 1–10 and 141,232 on Oct 20–22, with zero vote mismatches and no OHLC integrity errors. The September report's four trades omit the prior unwanted instant same-direction re-entry; the October trades are unchanged because no matching latch block was triggered. These fixed-only runs do not prove the patch caused the difference relative to a baseline. A source-matched before/after A/B matrix is being run using the historical pre-fix source and the fixed source over both periods; no causal improvement is claimed until all four arms complete with matching feed/history checks.

## 39. Direct TradingView parity and strategy gate remain separate

The repository still has no actual live TradingView chart-output CSV from the same symbol/feed and overlapping closed-bar timestamps. Therefore direct numerical TradingView chart-runtime parity remains **PENDING** despite successful Pine compiler, MetaEditor, independent published-formula, OHLC and Ichimoku checks. Strategy robustness also remains **NOT ESTABLISHED**: the recent 3-day progressive screen stopped at +$2.74 against a +$7.50 gate. Continue on research/candidate branches only.
