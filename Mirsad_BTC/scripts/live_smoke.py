from __future__ import annotations

import os

from mirsad.engines.mt5_market import MT5MarketDataEngine


def main() -> int:
    print("Mirsad BTC — MT5-only market feed smoke check. No external exchange APIs are queried.")
    market = MT5MarketDataEngine().collect()
    print(
        f"Engine 1: {market['status']} | source={market.get('source')} "
        f"| venue_count={market.get('venue_count')} | reason={market.get('reason')}"
    )
    if market.get("status") == "LIVE" and market.get("source") == "MT5_TERMINAL":
        print("PASS: fresh MT5 broker quote and multi-timeframe OHLC snapshot are available.")
        return 0
    if market.get("status") == "NOT_CONFIGURED" and os.getenv("GITHUB_ACTIONS") == "true":
        print("SKIP: isolated GitHub runner has no attached user's MT5 Common Files folder.")
        print("The parser, freshness, OHLC, symbol/server and Engine 4 contracts are covered by unit tests.")
        return 0
    print("WAIT: MT5 feed is not decision-ready. Engine 4 must remain WAIT; no order is published.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
