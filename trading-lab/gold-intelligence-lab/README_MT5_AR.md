# Gold Intelligence Lab — MT5 Expert Advisor

This folder contains the MQL5 source and a reproducible Windows CI build for the Gold Intelligence Lab expert advisor.

## What this version does

- Uses a fast/slow EMA trend filter.
- Looks for a closed-candle Donchian breakout.
- Uses ATR-based stop distance and a configurable reward/risk target.
- Calculates position size with OrderCalcProfit, rounds volume down to the broker step, and refuses a volume below the broker minimum rather than rounding risk upward.
- Checks spread, per-day trade count, per-day equity loss, maximum equity drawdown, current EA position, terminal/trading permissions, and the broker's stop distance.
- Shows the current signal/state on the chart.
- In signal-only mode, the chart status retains whether a BUY or SELL setup was detected.
- Daily-loss and maximum-drawdown guards block new EA entries; they do not automatically close already-open positions.

## Safety defaults

- EnableTrading=false: the EA shows state/signals and places no trades.
- AllowRealAccountTrading=false: it refuses new entries on a real account even if EnableTrading is enabled.
- The default CI workflow downloads MT5 to an isolated GitHub Actions runner, compiles the EA, and creates a ZIP artifact. It does not log into an account or place orders.

The real-account guard is an extra safeguard, not a proof that a trading strategy is safe. The risk-per-lot estimate is broker/symbol dependent. Check XAUUSD's contract size, minimum volume, volume step, tick size, tick value, spread, commissions, swaps and trading sessions for your broker before running any test or live instance.

## Build and test

The GitHub Actions workflow is .github/workflows/gold-lab-mql5-build.yml.

It performs:
1. Static safety-contract tests.
2. Download and isolated installation of the official MetaTrader 5 terminal.
3. Compilation with MetaEditor (requires zero errors and zero warnings).
4. Packaging of the MQ5, EX5, compile log, and this guide.

The downloadable build is published as a workflow artifact named GoldIntelligenceLab-MT5-Windows.

## Install the compiled EA

1. In MT5, choose File → Open Data Folder.
2. Open MQL5/Experts.
3. Copy GoldIntelligenceLabEA.ex5 there (or copy the source and compile it in MetaEditor).
4. In Navigator, right-click Expert Advisors → Refresh.
5. Open an XAUUSD chart and attach the EA.
6. Keep EnableTrading=false initially and check that the panel updates.
7. Run a historical Strategy Tester report with the exact broker symbol and settings before considering any live use.

For backtesting, set EnableTrading=true only inside the Strategy Tester settings. Do not enable live trading just to perform a backtest. The compiled build test is not a backtest and does not establish profitability.

## Current scope and limitations

This EA is a research baseline, not a promise of profit. It does not include a live economic calendar, AI image analysis, or automatic TradingView parity. In live terminal use, it stores initial equity, day-start equity, and daily trade count in MT5 terminal global variables keyed by environment/account/symbol/magic number, so ordinary restarts do not immediately reset these guards. Strategy Tester initializes separate in-memory baselines per test run. Terminal global variables are local to that MT5 installation and can expire after extended inactivity; keep a separate record of intended risk limits. The current CI workflow verifies compilation, not trading performance. A broker-specific real-data Strategy Tester run is still required before considering unattended use.
