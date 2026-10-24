# TV26 strategy comparison — 24 October 2026

## Test protocol

- Symbol: XAUUSD, Headway-Demo / Jarocel (Pty) Ltd.
- Tester: MetaTrader 5 build 5.0.0.6283 on isolated Windows GitHub Actions runners.
- Period: 21–23 October 2026 inclusive; MT5 `ToDate=2026.10.24` is exclusive.
- Deposit: 500 USD; leverage 1:1000.
- Requested model: `Model=4`, Every tick based on real ticks. The latest completed MT5 tester reports show `History Quality: 100% real ticks`, 4,119 M1 bars and 1,783,759 ticks for the tested window.
- Safety: `InpDemoOnly=true` and `InpTesterOnly=true`; trades were simulated only inside Strategy Tester. No live orders.
- The controlled strategy runs and latest indicator audit passed MT5 audit integrity and the independent published TechnicalRating v3 vote audit: 141,232 component votes checked across M1/M5/M15/M30/H1, zero mismatches. This is agreement within the recorded MT5 feed, not direct parity with a live TradingView chart.
- The first version of the log summarizer doubled diagnostic counts because MT5 mirrored EA event payloads into both terminal and tester-agent logs. The script now deduplicates event payloads before counting and has a regression test. The table below uses corrected unique counts.

## Latest comparable results

| Variant | Net profit | Profit factor | Expected payoff | Balance max DD | Equity max DD | Trades | Wins / losses | Unique min-lot risk-cap blocks | Same-signal latch blocks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Risk 0.50%, SL 2 ATR, TP 3 ATR | $0.00 | 0.00 | $0.00 | $0.00 (0.00%) | $0.00 (0.00%) | 0 | 0 / 0 | 14 | 0 |
| Risk 0.50%, SL 1 ATR, TP 1.5 ATR | +$2.15 | 2.38 | $1.08 | $1.56 (0.31%) | $3.41 (0.68%) | 2 | 1 / 1 | 11 | 0 |
| Risk 1.00%, SL 2 ATR, TP 3 ATR | +$4.39 | 2.42 | $2.20 | $3.09 (0.62%) | $4.94 (0.99%) | 2 | 1 / 1 | 11 | 0 |
| Risk 1.00%, SL 1 ATR, TP 1.5 ATR | **−$8.31** | **0.50** | **−$1.19** | $8.31 (1.66%) | $9.26 (1.85%) | 7 | 2 / 5 | 0 | 2 |
| Risk 1.00%, SL 1.5 ATR, TP 2.25 ATR | −$3.60 | 0.80 | −$0.60 | $9.15 (1.83%) | $10.93 (2.19%) | 6 | 2 / 4 | 0 | 1 |
| Risk 1.00%, SL 2 ATR, TP 3 ATR + M1 close-breakout gate | +$7.48 | 0.00* | +$7.48 | $0.00 (0.00%) | $3.76 (0.74%) | 1 | 1 / 0 | 6 | 0 |

All four runs recorded 14 unique strong-consensus M1 bars in the sample, all in the sell direction; none generated a buy entry in this short window. The four configurations differed only in risk percentage and ATR stop/target multiples, and all used the same date window and tester model.

## Evidence and artifacts

