"""Cross-timeframe consensus over independent live analysis reports.

This module never fetches prices or issues orders. It summarizes only reports
calculated by the caller and blocks consensus when any required timeframe is
missing, has incomplete indicators, or fails current-market data-quality checks.
"""
from __future__ import annotations

from typing import Any

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1")
BULLISH_CATEGORIES = frozenset({"شراء", "شراء قوي"})
BEARISH_CATEGORIES = frozenset({"بيع", "بيع قوي"})


def summarize_timeframe_consensus(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return a transparent five-timeframe alignment state without a trade order."""
    if not isinstance(reports, dict):
        raise ValueError("reports must be a dictionary keyed by timeframe.")

    rows: list[dict[str, Any]] = []
    counts = {"bullish": 0, "bearish": 0, "neutral": 0, "unavailable": 0}
    missing: list[str] = []
    blocked: list[str] = []

    for timeframe in TIMEFRAMES:
        report = reports.get(timeframe)
        if not isinstance(report, dict):
            missing.append(timeframe)
            rows.append({"timeframe": timeframe, "category": "غير متاح",
                         "bias": "unavailable", "eligible": False, "ready": False})
            counts["unavailable"] += 1
            continue

        analysis = report.get("analysis") or {}
        ratings = analysis.get("ratings") or {}
        readiness = analysis.get("readiness") or {}
        review = analysis.get("current_market_review") or {}
        category = str(ratings.get("overall_category_ar") or "غير متاح")
        ready = bool(readiness.get("complete", False))
        eligible = bool(review.get("eligible", False))
        if not ready or not eligible:
            blocked.append(timeframe)
        if category in BULLISH_CATEGORIES:
            bias = "bullish"
        elif category in BEARISH_CATEGORIES:
            bias = "bearish"
        elif category == "حياد":
            bias = "neutral"
        else:
            bias = "unavailable"
        counts[bias] += 1
        rows.append({"timeframe": timeframe, "category": category, "bias": bias,
                     "eligible": eligible, "ready": ready,
                     "rating": ratings.get("overall"),
                     "reason_ar": review.get("reason_ar", "")})

    all_present = not missing
    all_eligible = all_present and not blocked and counts["unavailable"] == 0
    bullish, bearish, neutral = counts["bullish"], counts["bearish"], counts["neutral"]

    status = "BLOCKED_OR_INCOMPLETE"
    title = "لا يمكن اعتماد توافق الأطر الخمسة"
    summary = "يلزم توفر الأطر الخمسة مع مؤشرات مكتملة وبيانات سوق مؤهلة وحديثة."
    if all_eligible:
        if bullish == 5 and all(r["category"] == "شراء قوي" for r in rows):
            status, title = "STRONG_BUY_ALL_FIVE", "شراء قوي متوافق على الأطر الخمسة"
            summary = "كل الأطر الخمسة مصنفة شراء قوي. هذه نتيجة تحليلية فقط وليست أمر تداول أو إثبات ربحية."
        elif bearish == 5 and all(r["category"] == "بيع قوي" for r in rows):
            status, title = "STRONG_SELL_ALL_FIVE", "بيع قوي متوافق على الأطر الخمسة"
            summary = "كل الأطر الخمسة مصنفة بيع قوي. هذه نتيجة تحليلية فقط وليست أمر تداول أو إثبات ربحية."
        elif bullish == 5:
            status, title = "BULLISH_ALIGNMENT_ALL_FIVE", "توافق صاعد على الأطر الخمسة"
            summary = "الأطر الخمسة صاعدة، لكن ليس جميعها مصنفًا شراء قوي."
        elif bearish == 5:
            status, title = "BEARISH_ALIGNMENT_ALL_FIVE", "توافق هابط على الأطر الخمسة"
            summary = "الأطر الخمسة هابطة، لكن ليس جميعها مصنفًا بيع قوي."
        elif bullish >= 4:
            status, title = "PARTIAL_BULLISH_ALIGNMENT", "ميل صاعد مع اختلاف إطار زمني"
            summary = "أربعة أطر أو أكثر صاعدة؛ يوجد اختلاف ولا يصح وصفها كتوافق كامل."
        elif bearish >= 4:
            status, title = "PARTIAL_BEARISH_ALIGNMENT", "ميل هابط مع اختلاف إطار زمني"
            summary = "أربعة أطر أو أكثر هابطة؛ يوجد اختلاف ولا يصح وصفها كتوافق كامل."
        else:
            status, title = "MIXED_TIMEFRAMES", "الأطر الزمنية متعارضة أو محايدة"
            summary = "لا يوجد توافق اتجاهي كافٍ بين الأطر الخمسة."
    return {
        "status": status, "title_ar": title, "summary_ar": summary,
        "timeframes_required": list(TIMEFRAMES), "rows": rows, "counts": counts,
        "missing_timeframes": missing, "blocked_timeframes": blocked,
        "all_five_present": all_present, "all_five_eligible": all_eligible,
        "trade_execution_enabled": False, "mode": "analysis_only",
    }


__all__ = ["TIMEFRAMES", "summarize_timeframe_consensus"]
