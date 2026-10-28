"""Transparent rule-based adviser over the TV26 rating and chart scanner.

This module produces an auditable interpretation only. It does not estimate a
win probability, issue an order, or calculate an executable entry/stop/target.
"""
from __future__ import annotations

import math
from typing import Any

RULE_VERSION = "0.1.0"
CONFIRMED_SETUP_STATES = frozenset({
    "confirmed_on_closed_bar", "confirmed_breakdown", "confirmed_breakout",
})


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "engine": "Gold Intelligence Lab rule adviser",
        "rule_version": RULE_VERSION,
        "status": "BLOCKED_DATA_QUALITY",
        "title_ar": "تعذّر التقييم الحالي بسبب جودة البيانات",
        "summary_ar": reason,
        "evidence_ar": [],
        "conflicts_ar": [],
        "missing_evidence_ar": [],
        "probability": None,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "trade_execution_enabled": False,
        "mode": "analysis_only",
    }


def build_advisory(technical_report: dict[str, Any], scanner_report: dict[str, Any]) -> dict[str, Any]:
    """Combine closed-bar technical votes and scanner evidence without issuing trade instructions."""
    if not isinstance(technical_report, dict) or not isinstance(scanner_report, dict):
        raise ValueError("Adviser inputs must be analysis dictionaries.")
    market_review = technical_report.get("current_market_review") or {}
    readiness = technical_report.get("readiness") or {}
    ratings = technical_report.get("ratings") or {}
    if not market_review.get("eligible", False):
        return _blocked(
            market_review.get("reason_ar", "البيانات غير مؤهلة لمراجعة سوق حالية.")
        )
    if not readiness.get("complete", False):
        return _blocked("لا تزال بعض المؤشرات غير جاهزة؛ لم يُصدر المستشار توافقًا اتجاهيًا.")
    rating = ratings.get("overall")
    if rating is None or not math.isfinite(float(rating)):
        return _blocked("التقييم الكلي غير متاح؛ لم يتم استنتاج اتجاه من قيمة مفقودة.")
    rating = float(rating)

    trend = (scanner_report.get("trend") or {}).get("state", "mixed")
    setups = scanner_report.get("setups") or []
    confirmed = [
        item for item in setups
        if isinstance(item, dict) and item.get("status") in CONFIRMED_SETUP_STATES
    ]
    bullish = [item for item in confirmed if item.get("direction") == "bullish"]
    bearish = [item for item in confirmed if item.get("direction") == "bearish"]

    strong_bullish = rating > 0.5
    strong_bearish = rating < -0.5
    evidence: list[str] = [
        f"التقييم الكلي الداخلي: {rating:.3f} ({ratings.get('overall_category_ar', 'غير مصنف')})."
    ]
    evidence.append((scanner_report.get("trend") or {}).get(
        "reason_ar", "حالة الاتجاه مأخوذة من محرك الماسح."
    ))
    for item in confirmed:
        evidence.append(
            f"نموذج مؤكد على إغلاق شمعة: {item.get('type', 'نموذج غير مسمى')} "
            f"({item.get('direction', 'اتجاه غير معروف')})."
        )

    conflicts: list[str] = []
    missing: list[str] = []
    if strong_bullish and trend == "bearish":
        conflicts.append("التقييم الكلي قوي الصعود بينما الاتجاه الوصفي للماسح هابط.")
    if strong_bearish and trend == "bullish":
        conflicts.append("التقييم الكلي قوي الهبوط بينما الاتجاه الوصفي للماسح صاعد.")
    if strong_bullish and bearish:
        conflicts.append("التقييم الكلي قوي الصعود لكن الماسح يرصد نموذجًا مؤكدًا في الاتجاه الهابط.")
    if strong_bearish and bullish:
        conflicts.append("التقييم الكلي قوي الهبوط لكن الماسح يرصد نموذجًا مؤكدًا في الاتجاه الصاعد.")
    if bullish and bearish:
        conflicts.append("توجد نماذج مؤكدة متعارضة الاتجاه في آخر الشموع.")

    if strong_bullish and not bullish:
        missing.append("لا يوجد حاليًا نموذج صاعد مؤكد يدعم التقييم الكلي.")
    if strong_bearish and not bearish:
        missing.append("لا يوجد حاليًا نموذج هابط مؤكد يدعم التقييم الكلي.")
    if strong_bullish and trend != "bullish":
        missing.append("الاتجاه الوصفي الصاعد غير مكتمل.")
    if strong_bearish and trend != "bearish":
        missing.append("الاتجاه الوصفي الهابط غير مكتمل.")

    if conflicts:
        status = "CONFLICTING_EVIDENCE"
        title = "تعارض أدلة — لا تفضيل لاتجاه"
        summary = "توجد أدلة لا تتفق فيما بينها. يعرض المستشار أسباب التعارض ولا يحوّلها إلى توصية تداول."
    elif strong_bullish and trend == "bullish" and bullish:
        status = "BULLISH_CONFLUENCE"
        title = "توافق تحليلي صاعد — للمراجعة فقط"
        summary = "التقييم الكلي والاتجاه والنموذج المؤكد متسقة، لكن هذا ليس أمر شراء ولا يثبت ربحية السيناريو."
    elif strong_bearish and trend == "bearish" and bearish:
        status = "BEARISH_CONFLUENCE"
        title = "توافق تحليلي هابط — للمراجعة فقط"
        summary = "التقييم الكلي والاتجاه والنموذج المؤكد متسقة، لكن هذا ليس أمر بيع ولا يثبت ربحية السيناريو."
    elif strong_bullish or strong_bearish:
        status = "INCOMPLETE_CONFLUENCE"
        title = "توافق غير مكتمل — يلزم دليل إضافي"
        summary = "التقييم الكلي قوي لكن لا تتوافر جميع أدلة الاتجاه والنموذج المطلوبة وفق قواعد المستشار."
    else:
        status = "NO_STRONG_CONFLUENCE"
        title = "لا يوجد توافق قوي كافٍ"
        summary = "لا يجتمع تقييم كلي قوي مع اتجاه ونموذج مؤكد ضمن القواعد الحالية؛ لا يستنتج المستشار صفقة."

    return {
        "engine": "Gold Intelligence Lab rule adviser",
        "rule_version": RULE_VERSION,
        "status": status,
        "title_ar": title,
        "summary_ar": summary,
        "evidence_ar": evidence,
        "conflicts_ar": conflicts,
        "missing_evidence_ar": missing,
        "rating": rating,
        "rating_category_ar": ratings.get("overall_category_ar", "غير مصنف"),
        "trend_state": trend,
        "confirmed_bullish_setups": [item.get("type") for item in bullish],
        "confirmed_bearish_setups": [item.get("type") for item in bearish],
        "probability": None,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "trade_execution_enabled": False,
        "mode": "analysis_only",
        "interpretation_ar": "درجة التقييم ليست احتمال نجاح إحصائيًا. لا توجد في هذا المكوّن أوامر تداول أو أهداف تنفيذية.",
    }


__all__ = ["build_advisory"]
