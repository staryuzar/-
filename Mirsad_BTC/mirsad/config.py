from __future__ import annotations
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA_DIR=Path(os.getenv("MIRSAD_DATA_DIR",str(ROOT/"data"))).expanduser()
DB_PATH=DATA_DIR/"mirsad.sqlite3"
DECISION_CALIBRATION_DB_PATH=DATA_DIR/"decision_calibration.sqlite3"
STATUS_PATH=DATA_DIR/"system_status.json"
SNAPSHOT_PATH=DATA_DIR/"latest_market.json"
CHART_DIR=DATA_DIR/"charts"
CHART_METADATA_PATH=DATA_DIR/"chart_metadata.json"
SYMBOL=os.getenv("MIRSAD_SYMBOL","BTCUSDT").upper()
COLLECT_INTERVAL_SECONDS=max(5,int(os.getenv("MIRSAD_COLLECT_SECONDS","10")))
MARKET_MAX_AGE_SECONDS=max(15,int(os.getenv("MIRSAD_MARKET_MAX_AGE","35")))
MT5_HEARTBEAT_MAX_AGE_SECONDS=max(5,int(os.getenv("MIRSAD_MT5_HEARTBEAT_MAX_AGE","20")))
MT5_QUOTE_MAX_AGE_SECONDS=max(1,int(os.getenv("MIRSAD_MT5_QUOTE_MAX_AGE","10")))
MT5_MARKET_DATA_MAX_AGE_SECONDS=max(3,int(os.getenv("MIRSAD_MT5_MARKET_DATA_MAX_AGE","15")))
MARKET_INTELLIGENCE_TIMEOUT_SECONDS=max(2.0,min(15.0,float(os.getenv("MIRSAD_INTELLIGENCE_TIMEOUT_SECONDS","4.5"))))
MARKET_INTELLIGENCE_DERIVATIVES_MAX_AGE_SECONDS=max(60,int(os.getenv("MIRSAD_INTELLIGENCE_DERIVATIVES_MAX_AGE","900")))
MARKET_INTELLIGENCE_FEAR_GREED_MAX_AGE_SECONDS=max(3600,int(os.getenv("MIRSAD_INTELLIGENCE_FEAR_GREED_MAX_AGE","129600")))
MARKET_INTELLIGENCE_GLOBAL_METRICS_MAX_AGE_SECONDS=max(3600,int(os.getenv("MIRSAD_INTELLIGENCE_GLOBAL_MAX_AGE","86400")))
TRADING_ECONOMICS_CALENDAR_COUNTRIES=tuple(
    item.strip().lower()
    for item in os.getenv(
        "MIRSAD_TRADING_ECONOMICS_CALENDAR_COUNTRIES",
        "united states,china,euro area,united kingdom,japan,canada,australia,south korea",
    ).split(",")
    if item.strip()
) or ("united states",)
TRADING_ECONOMICS_API_KEY=os.getenv("MIRSAD_TRADING_ECONOMICS_API_KEY","").strip()
MT5_MARKET_DIVERGENCE_MAX_PCT=max(0.001,float(os.getenv("MIRSAD_MT5_MARKET_DIVERGENCE_MAX_PCT","0.01")))
MT5_MAX_SPREAD_PCT=max(0.0001,float(os.getenv("MIRSAD_MT5_MAX_SPREAD_PCT","0.003")))
CHART_MAX_AGE_SECONDS=max(30,int(os.getenv("MIRSAD_CHART_MAX_AGE","300")))
RISK_PER_TRADE=float(os.getenv("MIRSAD_RISK_PER_TRADE","0.005"))
# Observed Headway-Demo BTC commission: USD 0.25 per 0.01 lot (USD 25 per lot).
# Override when the broker account/symbol commission schedule differs.
COMMISSION_PER_LOT=float(os.getenv("MIRSAD_COMMISSION_PER_LOT","25.0"))
# Production default: enforce a persistent UTC-day equity drawdown cap of 20%.
# An explicit environment override may disable/change it for deliberate testing.
DAILY_LOSS_LIMIT_ENABLED=os.getenv("MIRSAD_DAILY_LOSS_LIMIT_ENABLED","1").strip().lower() in {"1","true","yes","on"}
MAX_DAILY_LOSS_FRACTION=float(os.getenv("MIRSAD_MAX_DAILY_LOSS_FRACTION","0.20"))
RISK_STATE_PATH=DATA_DIR/"daily_risk_state.json"
_mt5_common_files_override = os.getenv("MIRSAD_MT5_COMMON_FILES", "").strip()
_mt5_common_files_default = (
    Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    if os.environ.get("APPDATA") else None
)
if _mt5_common_files_override:
    MT5_COMMON_FILES = _mt5_common_files_override
elif (
    _mt5_common_files_default is not None
    and (_mt5_common_files_default / "MirsadBTC" / "status.json").is_file()
):
    # Auto-detect the standard MT5 shared folder on Windows when the user
    # has not configured MIRSAD_MT5_COMMON_FILES explicitly.
    MT5_COMMON_FILES = str(_mt5_common_files_default)
else:
    MT5_COMMON_FILES = ""
# User-requested default: publish Engine 4 commands when a decision is ready and the MT5 bridge reports execution enabled.
# Set MIRSAD_ENABLE_ORDER_PUBLISH=0 only for an intentional read-only run.
ENABLE_ORDER_PUBLISH=os.getenv("MIRSAD_ENABLE_ORDER_PUBLISH","1").strip().lower() in {"1","true","yes","on"}

PROVIDERS={
 "Binance Spot":"https://api.binance.com",
 "Bybit Spot":"https://api.bybit.com",
 "OKX Spot":"https://www.okx.com",
}

