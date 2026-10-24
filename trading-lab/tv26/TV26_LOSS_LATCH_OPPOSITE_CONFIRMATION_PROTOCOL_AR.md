# TV26 opposite-consensus-after-loss latch — research protocol

**Status:** research only; not merged into the TV26 candidate/main branch.  
**Source base:** candidate snapshot used by commit `5562380d5661b2646d97b02403894685a1166d82`. The neutral-while-position-open latch is already present in that base.  
**Primary reproduction:** MT5 Model 4, XAUUSD M1, 20–22 October 2026, $500, risk 1%, SL 2 ATR, TP 4 ATR, M1 closed-candle breakout on, global cooldown zero.

## Hypothesis captured before reading the A/B result

On 20 October the first sell was accepted at 11:08 and stopped at 11:11:38 for -$3.81. The following 11:11 closed bar was neutral while flat, so the ordinary signal latch re-armed at 11:12. The all-timeframe consensus then returned to strong sell at 11:30 (M1 -0.558, M5 -0.636, M15 -0.512, M30 -0.603, H1 -0.648); the second sell stopped at 11:32:19 for -$3.07. The rule under test is not a timer: after a fully closed position whose complete deal lifecycle is net negative, block another order in that same direction until an opposite-direction strong-consensus order is accepted. A neutral reading does not clear the loss state. The opposite order must be accepted (not merely signaled) to release it.

## Design and guardrails

- Parameter `InpRequireOppositeSignalAfterLossBeforeReentry` defaults to `false`; tests explicitly set it to true/false.
- Calculate net position result over position-linked deals including profit, swap, commission, and fee. Do not arm on partial closes or when history cannot be read.
- Persist direction state by symbol and Magic for restart safety. Clear only after an opposite-direction order has been accepted.
- No forced waiting period, no daily-loss lock, no alteration to the 26 ratings, and no modification to the M1 breakout formula.
- Each A/B pair uses the same EA source and price history, with only the experimental parameter different. Each arm must pass MetaEditor compilation, OHLC integrity, and the independent 26-vote formula audit.
- All arms use Strategy Tester only, demo-only protection, $500 initial balance, 1% risk, SL 2 ATR, TP 4 ATR, Model 4, and no global cooldown.

## Windows

1. Oct 20–22: the three-day event reproduction.
2. Sep 1–10: independent earlier window with re-entry opportunities.
3. Sep 11–20: separate September holdout.
4. Oct 1–10: separate October holdout.

## Decision gates

First confirm the primary event is blocked and the diagnostic log shows the loss-state latch armed from a fully closed net-losing sell. Then compare net profit, PF, equity DD, trades, missed winners, and blocked-entry events across all windows. Do not accept merely because trade count or drawdown falls. If the gate introduces material lost winners or reduces results on independent windows, reject it or redesign it. Even a favorable A/B matrix is not a claim of strategy robustness; more periods and a forward holdout remain necessary.
