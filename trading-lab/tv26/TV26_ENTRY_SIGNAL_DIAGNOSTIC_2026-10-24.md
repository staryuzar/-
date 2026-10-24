# TV26 entry-signal diagnostic — 2026-10-24

**Status:** hypothesis generation only. The trade sample is small and was selected after inspecting the same period. No entry-filter change is approved on this evidence.

## What the accepted-trade logs show

Baseline settings: XAUUSD M1, all five timeframe ratings must be above +0.50 or below -0.50; M1 close-breakout gate enabled with one-bar lookback and zero ATR buffer; SL 2 ATR, TP 4 ATR, risk 1%.

The reported MQL values at each accepted entry are:
- Sep 14 10:10 sell (SL): M1 -0.545, M5 -0.591, M15 -0.636, M30 -0.648, H1 -0.545.
- Sep 14 10:30 sell (SL): M1 -0.591, M5 -0.636, M15 -0.636, M30 -0.603, H1 -0.545.
- Sep 15 09:11 sell (SL): M1 -0.524, M5 -0.648, M15 -0.603, M30 -0.558, H1 -0.558.
- Sep 15 12:14 sell (SL): M1 -0.512, M5 -0.524, M15 -0.558, M30 -0.636, H1 -0.636.
- Sep 18 09:00 buy (TP): M1 +0.558, M5 +0.603, M15 +0.591, M30 +0.558, H1 +0.603.
- Sep 18 09:40 buy (SL): M1 +0.545, M5 +0.570, M15 +0.570, M30 +0.558, H1 +0.558.

## Technical diagnosis

The aggregate score can be high because of moving-average alignment even when the oscillator average adds little confirmation. Reconstructing the recorded MA and oscillator component averages for the corresponding last-closed bars shows the weakest signed oscillator score across M1/M5/M15/M30/H1 was:
- Sep 14 10:10 sell loss: -0.091
- Sep 14 10:30 sell loss: -0.091
- Sep 15 09:11 sell loss: -0.182
- Sep 15 12:14 sell loss: -0.091
- Sep 18 09:00 buy winner: +0.182
- Sep 18 09:40 buy loss: +0.091

This suggests two candidate entry-only filters worth comparing separately:
1. Require absolute aggregate rating >= 0.55 on all five timeframes.
2. Require the directional oscillator average itself to reach at least 0.15 on each timeframe.

These are not presumed to work. The first is being tested in workflow 40105626487. The second should be introduced only after current runs finish, then compared against its unchanged baseline on the same screen and a separate window. Do not combine both filters until each is tested in isolation, and do not accept a one- or two-trade result as evidence of a durable edge.

## Evidence limits

The source trade details come from an isolated MT5 Model 4 Strategy Tester run on the Headway-Demo XAUUSD feed. MT5 may synthesize ticks where broker history is missing. The formula audit had zero mismatches against the independently coded published TechnicalRating v3 rules on the exported MT5 OHLCV, but this is not direct parity with a live TradingView chart export, and this six-trade sample cannot establish profitability.
