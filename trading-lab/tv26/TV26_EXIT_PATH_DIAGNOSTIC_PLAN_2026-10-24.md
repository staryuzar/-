# TV26 rule-based exit-path diagnostic — 2026-10-24

## Purpose

Validate the candidate's early-exit behavior separately from ordinary stop-loss/take-profit exits. This is a diagnostic, not a strategy-performance run.

## Source behavior inspected

- Entry consensus is restricted to the three summaries M5, M15, and M30. All three must be complete and each rating must be above +0.50 for a buy or below -0.50 for a sell.
- For an open buy, any complete M5/M15/M30 rating below -0.10 requests an exit. For an open sell, any complete rating above +0.10 requests an exit.
- If no opposite summary is detected, an M1 closed candle triggers the price-reversal rule only if it closes in the opposite candle direction and beyond the extreme of the preceding three closed candles.
- The exit path emits `TV26_EXIT_TRIGGER`, then either `TV26_EXIT_COMPLETED` or `TV26_EXIT_FAILED`.
- Exit management is evaluated on a new M1 bar, not on every tick. This means the exit rule is bar-confirmed and may not close intrabar.

## Diagnostic setup

Workflow: `.github/workflows/tv26-exit-diagnostic.yml`  
Branch: `tv26-exit-diagnostic-study`  
Window: 2026-09-01 through 2026-09-03 inclusive  
Tester: MT5 Strategy Tester, Model 4 (real-tick mode), XAUUSD M1  
Risk: 1%; SL 5 ATR; TP 20 ATR; M1 entry breakout disabled  
Magic: 26102481  
Guards: tester-only and demo-only remain enabled by the existing runner.

Widened SL/TP are intended only to make rule-based exits easier to observe. Their performance metrics must not be compared with the baseline's 2 ATR / 4 ATR configuration.

## Acceptance criteria

1. MetaEditor compile and Strategy Tester finish successfully.
2. Audit CSV and OHLC history are present and valid.
3. Independent formula audit completes without missing or mismatched votes.
4. At least one `TV26_EXIT_TRIGGER` occurs.
5. Each trigger is paired with a successful `TV26_EXIT_COMPLETED`; any `TV26_EXIT_FAILED` is a failure requiring diagnosis.
6. Logs identify whether each trigger was `OPPOSITE_SUMMARY` or `REAL_M1_REVERSAL`.
7. Zero triggers is **inconclusive**, not a pass. If no trigger occurs, choose a different three-day window based on available signal/position events rather than claiming the exit rule passed.

## Current status

Source-level logic inspection is complete. The earlier 2026-09-01 baseline produced nine trades, but its preserved logs did not show a rule-based exit trigger/completion; most exits were SL/TP. Therefore the early-exit behavior remains unverified by a completed Strategy Tester event.

The new diagnostic workflow has been committed to the isolated branch. Its execution status/results must be read from GitHub Actions before claiming runtime validation. The production candidate branch and default stop/target settings are unchanged.

## TradingView parity

The existing formula-level audit compares the EA's recorded votes with an independent implementation of published TechnicalRating v3 formulas. It does not replace a direct comparison against actual TradingView chart exports on matching symbol/feed/timestamps. Direct chart-runtime parity remains pending.
