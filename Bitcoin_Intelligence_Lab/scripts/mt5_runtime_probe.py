from __future__ import annotations

import argparse
import json
import os
from typing import Iterable


def select_btc_symbol_name(names: Iterable[str]) -> str:
    """Choose the most conventional BTC/USD broker symbol deterministically."""
    candidates = [str(name).strip() for name in names if "BTC" in str(name).upper()]
    if not candidates:
        raise ValueError("Headway exposes no BTC instrument in the connected terminal.")

    def rank(name: str) -> tuple[int, int, str]:
        upper = name.upper()
        if upper == "BTCUSD":
            preference = 0
        elif upper.startswith("BTCUSD"):
            preference = 1
        elif "BTCUSD" in upper:
            preference = 2
        elif upper.startswith("BTC"):
            preference = 3
        else:
            preference = 4
        return preference, len(name), upper

    return sorted(set(candidates), key=rank)[0]


def inspect_terminal(terminal_path: str, login: int, password: str, server: str) -> dict:
    """Read-only probe of the authenticated Headway DEMO terminal; never sends orders."""
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 Python package is not installed.") from exc

    initialized = mt5.initialize(
        path=terminal_path,
        login=login,
        password=password,
        server=server,
        timeout=60_000,
        portable=True,
    )
    if not initialized:
        error = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"MetaTrader5.initialize failed: {error!r}")

    try:
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or account is None:
            raise RuntimeError(f"Terminal/account information unavailable: {mt5.last_error()!r}")
        server_name = str(getattr(account, "server", "") or "")
        company = str(getattr(account, "company", "") or "")
        if int(getattr(account, "trade_mode", -1)) != int(mt5.ACCOUNT_TRADE_MODE_DEMO):
            raise RuntimeError("Connected Headway account is not in DEMO mode.")
        if not (
            "headway" in server_name.lower()
            or "trade-hw.online" in server_name.lower()
            or "headway" in company.lower()
        ):
            raise RuntimeError("Connected account is not identified as Headway.")
        if not bool(getattr(terminal, "connected", False)):
            raise RuntimeError("MT5 terminal reports that it is disconnected.")
        if bool(getattr(terminal, "trade_allowed", True)):
            raise RuntimeError("Safety gate failed: MT5 terminal automated trading is enabled.")

        symbols = mt5.symbols_get("*BTC*")
        names = [str(item.name) for item in (symbols or ())]
        symbol = select_btc_symbol_name(names)
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Could not select BTC symbol {symbol!r}: {mt5.last_error()!r}")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Could not read BTC symbol properties for {symbol!r}.")
        if int(getattr(info, "trade_mode", 0)) == int(mt5.SYMBOL_TRADE_MODE_DISABLED):
            raise RuntimeError(f"BTC symbol {symbol!r} is disabled by the broker.")
        common_root = str(getattr(terminal, "commondata_path", "") or "")
        if not common_root:
            raise RuntimeError("MT5 did not provide its common data folder.")
        return {
            "status": "ok",
            "symbol": symbol,
            "digits": int(info.digits),
            "point": float(info.point),
            "bid": float(info.bid),
            "ask": float(info.ask),
            "volume_min": float(info.volume_min),
            "volume_step": float(info.volume_step),
            "trade_mode": int(info.trade_mode),
            "account_mode": int(account.trade_mode),
            "account_server": server_name,
            "company": company,
            "terminal_connected": bool(terminal.connected),
            "terminal_trade_allowed": bool(terminal.trade_allowed),
            "common_data_path": common_root,
            "terminal_build": int(getattr(terminal, "build", 0)),
        }
    finally:
        mt5.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", default=os.environ.get("BTCIL_MT5_TERMINAL", ""))
    parser.add_argument("--login", type=int, default=int(os.environ.get("BTCIL_MT5_LOGIN", "0")))
    parser.add_argument("--server", default=os.environ.get("BTCIL_MT5_SERVER", ""))
    args = parser.parse_args()
    password = os.environ.get("BTCIL_MT5_PASSWORD", "")
    if not args.terminal or not args.login or not password or not args.server:
        print(json.dumps({"status": "error", "reason": "Missing terminal/login/password/server input."}))
        return 2
    try:
        result = inspect_terminal(args.terminal, args.login, password, args.server)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc)[:400]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
