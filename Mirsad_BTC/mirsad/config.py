from __future__ import annotations
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA_DIR=Path(os.getenv("MIRSAD_DATA_DIR",str(ROOT/"data"))).expanduser()
DB_PATH=DATA_DIR/"mirsad.sqlite3"
STATUS_PATH=DATA_DIR/"system_status.json"
SNAPSHOT_PATH=DATA_DIR/"latest_market.json"
CHART_DIR=DATA_DIR/"charts"
CHART_METADATA_PATH=DATA_DIR/"chart_metadata.json"
SYMBOL=os.getenv("MIRSAD_SYMBOL","BTCUSDT").upper()
COLLECT_INTERVAL_SECONDS=max(5,int(os.getenv("MIRSAD_COLLECT_SECONDS","10")))
MARKET_MAX_AGE_SECONDS=max(15,int(os.getenv("MIRSAD_MARKET_MAX_AGE","35")))
MT5_HEARTBEAT_MAX_AGE_SECONDS=max(5,int(os.getenv("MIRSAD_MT5_HEARTBEAT_MAX_AGE","20")))
RISK_PER_TRADE=float(os.getenv("MIRSAD_RISK_PER_TRADE","0.005"))
MT5_COMMON_FILES=os.getenv("MIRSAD_MT5_COMMON_FILES","").strip()
ENABLE_ORDER_PUBLISH=os.getenv("MIRSAD_ENABLE_ORDER_PUBLISH","0")=="1"

PROVIDERS={
 "Binance Spot":"https://api.binance.com",
 "Bybit Spot":"https://api.bybit.com",
 "OKX Spot":"https://www.okx.com",
}
