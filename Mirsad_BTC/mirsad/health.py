from __future__ import annotations

import time
from collections import Counter
from typing import Any

from .config import COLLECT_INTERVAL_SECONDS

_HEALTH_AR = {
    "HEALTHY": "يعمل فعلياً",
    "WAITING": "بانتظار بيانات أو اتصال",
    "ATTENTION": "خلل أو يحتاج متابعة",
    "SAFE_DISABLED": "معطّل عمداً للحماية أو التطوير",
}
_STATUS_AR = {
    "RUNNING": "يعمل",
    "LIVE": "متصل والبيانات حية",
    "READY": "جاهز",
    "READY_FOR_ENGINE_2_VALIDATION": "وصلت اللقطة واجتازت فحص النقل",
    "CONNECTED": "متصل",
    "CONFIRMED": "تمت مطابقة التنفيذ مع المراكز",
    "NO_PENDING_COMMAND": "لا يوجد أمر معلّق",
    "NO_OPEN_POSITIONS": "لا توجد مراكز مفتوحة حالياً",
    "PUBLISH_DISABLED": "نشر الأوامر معطّل",
    "DISABLED_FOR_DEVELOPMENT": "معطّل خلال التطوير",
    "WAITING_FOR_CAPTURE": "بانتظار صورة من MT5",
    "WAITING_FOR_IMAGE": "بانتظار صورة الرسم",
    "WAITING_FOR_EXPERT": "بانتظار نبض الخبير",
    "NOT_CONFIGURED": "لم تتم تهيئته على الجهاز بعد",
    "NOT_REPORTED": "لم ترد بيانات حالة بعد",
    "NOT_READY": "غير جاهز",
    "PARTIAL": "يعمل جزئياً",
    "STALE": "البيانات قديمة",
    "OFFLINE": "غير متصل",
    "ERROR": "خطأ",
    "INVALID": "بيانات غير صالحة",
    "OBSERVER_REFERENCE_NOT_VERIFIED": "مرجعية الرسم غير مؤكدة",
    "NOT_VERIFIED": "لم يجتز التحقق",
    "IDENTITY_MISMATCH": "اختلاف في هوية اللقطة",
    "HASH_MISMATCH": "اختلاف بصمة الصورة",
    "HASH_NOT_REPORTED": "بصمة الصورة غير متاحة للمقارنة",
    "LOCKED": "حاجز المخاطر مفعّل",
}

def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

def _label(value: Any) -> str:
    status = str(value or "NOT_REPORTED").strip().upper()
    return _STATUS_AR.get(status, status.replace("_", " ").lower())

def _health(value: Any) -> str:
    status = str(value or "NOT_REPORTED").strip().upper()
    if status in {
        "RUNNING", "LIVE", "READY", "READY_FOR_ENGINE_2_VALIDATION",
        "CONNECTED", "CONFIRMED", "NO_PENDING_COMMAND", "NO_OPEN_POSITIONS",
        "VERIFIED",
    }:
        return "HEALTHY"
    if status in {"PUBLISH_DISABLED", "DISABLED_FOR_DEVELOPMENT", "LOCKED"}:
        return "SAFE_DISABLED"
    if (
        status in {
            "ERROR", "FAILED", "STALE", "OFFLINE", "INVALID", "REJECTED",
            "IDENTITY_MISMATCH", "HASH_MISMATCH", "OBSERVER_REFERENCE_NOT_VERIFIED",
            "NOT_VERIFIED", "SYMBOL_MISMATCH", "CANDLE_IDENTITY_MISMATCH",
            "BRIDGE_IDENTITY_MISMATCH", "BLOCKED_QUALITY_GATE",
        }
        or status.startswith(("ERROR_", "FAILED_", "INVALID_", "MISMATCH_", "REJECTED_", "OBSERVER_"))
        or status.endswith("_BLOCKED")
        or "MISMATCH" in status
    ):
        return "ATTENTION"
    return "WAITING"

