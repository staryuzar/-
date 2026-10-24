# TV26 Long-Entry M15 Rating Gate Experiment — 24 October 2026

## Status

This experiment remains on isolated branch `tv26-long-m15-gate-study`. It has **not** been merged into the candidate branch or main, and all orders in the evidence are simulated inside MT5 Strategy Tester only.

Workflow: [TV26 long-entry M15 rating gate matrix — run 40103113874](https://github.com/staryuzar/-/actions/runs/40103113874)

The experiment keeps the 26 component formulas and five timeframes (M1/M5/M15/M30/H1) unchanged. Fixed settings: XAUUSD M1, Model 4 Every tick based on real ticks, $500 initial balance, leverage 1:1000, 1% risk, SL 2 ATR, TP 4 ATR, M1 close-breakout required, extra breakout buffer 0.10 ATR. The only experimental variable is the minimum M15 technical-rating value required for BUY entries. Sell entries retain the original five-frame strong-rating requirement.

## Training-period results — 1–23 October 2026

| Metric | Original BUY threshold 0.50 | Experimental BUY threshold 0.58 |
|---|---:|---:|
| Net profit | +$19.92 | +$30.67 |
| Gross profit | $62.07 | $62.07 |
| Gross loss | -$42.15 | -$31.40 |
| Profit factor | 1.47 | 1.98 |
| Equity drawdown max | 4.54% | 4.54% |
| Total trades | 19 | 16 |
| Winning / losing trades | 7 / 12 | 7 / 9 |
| Short trades | 13 | 13 |
| Long trades | 6 | 3 |
| Strong-consensus bars | 80 | 68 |
| Minimum-volume risk-cap blocks | 14 | 13 |

The candidate improved net profit by $10.75 and reduced gross loss by $10.75, while gross profit, all 13 short trades and both profitable long trades remained unchanged in this sample. It removed three losing long trades. The M15 threshold did not eliminate every long-side loss: the accepted October 9 long entry remained a loser.

This is a more useful result than merely increasing the target or reducing lot size, but it is still an in-sample finding. The same data was used to formulate the M15 hypothesis, so the training result cannot be the acceptance test.

## Formula and data audit

Both variants compiled in MetaEditor without non-zero errors/warnings, passed the MT5 audit structure check, and passed the independent implementation of the published TradingView TechnicalRating v3 formulas on the recorded MT5 OHLCV. Each variant compared 799,708 component votes with zero mismatches and zero missing/invalid comparisons. The audit also reported zero invalid OHLC rows, zero duplicate rows and zero summary aggregate mismatches.

Scope: this is formula-level agreement on the tested Headway-Demo/Jarocel MT5 feed; it is not proof of equality to live TradingView chart outputs and is not a profitability guarantee.

## Independent holdout — 11–20 September 2026

The two holdout jobs are running with the same settings and only the BUY M15 threshold differing (0.50 vs 0.58). This interval was not used to choose the threshold. Results and formula/data audits will be added here once both jobs finish.

Do not merge or approve the 0.58 gate before checking holdout net P/L, profit factor, equity drawdown, losing-trade count, direction split and trade count. A high profit factor based on only one or two trades is not a pass. The experiment also must not be called successful if the extra threshold merely excludes nearly all trades.

## Acceptance decision

**Status: promising training result, pending holdout. Not approved for merge or live trading.**

All historical ticks may not be available in the broker feed; MT5 can synthesize replacement ticks in missing intervals. The results are historical simulations and do not establish future returns.
