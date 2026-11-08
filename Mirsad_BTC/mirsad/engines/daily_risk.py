from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import time
from typing import Any


def evaluate_daily_risk(
    account: dict[str, Any] | None,
    previous_state: dict[str, Any] | None,
    *,
    max_daily_loss_fraction: float,
    enabled: bool = True,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Return the UTC-day equity drawdown gate and its persisted state.

    The first valid connected-equity snapshot of a UTC day becomes the baseline.
    Missing account identity/equity or an invalid enabled cap fails closed for
    new entries. The daily cap may be explicitly disabled during development;
    this does not bypass any other Engine 4 risk or signal-quality checks.
    """
    if not enabled:
        return {
            "report": {
                "status": "READY",
                "mode": "DISABLED_FOR_DEVELOPMENT",
                "enabled": False,
                "locked": False,
                "new_entries_blocked": False,
                "max_daily_loss_fraction": None,
                "configured_max_daily_loss_fraction": max_daily_loss_fraction,
                "daily_loss_fraction": None,
                "decision_eligible": False,
                "reason": (
                    "The daily loss cap is disabled for development; all other "
                    "account, quote, per-trade risk, signal-quality and position "
                    "management checks remain active."
                ),
            },
            "state": previous_state if isinstance(previous_state, dict) else {},
        }

    timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)

    def blocked(status: str, reason: str) -> dict[str, Any]:
        return {
            "report": {
                "status": status, "mode": "ENABLED", "enabled": True,
                "locked": True, "new_entries_blocked": True,
                "max_daily_loss_fraction": max_daily_loss_fraction,
                "decision_eligible": False, "reason": reason,
            },
            "state": previous_state if isinstance(previous_state, dict) else {},
        }

    try:
        cap = float(max_daily_loss_fraction)
        equity = float((account or {}).get("equity"))
        login = str((account or {}).get("login", "")).strip()
        server = str((account or {}).get("server", "")).strip()
        currency = str((account or {}).get("currency", "")).strip()
        if not (math.isfinite(cap) and 0.0 < cap < 0.5):
            return blocked("INVALID_CONFIGURATION", "Maximum daily loss fraction must be between 0 and 0.5.")
        if not (math.isfinite(equity) and equity > 0):
            return blocked("ACCOUNT_EQUITY_UNAVAILABLE", "A fresh positive MT5 account equity value is required.")
        if not login or not server or not currency:
            return blocked("ACCOUNT_IDENTITY_UNAVAILABLE", "MT5 account login, server and currency are required for a stable risk baseline.")
        day = datetime.fromtimestamp(timestamp / 1000.0, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return blocked("INVALID_ACCOUNT_DATA", "Account risk inputs or timestamp are invalid.")

    account_digest = hashlib.sha256(
        f"{server}|{login}|{currency}".encode("utf-8")
    ).hexdigest()
    prior = previous_state if isinstance(previous_state, dict) else {}
    try:
        prior_start = float(prior.get("starting_equity", 0))
        prior_day = str(prior.get("day_utc", ""))
        prior_account = str(prior.get("account_key_sha256", ""))
        prior_baseline_at = int(prior.get("baseline_at_ms", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        prior_start, prior_day, prior_account, prior_baseline_at = 0.0, "", "", 0

    reset_reason = None
    if prior_day != day:
        reset_reason = "NEW_UTC_DAY" if prior_day else "FIRST_VALID_EQUITY_SNAPSHOT"
    elif prior_account != account_digest:
        reset_reason = "ACCOUNT_CHANGED"
    elif not math.isfinite(prior_start) or prior_start <= 0 or prior_baseline_at <= 0:
        reset_reason = "INVALID_PERSISTED_BASELINE"

    # A process first started mid-session cannot infer losses that occurred
    # before its first snapshot. Only accept a fresh baseline close to UTC
    # midnight; otherwise lock new entries for the remainder of this UTC day.
    day_start_ms = int(
        datetime.fromtimestamp(timestamp / 1000.0, tz=timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp() * 1000
    )
    seconds_since_utc_day_start = max(0, timestamp - day_start_ms)
    baseline_grace_ms = 5 * 60 * 1000

    def pending_baseline(reason_code: str) -> dict[str, Any]:
        pending_state = {
            "schema": "MIR-DAILY-RISK-1",
            "day_utc": day,
            "account_key_sha256": account_digest,
            "baseline_pending": True,
            "baseline_pending_reason": reason_code,
            "updated_at_ms": timestamp,
        }
        return {
            "report": {
                "status": "BASELINE_UNAVAILABLE",
                "mode": "ENABLED",
                "enabled": True,
                "day_utc": day,
                "account_key_sha256": account_digest,
                "max_daily_loss_fraction": cap,
                "daily_loss_fraction": None,
                "locked": True,
                "new_entries_blocked": True,
                "baseline_pending": True,
                "seconds_since_utc_day_start": round(seconds_since_utc_day_start / 1000.0, 3),
                "baseline_grace_seconds": baseline_grace_ms / 1000.0,
                "baseline_reset_reason": reason_code,
                "decision_eligible": False,
                "reason": (
                    "No trustworthy UTC-day opening equity baseline is available. "
                    "New entries remain blocked until a valid baseline can be captured "
                    "near the next UTC midnight; protective MODIFY and CLOSE remain allowed."
                ),
            },
            "state": pending_state,
        }

    if reset_reason:
        if seconds_since_utc_day_start > baseline_grace_ms:
            return pending_baseline(reset_reason)
        starting_equity = equity
        baseline_at_ms = timestamp
    else:
        starting_equity = prior_start
        baseline_at_ms = prior_baseline_at

    daily_pnl = equity - starting_equity
    daily_loss_cash = max(0.0, -daily_pnl)
    daily_loss_fraction = daily_loss_cash / starting_equity
    locked = daily_loss_fraction >= cap
    state = {
        "schema": "MIR-DAILY-RISK-1",
        "day_utc": day,
        "account_key_sha256": account_digest,
        "starting_equity": round(starting_equity, 8),
        "baseline_at_ms": baseline_at_ms,
        "baseline_pending": False,
        "baseline_source": "UTC_DAY_OPEN_EQUITY_SNAPSHOT",
        "updated_at_ms": timestamp,
    }
    remaining_loss_cash = max(0.0, starting_equity * cap - daily_loss_cash)
    report = {
        "status": "READY",
        "mode": "ENABLED",
        "enabled": True,
        "day_utc": day,
        "account_key_sha256": account_digest,
        "starting_equity": round(starting_equity, 8),
        "current_equity": round(equity, 8),
        "daily_pnl_cash": round(daily_pnl, 8),
        "daily_loss_cash": round(daily_loss_cash, 8),
        "daily_loss_fraction": round(daily_loss_fraction, 8),
        "max_daily_loss_fraction": cap,
        "remaining_loss_cash": round(remaining_loss_cash, 8),
        "locked": locked,
        "new_entries_blocked": locked,
        "baseline_reset_reason": reset_reason,
        "baseline_at_ms": baseline_at_ms,
        "baseline_pending": False,
        "baseline_source": "UTC_DAY_OPEN_EQUITY_SNAPSHOT",
        "seconds_since_utc_day_start": round(seconds_since_utc_day_start / 1000.0, 3),
        "decision_eligible": False,
        "reason": (
            "UTC daily equity drawdown limit reached; new entries are blocked, "
            "while protective MODIFY and CLOSE commands remain permitted."
            if locked else
            "Daily equity baseline is persistent and below the configured loss limit."
        ),
    }
    return {"report": report, "state": state}


__all__ = ["evaluate_daily_risk"]