- Baseline, risk 0.50%, SL 2 ATR / TP 3 ATR: [run 40091401815](https://github.com/staryuzar/-/actions/runs/40091401815) · [artifact 12558958498](https://github.com/staryuzar/-/actions/runs/40091401815/artifacts/12558958498).
- Risk 0.50%, SL 1 ATR / TP 1.5 ATR: [run 40091401821](https://github.com/staryuzar/-/actions/runs/40091401821) · [artifact 12558628127](https://github.com/staryuzar/-/actions/runs/40091401821/artifacts/12558628127).
- Risk 1.00%, SL 2 ATR / TP 3 ATR: [run 40091401750](https://github.com/staryuzar/-/actions/runs/40091401750) · [artifact 12558774315](https://github.com/staryuzar/-/actions/runs/40091401750/artifacts/12558774315).
- Risk 1.00%, SL 1 ATR / TP 1.5 ATR: [run 40091841108](https://github.com/staryuzar/-/actions/runs/40091841108) · [artifact 12559002839](https://github.com/staryuzar/-/actions/runs/40091841108/artifacts/12559002839).
- Risk 1.00%, SL 1.5 ATR / TP 2.25 ATR: [run 40091841057](https://github.com/staryuzar/-/actions/runs/40091841057).
- Risk 1.00%, SL 2 ATR / TP 3 ATR with M1 close-breakout gate enabled: [run 40091841138](https://github.com/staryuzar/-/actions/runs/40091841138) · [artifact 12559019122](https://github.com/staryuzar/-/actions/runs/40091841138/artifacts/12559019122).
- [Latest comparator tests — 45 tests passed](https://github.com/staryuzar/-/actions/runs/40091850547).
- [Latest MetaEditor compile](https://github.com/staryuzar/-/actions/runs/40091850504).
- [Latest MT5 indicator audit, trading disabled](https://github.com/staryuzar/-/actions/runs/40091850456).
- [Latest comparator tests — 43+ deterministic tests, including event-count deduplication](https://github.com/staryuzar/-/actions/runs/40091409767).
- [Latest MetaEditor compile](https://github.com/staryuzar/-/actions/runs/40091409783).
- [Latest MT5 indicator audit](https://github.com/staryuzar/-/actions/runs/40091409786).

## Diagnosis

1. **The zero-trade baseline was blocked by the risk cap, not by missing indicators or a startup failure.** Of 14 unique strong-consensus bars, all 14 were blocked because the estimated stop-loss of the broker minimum 0.01 lot exceeded the 0.50% equity budget (about $2.50 on $500). For example, a 3.05 price-unit stop implies about $3.05 loss at 0.01 lot, already above budget.
2. **The two positive-result variants are not demonstrated profitable.** Each traded only twice, both sells, with one win and one loss. Profit factors 2.38 and 2.42 are not meaningful evidence of robustness with two trades.
3. **Raising risk to 1% with the wider 2 ATR stop lets two trades through, but does not show the strategy has an edge.** It earned $4.39 in this sample on one winning and one losing trade, while still recording 11 unique risk-cap blocks.
4. **Risk 1%, SL 1 ATR / TP 1.5 ATR performed poorly.** Seven sells generated two winners and five losses, net −$8.31, PF 0.50 and 1.85% maximum equity drawdown. The tester report shows several stop-outs happened quickly (within about 19–99 seconds for four of the losing trades), while the two winning trades lasted about 4 and 19 minutes. This suggests the tighter stop is vulnerable to short-term noise with the current entry timing in this sample; it is not enough data to generalize.
5. **Keep the minimum-volume risk cap.** It is correctly preventing a trade when the broker's 0.01 minimum lot cannot honor the configured risk budget. Do not force a minimum lot or disable the cap just to increase trade count. Any change to entry timing, confirmation or stop distance must be tested as a separate controlled variant, not assumed to improve expectancy.
6. **TradingView parity is still pending.** The current tests prove agreement between MT5 recorded votes and an independent implementation of published TechnicalRating v3 rules on the same MT5 candles. They do not prove numeric equality with TradingView's live chart. Direct parity requires a real `TV26_AllTF.csv` exported by the Pine reference on the actual XAUUSD chart. Strategy profitability is also not proven; the three-day window and 2–7 trades per configuration are too small to qualify the EA.

7. **The optional M1 close-breakout gate produced +$7.48 but only one trade.** It reduced the test to one sell, with no losing trade and no broker rejection; six signals were still blocked by the min-lot risk cap. The reported PF of 0.00 is not interpretable with zero gross loss/one trade. Treat this as a hypothesis worth retesting, not as evidence of a positive edge. It must pass a longer holdout and be compared across more than one market regime.

## Decision

Do not approve the candidate for live trading. Keep the risk guard, preserve the event deduplication, then prioritize direct TradingView parity and a broader held-out test window after the indicator definitions match. Any next strategy change should be a single-variable test with the same date window and real-tick model.
