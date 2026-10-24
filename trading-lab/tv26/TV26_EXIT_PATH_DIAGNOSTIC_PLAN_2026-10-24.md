# TV26 rule-based exit-path diagnostic — 2026-10-24

## Purpose

Validate the candidate's early-exit behavior separately from ordinary stop-loss/take-profit exits. This is a diagnostic, not a strategy-performance run.

## Source behavior inspected

- Entry consensus is restricted to the three summaries M5, M15, and M30. All three must be complete and each rating must be above +0.50 for a buy or below -0.50 for a sell.
- For an open buy, any complete M5/M15/M30 rating below -0.10 requests an exit. For an open sell, any complete rating above +0.10 requests an exit.
- If no opposite summary is detected, an M1 closed candle triggers the price-reversal rule only if it closes in the opposite candle direction and beyond the extreme of the preceding three closed candles.
- The exit path emits `TV26_EXIT_TRIGGER`, then either `TV26_EXIT_COMPLETED` or `TV26_EXIT_FAILED`.
- Exit management is evaluated on a new M1 bar, not on every tick. This means the exit rule is bar-confirmed and may not close intrabar.

## Diagnostic setup

Workflow: `.github/workflows/tv26-exit-diagnostic.yml`  
Branch: `tv26-exit-diagnostic-study`  
Window: 2026-09-01 through 2026-09-03 inclusive  
Tester: MT5 Strategy Tester, Model 4 (real-tick mode), XAUUSD M1  
Risk: 1%; SL 5 ATR; TP 20 ATR; M1 entry breakout disabled  
Magic: 26102481  
Guards: tester-only and demo-only remain enabled by the existing runner.

Widened SL/TP are intended only to make rule-based exits easier to observe. Their performance metrics must not be compared with the baseline's 2 ATR / 4 ATR configuration.

## Acceptance criteria

1. MetaEditor compile and Strategy Tester finish successfully.
2. Audit CSV and OHLC history are present and valid.
3. Independent formula audit completes without missing or mismatched votes.
4. At least one `TV26_EXIT_TRIGGER` occurs.
5. Each trigger is paired with a successful `TV26_EXIT_COMPLETED`; any `TV26_EXIT_FAILED` is a failure requiring diagnosis.
6. Logs identify whether each trigger was `OPPOSITE_SUMMARY` or `REAL_M1_REVERSAL`.
7. Zero triggers is **inconclusive**, not a pass. If no trigger occurs, choose a different three-day window based on available signal/position events rather than claiming the exit rule passed.

## Completed first runtime diagnostic — workflow run 40130018918

Run: https://github.com/staryuzar/-/actions/runs/40130018918  
Artifact: tv26-exit-path-diagnostic-40130018918  
Effective source SHA-256: 18f967c14b12120e9bb13185d5184725f981b175b5a42a024df3f25c6fddbb41

- MetaEditor compiled the EA with zero errors and zero warnings; MT5 Strategy Tester Model 4 completed successfully.
- Data integrity and formula audits passed: 141,232 component votes compared, zero vote mismatches; 5,432 candle groups, zero invalid/duplicate/timestamp errors; 16,296 summary aggregate values re-calculated with zero mismatches.
- Three trades were opened and all three exited through REAL_M1_REVERSAL. Unique event log confirms three triggers, three completed closes, zero close failures.
- No OPPOSITE_SUMMARY trigger occurred. That branch is still unproven at runtime.
- The three trades all lost: net -$7.47, 0 winners / 3 losers, maximal equity DD 1.86%. They were diagnostic settings (risk 2%, SL 5 ATR, TP 20 ATR), so this is not a comparison with the candidate's default 1% / 2 ATR / 4 ATR settings.
- The MT5 HTML deal table confirms the 3 positions were closed by the EA's close command and not by SL/TP. The price-rule trigger did close losing positions, but only an exit-off comparison can show whether it improves or harms the outcome on the same window.

A first run (40128087743) did not produce an audit because MT5 cancelled preliminary tick-history download and stopped with “no history data”; this was classified as infrastructure failure, not as a strategy result. The retry wrapper now retries only this evidenced history-download failure, once, and preserves the first-attempt logs.

