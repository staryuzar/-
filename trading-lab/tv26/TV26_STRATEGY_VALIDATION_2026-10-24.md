# TV26 Strategy Validation — 24 October 2026

## Executive result

The indicator-vote implementation continues to match an independent implementation of the published TradingView TechnicalRating v3 formulas on the tested MT5 feed. **That is formula-level parity, not live TradingView chart parity and not evidence of profitability.**

No EA configuration is approved for live trading.

## 10-day baseline matrix

Workflow: [run 40097583304](https://github.com/staryuzar/-/actions/runs/40097583304)

MT5 Strategy Tester used Model 4 (Every tick based on real ticks), XAUUSD, $500 initial deposit, 1:1000 leverage, 14–23 October 2026 inclusive. The tester-only guard was enabled; all orders were simulated and could not be sent to a live account. MT5 may synthesize ticks where broker real-tick history is unavailable.

| Variant | Net P/L | Profit factor | Max equity DD | Trades | Win rate | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Risk 0.5%, SL 2 ATR / TP 3 ATR, no breakout | +$1.00 | 1.44 | 0.50% | 2 | 50.0% | Too few trades; not a pass |
| Risk 1%, SL 2 ATR / TP 3 ATR, no breakout | -$7.32 | 0.73 | 3.92% | 11 | 27.3% | Fail |
| Risk 1%, SL 2 ATR / TP 3 ATR, M1 close breakout | -$1.40 | 0.93 | 2.72% | 9 | 33.3% | Better than baseline, still negative |
| Risk 1%, SL 1.5 ATR / TP 2.25 ATR, no breakout | -$23.57 | 0.46 | 7.47% | 15 | 20.0% | Fail; shorter stop performed materially worse |

## 1–23 October exit-parameter matrix

Workflow: [run 40101541668](https://github.com/staryuzar/-/actions/runs/40101541668)

The workflow title says “24 days,” but the actual tester range was 1–23 October inclusive (23 calendar days). Each variant required the closed M1 candle to close beyond the previous candle high/low.

| Variant | Net P/L | Profit factor | Max equity DD | Trades | Wins / losses |
|---|---:|---:|---:|---:|---:|
| Risk 1%, SL 2 ATR / TP 2.5 ATR | -$9.14 | 0.82 | 5.46% | 22 | 8 / 14 |
| Risk 1%, SL 2 ATR / TP 4 ATR | +$12.51 | 1.27 | 4.77% | 20 | 7 / 13 |
| Risk 1%, SL 1.5 ATR / TP 3 ATR | -$45.83 | 0.39 | 13.26% | 24 | 4 / 20 |
| Risk 0.5%, SL 2 ATR / TP 3 ATR | +$3.67 | 1.41 | 0.79% | 8 | 4 / 4 |

The 2 ATR stop / 4 ATR target was the strongest result in this small set, but it still had a 65% losing-trade rate and a maximum losing streak of six. It is a promising test candidate only; 20 trades cannot establish a durable edge. The 0.5% risk result also has too few trades to select confidently.

## Directional diagnostic

Workflow: [run 40101280765](https://github.com/staryuzar/-/actions/runs/40101280765)

| Period | Buys and sells allowed | Sell-only diagnostic | What it suggests |
|---|---|---|---|
| 1–10 October | -$6.57; 12 trades; PF 0.78 | +$0.79; 10 trades; PF 1.04 | Long entries were weak in this sample |
| 14–23 October | -$1.40; 9 trades; PF 0.93 | +$3.26; 5 trades; PF 1.31 | Sell-only improved results but halved the trade count |

The sell-only outcome is diagnostic, not a recommended configuration. Simply disabling buys would risk improving the backtest by excluding trades rather than fixing entry quality. The next experiment therefore adds an optional ATR-scaled distance requirement to the M1 breakout and compares it on the same 1–23 October data.

## One-day gate and audit isolation correction

Workflow: [one-day gate rerun](https://github.com/staryuzar/-/actions/runs/40102271856)

The first one-day run (23 October) executed zero trades, so there were no losing trades but also no trading evidence. The follow-on three-day tester report recorded one winning trade (+$7.48) and zero losing trades. However, its exported indicator audit failed validation because the repeated test reused the same audit-file identity and duplicated the one-day records. **That combined run is not accepted as a clean audit result.**

The runner was corrected to accept a distinct MT5 magic number per repeated stage, clear stale report output before rerunning, and use UTF-8 mode for Python on Windows. A fresh one-day → conditional three-day run is underway at the link above. This is a test-infrastructure fix, not a strategy improvement.

## Indicator formula audit

The completed 1–23 October exit matrix compared 799,708 component votes against an independent Python implementation of the published TradingView TechnicalRating v3 rules: zero vote mismatches and zero missing/invalid comparisons. The data-integrity checks covered 30,758 time-frame candle groups, with zero invalid OHLC rows and zero summary aggregate mismatches.

Scope limitation: this confirms agreement between the MT5 recorded votes and the independent formula implementation on the tested Headway-Demo / Jarocel feed. It does not prove numerical equality to the live TradingView chart. That still requires exporting actual TradingView Pine outputs for matching symbol/feed/timeframes and running the CSV comparator.

## Current entry-quality experiment

Workflow: [M1 breakout-buffer matrix](https://github.com/staryuzar/-/actions/runs/40102196337)

An isolated branch, `tv26-breakout-buffer-study`, adds `InpM1BreakoutBufferATR`. At zero, behavior is intended to preserve the previous breakout rule; positive values require the closed M1 price to exceed the previous high/low by an additional fraction of M1 ATR. The matrix holds risk at 1%, SL at 2 ATR, TP at 4 ATR, and tests buffer distances 0.00, 0.05, 0.10, and 0.20 ATR on 1–23 October inclusive. The matrix is still running; no outcome is claimed yet, and this candidate has not been merged into the main line.

## Short 3-day diagnostic runs — 21–23 October

All results below are MT5 Strategy Tester simulations, not live trades. Their sample sizes are too small for parameter selection; they are useful only as a quick check of loss modes and the interaction with minimum-volume risk protection.

| Configuration | Net P/L | Profit factor | Max equity DD | Trades | Wins / losses | Diagnostic |
|---|---:|---:|---:|---:|---:|---|
| Risk 1%, SL 2 ATR / TP 3 ATR, M1 close-breakout enabled | +$7.48 | 0.00 (no losing trade) | 0.74% | 1 | 1 / 0 | One winning trade only; no statistical pass |
| Risk 1%, SL 2 ATR / TP 3 ATR, no breakout | +$4.39 | 2.42 | 0.99% | 2 | 1 / 1 | One loss; sample too small |
| Risk 1%, SL 1 ATR / TP 1.5 ATR, no breakout | -$8.31 | 0.50 | 1.85% | 7 | 2 / 5 | Fail |
| Risk 1%, SL 1.5 ATR / TP 2.25 ATR, no breakout | -$3.60 | 0.80 | 2.19% | 6 | 2 / 4 | Fail |

The 3-day baseline at 0.5% risk with SL 2 ATR / TP 3 ATR took zero trades. In the short 3-day window, 14 bars generated strong five-timeframe consensus, but minimum-volume risk protection blocked 11 entries; the 1% breakout variant had 14 consensus bars and 6 minimum-volume blocks. Keep this protection; allowing a 0.01 lot when its stop would exceed the risk budget would make the displayed risk percentage untrue.

A later 10-day variant configured with M1 breakout but missing tick history failed to generate the audit CSV. The job log said MT5's preliminary tick-history download was cancelled / no history data, so it is classified as an **incomplete infrastructure run**, not as a losing strategy result.

These tests support retaining SL 2 ATR rather than the tested tighter 1 ATR / 1.5 ATR settings; they do not settle the best target multiplier. Target-selection should use the larger matrices plus a separate holdout, not this three-day sample.

## Acceptance criteria

A candidate must have:
- Correct compile and clean, isolated test artifacts.
- Valid OHLC and formula audit with no duplicates.
- Positive expectancy after realistic execution costs across several distinct periods.
- Controlled equity drawdown and enough trades to avoid selecting a single lucky result.
- Holdout confirmation before any live-use discussion.

Do not remove the minimum-volume risk protection just to raise trade count. Keep all experiments tester-only and unmerged until their evidence is reviewed.
