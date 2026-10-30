from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .live_snapshot import build_live_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live BTC public-market connectivity check.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--output", default="artifacts/live_market_check.json")
    args = parser.parse_args()

    report = build_live_snapshot(symbol=args.symbol, interval=args.interval)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "symbol": report["symbol"], "as_of_utc": report["as_of_utc"],
        "sources": {name: item.get("status") for name, item in report["source_states"].items()},
        "decision": report["decision"]["action"], "blockers": report["decision"]["blockers"],
        "errors": report["errors"], "report": str(output),
    }, indent=2, ensure_ascii=False))
    required = ("spot", "orderflow", "derivatives")
    return 0 if all(report["source_states"].get(key, {}).get("status") == "fresh" for key in required) else 2


if __name__ == "__main__":
    sys.exit(main())
