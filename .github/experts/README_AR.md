# XAUUSD Trend-Pullback EA — Research Candidate 1.00

## Purpose
A conservative research candidate for MetaTrader 5. It is not represented as profitable or production-ready.

## Signal logic
- Direction gate: H1 EMA(50) versus EMA(200).
- Entry timeframe: M15.
- Entry: completed candle crosses the M15 EMA(20) in the H1 trend direction and RSI(14) crosses 50 in the same direction.
- Stop loss: 2.0 × M15 ATR(14).
- Take profit: 3.0 × M15 ATR(14).
- Break-even management: after price moves 1.0 × ATR in favor, move stop to entry.
- One open position per symbol and magic number; no immediate same-bar re-entry.
- Spread filter defaults to 100 points. Check the broker's XAUUSD point/digits convention before testing.

## Risk controls
- Default risk: 0.50% of current equity per trade.
- Daily equity loss lock: pause new entries after a 3% loss relative to the equity recorded at the start of the broker-server day.
- Volume is rounded down to the broker's volume step. If calculated volume is below minimum, the EA skips rather than rounding risk up.
- No grid, martingale, averaging down, or automatic reversal.
- These are guardrails, not guarantees. Gaps, slippage, commissions, swaps, and broker execution can increase actual losses.

## Current validation state
- Source review only until GitHub Actions compiles this exact file using MetaEditor.
- Compile success is not a backtest. A real MT5 Strategy Tester run needs broker-compatible XAUUSD history and an explicit tester report.
- Do not attach to a live account. Start with demo/backtest only.
