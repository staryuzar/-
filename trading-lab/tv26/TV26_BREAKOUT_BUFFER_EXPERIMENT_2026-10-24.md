# TV26 M1 Breakout Buffer Experiment — 24 October 2026

## Status

The source and test matrix are isolated on branch `tv26-breakout-buffer-study`. Nothing from this experiment has been merged into the candidate branch or main branch. All trades are simulated inside the MT5 Strategy Tester; this is not a live run.

- 23-day matrix: [GitHub Actions run 40102196337](https://github.com/staryuzar/-/actions/runs/40102196337)
- Independent 10-day holdout: [GitHub Actions run 40102679768](https://github.com/staryuzar/-/actions/runs/40102679768) — running at the time of this report.
- Instrument: XAUUSD, tester timeframe M1, ratings from M1/M5/M15/M30/H1.
- Period for first matrix: 2026-10-01 through 2026-10-23 inclusive.
- Model 4 (Every tick based on real ticks), $500 initial balance, 1:1000 leverage.
- Fixed settings across all four variants: 1.00% risk, SL 2.00 ATR, TP 4.00 ATR, M1 close-breakout required.
- Only the extra distance beyond the previous M1 candle high/low changed. The distance is measured as a fraction of M1 ATR from the last closed candle.

## Results on 1–23 October

| Extra breakout buffer | Net P/L | Profit factor | Max equity drawdown | Trades | Wins | Losses | Max consecutive losses |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.00 ATR (baseline) | +$12.51 | 1.27 | 4.77% | 20 | 7 | 13 | 6 |
| 0.05 ATR | +$12.51 | 1.27 | 4.77% | 20 | 7 | 13 | 6 |
| 0.10 ATR | +$19.92 | 1.47 | 4.54% | 19 | 7 | 12 | 6 |
| 0.20 ATR | +$18.94 | 1.45 | 4.54% | 19 | 7 | 12 | 6 |

All four jobs completed successfully. Each variant's source compiled without errors or warnings. The audit/data-integrity checks and independent formula comparison succeeded for all four variants. Each compared 799,708 component votes, with zero vote mismatches and zero missing/invalid comparisons; the exported audit had zero duplicate rows, zero invalid OHLC rows, and zero summary aggregate mismatches. This is formula-level agreement on the tested MT5 feed, not proof of equality with live TradingView chart output.

## Interpretation

- 0.05 ATR had no effect: it produced the same 20 trades and identical deal-by-deal returns as the 0.00 ATR baseline in this period.
- 0.10 ATR was the best of these four variants on this particular period: net profit improved by $7.41 versus baseline, profit factor rose from 1.27 to 1.47, drawdown reduced from 4.77% to 4.54%, and trade count fell by only one (20 to 19).
- 0.20 ATR was slightly worse than 0.10 ATR: +$18.94 vs +$19.92, with the same 19 trades and same 7 winners / 12 losers.
- The improvement at 0.10 ATR came with the same maximum losing streak of six. The sample still contains more losing trades than winning trades; the net gain depends on the relative size of winners and losers.
- The 0.10 ATR run did not merely remove a large set of trades: it retained 19 of 20 entries. However, entry timing changed on one profitable short around 7 October, as well as excluding a losing short on 20 October; this is exactly why an independent-period check is necessary.

## Independent holdout

A second, two-variant test has been started on 2026-09-01 through 2026-09-10, with the same 1% risk, SL 2 ATR, TP 4 ATR, breakout requirement, tester model, and initial balance. Only the buffer differs (0.00 vs 0.10 ATR). This period was not used to pick the buffer value. The results must be evaluated before deciding whether to keep the feature.

## Acceptance decision

**Provisional candidate for further testing: 0.10 ATR. Not approved for live trading or merge.**

Do not select a parameter solely from this 23-day backtest. The change remains experimental until the September holdout confirms that the benefit persists with valid, isolated evidence and without excessive drawdown. A positive holdout is still not proof of a durable edge; additional periods and realistic cost sensitivity remain necessary.

MT5 may synthesize replacement ticks in intervals where the broker's real-tick history is missing. The test is historical simulation and does not establish future returns.
