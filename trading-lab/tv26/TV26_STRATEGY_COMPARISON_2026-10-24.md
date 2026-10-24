# TV26 strategy comparison — 24 October 2026

## Test protocol

- Symbol/account environment: XAUUSD, Headway-Demo / Jarocel (Pty) Ltd.
- Tester: MetaTrader 5 build 5.0.0.6283 on an isolated Windows GitHub Actions runner.
- Period: 21–23 October 2026 inclusive; MT5 ToDate 2026-10-24 is exclusive.
- Deposit: 500 USD; leverage 1:1000.
- Model requested: `Model=4`, Every tick based on real ticks.
- Safety: `InpDemoOnly=true` and `InpTesterOnly=true`; orders were simulated only inside Strategy Tester. No live orders.
- Tick logs report “generating based on real ticks”, tick history beginning 2026-10-21 00:00, 1,783,759 ticks, and 4,119 M1 bars. The archived logs do not provide a quantified percentage of missing-minute replacements, so this report does not claim 100% of all modeled ticks were broker-provided real ticks.
- All three completed runs passed MT5 audit CSV integrity checks and an independent implementation of the published TechnicalRating v3 voting rules: 141,232 component votes checked across M1/M5/M15/M30/H1, zero mismatches. This is parity within the recorded MT5 feed, not direct parity with a live TradingView chart.

## Results

| Variant | Net profit | Profit factor | Expected payoff | Balance max DD | Equity max DD | Trades | Wins / losses | Risk-cap blocks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Risk 0.50%, SL 2 ATR, TP 3 ATR | $0.00 | 0.00 | $0.00 | $0.00 (0.00%) | $0.00 (0.00%) | 0 | 0 / 0 | 28 |
| Risk 0.50%, SL 1 ATR, TP 1.5 ATR | +$2.15 | 2.38 | $1.08 | $1.56 (0.31%) | $3.41 (0.68%) | 2 | 1 / 1 | 22 |
| Risk 1.00%, SL 2 ATR, TP 3 ATR | +$4.39 | 2.42 | $2.20 | $3.09 (0.62%) | $4.94 (0.99%) | 2 | 1 / 1 | 22 |
| Risk 1.00%, SL 1 ATR, TP 1.5 ATR | **RUNNING when this report was created** | — | — | — | — | — | — | — |

Evidence:
- [Baseline: risk 0.50%, SL 2 ATR / TP 3 ATR — run 40090855343](https://github.com/staryuzar/-/actions/runs/40090855343) · [artifact](https://github.com/staryuzar/-/actions/runs/40090855343/artifacts/12559117226)
- [Risk 0.50%, SL 1 ATR / TP 1.5 ATR — run 40090855322](https://github.com/staryuzar/-/actions/runs/40090855322) · [artifact](https://github.com/staryuzar/-/actions/runs/40090855322/artifacts/12558658609)
- [Risk 1.00%, SL 2 ATR / TP 3 ATR — run 40090855320](https://github.com/staryuzar/-/actions/runs/40090855320) · [artifact](https://github.com/staryuzar/-/actions/runs/40090855320/artifacts/12558877943)
- [Risk 1.00%, SL 1 ATR / TP 1.5 ATR cross-check — run 40091113606](https://github.com/staryuzar/-/actions/runs/40091113606)

## Diagnosis

1. The baseline's zero trades are explained by the risk-cap guard, not by missing indicator values or an EA startup failure. The run recorded 28 consensus-signal bars; every one was blocked because the minimum 0.01-lot stop-loss estimate exceeded the 0.50% equity budget (about $2.50 on a $500 account). For example, a 3.05 price-unit stop implies about $3.05 loss at 0.01 lot, already above the budget.
2. The two variants that traded each took only two short positions: one winner and one loser; neither generated a long entry in this three-day sample. The positive net results are too small a sample to qualify the strategy as profitable.
3. In both trading variants, 22 signal bars were blocked by the same minimum-volume risk guard. This is a material execution constraint at the tested deposit/lot step/ATR distances; do not disable the guard or force the minimum lot just to increase trade count.
4. The more informative next comparison is the pending 1.00% risk / 1 ATR stop / 1.5 ATR target run, which isolates the effect of risk sizing while retaining the same stop/target multiples.
5. Direct TradingView parity remains **PENDING** until the real `TV26_AllTF.csv` export is present. None of these MT5 formula-audit passes proves equality to current TradingView chart values. Profitability also remains unproven; a longer and preferably independent holdout is needed after the current short-window diagnostic.

## Decision

Do not approve this candidate for live trading. Keep the minimum-volume risk cap, preserve the per-trade diagnostics, finish the fourth controlled comparison, then expand testing only after interpreting these entry-block causes and obtaining direct TradingView parity evidence.
