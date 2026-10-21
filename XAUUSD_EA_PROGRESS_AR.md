# XAUUSD EA — Progress report (2026-10-21)

## What changed
- Created branch `xauusd-ea-dev` from `gold-xauusd-expert-lab`.
- Added a first research candidate at `.github/experts/XAUUSD_TrendPullback_EA.mq5`.
- The strategy uses H1 EMA trend confirmation, M15 EMA pullback plus RSI-50 cross, ATR-based SL/TP, 0.5% default risk, one position per magic, and a 3% daily equity-loss entry lock.
- Added explicit documentation that compile evidence is not a profitability claim.

## Verification status
- This commit creates the candidate source and review documents only.
- The next code commit will wire the exact source into the existing Windows/MT5 workflow so MetaEditor compiles the candidate itself, not only a disposable smoke-test EA.
- No Strategy Tester report is available yet. Do not describe this candidate as profitable or validated for live trading.

## Next steps
1. Add exact-source MetaEditor compilation to `.github/scripts/mt5_install_smoke.ps1`.
2. Run the Windows validation workflow and inspect the MT5 artifact and compile log.
3. If compilation passes, implement a controlled three-day Strategy Tester job using explicit XAUUSD history, tick model, spread/commission settings, and an archived HTML report. If the required data or tester capabilities are unavailable in CI, document the blocker rather than substituting a simulation.
4. Fix all compiler/runtime issues found, then test a separate date range before considering any demo forward test.
