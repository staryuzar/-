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
    "CONFIRMED_FROM_DEAL_HISTORY": "تم تأكيد التنفيذ من سجل صفقات MT5",
    "POSITION_CLOSED_AFTER_MODIFY": "\u0623\u064f\u063a\u0644\u0642 \u0627\u0644\u0645\u0631\u0643\u0632 \u0644\u0627\u062d\u0642\u0627\u064b \u0648\u062a\u0623\u0643\u062f \u0627\u0644\u0625\u063a\u0644\u0627\u0642 \u0645\u0646 \u0633\u062c\u0644 MT5",
    "NO_PENDING_COMMAND": "لا يوجد أمر معلّق",
    "NO_OPEN_POSITIONS": "لا توجد مراكز مفتوحة حالياً",
    "PUBLISH_DISABLED": "نشر الأوامر معطّل",
    "DISABLED_FOR_DEVELOPMENT": "معطّل خلال التطوير",
    "OPTIONAL_DISABLED": "مسار اختياري معطّل بأمان ولا يؤثر في القرار",
    "WAITING_FOR_EXPERT": "بانتظار نبض الخبير",
    "NOT_CONFIGURED": "لم تتم تهيئته على الجهاز بعد",
    "NOT_REPORTED": "لم ترد بيانات حالة بعد",
    "NOT_READY": "غير جاهز",
    "NOT_REQUIRED": "غير مطلوب في هذه الدورة",
    "PARTIAL": "يعمل جزئياً",
    "STALE": "البيانات قديمة",
    "OFFLINE": "غير متصل",
    "ERROR": "خطأ",
    "INVALID": "بيانات غير صالحة",
    "NOT_VERIFIED": "لم يجتز التحقق",
    "LOCKED": "حاجز المخاطر مفعّل",
    "HIGH_IMPACT_EVENT_WINDOW": "توقف دخول مؤقت بسبب حدث اقتصادي عالي الأهمية",
    "WAITING_FOR_CONFLUENCE": "التحليل مكتمل؛ بانتظار توافق اتجاهي كافٍ",
    "WAITING_FOR_ENGINE_2": "المحرك الرابع ينتظر توافق بنية السعر من المحرك الثاني",
    "WAITING_FOR_DIRECTIONAL_SAMPLES": "الأرشيف يحفظ القرارات، لكن لا توجد عينات BUY/SELL بعد",
    "DIRECTIONAL_SAMPLES_AVAILABLE": "توجد عينات BUY/SELL؛ تقييم الأداء لا يزال غير معتمد",
    "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE": "المحرك الثاني لم يجتز بوابة توافق بنية السعر",
    "WAITING_FOR_ENGINE_2_CANDLE_PATTERN_CONFLUENCE": "نماذج الشموع لا تؤكد اتجاهًا موحدًا",
    "NO_DIRECTIONAL_CANDLE_PATTERN": "لا توجد نماذج شموع اتجاهية مؤكدة",
    "BULLISH_CANDLE_PATTERN_EVIDENCE": "نماذج الشموع تميل للصعود",
    "BEARISH_CANDLE_PATTERN_EVIDENCE": "نماذج الشموع تميل للهبوط",
    "MIXED_TIMEFRAME_DIRECTIONS": "اتجاهات الأطر الزمنية متعارضة",
    "MIXED_CANDLE_PATTERN_EVIDENCE": "أدلة نماذج الشموع متعارضة",
    "CANDLE_PATTERN_DIRECTION_CONFLICT": "نموذج الشموع يعارض اتجاه البنية",
    "MIXED_OR_NO_CONFLUENCE": "لا يوجد توافق بنيوي كافٍ",
    "INSUFFICIENT_DIRECTIONAL_FRAME_COVERAGE": "تغطية الأطر ذات الاتجاه المؤكد غير كافية",
    "INSUFFICIENT_STRUCTURE_EVIDENCE_QUALITY": "جودة أدلة بنية السعر غير كافية",
    "STORED": "حُفظت عينة المعايرة",
    "ALREADY_STORED": "العينة محفوظة مسبقاً",
    "SKIPPED": "تُخطيت العينة لعدم اكتمال شروطها",
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
        "CONNECTED", "CONFIRMED", "CONFIRMED_FROM_DEAL_HISTORY", "POSITION_CLOSED_AFTER_MODIFY",
        "NO_PENDING_COMMAND", "NO_OPEN_POSITIONS",
        "VERIFIED", "STORED", "ALREADY_STORED", "NOT_REQUIRED", "DIRECTIONAL_SAMPLES_AVAILABLE",
    }:
        return "HEALTHY"
    if status in {"PUBLISH_DISABLED", "DISABLED_FOR_DEVELOPMENT", "LOCKED", "OPTIONAL_DISABLED"}:
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
    market_intelligence = _dict(state.get("market_intelligence"))
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

    def add(
        engine: str,
        component: str,
        status: Any,
        detail: str = "",
        health: str | None = None,
        source: str | None = None,
    ) -> None:
        raw = str(status or "NOT_REPORTED").strip().upper()
        level = health or _health(raw)
        source_by_component = {
            "نبض ودورة البرنامج الرئيسية": "data/system_status.json · runtime heartbeat",
            "تغذية السوق وسعر MT5": "MT5 Common Files/MirsadBTC/market.json",
            "نبض عروض الأسعار والسبريد": "MT5 Common Files/MirsadBTC/market.json · broker ticks",
            "موجز الأخبار متعدد المصادر": "Engine 1 · CoinDesk / The Block / Decrypt / Cointelegraph",
            "مؤشر الخوف والطمع": "Alternative.me · Fear & Greed Index",
            "المشتقات والتمويل والفائدة المفتوحة": "Engine 1 · Deribit / Gate.io / Bybit / Binance / OKX / Hyperliquid",
            "السياق الكلي والسيناريو السوقي": "Engine 1 · independent market-intelligence aggregation",
            "التقويم الاقتصادي العام المستقل": "Engine 1 · Forex Factory + ShowMyTrades (Trading Economics optional)",
            "سجل الشموع الأصلية متعددة الأطر": "MT5 Common Files/MirsadBTC/observer/candles.json",
            "تحليل القمم والقيعان وبنية السعر": "Engine 2 · native MT5 closed OHLC from observer/candles.json",
            "التوافق البنيوي وجودة الأدلة متعددة الأطر": "Engine 2 · confirmed OHLC swing / BOS / CHOCH analysis",
            "أهلية التصويت الاتجاهي والدخول": "Engine 4 gate · Engine 2 native OHLC eligibility",
            "EMA / RSI / ATR والمؤشرات المحسوبة": "Engine 3 · closed candles supplied by Engine 2",
            "تغذية مؤشرات MT5 الأصلية وCopyBuffer": "MT5 Common Files/MirsadBTC/observer/indicators.json · CopyBuffer",
            "محرك القرار المركزي": "Engine 4 · Engine 1 (20%) + Engine 2 (55%) + Engine 3 (25%)",
            "حفظ أدلة معايرة القرار": "data/decision_calibration.sqlite3",
            "تغطية عينات القرار الاتجاهية": "data/decision_calibration.sqlite3 · final BUY/SELL/WAIT action counts",
            "حساب الدخول والوقف والهدف والحجم": "Engine 4 risk plan · live MT5 account and symbol specifications",
            "حاجز حد الخسارة اليومية": "Engine 4 daily-risk configuration and persisted daily-risk state",
            "متابعة المراكز المفتوحة وحمايتها": "MT5 Common Files/MirsadBTC/positions.json",
            "نبض الخبير والاتصال الثنائي": "MT5 Common Files/MirsadBTC/status.json · MIR1",
            "مطابقة إقرار ACK مع المراكز الفعلية": "MT5 Common Files/MirsadBTC/ack.json + positions.json",
            "دفتر صفقات الوسيط المحفوظ": "MT5 deals.json + local SQLite deal ledger",
            "بوابة نشر أوامر MIR1": "MIRSAD_ENABLE_ORDER_PUBLISH + Engine 4 command_publish",
        }
        items.append({
            "engine": engine,
            "component": component,
            "source": source or source_by_component.get(
                component, "data/system_status.json · runtime component telemetry"
            ),
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
    runtime_error = str(state.get("runtime_error") or "").strip()
    runtime_failed = str(state.get("overall_status") or "").upper() == "ERROR" or bool(runtime_error)
    runtime_status = (
        "ERROR" if runtime_failed
        else "RUNNING" if age is not None and 0 <= age <= limit
        else "STALE" if age is not None
        else "NOT_REPORTED"
    )
    if runtime_failed:
        runtime_detail = f"فشلت آخر دورة تشغيل: {runtime_error or 'runtime أعلن ERROR دون تفاصيل نصية.'}"
    elif age is not None:
        runtime_detail = f"آخر نبض: {age:.1f} ثانية؛ حد المراقبة: {limit} ثانية."
    else:
        runtime_detail = "لم يسجل runtime نبضاً صالحاً."
    add("التشغيل", "نبض ودورة البرنامج الرئيسية", runtime_status, runtime_detail)

    # Engine 5 broker quote telemetry is separate from Engine 1 intelligence.
    market_age = state.get("market_age_seconds")
    add("المحرك الخامس — جسر التواصل مع MT5", "تغذية السوق وسعر MT5", market.get("status"),
        f"السعر: {market.get('price', '—')} | المصدر: {market.get('primary_venue', '—')} | عمر البيانات: {market_age if market_age is not None else '—'} ثانية.")
    venues = _dict(market.get("venues"))
    primary_name = str(market.get("primary_venue") or "")
    primary = _dict(venues.get(primary_name))
    micro = _dict(primary.get("microstructure"))
    add("المحرك الخامس — جسر التواصل مع MT5", "نبض عروض الأسعار والسبريد", micro.get("status"),
        f"المصدر: {primary_name or 'غير محدد'} | تحديث/دقيقة: {micro.get('tick_rate_per_minute', '—')} | السبريد: {micro.get('current_spread_pct', '—')}. حركة Bid/Ask وليست صفقات منفذة.")

    intel_news = _dict(market_intelligence.get("news"))
    add("المحرك الأول — استخبارات السوق", "موجز الأخبار متعدد المصادر", intel_news.get("status"),
        f"العناوين: {intel_news.get('count', 0)} | المصادر الحية: {', '.join(k for k,v in _dict(intel_news.get('sources')).items() if v == 'READY') or 'لا يوجد'}.")
    fear = _dict(market_intelligence.get("fear_greed"))
    add("المحرك الأول — استخبارات السوق", "مؤشر الخوف والطمع", fear.get("status"),
        f"القيمة: {fear.get('value', '—')} | {fear.get('classification', '—')} | مصدر Alternative.me.")
    derivatives = _dict(market_intelligence.get("derivatives"))
    add("المحرك الأول — استخبارات السوق", "المشتقات والتمويل والفائدة المفتوحة", derivatives.get("status"),
        f"المنصات: {derivatives.get('venue_count', 0)} | درجة التموضع: {derivatives.get('score', '—')} | بيانات مشتقات خاصة بكل منصة.")
    add("المحرك الأول — استخبارات السوق", "السياق الكلي والسيناريو السوقي", market_intelligence.get("status"),
        f"الميل: {market_intelligence.get('direction', 'UNKNOWN')} | درجة السياق: {market_intelligence.get('directional_score', '—')} | تغطية الأدلة: {market_intelligence.get('evidence_coverage', 0)} | الثقة ليست احتمال ربح.")
    intel_calendar = _dict(market_intelligence.get("economic_calendar"))
    calendar_sources = _dict(intel_calendar.get("sources"))
    calendar_window_active = intel_calendar.get("high_impact_window_active") is True
    calendar_health_status = "HIGH_IMPACT_EVENT_WINDOW" if calendar_window_active else intel_calendar.get("status")
    add("المحرك الأول — استخبارات السوق", "التقويم الاقتصادي العام المستقل", calendar_health_status,
        f"المزودون: {', '.join(f'{name}={status}' for name, status in calendar_sources.items()) or 'لا يوجد'} | بوابة المداخل: {intel_calendar.get('new_entry_gate', 'NOT_REPORTED')} | الأحداث النشطة: {len(intel_calendar.get('active_high_impact_events', []))}.")

    # Engine 2 native OHLC is the sole price-action source.
    frames = _dict(candles.get("timeframes"))
    add(
        "المحرك الثاني — الشموع وبنية السعر",
        "سجل الشموع الأصلية متعددة الأطر",
        candles.get("status"),
        f"الأطر المستلمة: {len(frames)} | "
        + (", ".join(f"{tf}: {count}" for tf, count in frames.items()) or "لا توجد شموع.")
    )
    pa_summary = _dict(price_action.get("summary"))
    eligible = pa_summary.get("eligible_timeframes", [])
    add(
        "المحرك الثاني — الشموع وبنية السعر",
        "تحليل القمم والقيعان وبنية السعر",
        price_action.get("status"),
        f"الاتجاه: {price_action.get('direction', '—')} | الدرجة: {price_action.get('structure_score', '—')} | "
        f"الأطر المؤهلة: {', '.join(eligible) or '—'} | {price_action.get('reason') or ''}"
    )
    alignment = pa_summary.get("timeframe_alignment", multi_tf.get("alignment", "—"))
    coverage = pa_summary.get("timeframe_weight_coverage", "—")
    agreement = pa_summary.get("directional_structure_agreement", "—")
    confluence_status = (
        "READY"
        if alignment in {"BULLISH_STRUCTURE_CONFLUENCE", "BEARISH_STRUCTURE_CONFLUENCE"}
        else "WAITING_FOR_CONFLUENCE"
        if price_action.get("status") == "READY"
        else multi_tf.get("status", price_action.get("status"))
    )
    add(
        "المحرك الثاني — الشموع وبنية السعر",
        "التوافق البنيوي وجودة الأدلة متعددة الأطر",
        confluence_status,
        f"التوافق: {alignment} | تغطية الأطر: {coverage} | اتفاق البنية: {agreement}."
    )
    price_action_context = _dict(decision.get("engine_2_native_price_action_context"))
    decision_eligible = price_action_context.get(
        "decision_eligible", price_action.get("decision_eligible")
    ) is True
    observed_direction = price_action_context.get(
        "direction", price_action.get("direction", "UNKNOWN")
    )
    confluence_gate = price_action_context.get(
        "gate", alignment or "NOT_REPORTED"
    )
    directional_coverage = price_action_context.get(
        "directional_frame_coverage", pa_summary.get("directional_frame_coverage", "—")
    )
    eligibility_status = (
        "READY" if decision_eligible
        else "WAITING_FOR_CONFLUENCE" if price_action.get("status") == "READY"
        else price_action.get("status", "NOT_REPORTED")
    )
    add(
        "المحرك الثاني — الشموع وبنية السعر",
        "أهلية التصويت الاتجاهي والدخول",
        eligibility_status,
        f"الاتجاه المرصود: {observed_direction} | مؤهل للتصويت: {'نعم' if decision_eligible else 'لا'} | "
        f"تغطية الاتجاه: {directional_coverage} | بوابة التوافق: {confluence_gate}."
    )

    # Engine 3
    values = _dict(indicators.get("values"))
    add("المحرك الثالث — المؤشرات", "EMA / RSI / ATR والمؤشرات المحسوبة", indicators.get("status"),
        f"EMA20/1m: {values.get('ema20_1m', '—')} | RSI14/1m: {values.get('rsi14_1m', '—')} | ATR14/5m: {values.get('atr14_5m', '—')} | مصدر الشموع: {indicators.get('source', '—')}.")
    native_frames = _dict(native_indicators.get("timeframes"))
    native_ready_count = 0
    native_expected_count = 0
    native_missing: set[str] = set()
    for native_frame in native_frames.values():
        frame = _dict(native_frame)
        frame_values = _dict(frame.get("values"))
        native_expected_count += len(frame_values)
        try:
            frame_ready_count = int(frame.get("ready_indicator_count"))
        except (TypeError, ValueError, OverflowError):
            frame_ready_count = sum(
                1 for item in frame_values.values()
                if _dict(item).get("status") == "READY"
            )
        native_ready_count += max(0, frame_ready_count)
        native_missing.update(
            str(item) for item in (frame.get("missing_required_indicators") or [])
        )
    parity = _dict(indicators.get("mt5_native_parity"))
    parity_frames = _dict(parity.get("timeframes"))
    parity_passed = sum(
        1 for frame in parity_frames.values()
        for metric in _dict(frame).get("metrics", {}).values()
        if _dict(metric).get("status") == "PASS"
    )
    parity_total = sum(
        len(_dict(frame).get("metrics", {}))
        for frame in parity_frames.values()
    )
    parity_text = (
        f" | تطابق Engine 3/MT5: {parity_passed}/{parity_total} ({parity.get('status')})"
        if parity_total else " | لم يرد تقرير تطابق رقمي مستقل"
    )
    native_count_text = (
        f"{native_ready_count}/{native_expected_count}"
        if native_expected_count else "غير متاح"
    )
    alignment_text = str(native_indicators.get("bar_alignment_status", "NOT_CHECKED"))
    add(
        "المحرك الثالث — المؤشرات",
        "تغذية مؤشرات MT5 الأصلية وCopyBuffer",
        native_indicators.get("status"),
        f"القيم الجاهزة: {native_count_text} | الأطر الجاهزة: {native_indicators.get('ready_timeframe_count', 0)}/6 | "
        f"تزامن توقيت الشموع: {alignment_text} | المفقودة: {', '.join(sorted(native_missing)) or 'لا يوجد'}"
        f"{parity_text} | {native_indicators.get('reason') or ''}",
    )

    # Engine 4
    decision_status = str(decision.get("status", "NOT_REPORTED")).upper()
    decision_context = _dict(decision.get("engine_2_native_price_action_context"))
    if decision_status == "WAITING_FOR_ENGINE_2":
        decision_detail = (
            f"القرار: {decision.get('action', 'WAIT')} | الإشارة المرشحة: {decision.get('candidate_action', 'WAIT')} | "
            f"جاهزية الأمر: لا | بوابة بنية السعر: {_label(decision_context.get('gate', decision.get('engine_2_confluence_gate')))} | "
            f"اتجاهات الأطر: {_label(decision_context.get('timeframe_alignment'))} | "
            f"نماذج الشموع: {_label(decision_context.get('latest_candle_pattern_alignment'))} | "
            "لا يُرسل دخول جديد قبل اجتياز شروط المحرك الثاني."
        )
    else:
        decision_detail = (
            f"القرار: {decision.get('action', '—')} | الإشارة المرشحة: {decision.get('candidate_action', '—')} | "
            f"جاهزية الأمر: {'نعم' if decision.get('command_ready') else 'لا'} | {decision.get('reason') or 'ستظهر تفاصيل القرار بعد اكتمال مدخلات المحركات.'}"
        )
    add("المحرك الرابع — القرار وإدارة الصفقات", "محرك القرار المركزي", decision_status, decision_detail)
    calibration = _dict(state.get("decision_calibration_persistence"))
    calibration_archive = _dict(state.get("decision_calibration_archive"))
    calibration_count = calibration.get("sample_count", calibration.get("write_reported_sample_count", "—"))
    add(
        "المحرك الرابع — القرار وإدارة الصفقات",
        "حفظ أدلة معايرة القرار",
        calibration.get("status"),
        f"ملف الأوزان: {calibration.get('profile_version', '—')} | عينة الحفظ الأخيرة: {calibration_count} | {calibration.get('reason') or ''}",
    )
    if calibration_archive:
        final_counts = _dict(calibration_archive.get("current_profile_final_action_counts"))
        candidate_counts = _dict(calibration_archive.get("current_profile_candidate_action_counts"))
        directional_count = int(calibration_archive.get("current_profile_directional_sample_count", 0) or 0)
        if calibration_archive.get("status") == "ERROR":
            archive_status = "ERROR"
            archive_health = "ATTENTION"
        elif directional_count > 0:
            archive_status = "DIRECTIONAL_SAMPLES_AVAILABLE"
            archive_health = "HEALTHY"
        else:
            archive_status = "WAITING_FOR_DIRECTIONAL_SAMPLES"
            archive_health = "WAITING"
        add(
            "المحرك الرابع — القرار وإدارة الصفقات",
            "تغطية عينات القرار الاتجاهية",
            archive_status,
            f"العينات: {calibration_archive.get('current_profile_sample_count', '—')} | "
            f"القرارات النهائية: BUY={final_counts.get('BUY', 0)} / SELL={final_counts.get('SELL', 0)} / WAIT={final_counts.get('WAIT', 0)} | "
            f"المرشحة: BUY={candidate_counts.get('BUY', 0)} / SELL={candidate_counts.get('SELL', 0)} / WAIT={candidate_counts.get('WAIT', 0)} | "
            f"حالة الأداء: {calibration_archive.get('validation_status', 'UNVALIDATED')} | "
            f"{calibration_archive.get('note') or calibration_archive.get('reason') or '' }",
            archive_health,
        )
    risk_plan = _dict(decision.get("risk_plan"))
    add("المحرك الرابع — القرار وإدارة الصفقات", "حساب الدخول والوقف والهدف والحجم", risk_plan.get("status"),
        f"الحجم: {risk_plan.get('volume', '—')} | ميزانية المخاطرة: {risk_plan.get('risk_cash', '—')} | خسارة السعر: {risk_plan.get('estimated_stop_loss', '—')} | العمولة المقدرة: {risk_plan.get('estimated_commission', '—')} | الإجمالي عند الوقف: {risk_plan.get('estimated_loss', '—')} | {risk_plan.get('reason') or ''}")
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
    reconciliation_detail = reconciliation.get("reason") or "\u064a\u062c\u0628 \u0645\u0637\u0627\u0628\u0642\u0629 ACK \u0645\u0639 \u0644\u0642\u0637\u0629 \u0645\u0631\u0627\u0643\u0632 \u0644\u0627\u062d\u0642\u0629"
    if reconciliation.get("status") == "POSITION_CLOSED_AFTER_MODIFY":
        reconciliation_detail += " | close_kind={} | closed_volume={} | deal_tickets={}".format(
            reconciliation.get("close_kind", "UNKNOWN"), reconciliation.get("closed_volume", "?"),
            ",".join(reconciliation.get("deal_tickets", [])),
        )
    add("المحرك الخامس — جسر التواصل مع MT5", "مطابقة إقرار ACK مع المراكز الفعلية",
        reconciliation.get("status"), reconciliation_detail)
    deal_history = _dict(bridge.get("deal_history"))
    deal_persistence = _dict(bridge.get("deal_ledger_persistence"))
    deal_status = str(deal_history.get("status", "NOT_REPORTED"))
    if deal_status == "READY" and deal_persistence.get("status") == "READY":
        add("المحرك الخامس — جسر التواصل مع MT5", "دفتر صفقات الوسيط المحفوظ",
            "READY",
            f"صفقات مرصاد المطابقة: {deal_history.get('deal_count', deal_persistence.get('received', 0))} | العملة: {deal_persistence.get('currency', '—')} | نافذة السجل: {deal_history.get('truncated', False) and 'مقتطعة بسبب حد التصدير' or 'ضمن الحد'}.",
            "HEALTHY")
    elif deal_status in {"NOT_REPORTED", "WAITING_FOR_EXPERT"}:
        add("المحرك الخامس — جسر التواصل مع MT5", "دفتر صفقات الوسيط المحفوظ",
            "NOT_REPORTED", deal_history.get("reason") or "بانتظار ملف سجل الصفقات من خبير MT5.")
    else:
        add("المحرك الخامس — جسر التواصل مع MT5", "دفتر صفقات الوسيط المحفوظ",
            "INVALID", deal_history.get("reason") or deal_persistence.get("reason") or "تعذر التحقق من سجل صفقات الوسيط.")
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

