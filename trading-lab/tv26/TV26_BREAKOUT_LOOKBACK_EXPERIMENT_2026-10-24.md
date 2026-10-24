# TV26 M1 breakout lookback experiment — 2026-10-24

**Status:** screening only; no production recommendation. Isolated branch: `tv26-breakout-lookback-study`. No merge to main.

## Test design

- Symbol: XAUUSD, Headway-Demo / Jarocel (Pty) Ltd.
- MT5 Strategy Tester: Every tick based on real ticks (Model 4); tester may synthesize ticks where broker tick history is missing.
- Window: 2026-09-14 through 2026-09-18 inclusive.
- Deposit: $500; risk 1%; stop 2 ATR; target 4 ATR.
- M1 close-breakout gate enabled; extra ATR buffer 0.
- One configuration parameter changes: number of prior closed M1 candles whose extreme must be broken by the most recently closed candle.
- The test window is a diagnostic screen chosen after inspecting trades on this same period; it is therefore not an independent holdout and should not be used to claim generalization.

## Current results

| Prior bars required | Net profit | Profit factor | Equity DD max | Trades | Wins / losses |
|---:|---:|---:|---:|---:|---:|
| 1 (baseline) | -$11.41 | 0.43 | 3.39% | 6 | 1 / 5 |
| 3 | -$7.57 | 0.54 | 2.63% | 5 | 1 / 4 |
| 5 | Pending | Pending | Pending | Pending | Pending |

Sources:
- Workflow run: https://github.com/staryuzar/-/actions/runs/40105195141
- 1-bar artifact: `tv26-lookback-screen-1bars-40105195141`
- 3-bar artifact: `tv26-lookback-screen-3bars-40105195141`

The 3-bar variant preserved the Sep 18 09:00 buy winner (+$8.78), retained both Sep 14 sell losses, shifted the Sep 15 09:11 losing sell to 09:12 (its loss increased from -$3.84 to -$4.01), and blocked the Sep 15 12:14 losing sell (-$4.01). This makes the net improvement +$3.84 against baseline, despite a slightly worse remaining loss at the shifted entry.

Both finished runs passed MetaEditor compilation with 0 errors and 0 warnings. Their exported audit data and independent published-formula comparisons passed:
- Lookback 1: 235,300 votes checked; 0 mismatches; 9,050 candle groups checked; zero invalid OHLC rows, duplicates, or timestamp errors.
- Lookback 3: same audit and history SHA-256 values as the 1-bar run; 235,300 votes checked; 0 mismatches; clean OHLC integrity.

These audits validate code/formula behavior on this MT5 broker feed; they are not direct comparisons with a user's live TradingView chart export and do not validate profitability.

## Interpretation / next gate

The 3-bar screen is less negative, not profitable. Do not promote it on this evidence. Finish the 5-bar screen, then test the best-looking value on a separate, untouched period before accepting any change. Preserve risk controls and the 0.01-lot minimum-risk cap; do not loosen them merely to increase trades.
