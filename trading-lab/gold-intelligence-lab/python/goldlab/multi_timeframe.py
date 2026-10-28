"""Cross-timeframe consensus with data-quality and snapshot-integrity gates."""
from __future__ import annotations
from typing import Any

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1")
BULLISH_CATEGORIES = frozenset({"شراء", "شراء قوي"})
BEARISH_CATEGORIES = frozenset({"بيع", "بيع قوي"})


def summarize_timeframe_consensus(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarize five frames; reject absent frames, stale data, or mixed snapshots."""
    if not isinstance(reports, dict):
        raise ValueError("reports must be a dictionary keyed by timeframe.")

    rows: list[dict[str, Any]] = []
    counts = {"bullish": 0, "bearish": 0, "neutral": 0, "unavailable": 0}
    missing: list[str] = []
    blocked: list[str] = []
    snapshot_issues: list[str] = []
    snapshot_ids: set[str] = set()
    capture_times: set[str] = set()

    for timeframe in TIMEFRAMES:
        report = reports.get(timeframe)
        if not isinstance(report, dict):
            missing.append(timeframe)
            rows.append({"timeframe": timeframe, "category": "غير متاح",
                         "bias": "unavailable", "eligible": False, "ready": False,
                         "snapshot_id": None, "snapshot_captured_at_utc": None})
            counts["unavailable"] += 1
            continue

        source = report.get("market_source") or {}
        snapshot_id = str(source.get("snapshot_id") or "").strip()
        captured_at = str(source.get("snapshot_captured_at_utc") or "").strip()
        source_consistent = source.get("snapshot_time_consistent") is True
        if not snapshot_id or not captured_at or not source_consistent:
            snapshot_issues.append(timeframe)
        if snapshot_id:
            snapshot_ids.add(snapshot_id)
        if captured_at:
            capture_times.add(captured_at)

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
        rows.append({
            "timeframe": timeframe, "category": category, "bias": bias,
            "eligible": eligible, "ready": ready, "rating": ratings.get("overall"),
            "reason_ar": review.get("reason_ar", ""),
            "snapshot_id": snapshot_id or None,
            "snapshot_captured_at_utc": captured_at or None,
        })

    all_present = not missing
    if snapshot_issues:
        snapshot_message = "بيانات اللقطة ناقصة أو غير موثقة في الأطر: " + "، ".join(snapshot_issues)
    elif len(snapshot_ids) != 1 or len(capture_times) != 1:
        snapshot_message = "الأطر لا تنتمي إلى لقطة واحدة؛ مُنع تجميعها في توافق مشترك."
        snapshot_issues = [row["timeframe"] for row in rows if row["timeframe"] in reports]
    elif not all_present:
        snapshot_message = "لا يمكن تأكيد اتساق اللقطة قبل توفر الأطر الخمسة."
    else:
        snapshot_message = "معرّف اللقطة ووقت الالتقاط متطابقان في الأطر الخمسة."
    snapshot_consistent = (
        all_present and not snapshot_issues and len(snapshot_ids) == 1 and len(capture_times) == 1
        and all(row.get("snapshot_id") for row in rows)
        and all(row.get("snapshot_captured_at_utc") for row in rows)
    )
    snapshot_integrity = {
        "consistent": bool(snapshot_consistent),
        "snapshot_id": next(iter(snapshot_ids)) if len(snapshot_ids) == 1 else None,
        "snapshot_captured_at_utc": next(iter(capture_times)) if len(capture_times) == 1 else None,
        "issues": snapshot_issues,
        "message_ar": snapshot_message,
    }

    all_eligible = all_present and not blocked and counts["unavailable"] == 0 and snapshot_integrity["consistent"]
    bullish, bearish = counts["bullish"], counts["bearish"]
    status = "BLOCKED_OR_INCOMPLETE"
    title = "لا يمكن اعتماد توافق الأطر الخمسة"
    summary = "يلزم توفر الأطر الخمسة مع مؤشرات مكتملة وبيانات سوق مؤهلة ولقطة متسقة."
    if all_eligible:
        if bullish == 5 and all(row["category"] == "شراء قوي" for row in rows):
            status, title = "STRONG_BUY_ALL_FIVE", "شراء قوي متوافق على الأطر الخمسة"
            summary = "كل الأطر الخمسة مصنفة شراء قوي على اللقطة نفسها. هذه نتيجة تحليلية فقط وليست أمر تداول أو إثبات ربحية."
        elif bearish == 5 and all(row["category"] == "بيع قوي" for row in rows):
            status, title = "STRONG_SELL_ALL_FIVE", "بيع قوي متوافق على الأطر الخمسة"
            summary = "كل الأطر الخمسة مصنفة بيع قوي على اللقطة نفسها. هذه نتيجة تحليلية فقط وليست أمر تداول أو إثبات ربحية."
        elif bullish == 5:
            status, title = "BULLISH_ALIGNMENT_ALL_FIVE", "توافق صاعد على الأطر الخمسة"
            summary = "الأطر الخمسة صاعدة على اللقطة نفسها، لكن ليس جميعها مصنفًا شراء قوي."
        elif bearish == 5:
            status, title = "BEARISH_ALIGNMENT_ALL_FIVE", "توافق هابط على الأطر الخمسة"
            summary = "الأطر الخمسة هابطة على اللقطة نفسها، لكن ليس جميعها مصنفًا بيع قوي."
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
        "snapshot_integrity": snapshot_integrity,
        "trade_execution_enabled": False, "mode": "analysis_only",
    }


__all__ = ["TIMEFRAMES", "summarize_timeframe_consensus"]
