# TV26 post-exit cooldown diagnostic — 2026-10-24

**Branch:** `tv26-breakout-buffer-study`; isolated Strategy Tester only; not merged to main.

## Test design

XAUUSD, Headway-Demo / Jarocel (Pty) Ltd; MT5 Model 4 (Every tick based on real ticks); 2026-09-11 to 2026-09-20 inclusive; $500 initial deposit; risk 1%; SL 2 ATR; TP 4 ATR; M1 close-breakout enabled with 0.00 ATR extra buffer. Only `InpCooldownBarsAfterExit` is varied. Risk controls and minimum-volume cap remain enabled.

## Results so far

| Cooldown after close | Net profit | Profit factor | Max equity DD | Trades | Wins / losses | Cooldown-block logs |
|---:|---:|---:|---:|---:|---:|---:|
| 0 bars | -$11.41 | 0.43 | 3.39% | 6 | 1 / 5 | 0 |
| 10 bars | -$11.41 | 0.43 | 3.39% | 6 | 1 / 5 | 4 |
| 20 bars | -$11.32 | 0.44 | 3.38% | 6 | 1 / 5 | 7 |

Workflow: https://github.com/staryuzar/-/actions/runs/40104815052

The 0- and 10-bar tests had identical source SHA-256, identical exported MT5 audit SHA-256 and identical reference OHLCV SHA-256. Both compiled with 0 errors and 0 warnings. Each passed audit integrity (10,859 OHLC candle groups, zero invalid/duplicate/timestamp issues) and formula-level checking (282,334 component votes, zero mismatches). This validates comparable test inputs, not profitability or parity against a live TradingView chart.

The 10-bar variant recorded four POST_EXIT_COOLDOWN blocks on Sep 18 between 09:06 and 09:10 after the 09:01:18 take-profit. Its next accepted position was still the Sep 18 09:40 buy, exactly as in the baseline, so the cooldown did not change the six accepted trades or net result. A ten-bar pause therefore did not solve the observed loss cluster.

The 20-bar variant recorded seven cooldown blocks but also left the six accepted trades unchanged. Net improved from -$11.41 to -$11.32 (just $0.09), PF from 0.43 to 0.44, and max equity DD from 3.39% to 3.38%. This is immaterial and does not support selecting a cooldown as a performance fix. The 20-bar test compiled with zero errors/warnings and passed the same audit: 282,334 votes, zero formula mismatches; 10,859 candle groups, zero data-integrity issues. The audit/history SHA-256 values match the zero-cooldown run.

## Interpretation

Final decision: reject post-exit cooldown as a strategy-performance enhancement on this sample. Both 10- and 20-bar variants added blocked-attempt diagnostics but did not change trade count or meaningfully improve outcome. Do not merge either change as a profit fix.
