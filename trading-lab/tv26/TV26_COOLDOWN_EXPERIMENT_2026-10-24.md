# TV26 post-exit cooldown diagnostic — 2026-10-24

**Branch:** `tv26-breakout-buffer-study`; isolated Strategy Tester only; not merged to main.

## Test design

XAUUSD, Headway-Demo / Jarocel (Pty) Ltd; MT5 Model 4 (Every tick based on real ticks); 2026-09-11 to 2026-09-20 inclusive; $500 initial deposit; risk 1%; SL 2 ATR; TP 4 ATR; M1 close-breakout enabled with 0.00 ATR extra buffer. Only `InpCooldownBarsAfterExit` is varied. Risk controls and minimum-volume cap remain enabled.

## Results so far

| Cooldown after close | Net profit | Profit factor | Max equity DD | Trades | Wins / losses | Cooldown-block logs |
|---:|---:|---:|---:|---:|---:|---:|
| 0 bars | -$11.41 | 0.43 | 3.39% | 6 | 1 / 5 | 0 |
| 10 bars | -$11.41 | 0.43 | 3.39% | 6 | 1 / 5 | 4 |
| 20 bars | Pending | Pending | Pending | Pending | Pending | Pending |

Workflow: https://github.com/staryuzar/-/actions/runs/40104815052

The 0- and 10-bar tests had identical source SHA-256, identical exported MT5 audit SHA-256 and identical reference OHLCV SHA-256. Both compiled with 0 errors and 0 warnings. Each passed audit integrity (10,859 OHLC candle groups, zero invalid/duplicate/timestamp issues) and formula-level checking (282,334 component votes, zero mismatches). This validates comparable test inputs, not profitability or parity against a live TradingView chart.

The 10-bar variant recorded four POST_EXIT_COOLDOWN blocks on Sep 18 between 09:06 and 09:10 after the 09:01:18 take-profit. Its next accepted position was still the Sep 18 09:40 buy, exactly as in the baseline, so the cooldown did not change the six accepted trades or net result. A ten-bar pause therefore did not solve the observed loss cluster.

## Interpretation

Do not keep a cooldown merely because it blocks log events. It should change a harmful accepted entry or improve net outcome on held-out periods. Await the 20-bar variant before concluding whether a longer post-exit pause has a measurable effect.
