# TradingView parity input — disabled for real chart market data

Do not upload a CSV containing TradingView chart prices or indicator outputs here. The automated workflow that processed chart exports has been disabled because TradingView's current market-data policy restricts non-display processing.

Use the display-only Pine dashboard instead:
- trading-lab/tv26/TradingView_Visual_Parity_5TF.pine

Compare the closed-bar timestamp and OHLC first, then the official summary ratings and component votes against the MT5 Arabic panel by eye. Do not use TradingView data as an EA input or strategy-test feed.

Official references:
- https://www.tradingview.com/policies/
- https://www.tradingview.com/support/solutions/43000614331-technical-ratings/

The old CSV decoder/comparator remain only for synthetic test fixtures and formula-contract regression tests; they are not an approved pipeline for real TradingView market data.
