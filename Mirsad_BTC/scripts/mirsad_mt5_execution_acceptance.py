from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from mirsad.config import RISK_PER_TRADE
from mirsad.engines.mt5_bridge import MT5BridgeEngine
from mirsad.engines.position_ledger import aggregate_position_cycles


TERMINAL_FAILURE_STATES = {"REJECTED", "CANCELLED", "EXPIRED"}
CONFIRMED_RECONCILIATIONS = {"CONFIRMED", "CONFIRMED_PARTIAL"}


def read_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def positive_number(mapping: dict[str, Any], key: str) -> float:
    value = float(mapping.get(key, 0) or 0)
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(f"Live MT5 field '{key}' must be finite and positive.")
    return value


def make_command_id(label: str) -> str:
    seed = f"MIR1-ACCEPTANCE|{label}|{time.time_ns()}"
    return "MIR-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def position_for_ticket(
    state: dict[str, Any], *, ticket: int, symbol: str, magic: int
) -> dict[str, Any] | None:
    for row in state.get("positions", []):
        if not isinstance(row, dict):
            continue
        try:
            if (
                int(row.get("ticket", 0)) == ticket
                and str(row.get("symbol", "")).upper() == symbol.upper()
                and int(row.get("magic", -1)) == magic
            ):
                return row
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def symbol_positions(state: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    rows = state.get("positions")
    if not isinstance(rows, list):
        raise RuntimeError("MIR1 positions telemetry is not a list.")
    result = []
    for row in rows:
        if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol.upper():
            result.append(row)
    return result


def wait_for_reconciliation(
    engine: MT5BridgeEngine,
    command_id: str,
    *,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ack_path = engine.root / "ack.json"  # type: ignore[operator]
    deadline = time.monotonic() + timeout_seconds
    last_state: dict[str, Any] = {}
    last_ack: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_state = engine.inspect()
        last_ack = read_object(ack_path)
        if last_ack.get("command_id") == command_id:
            ack_state = str(last_ack.get("state", "")).upper()
            if ack_state in TERMINAL_FAILURE_STATES:
                raise RuntimeError(
                    f"MIR1 command was rejected by MT5: {ack_state}; "
                    f"{str(last_ack.get('message', ''))[:300]}"
                )
            reconciliation = last_state.get("position_reconciliation")
            if (
                ack_state in {"FILLED", "PARTIAL"}
                and isinstance(reconciliation, dict)
                and reconciliation.get("command_id") == command_id
                and reconciliation.get("status") in CONFIRMED_RECONCILIATIONS
            ):
                return last_state, last_ack
        time.sleep(1)
    state_label = str(last_ack.get("state", "NO_ACK")) if last_ack else "NO_ACK"
    raise TimeoutError(
        f"Timed out waiting for reconciled MIR1 ACK for {command_id}; last state={state_label}."
    )


def build_open_decision(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    symbol = str(state.get("symbol", "")).strip()
    market_symbol = str(state.get("market_symbol", "")).strip()
    if not symbol or not market_symbol:
        raise RuntimeError("MIR1 symbol mapping is missing.")

    quote = state.get("quote") if isinstance(state.get("quote"), dict) else {}
    spec = state.get("symbol_spec") if isinstance(state.get("symbol_spec"), dict) else {}
    account = state.get("account") if isinstance(state.get("account"), dict) else {}
    bid, ask = positive_number(quote, "bid"), positive_number(quote, "ask")
    tick_size = positive_number(spec, "tick_size")
    tick_value_loss = positive_number(spec, "tick_value_loss")
    volume_min = positive_number(spec, "volume_min")
    volume_step = positive_number(spec, "volume_step")
    volume_max = positive_number(spec, "volume_max")
    point = positive_number(spec, "point")
    equity = positive_number(account, "equity")
    digits = int(spec.get("digits", 0) or 0)
    stops_points = max(0, int(spec.get("stops_level_points", 0) or 0))
    freeze_points = max(0, int(spec.get("freeze_level_points", 0) or 0))
    if ask < bid or digits < 0 or digits > 10:
        raise RuntimeError("MT5 quote or price precision is invalid.")

    quote_age = float(state.get("quote_age_seconds", math.inf))
    tick_age = float(quote.get("tick_age_seconds", math.inf))
    spread = ask - bid
    if (
        not math.isfinite(quote_age) or not math.isfinite(tick_age)
        or quote_age < 0 or quote_age > 10 or tick_age < 0 or tick_age > 10
        or spread < 0 or spread / ((ask + bid) / 2.0) > 0.003
    ):
        raise RuntimeError(
            "MT5 quote is stale or outside the configured 0.3% spread gate "
            f"(quote_age={quote_age}, tick_age={tick_age}, bid={bid}, ask={ask}, "
            f"spread_pct={(spread / ((ask + bid) / 2.0) * 100.0) if ask + bid > 0 else None})."
        )

    minimum_stop_gap = max(stops_points, freeze_points) * point + 2.0 * tick_size
    # BTC can move several dollars between Python publishing and the EA timer.
    # Use a wider 0.25% protective gap so a fresh tick does not invalidate SL/TP.
    gap = max(minimum_stop_gap, spread * 4.0, tick_size * 10.0, ask * 0.0025)
    stop_loss = math.floor((ask - gap) / tick_size + 1e-10) * tick_size
    take_profit = math.ceil((ask + 3.0 * gap) / tick_size - 1e-10) * tick_size
    stop_loss = round(stop_loss, digits)
    take_profit = round(take_profit, digits)
    if not (0 < stop_loss < ask < take_profit):
        raise RuntimeError("Could not construct broker-aligned BUY stop and target prices.")

    risk_fraction = float(RISK_PER_TRADE)
    if not math.isfinite(risk_fraction) or not 0 < risk_fraction < 0.5:
        raise RuntimeError("The configured per-trade risk fraction is invalid.")
    risk_cash = equity * risk_fraction
    loss_per_lot = abs(ask - stop_loss) / tick_size * tick_value_loss
    if not math.isfinite(loss_per_lot) or loss_per_lot <= 0:
        raise RuntimeError("Broker loss-side tick value cannot produce a valid order size.")
    raw_volume = risk_cash / loss_per_lot
    if raw_volume < volume_min - 1e-12:
        raise RuntimeError(
            "Broker minimum volume would exceed the configured per-trade risk budget; "
            "acceptance order was not sent."
        )
    # This is a one-off acceptance probe, not a trading signal. Cap its
    # notional exposure at USD 1,000 in addition to the normal 0.5% risk cap.
    max_test_notional = 1000.0
    notional_volume_cap = min(volume_max, max_test_notional / ask)
    if notional_volume_cap < volume_min - 1e-12:
        raise RuntimeError("Broker minimum lot exceeds the USD 1,000 acceptance notional cap.")
    allowed_volume_cap = volume_min + math.floor(
        (notional_volume_cap - volume_min + 1e-12) / volume_step
    ) * volume_step
    effective_volume_cap = min(volume_max, allowed_volume_cap)
    steps = math.floor((min(raw_volume, effective_volume_cap) - volume_min + 1e-12) / volume_step)
    volume = round(volume_min + max(0, steps) * volume_step, 8)
    if volume < volume_min - 1e-9 or volume > volume_max + 1e-9:
        raise RuntimeError("Calculated acceptance volume violates broker min/max limits.")
    if volume * ask > max_test_notional + 1e-6:
        raise RuntimeError("Acceptance order exceeds the USD 1,000 notional cap.")
    estimated_loss = loss_per_lot * volume
    if estimated_loss > risk_cash + max(0.01, risk_cash * 1e-8):
        raise RuntimeError("Acceptance volume exceeds the configured per-trade risk budget.")

    decision = {
        "status": "READY",
        "command_ready": True,
        "action": "BUY",
        "signal_id": make_command_id("OPEN"),
        "symbol": symbol,
        "market_symbol": market_symbol,
        "entry_reference": ask,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_plan": {
            "status": "READY",
            "volume": volume,
            "risk_fraction": risk_fraction,
            "risk_cash": round(risk_cash, 8),
            "estimated_loss": round(estimated_loss, 8),
            "purpose": "MIR1_DEMO_ACCEPTANCE_OPEN",
        },
    }
    sizing = {
        "risk_fraction": risk_fraction,
        "risk_budget": round(risk_cash, 8),
        "estimated_stop_loss": round(estimated_loss, 8),
        "max_test_notional": max_test_notional,
        "estimated_notional": round(volume * ask, 8),
        "volume": volume,
        "broker_volume_min": volume_min,
        "broker_volume_step": volume_step,
        "entry_reference": ask,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "spread": spread,
    }
    return decision, sizing


def build_close_decision(
    state: dict[str, Any], position: dict[str, Any]
) -> dict[str, Any]:
    symbol = str(state.get("symbol", "")).strip()
    market_symbol = str(state.get("market_symbol", "")).strip()
    ticket = int(position.get("ticket", 0) or 0)
    volume = positive_number(position, "volume")
    if ticket <= 0:
        raise RuntimeError("The acceptance position ticket is invalid.")
    return {
        "status": "READY",
        "command_ready": True,
        "action": "CLOSE",
        "signal_id": make_command_id(f"CLOSE-{ticket}"),
        "symbol": symbol,
        "market_symbol": market_symbol,
        "position_ticket": ticket,
        "risk_plan": {
            "status": "READY",
            "volume": volume,
            "purpose": "MIR1_DEMO_ACCEPTANCE_CLOSE",
        },
    }


def publish(engine: MT5BridgeEngine, decision: dict[str, Any], state: dict[str, Any]) -> None:
    result = engine.publish_decision(decision, state)
    if result.get("status") != "PUBLISHED":
        raise RuntimeError(
            f"Python MIR1 bridge refused {decision.get('action')} command: "
            f"{result.get('status')} — {result.get('message', result.get('reason', ''))}"
        )


def close_tracked_position(
    engine: MT5BridgeEngine,
    *,
    ticket: int,
    symbol: str,
    magic: int,
    timeout_seconds: int,
    max_attempts: int = 3,
) -> dict[str, Any]:
    close_results: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        state = engine.inspect()
        position = position_for_ticket(state, ticket=ticket, symbol=symbol, magic=magic)
        if position is None:
            return {"status": "CLOSED", "attempts": close_results}
        decision = build_close_decision(state, position)
        publish(engine, decision, state)
        state_after, ack = wait_for_reconciliation(
            engine, decision["signal_id"], timeout_seconds=timeout_seconds
        )
        rec = state_after.get("position_reconciliation") or {}
        close_results.append({
            "attempt": attempt,
            "ack_state": ack.get("state"),
            "filled_volume": ack.get("filled_volume"),
            "reconciliation": rec.get("status"),
        })
        current = position_for_ticket(state_after, ticket=ticket, symbol=symbol, magic=magic)
        if current is None:
            return {"status": "CLOSED", "attempts": close_results}
        if str(ack.get("state", "")).upper() not in {"FILLED", "PARTIAL"}:
            raise RuntimeError("The close command did not reach a reconciled filled state.")
    raise RuntimeError("The acceptance position still exists after three reconciled close attempts.")


def run_acceptance(common_files: Path, *, timeout_seconds: int, report_path: Path) -> int:
    engine = MT5BridgeEngine(common_files=str(common_files))
    result: dict[str, Any] = {
        "schema": "MIR1-EXECUTION-ACCEPTANCE-1",
        "status": "RUNNING",
        "steps": [],
        "trade": {},
    }
    tracked_ticket: int | None = None
    open_command_published = False
    exit_code = 1
    symbol = ""
    magic = 0
    try:
        # A fresh status snapshot may land just at the edge of the
        # heartbeat-age window after the PowerShell transport checks. Wait
        # briefly for the next one-second EA heartbeat instead of failing a
        # healthy terminal on a single stale read.
        ready_deadline = time.monotonic() + 45
        state: dict[str, Any] = {}
        readiness_snapshot: dict[str, Any] = {}
        while time.monotonic() < ready_deadline:
            state = engine.inspect()
            readiness_snapshot = {
                "status": state.get("status"),
                "heartbeat_age_seconds": state.get("heartbeat_age_seconds"),
                "terminal_connected": state.get("terminal_connected"),
                "execution_enabled": state.get("execution_enabled"),
                "execution_input_enabled": state.get("execution_input_enabled"),
                "trade_permissions_available": state.get("trade_permissions_available"),
                "symbol": state.get("symbol"),
                "quote_age_seconds": state.get("quote_age_seconds"),
            }
            if (
                state.get("status") == "CONNECTED"
                and state.get("terminal_connected") is True
                and state.get("execution_enabled") is True
                and state.get("execution_input_enabled") is True
                and state.get("trade_permissions_available") is True
            ):
                result["steps"].append({
                    "step": "FRESH_MIR1_EXECUTION_PERMISSIONS",
                    "status": "PASS",
                    "wait_seconds": round(45 - max(0, ready_deadline - time.monotonic()), 2),
                    "details": readiness_snapshot,
                })
                break
            time.sleep(1)
        else:
            raise RuntimeError(
                "Fresh MIR1 heartbeat and every MT5 execution permission are required; "
                f"last snapshot={readiness_snapshot}"
            )
        symbol = str(state.get("symbol", "")).strip()
        market_symbol = str(state.get("market_symbol", "")).strip()
        magic = int(state.get("magic_number", 0) or 0)
        if not symbol or not market_symbol or magic <= 0:
            raise RuntimeError("MIR1 execution identity is incomplete.")

        # Refuse to mix a protocol probe with any pre-existing BTC exposure,
        # including positions not owned by this EA.
        existing = symbol_positions(state, symbol)
        if existing:
            raise RuntimeError(
                f"Acceptance probe refused: {len(existing)} pre-existing position(s) are open on {symbol}."
            )
        if not state.get("positions_file_valid"):
            raise RuntimeError("MIR1 positions.json is missing or malformed.")

        current_command = state.get("current_command") or {}
        current_ack = state.get("last_order_ack") or {}
        if current_command.get("command_id"):
            command_id = current_command.get("command_id")
            if current_ack.get("command_id") != command_id:
                raise RuntimeError("An unresolved MIR1 command already exists; refusing to overwrite it.")
            current_ack_state = str(current_ack.get("state", "")).upper()
            rec = state.get("position_reconciliation") or {}
            settled = (
                current_ack_state in TERMINAL_FAILURE_STATES
                or (
                    current_ack_state in {"FILLED", "PARTIAL"}
                    and rec.get("command_id") == command_id
                    and rec.get("status") in CONFIRMED_RECONCILIATIONS
                )
            )
            if not settled:
                raise RuntimeError("A previous MIR1 command has not reached a reconciled terminal state.")

        opened_state: dict[str, Any] | None = None
        open_ack: dict[str, Any] | None = None
        decision: dict[str, Any] | None = None
        sizing: dict[str, Any] | None = None
        last_rejection = ""
        broker_rejections = 0
        for attempt in range(1, 16):
            state = engine.inspect()
            if state.get("status") != "CONNECTED":
                result["steps"].append({
                    "step": f"WAIT_FOR_CONNECTED_QUOTE_{attempt}",
                    "status": "RETRY",
                    "heartbeat_age_seconds": state.get("heartbeat_age_seconds"),
                })
                time.sleep(1)
                continue
            if symbol_positions(state, symbol):
                raise RuntimeError("A BTC position appeared before the acceptance BUY; refusing to add exposure.")
            try:
                decision, sizing = build_open_decision(state)
            except RuntimeError as quote_error:
                quote_message = str(quote_error)
                if "quote is stale or outside the configured 0.3% spread gate" not in quote_message:
                    raise
                result["steps"].append({
                    "step": f"WAIT_FOR_FRESH_TIGHT_QUOTE_{attempt}",
                    "status": "RETRY",
                    "reason": quote_message[:300],
                })
                time.sleep(1)
                continue
            result["steps"].append({
                "step": f"LIVE_SIZE_AND_PROTECTIVE_LEVELS_ATTEMPT_{attempt}",
                "status": "PASS",
                "details": sizing,
                "quote_age_seconds": state.get("quote_age_seconds"),
                "tick_age_seconds": (state.get("quote") or {}).get("tick_age_seconds"),
            })
            publish(engine, decision, state)
            open_command_published = True
            broker_rejections += 1
            result["steps"].append({
                "step": f"PYTHON_BRIDGE_PUBLISHED_BUY_ATTEMPT_{broker_rejections}",
                "status": "PASS",
            })
            try:
                opened_state, open_ack = wait_for_reconciliation(
                    engine, decision["signal_id"], timeout_seconds=timeout_seconds
                )
                break
            except RuntimeError as exc:
                refreshed = engine.inspect()
                candidates = [
                    row for row in symbol_positions(refreshed, symbol)
                    if int(row.get("magic", -1)) == magic
                ]
                if candidates:
                    if len(candidates) == 1:
                        tracked_ticket = int(candidates[0].get("ticket", 0) or 0)
                    raise RuntimeError(
                        "The BUY result was not fully reconciled but broker exposure is visible; "
                        "automatic retry is prohibited and cleanup will target that position."
                    ) from exc
                ack_state = refreshed.get("last_order_ack") or {}
                last_rejection = str(ack_state.get("message", exc))
                if str(ack_state.get("state", "")).upper() != "REJECTED":
                    raise
                retryable = any(
                    token in last_rejection.lower()
                    for token in ("price", "stop", "requote", "off quotes", "invalid stops", "ordercheck")
                )
                if not retryable or broker_rejections >= 3:
                    raise RuntimeError(f"MT5 rejected the acceptance BUY: {last_rejection}") from exc
                result["steps"].append({
                    "step": f"REQUOTE_RETRY_{broker_rejections}",
                    "status": "RETRY",
                    "reason": last_rejection[:300],
                })
                time.sleep(1)
        else:
            raise TimeoutError(
                "No broker quote passed the 10-second age and 0.3% spread gates within 15 fresh-snapshot attempts."
            )
        if opened_state is None or open_ack is None or decision is None or sizing is None:
            raise RuntimeError("MIR1 acceptance BUY could not be reconciled after three fresh-price attempts.")
        open_rec = opened_state.get("position_reconciliation") or {}
        new_positions = [
            row for row in symbol_positions(opened_state, symbol)
            if int(row.get("magic", -1)) == magic
        ]
        if len(new_positions) != 1:
            raise RuntimeError(
                f"Expected exactly one new Mirsad position after reconciled BUY; observed {len(new_positions)}."
            )
        opened_position = new_positions[0]
        tracked_ticket = int(opened_position.get("ticket", 0) or 0)
        position_id = int(opened_position.get("position_id", 0) or 0)
        if tracked_ticket <= 0 or position_id <= 0:
            raise RuntimeError("MT5 opened a position without a valid ticket/position identifier.")

        result["trade"] = {
            "symbol": symbol,
            "market_symbol": market_symbol,
            "magic_number": magic,
            "volume_requested": sizing["volume"],
            "volume_filled": float(open_ack.get("filled_volume", 0) or 0),
            "open_ack_state": open_ack.get("state"),
            "open_reconciliation": open_rec.get("status"),
            "position_ticket": tracked_ticket,
            "position_id": position_id,
            "entry_price": float(opened_position.get("price_open", 0) or 0),
            "initial_stop_loss": float(opened_position.get("stop_loss", 0) or 0),
            "initial_take_profit": float(opened_position.get("take_profit", 0) or 0),
        }
        result["steps"].append({"step": "MT5_OPEN_FILLED_AND_RECONCILED", "status": "PASS"})

        close_result = close_tracked_position(
            engine,
            ticket=tracked_ticket,
            symbol=symbol,
            magic=magic,
            timeout_seconds=timeout_seconds,
        )
        result["trade"]["close_attempts"] = close_result["attempts"]
        result["steps"].append({"step": "MT5_CLOSE_FILLED_AND_RECONCILED", "status": "PASS"})

        # The EA refreshes the bounded deal-history snapshot periodically. Wait
        # for the broker's entry and exit records, then aggregate by position_id.
        deadline = time.monotonic() + 125
        closed_cycle = None
        while time.monotonic() < deadline:
            after_close = engine.inspect()
            history = after_close.get("deal_history") or {}
            deals = history.get("deals") if isinstance(history.get("deals"), list) else []
            cycles = aggregate_position_cycles(deals)
            closed_cycle = next(
                (row for row in cycles if str(row.get("position_id")) == str(position_id)),
                None,
            )
            if (
                history.get("status") == "READY"
                and history.get("truncated") is False
                and isinstance(closed_cycle, dict)
                and closed_cycle.get("state") == "CLOSED"
                and int(closed_cycle.get("entry_count", 0)) >= 1
                and int(closed_cycle.get("exit_count", 0)) >= 1
            ):
                break
            time.sleep(2)
        if not isinstance(closed_cycle, dict) or closed_cycle.get("state") != "CLOSED":
            raise RuntimeError("MT5 position was closed, but a complete CLOSED deal cycle was not observed in MIR1 history.")
        result["trade"]["deal_cycle"] = {
            "state": closed_cycle.get("state"),
            "position_id": closed_cycle.get("position_id"),
            "deal_count": closed_cycle.get("deal_count"),
            "entry_count": closed_cycle.get("entry_count"),
            "exit_count": closed_cycle.get("exit_count"),
            "realized_deal_profit": closed_cycle.get("realized_deal_profit"),
            "commission": closed_cycle.get("commission"),
            "swap": closed_cycle.get("swap"),
            "fee": closed_cycle.get("fee"),
            "net_deal_cashflow": closed_cycle.get("net_deal_cashflow"),
            "currency": closed_cycle.get("currency"),
        }
        result["steps"].append({"step": "BROKER_DEAL_LEDGER_CLOSED_CYCLE", "status": "PASS"})
        result["status"] = "SUCCESS"
        exit_code = 0
    except Exception as exc:
        result["status"] = "FAILED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        exit_code = 1
    finally:
        # If a BUY was confirmed but any later acceptance assertion failed,
        # make a best-effort close of only the tracked test ticket.
        if open_command_published and tracked_ticket is None and symbol and magic:
            try:
                # If the broker filled the request but the normal ACK wait timed
                # out, recover the only new Mirsad BTC ticket before exiting.
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and tracked_ticket is None:
                    current = engine.inspect()
                    candidates = [
                        row for row in symbol_positions(current, symbol)
                        if int(row.get("magic", -1)) == magic
                    ]
                    if len(candidates) == 1:
                        tracked_ticket = int(candidates[0].get("ticket", 0) or 0)
                        break
                    if len(candidates) > 1:
                        raise RuntimeError(
                            "More than one Mirsad BTC position appeared during acceptance recovery; "
                            "automatic cleanup is withheld to avoid closing an unrelated position."
                        )
                    time.sleep(1)
                if tracked_ticket:
                    result["recovered_position_ticket_for_cleanup"] = tracked_ticket
            except Exception as recovery_error:
                result["cleanup_error"] = f"{type(recovery_error).__name__}: {recovery_error}"
                result["status"] = "FAILED"

        if tracked_ticket and symbol and magic:
            try:
                current = engine.inspect()
                still_open = position_for_ticket(
                    current, ticket=tracked_ticket, symbol=symbol, magic=magic
                )
                if still_open is not None:
                    cleanup = close_tracked_position(
                        engine,
                        ticket=tracked_ticket,
                        symbol=symbol,
                        magic=magic,
                        timeout_seconds=timeout_seconds,
                        max_attempts=4,
                    )
                    result["cleanup"] = cleanup
            except Exception as cleanup_error:
                result["cleanup_error"] = f"{type(cleanup_error).__name__}: {cleanup_error}"
                result["status"] = "FAILED"
        write_report(report_path, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code if result.get("status") == "SUCCESS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a single bounded MIR1 BUY/CLOSE acceptance trade through the Python bridge and MT5 EA."
    )
    parser.add_argument("--common-files", required=True, help="MT5 Terminal Common/Files directory.")
    parser.add_argument("--report", required=True, help="Sanitized JSON report output path.")
    parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait for each ACK/reconciliation.")
    args = parser.parse_args()
    common_files = Path(args.common_files).expanduser()
    if not common_files.is_dir():
        raise SystemExit("MT5 Common/Files path does not exist.")
    if not (1 <= args.timeout <= 180):
        raise SystemExit("--timeout must be between 1 and 180 seconds.")
    return run_acceptance(
        common_files,
        timeout_seconds=args.timeout,
        report_path=Path(args.report).expanduser(),
    )


if __name__ == "__main__":
    sys.exit(main())
