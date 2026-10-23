# TV26 Strategy Tester — preliminary 3-day result

**Run date:** 2026-10-23  
**GitHub Actions run:** https://github.com/staryuzar/-/actions/runs/39972607072  
**Full artifact:** https://github.com/staryuzar/-/actions/artifacts/12510365482

## Results

The first strategy simulation completed. This is the first actual order-level outcome, separate from the earlier indicator formula audit.

| Metric | Result |
|---|---:|
| Test dates | 2026-09-01 to 2026-09-03 inclusive |
| Starting deposit | USD 500.00 |
| Net profit | **-USD 2.42** |
| Total trades | 1 |
| Winning trades | 0 (0%) |
| Losing trades | 1 (100%) |
| Profit factor | 0.00 |
| Expected payoff | -USD 2.42 per trade |
| Maximum balance drawdown | USD 2.42 (0.48%) |
| Maximum equity drawdown | USD 4.43 (0.88%) |
| Holding time | 18 minutes 20 seconds |

## The trade

- XAUUSD sell; 0.01 lot.
- Entry time shown by the tester: 2026-09-01 07:45:00.
- Actual deal entry: 4427.54.
- Stop loss: 4429.96; take profit: 4423.91.
- Exit: 2026-09-01 08:03:20 at 4429.96, stop-loss comment.
- Realized result: -USD 2.42.

The single loss is approximately 0.484% of the USD 500 initial deposit, near the nominal 0.5% risk setting. This one trade does not establish that risk sizing always behaves correctly.

## Safety and audit integrity

- The run was a historical MT5 Strategy Tester simulation on an isolated GitHub-hosted Windows terminal, not a live account execution.
- InpEnableTrading=true was accepted only with InpTesterOnly=true and InpDemoOnly=true. The EA now blocks trading outside Strategy Tester when tester-only mode is enabled.
- Model: 1-minute OHLC, not real ticks.
- MT5 exported 5,432 complete summary candles and 141,232 component votes across M1/M5/M15/M30/H1.
- Audit-file integrity and aggregate score arithmetic passed with zero missing/invalid rows and zero aggregate mismatches.
- Independent published-formula audit passed all 141,232 votes with zero mismatches. This is not a direct comparison to a live TradingView Pine export.

## Decision

**The strategy is not yet demonstrated profitable.** One trade over three days is too small a sample; it is not statistically meaningful and it should not be optimized to this single outcome. A follow-up test has been set to extend the same parameters to ten days, 2026-09-01 through 2026-09-10 inclusive. Evaluate trade count, net profit, profit factor, drawdown, win/loss distribution, and whether every input was actually applied. Do not accept positive net profit by itself as a pass.


## Follow-up baseline: ten days and entry-block diagnostics

- **Run:** https://github.com/staryuzar/-/actions/runs/39974692726
- **Artifact with redacted logs:** https://github.com/staryuzar/-/actions/artifacts/12511017230
- **Date window:** 2026-09-01 through 2026-09-10 inclusive.
- **Net result remains:** -USD 2.42; 1 total trade, 0 winners, 1 loser; profit factor 0.00; maximum equity drawdown USD 4.43 (0.88%).
- **Formula audit:** PASS across all five frames; 371,332 vote comparisons, 0 mismatches, 0 missing values.
- **Data validation:** PASS; 14,282 complete summary candles and 371,332 component votes are present.

### Why most signals did not become orders

MT5 journal instrumentation records 122 M1 bars on which the five-frame consensus was strong. Of those, 116 entry attempts were blocked by the minimum-volume risk cap. There were 0 spread blocks and 0 ATR-not-ready blocks. The broker minimum is 0.01 lot; a lot cannot be rounded below that minimum while still claiming to preserve the configured risk budget.

A concrete blocked attempt on 2026-09-01 at 15:59 had equity USD 497.58 and a risk budget USD 2.49. ATR was 2.74286, so a 2-ATR stop distance was USD 5.49. MT5 OrderCalcProfit estimated a USD 5.49 loss for the minimum 0.01 lot at that stop, more than twice the available risk budget. The EA correctly refused that entry. Some later blocked attempts had even wider stops.

This explains the low trade count under current constraints. It is **not** a reason to raise the risk percentage or override the minimum volume safety check.

A separate tester-only variant now uses **SL=1 ATR, TP=1.5 ATR, risk still 0.5%**, with the same 2026-09-01 through 2026-09-10 period. The default EA settings are unchanged. Compare this variant against the 2-ATR/3-ATR baseline using trade count, net profit, profit factor, drawdown and stop-out details; do not select it merely because it generates more trades or a positive ten-day result.
