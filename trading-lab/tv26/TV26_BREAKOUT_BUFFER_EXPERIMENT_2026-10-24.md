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

## Independent holdout result — 1–10 September

Workflow: [GitHub Actions run 40102679768](https://github.com/staryuzar/-/actions/runs/40102679768)

The two holdout jobs completed successfully using Model 4, XAUUSD M1, $500 initial deposit, 1:1000 leverage, 1% risk, SL 2 ATR, TP 4 ATR and the same close-breakout requirement. Only the buffer value differed.

| Buffer | Net P/L | Profit factor | Max equity DD | Trades | Wins / losses |
|---|---:|---:|---:|---:|---:|
| 0.00 ATR | +$3.35 | 1.23 | 2.48% | 5 | 2 / 3 |
| 0.10 ATR | +$13.06 | 3.97 | 1.54% | 3 | 2 / 1 |

Both runs passed data-integrity and formula-level audits: 371,332 votes compared each, zero vote mismatches, zero missing/invalid comparisons, zero duplicated rows, zero invalid OHLC candles, and zero summary aggregate mismatches.

The holdout improvement is promising but still a very small sample (three trades with the candidate). Trade records show the buffer changed entry timing and eliminated two losing short outcomes from the baseline sequence while retaining the two later winners; it did **not** filter the losing long on 10 September. That trade entered long at 4431.41 around 08:59 and closed by stop at 09:02:59 for -$4.40 in both variants. The 0.10 ATR variant had two profitable shorts (+$8.47 and +$8.99) and the same $4.40 loss, netting +$13.06. The loss means this holdout fails the strict “no losing trades” gate; do not extend this exact gate as if it passed.

## Acceptance decision

**Provisional candidate for further testing: 0.10 ATR. Not approved for live trading or merge.**

The independent period supports continuing research on 0.10 ATR, but 3 trades cannot establish a reliable edge. The remaining long-side loss points to a separate entry-quality question and must be studied separately; do not pretend the breakout buffer solved it. Before merge or live-use consideration, test additional independent periods, use realistic execution costs, and check for drawdown and loss-streak stability.

MT5 may synthesize replacement ticks in intervals where the broker's real-tick history is missing. The test is historical simulation and does not establish future returns.
