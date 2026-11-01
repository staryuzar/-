from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mirsad.engines.market import MarketEngine

def main() -> int:
    print("Mirsad BTC live market connection check — real public endpoints only.")
    snapshot=MarketEngine().collect()
    for name,venue in snapshot["venues"].items():
        print(f"{name}: {venue['status']} | latency_ms={venue.get('latency_ms')} | error={venue.get('error')}")
    if snapshot.get("price") is None or snapshot.get("venue_count",0)<1:
        print("FAIL: no live public BTC/USDT market feed was reachable.")
        return 1
    if not snapshot.get("primary_venue"):
        print("FAIL: live price returned without a primary venue.")
        return 1
    print(f"PASS: live BTC/USDT reference price={snapshot['price']}; venue={snapshot['primary_venue']}")
    print("No order was placed or simulated.")
    return 0
if __name__=="__main__": raise SystemExit(main())