## Matched A/B validation in the isolated branch

The diagnostic-only source now has a default-true InpUseRuleBasedEarlyExit switch. When false in the A/B arm, the EA continues to hold the open position and does not permit another entry, while broker SL/TP remain active. The main candidate branch/source is unchanged.

Workflow: https://github.com/staryuzar/-/actions/runs/40130429104  
The workflow runs the exit-on and exit-off arms sequentially in one isolated Windows job, with the same MQL5 source hash, three-day dates (2026-09-01 through 2026-09-03), model, risk, SL/TP and reference history. It changes only the early-exit input and magic number. It saves each arm's logs separately, audits each arm independently, then checks hashes/settings and writes a matched comparison report.

Acceptance still requires equal source and history hashes, valid formula/data audits for both arms, successfully paired exit-on triggers, and no early-exit events in the exit-off arm. Profitability is evaluated separately from rule execution. The opposite-summary branch remains unvalidated until a reason=OPPOSITE_SUMMARY trigger is captured.

The production candidate branch and its default stop/target settings are unchanged.

## TradingView parity

The existing formula-level audit compares the EA's recorded votes with an independent implementation of published TechnicalRating v3 formulas. It does not replace a direct comparison against actual TradingView chart exports on matching symbol/feed/timestamps. Direct chart-runtime parity remains pending.


## 12. Confirmed close-path run with diagnostic switch explicitly enabled

Workflow: https://github.com/staryuzar/-/actions/runs/40130332691  
Artifact: https://github.com/staryuzar/-/actions/runs/40130332691/artifacts/12574199270  
Compiled source SHA-256: `cd69daff1268ac8d908a7563ee2535d1f403d3ca79a221235e3d5922c77cc5bf`  
Audit SHA-256: `a9cfc51942a55cb3b6c7328d0e3e6805ca0e4a69da2763c7d92700704ba3f106`  
Reference OHLCV SHA-256: `5fa5ea953cb7e5957bac8e5e8c3771550b58a3a56ae7a688131cd744db1cc21b`

The source was compiled and checked in MT5 Strategy Tester Model 4 with `InpUseRuleBasedEarlyExit=true`. The static entry/exit contract checks, MT5 exported-data integrity validation, and independent published-formula audit all passed. Audit coverage: 141,232 votes compared, zero vote mismatches; 5,432 candle groups checked with zero data integrity errors; 16,296 summary aggregates recalculated with zero mismatches.

| Position | Entry | Exit | Hold | Direction | Closed by | Net |
|---|---|---|---:|---|---|---:|
| 1 | 2026-09-01 07:45 | 2026-09-01 07:54 | 9 min | Sell | Confirmed M1 reversal | -$1.96 |
| 2 | 2026-09-01 09:30 | 2026-09-01 09:36 | 6 min | Sell | Confirmed M1 reversal | -$2.63 |
| 3 | 2026-09-02 23:00 | 2026-09-02 23:08 | 8 min | Buy | Confirmed M1 reversal | -$2.88 |

Total: **3 trades, 0 wins / 3 losses, -$7.47 net, 1.86% maximum equity drawdown**, risk 2%, SL 5 ATR and TP 20 ATR. These settings were deliberately widened for execution-path diagnostics and must not be compared with the default production configuration.

Unique log result: `REAL_M1_REVERSAL=3`, `OPPOSITE_SUMMARY=0`, `TV26_EXIT_COMPLETED=3`, `TV26_EXIT_FAILED=0`. The MT5 report's closing orders all have comment `TV26 close opposite`, which corroborates that the EA actually issued the close. This establishes a price-reversal close path, but the result is negative on all three trades and does not establish that early exits improve performance. The opposite-summary exit path remains unverified.

## 13. Latest matched A/B job

Workflow: https://github.com/staryuzar/-/actions/runs/40130429104

The latest diagnostic job passed the static entry/exit contract suite and is running two sequential MT5 arms with the same compiled source, broker history, dates, model, risk, stop and target. The only intended behavioral difference is `InpUseRuleBasedEarlyExit` true versus false. At the time of this report update, the run had not yet completed; no A/B performance conclusion is claimed. A report update is required after both arms and their data/formula audits finish.
