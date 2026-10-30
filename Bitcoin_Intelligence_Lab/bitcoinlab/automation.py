from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .ea_bridge import current_ack, publish_close_order, publish_decision_order
from .position_manager import next_position_action


_SUCCESS_ACKS = {
    "FILLED", "CLOSED", "OPEN_FILL_CONFIRMED", "CLOSE_FILL_CONFIRMED",
}
_REJECTED_ACKS = {"REJECTED"}


def run_auto_management_cycle(
    *,
    report: Mapping[str, Any],
    positions: Sequence[Mapping[str, Any]],
    common_files: str | Path,
    volume: float = 0.01,
    state: Mapping[str, Any] | None = None,
    now_seconds: int | None = None,
    pending_timeout_seconds: int = 120,
) -> dict[str, Any]:
    """
    Run one idempotent board-management cycle.

    - One command may be pending at a time.
    - OPEN is sent only when there is no managed BTC position.
    - An opposite central decision closes one opposing ticket first.
    - HOLD never closes an open position.
    - A published command is not repeated while waiting for its MT5 ACK.
    - A failed attempt is not repeated on the same completed market candle.
    """
    now = int(time.time()) if now_seconds is None else int(now_seconds)
    next_state = dict(state or {})
    pending = next_state.get("pending")
    ack = current_ack(common_files)

    if isinstance(pending, dict):
        age = now - int(pending.get("issued_at", now))
        matching_ack = ack if ack.get("id") == pending.get("command_id") else {}

        ack_status = str(matching_ack.get("status", "")).upper()
        if ack_status in _REJECTED_ACKS:
            next_state["pending"] = None
            next_state["last_event"] = {
                "status": "rejected",
                "command_id": pending.get("command_id"),
                "detail": matching_ack.get("detail", "MT5 rejected the command."),
            }
            return {
                "state": next_state,
                "status": "rejected",
                "message": f"رفض MT5 الأمر: {matching_ack.get('detail', '')}",
                "ack": matching_ack,
            }

        if ack_status in _SUCCESS_ACKS:
            kind = pending.get("action")
            if kind == "OPEN":
                side = str(pending.get("side", "")).upper()
                confirmed = any(
                    str(row.get("type", "")).upper() == side
                    and "BTC" in str(row.get("symbol", "")).upper()
                    for row in positions
                )
            else:
                ticket = int(pending.get("ticket", 0))
                confirmed = not any(int(row.get("ticket", 0)) == ticket for row in positions)
            if confirmed:
                next_state["pending"] = None
                next_state["last_event"] = {
                    "status": "confirmed",
                    "command_id": pending.get("command_id"),
                    "ack": ack_status,
                }
                return {
                    "state": next_state,
                    "status": "confirmed",
                    "message": "وصل تأكيد التنفيذ من MT5 وتطابقت حالة المراكز.",
                    "ack": matching_ack,
                }

        if age > pending_timeout_seconds:
            next_state["pending"] = None
            next_state["last_event"] = {
                "status": "timeout",
                "command_id": pending.get("command_id"),
            }
            return {
                "state": next_state,
                "status": "timeout",
                "message": "انتهت مهلة انتظار إقرار MT5؛ لم يُرسل البرنامج أمراً بديلاً تلقائياً في هذه الدورة.",
                "ack": matching_ack,
            }

        return {
            "state": next_state,
            "status": "waiting_for_mt5",
            "message": (
                f"ينتظر البرنامج تأكيد MT5 للأمر {pending.get('command_id')} "
                f"(الحالة: {ack_status or 'لم يصل إقرار بعد'})."
            ),
            "ack": matching_ack,
        }

    try:
        observed_at = datetime.fromisoformat(
            str(report.get("as_of_utc", "")).replace("Z", "+00:00")
        )
        signal_age = (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return {
            "state": next_state,
            "status": "signal_timestamp_missing",
            "message": "لا يُسمح بإدارة المراكز باستخدام لقطة بلا توقيت صالح.",
        }
    if signal_age < -5 or signal_age > 90:
        return {
            "state": next_state,
            "status": "signal_stale",
            "message": f"لقطة القرار قديمة ({signal_age:.1f} ثانية)؛ لا يُرسل البرنامج أمراً.",
        }

    intent = next_position_action(report.get("decision", {}), positions)
    if intent["action"] == "HOLD":
        return {
            "state": next_state,
            "status": "holding",
            "message": f"لا يُرسل أمر جديد: {intent.get('reason')}.",
            "intent": intent,
            "ack": ack,
        }

    bar = (report.get("spot") or {}).get("last_bar") or {}
    bar_key = int(bar.get("close_time_ms") or 0)
    if bar_key <= 0:
        return {
            "state": next_state,
            "status": "missing_candle_time",
            "message": "لا يمكن ربط محاولة التنفيذ بآخر شمعة مكتملة.",
            "intent": intent,
        }

    action_key = intent["action"]
    target_key = intent.get("side") or str(intent.get("ticket"))
    attempt_key = f"{action_key}:{target_key}:{bar_key}"
    if next_state.get("last_attempt_key") == attempt_key:
        return {
            "state": next_state,
            "status": "already_attempted_this_candle",
            "message": "تمت محاولة هذا القرار في الشمعة المكتملة الحالية؛ لن يكرر البرنامج الأمر.",
            "intent": intent,
        }

    if action_key == "OPEN":
        result = publish_decision_order(
            report=dict(report), common_files=common_files, volume=volume,
        )
    else:
        result = publish_close_order(
            ticket=int(intent["ticket"]), common_files=common_files,
        )

    if result.get("status") != "published":
        return {
            "state": next_state,
            "status": "not_published",
            "message": f"لم يُنشر أمر إلى MT5: {result.get('status')} — {result.get('reason', '')}",
            "result": result,
            "intent": intent,
        }

    next_state["last_attempt_key"] = attempt_key
    next_state["pending"] = {
        "command_id": result["command_id"],
        "action": action_key,
        "side": intent.get("side"),
        "ticket": intent.get("ticket"),
        "issued_at": now,
    }
    next_state["last_event"] = {
        "status": "published",
        "command_id": result["command_id"],
        "action": action_key,
    }
    return {
        "state": next_state,
        "status": "published",
        "message": (
            f"أرسل البرنامج أمر {action_key} إلى MT5؛ "
            "ينتظر إقرار التنفيذ وتحديث ملف المراكز قبل أي أمر تالٍ."
        ),
        "result": result,
        "intent": intent,
    }