def build_component_health(state: dict[str, Any] | None, *, now_ms: int | None = None) -> list[dict[str, Any]]:
    """Build dashboard health exclusively from the latest runtime telemetry."""
    if not isinstance(state, dict) or not state:
        return []

    market = _dict(state.get("market"))
    observer = _dict(state.get("chart_observer"))
    chart = _dict(state.get("chart"))
    candles = _dict(state.get("engine_2_candles"))
    price_action = _dict(state.get("engine_2_price_action"))
    multi_tf = _dict(state.get("engine_2_multi_timeframe_structure"))
    indicators = _dict(state.get("indicators"))
    native_indicators = _dict(state.get("mt5_native_indicators"))
    bridge = _dict(state.get("bridge"))
    decision = _dict(state.get("decision"))
    daily_risk = _dict(state.get("daily_risk"))
    command_publish = _dict(state.get("command_publish"))
    controls = _dict(state.get("execution_controls"))
    items: list[dict[str, str]] = []

    def add(engine: str, component: str, status: Any, detail: str = "", health: str | None = None) -> None:
        raw = str(status or "NOT_REPORTED").strip().upper()
        level = health or _health(raw)
        items.append({
            "engine": engine,
            "component": component,
            "status": raw,
            "status_label": _label(raw),
            "health": level,
            "health_label": _HEALTH_AR[level],
            "detail": detail or "لا توجد تفاصيل تشخيصية إضافية في آخر دورة.",
        })

    try:
        heartbeat = int(state.get("heartbeat_at_ms", 0) or 0)
        clock = int(now_ms) if now_ms is not None else time.time_ns() // 1_000_000
        age = (clock - heartbeat) / 1000 if heartbeat > 0 else None
    except (TypeError, ValueError, OverflowError):
        age = None
    limit = max(30, 3 * COLLECT_INTERVAL_SECONDS)
    runtime_status = "RUNNING" if age is not None and 0 <= age <= limit else "STALE" if age is not None else "NOT_REPORTED"
    add("التشغيل", "نبض ودورة البرنامج الرئيسية", runtime_status,
        f"آخر نبض: {age:.1f} ثانية؛ حد المراقبة: {limit} ثانية." if age is not None else "لم يسجل runtime نبضاً صالحاً.")

    # Engine 1
    market_age = state.get("market_age_seconds")
    add("المحرك الأول — استخبارات السوق", "تغذية السوق وسعر MT5", market.get("status"),
        f"السعر: {market.get('price', '—')} | المصدر: {market.get('primary_venue', '—')} | عمر البيانات: {market_age if market_age is not None else '—'} ثانية.")
    venues = _dict(market.get("venues"))
    primary_name = str(market.get("primary_venue") or "")
    primary = _dict(venues.get(primary_name))
    micro = _dict(primary.get("microstructure"))
    add("المحرك الأول — استخبارات السوق", "نبض عروض الأسعار والسبريد", micro.get("status"),
        f"المصدر: {primary_name or 'غير محدد'} | تحديث/دقيقة: {micro.get('tick_rate_per_minute', '—')} | السبريد: {micro.get('current_spread_pct', '—')}. حركة Bid/Ask وليست صفقات منفذة.")
    calendars = [str(_dict(row).get("economic_calendar_status") or "NOT_REPORTED").upper() for row in venues.values()]
    calendar_status = (
        "READY" if any(value in {"READY", "LIVE", "AVAILABLE"} for value in calendars)
        else "NOT_AVAILABLE" if calendars and all(value in {"NOT_AVAILABLE", "UNAVAILABLE", "DISABLED"} for value in calendars)
        else "NOT_REPORTED"
    )
    add("المحرك الأول — استخبارات السوق", "تقويم MT5 الاقتصادي", calendar_status,
        "مصدره تقويم الوسيط في MT5 وليس موجز أخبار BTC النصي.")

    # Engine 2
    observer_chart = _dict(observer.get("chart"))
    add("المحرك الثاني — التحليل البصري والسعري", "استقبال صور الشارت من خبير MT5", observer.get("status"),
        f"الرمز/الإطار: {observer_chart.get('symbol', '—')} / {observer_chart.get('timeframe', '—')} | عمر اللقطة: {observer.get('age_seconds', '—')} ثانية | شموع OHLC: {observer.get('bar_count', '—')}.")
    capture = _dict(chart.get("observer_capture"))
    inbox_id = str(observer.get("capture_id") or "").strip()
    analyzed_id = str(capture.get("capture_id") or chart.get("observer_capture_id") or "").strip()
    inbox_hash = str(observer.get("image_sha256") or "").strip().lower()
    analyzed_hash = str(capture.get("image_sha256") or "").strip().lower()
    if inbox_id and analyzed_id and inbox_id != analyzed_id:
        identity_status, identity_detail = "IDENTITY_MISMATCH", f"Capture ID مختلف: inbox={inbox_id} والتحليل={analyzed_id}."
    elif inbox_hash and analyzed_hash and inbox_hash != analyzed_hash:
        identity_status, identity_detail = "HASH_MISMATCH", "بصمة SHA-256 لصورة التحليل لا تطابق صورة صندوق الاستقبال."
    elif inbox_id and analyzed_id and inbox_id == analyzed_id and inbox_hash and analyzed_hash:
        identity_status, identity_detail = "VERIFIED", f"تطابق Capture ID وبصمة الصورة: {inbox_id}."
    elif inbox_id and analyzed_id and inbox_id == analyzed_id:
        identity_status, identity_detail = "HASH_NOT_REPORTED", "تطابق Capture ID، لكن بصمة الصورة في التحليل غير متاحة؛ الهوية غير مكتملة."
    else:
        identity_status, identity_detail = "NOT_REPORTED", "لا توجد هوية لقطة وبصمتان مكتملتان في تقرير الدورة نفسه."
    add("المحرك الثاني — التحليل البصري والسعري", "تطابق هوية الصورة مع بيانات التحليل", identity_status, identity_detail)

    visual_status = chart.get("status", "NOT_REPORTED")
    visual_ok = visual_status == "READY" and chart.get("decision_eligible") is True
    add("المحرك الثاني — التحليل البصري والسعري", "تحليل الصورة وأهلية المعايرة", "READY" if visual_ok else visual_status,
        f"أهلية القرار: {'نعم' if visual_ok else 'لا'} | الشموع المكتشفة: {chart.get('detected_bar_count', '—')} | مصدر المعايرة: {_dict(chart.get('calibration')).get('source', '—')}.")
    reference = _dict(chart.get("reference_multi_calibration"))
    axis = _dict(chart.get("reference_axis_validation"))
    geometry_status = "READY" if reference.get("status") == "READY" and axis.get("status") == "READY" else reference.get("status") or axis.get("status") or "NOT_REPORTED"
    add("المحرك الثاني — التحليل البصري والسعري", "معايرة محور السعر والهندسة", geometry_status,
        f"ملاءمة المراجع: {reference.get('status', '—')} | تحقق المحور: {axis.get('status', '—')} | أهلية الصورة: {'نعم' if visual_ok else 'لا'}.")
    native_ohlc = _dict(chart.get("native_ohlc_analysis"))
    add("المحرك الثاني — التحليل البصري والسعري", "مطابقة OHLC مع شموع MT5 الأصلية", native_ohlc.get("status"),
        native_ohlc.get("reason") or "نتيجة مقارنة هندسة الصورة مع OHLC الأصلي؛ لا تتجاوز بوابات المعايرة.")
    patterns = _dict(chart.get("reference_patterns"))
    add("المحرك الثاني — التحليل البصري والسعري", "مرجع الأنماط الحسابي TA-Lib", patterns.get("status"),
        f"التعريفات: {patterns.get('pattern_definition_count', '—')} | الأحداث: {patterns.get('event_count', '—')}.")
    frames = _dict(candles.get("timeframes"))
    add("المحرك الثاني — التحليل البصري والسعري", "سجل الشموع الأصلية متعددة الأطر", candles.get("status"),
        f"الأطر المستلمة: {len(frames)} | " + (", ".join(f"{tf}: {count}" for tf, count in frames.items()) or "لا توجد شموع."))
    pa_summary = _dict(price_action.get("summary"))
    add("المحرك الثاني — التحليل البصري والسعري", "تحليل القمم والقيعان وبنية السعر", price_action.get("status"),
        f"الاتجاه البنيوي: {price_action.get('direction', '—')} | الأطر المؤهلة: {', '.join(pa_summary.get('eligible_timeframes', [])) or '—'} | {price_action.get('reason') or ''}")
    add("المحرك الثاني — التحليل البصري والسعري", "التوافق البنيوي بين الأطر الزمنية", multi_tf.get("status"),
        f"الأطر المؤهلة: {', '.join(multi_tf.get('eligible_timeframes', [])) or '—'} | التوافق: {multi_tf.get('alignment', '—')} | {multi_tf.get('reason') or ''}")

    # Engine 3
    values = _dict(indicators.get("values"))
    add("المحرك الثالث — المؤشرات", "EMA / RSI / ATR والمؤشرات المحسوبة", indicators.get("status"),
        f"EMA20/1m: {values.get('ema20_1m', '—')} | RSI14/1m: {values.get('rsi14_1m', '—')} | ATR14/5m: {values.get('atr14_5m', '—')} | مصدر الشموع: {indicators.get('source', '—')}.")
    add("المحرك الثالث — المؤشرات", "تغذية مؤشرات MT5 الأصلية وCopyBuffer", native_indicators.get("status"),
        f"المؤشرات الجاهزة: {native_indicators.get('ready_indicator_count', '—')} | المفقودة: {', '.join(native_indicators.get('missing_required_indicators', [])) or 'لا يوجد'} | {native_indicators.get('reason') or ''}")

    # Engine 4
    add("المحرك الرابع — القرار وإدارة الصفقات", "محرك القرار المركزي", decision.get("status"),
        f"القرار: {decision.get('action', '—')} | الإشارة المرشحة: {decision.get('candidate_action', '—')} | جاهزية الأمر: {'نعم' if decision.get('command_ready') else 'لا'} | {decision.get('reason') or ''}")
    risk_plan = _dict(decision.get("risk_plan"))
    add("المحرك الرابع — القرار وإدارة الصفقات", "حساب الدخول والوقف والهدف والحجم", risk_plan.get("status"),
        f"الحجم: {risk_plan.get('volume', '—')} | المخاطرة النقدية: {risk_plan.get('risk_cash', '—')} | {risk_plan.get('reason') or ''}")
    if daily_risk.get("enabled") is False or daily_risk.get("mode") == "DISABLED_FOR_DEVELOPMENT":
        add("المحرك الرابع — القرار وإدارة الصفقات", "حاجز حد الخسارة اليومية", "DISABLED_FOR_DEVELOPMENT",
            "معطّل خلال التطوير حسب الإعداد الحالي؛ لا يعني تعطيل بقية ضوابط المخاطر.", "SAFE_DISABLED")
    elif daily_risk.get("locked") is True:
        add("المحرك الرابع — القرار وإدارة الصفقات", "حاجز حد الخسارة اليومية", "LOCKED",
            daily_risk.get("reason") or "الحاجز يمنع فتح مراكز جديدة.", "SAFE_DISABLED")
    else:
        add("المحرك الرابع — القرار وإدارة الصفقات", "حاجز حد الخسارة اليومية", daily_risk.get("status"),
            daily_risk.get("reason") or "حالة حد الخسارة اليومية.")
    positions = bridge.get("positions")
    if bridge.get("status") == "CONNECTED" and isinstance(positions, list):
        add("المحرك الرابع — القرار وإدارة الصفقات", "متابعة المراكز المفتوحة وحمايتها",
            "READY" if positions else "NO_OPEN_POSITIONS", f"لقطة المراكز وصلت من الخبير؛ عدد المراكز: {len(positions)}.", "HEALTHY")
    else:
        add("المحرك الرابع — القرار وإدارة الصفقات", "متابعة المراكز المفتوحة وحمايتها",
            "WAITING_FOR_EXPERT" if bridge.get("status") in {"NOT_CONFIGURED", "WAITING_FOR_EXPERT", None} else bridge.get("status"),
            "مراقبة المراكز تعتمد على لقطة المراكز الحية من المحرك الخامس.")

    # Engine 5
    add("المحرك الخامس — جسر التواصل مع MT5", "نبض الخبير والاتصال الثنائي", bridge.get("status"),
        f"عمر النبض: {bridge.get('heartbeat_age_seconds', '—')} ثانية | الرمز: {bridge.get('symbol', '—')} | رمز السوق: {bridge.get('market_symbol', '—')}.")
    reconciliation = _dict(bridge.get("position_reconciliation"))
    add("المحرك الخامس — جسر التواصل مع MT5", "مطابقة إقرار ACK مع المراكز الفعلية",
        reconciliation.get("status"), reconciliation.get("reason") or "يجب مطابقة ACK مع لقطة مراكز لاحقة؛ ACK وحده لا يثبت التنفيذ.")
    if controls.get("order_publish_enabled") is False:
        add("المحرك الخامس — جسر التواصل مع MT5", "بوابة نشر أوامر MIR1", "PUBLISH_DISABLED",
            "نشر الأوامر معطّل في إعداد البرنامج (MIRSAD_ENABLE_ORDER_PUBLISH=0).", "SAFE_DISABLED")
    else:
        add("المحرك الخامس — جسر التواصل مع MT5", "بوابة نشر أوامر MIR1", command_publish.get("status"),
            command_publish.get("message") or "حالة نشر الأوامر وفق آخر دورة.")

    return items

def summarize_component_health(items: list[dict[str, Any]] | None) -> dict[str, int]:
    counts = Counter(str(item.get("health", "WAITING")) for item in (items or []))
    return {
        "total": sum(counts.values()),
        "healthy": counts.get("HEALTHY", 0),
        "waiting": counts.get("WAITING", 0),
        "attention": counts.get("ATTENTION", 0),
        "safe_disabled": counts.get("SAFE_DISABLED", 0),
    }
