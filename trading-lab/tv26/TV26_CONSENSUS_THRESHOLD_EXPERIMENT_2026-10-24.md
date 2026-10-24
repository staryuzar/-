# TV26 entry-consensus threshold experiment — 2026-10-24

**Branch:** `tv26-consensus-threshold-study`. Screening only; tester-only. No merge to main.

## Test design

- Symbol/feed: XAUUSD, Headway-Demo / Jarocel (Pty) Ltd.
- MT5 Strategy Tester, Model 4 (Every tick based on real ticks).
- Date window: 2026-09-14 through 2026-09-18 inclusive. This is the same diagnostic sample used to formulate the threshold hypothesis; it is not an independent validation window.
- Deposit $500; risk 1%; stop 2 ATR; target 4 ATR; M1 close breakout enabled; lookback 1 bar; buffer 0 ATR.
- Only `InpEntryConsensusThreshold` changes. The displayed TradingView rating labels still use their standard +/-0.50 boundary; the experimental value adds a stricter entry gate.

## Results so far

| Minimum absolute rating on every timeframe | Net profit | PF | Max equity DD | Trades | Wins / losses |
|---:|---:|---:|---:|---:|---:|
| 0.50 (baseline) | -$11.41 | 0.43 | 3.39% | 6 | 1 / 5 |
| 0.55 | +$1.08 | 1.14 | 0.90% | 3 | 1 / 2 |
| 0.60 | Pending | Pending | Pending | Pending | Pending |

Workflow: https://github.com/staryuzar/-/actions/runs/40105626487

The 0.50 and 0.55 runs share the same EA source SHA and reference OHLCV SHA. Both compiled with 0 errors and 0 warnings and passed formula-level audit: 235,300 component votes checked, zero mismatches; clean data-integrity report. That establishes comparable inputs on this feed, not direct live TradingView chart parity.

The 0.55 setting removed both Sep 14 sell losses (-$4.38 and -$4.37) and the Sep 15 12:14 sell loss (-$4.01) from their original entry times. It did **not** eliminate the Sep 15 09:11 losing sell; entry moved to 09:12 and lost -$4.01. The Sep 18 09:00 buy TP (+$8.78) remained, while the Sep 18 later buy moved from 09:40 to 09:41 and lost -$3.69. Net is +$1.08 on three trades, too small to establish a durable edge.

## Decision gates

Do not select threshold 0.55 from this same window alone; the experiment was prompted by these very losses. Finish the 0.60 screen, then compare the baseline and any candidate on an earlier untouched window such as 2026-09-01 through 2026-09-10. Reject any candidate that only produces no trades or a one-trade result as inconclusive, and preserve the minimum-volume risk cap.
