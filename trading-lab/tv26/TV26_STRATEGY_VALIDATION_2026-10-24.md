# TV26 Strategy Validation — 24 October 2026

## 10-day baseline matrix result

Workflow: [run 40097583304](https://github.com/staryuzar/-/actions/runs/40097583304)

MT5 Strategy Tester used Model 4 (Every tick based on real ticks), XAUUSD, $500 initial deposit, 1:1000 leverage, 14–23 October 2026 inclusive. The tester-only guard was enabled; all orders were simulated and could not be sent to a live account. MT5 may synthesize ticks where broker real-tick history is unavailable.

| Variant | Net P/L | Profit factor | Max equity DD | Trades | Win rate | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Risk 0.5%, SL 2 ATR / TP 3 ATR, no breakout | +$1.00 | 1.44 | 0.50% | 2 | 50.0% | Too few trades; not a pass |
| Risk 1%, SL 2 ATR / TP 3 ATR, no breakout | -$7.32 | 0.73 | 3.92% | 11 | 27.3% | Fail |
| Risk 1%, SL 2 ATR / TP 3 ATR, M1 close breakout | -$1.40 | 0.93 | 2.72% | 9 | 33.3% | Better than baseline, still negative |
| Risk 1%, SL 1.5 ATR / TP 2.25 ATR, no breakout | -$23.57 | 0.46 | 7.47% | 15 | 20.0% | Fail; shorter stop performed materially worse |

All four jobs completed successfully, including EA compile, tester execution, audit structure validation, and independent formula vote comparison. Workflow success means the experiment ran and its evidence passed validation; it does not mean the strategy passed profitability criteria.

## What the trades tell us

- The default entry produced 8 losses and 3 wins over 11 trades. Several losses occurred shortly after entry, while two trades reached the target.
- Requiring the closed M1 candle to break the prior candle's high/low reduced the sample to 9 trades and reduced the loss from $7.32 to $1.40, but it did not produce positive expectancy.
- The 0.5% risk result is not statistically meaningful at only 2 trades and should not be selected based on the apparent positive profit factor.
- The 1.5 ATR stop / 2.25 ATR target setting was clearly worse in this sample. Do not adopt it.
- Across all variants, 39 bars produced strong five-timeframe consensus; minimum-volume risk protection blocked entries many times. Do not remove the protection simply to increase trade count.

## Formula audit

The same run compared 376,402 component votes against an independent implementation of the published TradingView TechnicalRating v3 rules, with zero vote mismatches and zero missing/invalid comparisons across M1, M5, M15, M30 and H1. OHLC integrity checks found zero invalid rows and zero aggregate mismatches.

Scope limitation: this establishes agreement between the recorded MT5 votes and the independent reference implementation on the tested Headway-Demo/Jarocel feed. It is not a comparison against live TradingView chart outputs, and it does not prove profitability.

## Next experiment

The follow-up workflow [TV26 breakout exit-parameter validation](https://github.com/staryuzar/-/actions/workflows/tv26-breakout-exit-validation.yml) compares exit settings over 1–23 October 2026, keeping the M1 close-breakout condition enabled in each variant:
- 1% risk, SL 2 ATR / TP 2.5 ATR
- 1% risk, SL 2 ATR / TP 4 ATR
- 1% risk, SL 1.5 ATR / TP 3 ATR
- 0.5% risk, SL 2 ATR / TP 3 ATR

The follow-up run is currently being evaluated. No setting is approved for live trading. Acceptance requires a materially larger sample, positive expectancy after realistic costs, controlled drawdown, data integrity, and out-of-sample confirmation.
