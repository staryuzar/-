"""Gold Intelligence Lab local dashboard — read-only market analysis."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd
import streamlit as st

from goldlab.cot_data import CFTC_COT_SOURCE_URL, COTDataError, fetch_cftc_gold_cot
from goldlab.audit_ledger import AuditLedgerError, LocalAuditLedger
from goldlab.economic_calendar import EconomicCalendarError, BLS_CALENDAR_URL, fetch_bls_calendar
from goldlab.live_mt5 import LiveMT5Error, analyze_live_mt5_multi
from goldlab.macro_context import MacroDataError, SOURCE_URL as TREASURY_SOURCE_URL, FRED_SOURCE_URL, SERIES as FRED_SERIES, fetch_gold_macro_context
from goldlab.feature_catalog import get_feature_catalog, summarize_feature_catalog, STATUS_LABELS_AR
from goldlab.market_time import DEFAULT_SERVER_TIMEZONE
from goldlab.multi_timeframe import summarize_timeframe_consensus

st.set_page_config(page_title="Gold Intelligence Lab", page_icon="📊", layout="wide")
st.title("مختبر ذكاء الذهب — Gold Intelligence Lab")
st.caption("البرنامج المركزي لتحليل الذهب: بيانات MT5، التحليل الفني وبنية السعر، الاقتصاد الكلي، COT، وسجل التدقيق. التنفيذ مفصول عن لوحة التحليل.")

with st.expander("خريطة قدرات المختبر والميزات المرجعية", expanded=False):
    catalog = get_feature_catalog()
    catalog_summary = summarize_feature_catalog()
    st.caption("سجل نطاق المنتج: يميّز بين ما هو منفذ وما هو جزئي أو مخطط أو معتمد على مصدر خارجي. إدراج ميزة لا يعني دمج خدمة خارجية.")
    feature_cols = st.columns(5)
    feature_cols[0].metric("إجمالي القدرات", catalog_summary["total"])
    feature_cols[1].metric("منفذ", catalog_summary["implemented"])
    feature_cols[2].metric("جزئي", catalog_summary["partial"])
    feature_cols[3].metric("مخطط", catalog_summary["planned"])
    feature_cols[4].metric("خارجي/بحث", catalog_summary["external_dependency"] + catalog_summary["research_required"])
    feature_status_options = ["الكل", *STATUS_LABELS_AR.values()]
    feature_status_filter = st.selectbox("تصفية حالة الميزة", feature_status_options, key="goldlab_feature_status_filter")
    visible_catalog = catalog if feature_status_filter == "الكل" else [item for item in catalog if item["status_ar"] == feature_status_filter]
    st.dataframe(pd.DataFrame([{
        "المعرف": item["id"], "المجال": item["category_ar"], "الميزة": item["name_ar"],
        "الحالة": item["status_ar"], "التفاصيل والحدود": item["detail_ar"],
        "المصادر المرجعية": " · ".join(item["sources"]),
    } for item in visible_catalog]), hide_index=True, width="stretch")

with st.sidebar:
    st.header("إعدادات قراءة السوق")
    symbol = st.text_input("رمز الذهب كما يظهر في MT5", value=os.environ.get("GOLDLAB_SYMBOL", "XAUUSD"))
    timeframe = st.selectbox("الإطار الزمني للتفاصيل", ["M1", "M5", "M15", "M30", "H1"])
    all_timeframes = st.checkbox(
        "تحليل الأطر الزمنية الخمسة معًا", value=True,
        help="يقرأ M1 وM5 وM15 وM30 وH1 من MT5. إذا فشل إطار، يُعرض خطؤه ولا يُستبدل ببيانات مخمّنة.",
    )
    bars_count = st.number_input("عدد الشموع المكتملة لكل إطار", min_value=260, max_value=5000, value=500, step=100)
    default_terminal_path = os.environ.get("GOLDLAB_MT5_PATH", "").strip()
    if not default_terminal_path and os.name == "nt":
        headway_candidate = r"C:\Program Files\Headway MT5 Terminal\terminal64.exe"
        if Path(headway_candidate).is_file():
            default_terminal_path = headway_candidate
    terminal_path = st.text_input(
        "مسار MT5", value=default_terminal_path,
        help="يُكتشف مسار Headway تلقائيًا إذا كان مثبتًا في المسار الافتراضي. يمكنك تغييره إلى مسار الطرفية التي سجلت الدخول فيها.",
    )
    timezone_options = {
        "Headway: UTC+2 شتاءً / UTC+3 صيفًا": "Europe/Athens",
        "UTC: الطوابع الزمنية مستندة إلى UTC أصلًا": "UTC",
    }
    timezone_labels = list(timezone_options)
    default_timezone = os.environ.get("GOLDLAB_MT5_SERVER_TIMEZONE", DEFAULT_SERVER_TIMEZONE)
    default_timezone_label = next(
        (label for label, value in timezone_options.items() if value == default_timezone),
        timezone_labels[0],
    )
    server_timezone_label = st.selectbox(
        "منطقة توقيت خادم MT5",
        timezone_labels,
        index=timezone_labels.index(default_timezone_label),
        help="التصحيح يخص تفسير وقت خادم الوسيط فقط؛ لا يغيّر ساعة Windows ولا أسعار OHLC.",
    )
    server_timezone = timezone_options[server_timezone_label]
    max_quote_age = st.number_input("أقصى عمر للسعر بالثواني", min_value=5, max_value=3600, value=120, step=15)
    refresh = st.button("قراءة السوق وتحليل الأطر الزمنية", type="primary", width="stretch")
    refresh_bls = st.button("تحديث تقويم إصدارات BLS", width="stretch")
    refresh_cot = st.button("تحديث مراكز الذهب COT", width="stretch")
    refresh_macro = st.button("تحديث العوامل الكلية من FRED", width="stretch")
    st.caption("كل مصدر يُحدّث يدويًا عند الضغط على زره. تعطل مصدر خارجي لا ينبغي أن يمنع قراءة MT5؛ لا توجد أوامر تداول من هذه اللوحة.")

if refresh:
    selected_timeframes = ["M1", "M5", "M15", "M30", "H1"] if all_timeframes else [timeframe]
    try:
        with st.spinner("جارٍ أخذ لقطة واحدة من MT5 وتحليل الأطر الزمنية المختارة..."):
            multi_result = analyze_live_mt5_multi(
                symbol=symbol, timeframes=tuple(selected_timeframes), bars_count=int(bars_count),
                terminal_path=terminal_path or None, max_quote_age_seconds=float(max_quote_age),
                server_timezone=server_timezone,
            )
        completed_reports = multi_result["reports"]
        timeframe_errors = multi_result["errors"]
        st.session_state["goldlab_snapshot_id"] = multi_result["snapshot_id"]
        st.session_state["goldlab_snapshot_captured_at_utc"] = multi_result["snapshot_captured_at_utc"]
        st.session_state["goldlab_latest_error"] = None
    except (LiveMT5Error, ValueError, RuntimeError) as exc:
        completed_reports = {}
        timeframe_errors = {tf: str(exc) for tf in selected_timeframes}
        st.session_state.pop("goldlab_snapshot_id", None)
        st.session_state.pop("goldlab_snapshot_captured_at_utc", None)
    st.session_state["goldlab_timeframe_reports"] = completed_reports
    st.session_state["goldlab_timeframe_errors"] = timeframe_errors
    if timeframe in completed_reports:
        st.session_state["goldlab_latest_report"] = completed_reports[timeframe]
        st.session_state["goldlab_latest_error"] = None
    else:
        st.session_state.pop("goldlab_latest_report", None)
        st.session_state["goldlab_latest_error"] = timeframe_errors.get(
            timeframe, "لم تُقرأ بيانات هذا الإطار ضمن الطلب الأخير."
        )

if refresh_bls:
    try:
        with st.spinner("جارٍ جلب تقويم الإصدارات الرسمي من BLS..."):
            st.session_state["goldlab_bls_calendar"] = fetch_bls_calendar(window_days=120, max_events=100)
            st.session_state["goldlab_bls_error"] = None
    except EconomicCalendarError as exc:
        st.session_state["goldlab_bls_error"] = str(exc)

if refresh_cot:
    try:
        with st.spinner("جارٍ جلب تقرير مراكز الذهب الأسبوعي من CFTC..."):
            st.session_state["goldlab_cot_report"] = fetch_cftc_gold_cot(rows_count=156)
            st.session_state["goldlab_cot_error"] = None
    except COTDataError as exc:
        st.session_state["goldlab_cot_error"] = str(exc)

if refresh_macro:
    try:
        with st.spinner("جارٍ جلب سلاسل العوائد والدولار والتقلب من FRED..."):
            st.session_state["goldlab_macro_context"] = fetch_gold_macro_context()
            st.session_state["goldlab_macro_error"] = None
    except MacroDataError as exc:
        st.session_state["goldlab_macro_error"] = str(exc)

st.subheader("تقويم الإصدارات الاقتصادية الرسمي")
st.caption("المصدر: مكتب إحصاءات العمل الأمريكي BLS. يُعرض موعد النشر فقط؛ لا يتضمن هذا الملف القيم الفعلية أو توقعات السوق.")
st.markdown(f"[مصدر التقويم الرسمي وشرح حدوده]({BLS_CALENDAR_URL})")
bls_error = st.session_state.get("goldlab_bls_error")
if bls_error:
    st.warning("تعذر تحديث تقويم BLS. ستظل قراءة السوق وتحليل المؤشرات متاحين بصورة مستقلة. " + bls_error)

bls = st.session_state.get("goldlab_bls_calendar")
if bls:
    fetched = datetime.fromisoformat(bls["fetched_at_utc"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    st.caption(f"آخر جلب ناجح: {fetched} · الأحداث خلال {bls['window_days']} يومًا: {bls['count']} · SHA-256: {bls['response_sha256'][:16]}…")
    if bls["events"]:
        visible = []
        for event in bls["events"]:
            if event["all_day"]:
                when = f"{event['date']} (حدث طوال اليوم)"
            else:
                local_dt = datetime.fromisoformat(event["starts_at_utc"]).astimezone()
                when = local_dt.strftime("%Y-%m-%d %H:%M %Z")
            visible.append({
                "الموعد المحلي على هذا الجهاز": when,
                "الإصدار": event["title"],
                "الموضوع": "، ".join(event["topic_tags_ar"]),
                "ملاحظة": event["relevance_note_ar"],
                "المصدر": event["url"] or BLS_CALENDAR_URL,
            })
        st.dataframe(pd.DataFrame(visible), hide_index=True, width="stretch")
    else:
        st.info("لا توجد إصدارات قادمة ضمن نافذة العرض الحالية وفق آخر ملف تقويم جرى جلبه.")
    st.caption(bls["note_ar"])
else:
    st.info("لم يُحمّل التقويم بعد. اضغط زر التحديث عند الحاجة؛ لن يتصل البرنامج بالشبكة تلقائيًا.")


st.divider()
st.subheader("مراكز متداولي عقود الذهب — CFTC COT")
st.caption("تقرير Disaggregated Futures Only لعقود الذهب الآجلة؛ بيانات أسبوعية وليست حركة سعر لحظية.")
st.markdown(f"[مصدر بيانات CFTC الرسمي]({CFTC_COT_SOURCE_URL})")
cot_error = st.session_state.get("goldlab_cot_error")
if cot_error:
    st.warning("تعذر تحديث تقرير COT. لن يؤثر ذلك في قراءة السوق أو باقي التحليل. " + cot_error)
cot = st.session_state.get("goldlab_cot_report")
if cot:
    fetched_cot = datetime.fromisoformat(cot["fetched_at_utc"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    st.caption(f"آخر تاريخ مراكز: {cot['latest_report_date']} · تاريخ الجلب: {fetched_cot} · الصفوف: {cot['rows_count']} · SHA-256: {cot['response_sha256'][:16]}…")
    latest_cot = cot["rows"][0]
    if cot["latest_report_age_days"] > 14:
        st.warning(f"آخر تقرير عمره {cot['latest_report_age_days']} يومًا منذ تاريخ الرصد؛ تحقق من موقع CFTC للتأكد من عدم تأخر النشر.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("شراء Managed Money", f"{latest_cot['managed_money_long']:,}" if latest_cot["managed_money_long"] is not None else "غير متاح")
    m2.metric("بيع Managed Money", f"{latest_cot['managed_money_short']:,}" if latest_cot["managed_money_short"] is not None else "غير متاح")
    m3.metric("الصافي (شراء − بيع)", f"{latest_cot['managed_money_net']:+,}" if latest_cot["managed_money_net"] is not None else "غير متاح")
    delta_net = latest_cot["net_change_vs_previous_report"]
    m4.metric("تغير الصافي", f"{delta_net:+,}" if delta_net is not None else "غير متاح")
    cot_history = [{"تاريخ التقرير": row["report_date"], "صافي مراكز Managed Money": row["managed_money_net"]} for row in reversed(cot["rows"])]
    if any(row["managed_money_net"] is not None for row in cot["rows"]):
        st.line_chart(pd.DataFrame(cot_history).set_index("تاريخ التقرير"), width="stretch")
    st.dataframe(pd.DataFrame([{
        "التاريخ": row["report_date"],
        "مراكز شراء": row["managed_money_long"],
        "مراكز بيع": row["managed_money_short"],
        "الصافي": row["managed_money_net"],
        "التغير الأسبوعي": row["net_change_vs_previous_report"],
        "الفائدة المفتوحة": row["open_interest"],
        "الصافي % الفائدة المفتوحة": round(row["managed_money_net_pct_open_interest"], 3) if row["managed_money_net_pct_open_interest"] is not None else None,
    } for row in cot["rows"][:20]]), hide_index=True, width="stretch")
    st.caption(cot["note_ar"])
else:
    st.info("لم يُحمّل تقرير COT بعد. اضغط زر التحديث عند الحاجة؛ لا يُستخدم مفتاح API ولا يعمل التحديث في الخلفية.")


st.divider()
st.subheader("سياق الاقتصاد الكلي المرتبط بدراسة الذهب")
st.caption("المصدر: FRED — سلاسل يومية للعوائد والدولار وVIX. ليست أسعارًا لحظية ولا إشارات دخول؛ لكل سلسلة تاريخ رصد مستقل.")
st.markdown(f"[العوائد الرسمية من وزارة الخزانة]({TREASURY_SOURCE_URL}) · [السلاسل المساندة من FRED]({FRED_SOURCE_URL})")
macro_error = st.session_state.get("goldlab_macro_error")
if macro_error:
    st.warning("تعذر جلب بيانات الاقتصاد الكلي. ستظل بقية أقسام المختبر مستقلة عن هذا المصدر. " + macro_error)
macro_context = st.session_state.get("goldlab_macro_context")
if macro_context:
    fetched_macro = datetime.fromisoformat(macro_context["fetched_at_utc"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    st.caption(f"آخر جلب ناجح: {fetched_macro} · الحالة: {macro_context['status']} · SHA-256: {macro_context['response_sha256'][:16]}…")
    if macro_context["status"] != "ok":
        st.warning("بعض السلاسل مفقودة أو قديمة حسب تاريخ الرصد؛ افحص حالة كل صف ولا تعامل البيانات كآنية.")
    for macro_warning in macro_context.get("warnings_ar", []):
        st.caption(macro_warning)
    macro_series = macro_context["series"]
    macro_cols = st.columns(4)
    for column, series_id in zip(macro_cols, FRED_SERIES):
        item = macro_series.get(series_id, {})
        value = item.get("latest_value")
        if value is None:
            shown = "غير متاح"
        elif item.get("unit_ar") == "%":
            shown = f"{value:.3f}%"
        elif series_id == "VIXCLS":
            shown = f"{value:.2f} نقطة"
        else:
            shown = f"{value:.3f}"
        change = item.get("change_5_display")
        change_text = f"{change:+.2f} {item.get('change_unit_ar', '')}" if change is not None else "تغير غير متاح"
        label = item.get("label_ar", series_id)
        if item.get("status") == "stale":
            label += " — قديمة"
        column.metric(label, shown, change_text)
        age = item.get("age_days")
        column.caption(f"آخر رصد: {item.get('latest_observation_date') or 'غير متاح'} · العمر: {age if age is not None else '—'} يوم")
    st.dataframe(pd.DataFrame([{
        "السلسلة": sid, "المؤشر": item.get("label_ar"), "القيمة": item.get("latest_value"),
        "تاريخ الرصد": item.get("latest_observation_date"), "عمر البيانات (أيام)": item.get("age_days"),
        "التغير مقابل الرصد الخامس السابق": item.get("change_5_display"),
        "وحدة التغير": item.get("change_unit_ar"), "حالة الحداثة": item.get("status"),
        "المرجع": item.get("source_url"),
    } for sid, item in macro_series.items()]), hide_index=True, width="stretch")
    st.caption(macro_context["note_ar"])
else:
    st.info("لم يُحمّل سياق الاقتصاد الكلي بعد. اضغط زر التحديث؛ لن يتصل البرنامج بهذا المصدر تلقائيًا في الخلفية.")

st.divider()
st.subheader("ملخص الأطر الزمنية — Gold Intelligence Lab")
timeframe_reports = st.session_state.get("goldlab_timeframe_reports", {})
timeframe_errors = st.session_state.get("goldlab_timeframe_errors", {})
if timeframe_reports or timeframe_errors:
    snapshot_id = st.session_state.get("goldlab_snapshot_id")
    snapshot_time = st.session_state.get("goldlab_snapshot_captured_at_utc")
    if snapshot_id and snapshot_time:
        st.caption(f"معرّف لقطة MT5 المشتركة: {snapshot_id} · وقت الالتقاط UTC: {snapshot_time}")
    st.caption("تُستخدم لقطة سعر واحدة وساعة مرجعية واحدة للأطر المقروءة؛ أي إطار يتعذر قراءته يظهر كخطأ مستقل.")
    if snapshot_id and timeframe_reports:
        sample_market = next(iter(timeframe_reports.values())).get("market", {})
        st.caption(
            f"منطقة الخادم: {server_timezone_label} · "
            f"فرق خادم/UTC المقاس من الطابع: {sample_market.get('server_utc_offset_seconds', 'غير متاح')} ثانية"
        )
    consensus = summarize_timeframe_consensus(timeframe_reports)
    snapshot_integrity = consensus["snapshot_integrity"]
    if snapshot_integrity["consistent"]:
        st.success("اتساق لقطة الأطر: سليم — " + str(snapshot_integrity["snapshot_id"]))
    elif consensus["missing_timeframes"]:
        st.warning("لم يكتمل فحص اتساق اللقطة: " + snapshot_integrity["message_ar"])
    else:
        st.error("حارس اتساق اللقطة: " + snapshot_integrity["message_ar"])
    if consensus["status"] in {"STRONG_BUY_ALL_FIVE", "STRONG_SELL_ALL_FIVE"}:
        st.success(consensus["title_ar"])
    elif consensus["status"] in {"BLOCKED_OR_INCOMPLETE", "MIXED_TIMEFRAMES"}:
        st.warning(consensus["title_ar"])
    else:
        st.info(consensus["title_ar"])
    st.write(consensus["summary_ar"])
    display_rows = []
    consensus_by_tf = {row["timeframe"]: row for row in consensus["rows"]}
    for tf in ("M1", "M5", "M15", "M30", "H1"):
        row = consensus_by_tf[tf]
        report_category = row["category"]
        if tf in timeframe_errors:
            state_text = "فشل القراءة"
            detail = timeframe_errors[tf]
            report_category = "غير متاح"
            eligible_text = "لا"
            readiness_text = "لا"
        elif tf in timeframe_reports:
            state_text = row["bias"]
            detail = row.get("reason_ar", "")
            eligible_text = "نعم" if row["eligible"] else "لا"
            readiness_text = "مكتملة" if row["ready"] else "ناقصة"
        else:
            state_text = "لم يُطلب"
            detail = "فعّل تحليل الأطر الخمسة لقراءة هذا الإطار."
            eligible_text = "لا"
            readiness_text = "غير متاح"
        score_value = row.get("rating")
        display_rows.append({
            "الإطار": tf,
            "التقييم العام": f"{float(score_value):.3f}" if score_value is not None else "غير متاح",
            "التصنيف": report_category,
            "الميل": state_text,
            "جاهزية المؤشرات": readiness_text,
            "البيانات مؤهلة للمراجعة": eligible_text,
            "ملاحظات": detail,
        })
    st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")
    if consensus["blocked_timeframes"]:
        st.caption("أطر محجوبة بسبب نقص المؤشرات أو حداثة/جودة بيانات السوق: " + "، ".join(consensus["blocked_timeframes"]))
    if consensus["missing_timeframes"]:
        st.caption("أطر لم تُقرأ: " + "، ".join(consensus["missing_timeframes"]))

st.divider()
st.subheader(f"التفاصيل التحليلية — {timeframe}")
error = st.session_state.get("goldlab_latest_error")
report = st.session_state.get("goldlab_latest_report")
if error:
    st.error(error)
if report is None:
    st.info("افتح MT5 وسجّل الدخول بنفسك، وتأكد من ظهور رمز الذهب في Market Watch، ثم اضغط «قراءة السوق وتحليل المؤشرات».")
else:
    market, analysis = report["market"], report["analysis"]
    ratings, readiness = analysis["ratings"], analysis["readiness"]
    if analysis["current_market_review"]["eligible"]:
        st.success(analysis["current_market_review"]["reason_ar"])
    else:
        st.warning(analysis["current_market_review"]["reason_ar"])

    st.subheader(f"السوق: {report['market_source']['symbol']} — {report['market_source']['timeframe']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bid", f"{market['bid']:.{market['price_digits']}f}")
    c2.metric("Ask", f"{market['ask']:.{market['price_digits']}f}")
    c3.metric("السبريد", f"{market['spread_points']:.1f} نقطة" if market["spread_points"] is not None else "غير متاح")
    c4.metric("عمر السعر", f"{market['quote_age_seconds']:.0f} ثانية")
    st.caption(
        f"وقت السعر UTC: {market['quote_time_utc']} · آخر شمعة مكتملة بدأت UTC: "
        f"{market['last_closed_bar_open_utc']} · الشموع المستلمة: "
        f"{report['market_source']['bars_received']}/{report['market_source']['bars_requested']}"
    )


    st.subheader("سجل التدقيق المحلي")
    st.caption("يحفظ لقطة التحليل عند طلبك فقط على هذا الجهاز في SQLite؛ لا يُرسل شيء إلى GitHub أو إلى خدمة خارجية.")
    audit_col1, audit_col2 = st.columns(2)
    with audit_col1:
        save_audit = st.button("حفظ لقطة التحليل محليًا", key="goldlab_save_audit")
    with audit_col2:
        load_audit = st.button("عرض آخر السجلات", key="goldlab_load_audit")
    if save_audit:
        try:
            saved_event = LocalAuditLedger(ROOT / "data" / "audit.sqlite3").append_analysis(report)
            st.session_state["goldlab_audit_saved"] = saved_event
            st.session_state["goldlab_audit_error"] = None
        except (AuditLedgerError, ValueError) as exc:
            st.session_state["goldlab_audit_error"] = str(exc)
    saved_event = st.session_state.get("goldlab_audit_saved")
    if saved_event:
        st.success(f"تم حفظ السجل {saved_event['event_id']} · SHA-256: {saved_event['payload_sha256'][:16]}…")
    audit_error = st.session_state.get("goldlab_audit_error")
    if audit_error:
        st.error("تعذر حفظ السجل المحلي: " + audit_error)
    if load_audit:
        try:
            st.session_state["goldlab_audit_rows"] = LocalAuditLedger(ROOT / "data" / "audit.sqlite3").list_recent(50)
            st.session_state["goldlab_audit_error"] = None
        except AuditLedgerError as exc:
            st.session_state["goldlab_audit_error"] = str(exc)
    audit_rows = st.session_state.get("goldlab_audit_rows", [])
    if audit_rows:
        st.dataframe(pd.DataFrame([{
            "المعرف": row["event_id"], "وقت الحفظ UTC": row["created_at_utc"],
            "الرمز": row["symbol"], "الإطار": row["timeframe"],
            "حالة المستشار": row["advisor_status"],
            "سلامة البصمة": "سليم" if row["payload_integrity_ok"] else "تحذير: فشل التحقق",
            "SHA-256": row["payload_sha256"][:16],
        } for row in audit_rows]), hide_index=True, width="stretch")
        st.download_button(
            "تصدير السجلات المعروضة بصيغة JSON",
            data=json.dumps(audit_rows, ensure_ascii=False, indent=2),
            file_name="goldlab-audit-events.json",
            mime="application/json",
        )

    st.subheader("ملخص المؤشرات")
    r1, r2, r3, r4 = st.columns(4)
    overall, ma_rating, osc_rating = ratings["overall"], ratings["moving_averages"], ratings["oscillators"]
    r1.metric("التقييم العام", f"{overall:.3f}" if overall is not None else "غير متاح", ratings["overall_category_ar"])
    r2.metric("المتوسطات — 15", f"{ma_rating:.3f}" if ma_rating is not None else "غير متاح", ratings["moving_averages_category_ar"])
    r3.metric("المذبذبات — 11", f"{osc_rating:.3f}" if osc_rating is not None else "غير متاح", ratings["oscillators_category_ar"])
    r4.metric("جاهزية المؤشرات", f"{readiness['total_ready']}/26", "مكتمل" if readiness["complete"] else "بيانات غير كافية")
    st.caption(f"قاعدة ADX: {analysis['adx_profile']} — {analysis['adx_rule_note_ar']}")

    st.subheader("ماسح بنية الرسم")
    scanner = report["scanner"]
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("الاتجاه الوصفي", scanner["trend"]["state_ar"])
    t2.metric("ATR(14)", f"{scanner['volatility']['atr14']:.3f}" if scanner["volatility"]["atr14"] is not None else "غير متاح")
    t3.metric("حالة التذبذب", scanner["volatility"]["state_ar"])
    t4.metric("المحاور المؤكدة", f"{len(scanner['confirmed_swings']['highs'])} قمم / {len(scanner['confirmed_swings']['lows'])} قيعان")

    s1, s2 = st.columns(2)
    with s1:
        st.markdown("**أقرب مناطق دعم تقريبية**")
        st.dataframe(pd.DataFrame(scanner["support_zones"]), hide_index=True, width="stretch")
    with s2:
        st.markdown("**أقرب مناطق مقاومة تقريبية**")
        st.dataframe(pd.DataFrame(scanner["resistance_zones"]), hide_index=True, width="stretch")

    st.markdown("**النماذج والاختراقات المرصودة على شموع مكتملة**")
    if scanner["setups"]:
        for setup in scanner["setups"]:
            st.write(f"**{setup['type']} — {setup['status']}**")
            st.write(setup["reason_ar"])
            st.caption(
                f"المستوى المرجعي: {setup['reference_level']:.3f} · "
                f"مستوى الإبطال الوصفي: {setup['invalidation_level']:.3f}"
            )
    else:
        st.info("لم يعثر الماسح على اختراق أو نموذج من الأنواع المعرّفة على آخر الشموع المكتملة.")
    for limitation in scanner["limitations_ar"]:
        st.caption(limitation)

    st.subheader("خلاصة المستشار التحليلي")
    advisor = report["advisor"]
    if advisor["status"] in {"BLOCKED_DATA_QUALITY", "CONFLICTING_EVIDENCE"}:
        st.warning(advisor["title_ar"])
    else:
        st.info(advisor["title_ar"])
    st.write(advisor["summary_ar"])
    if advisor["evidence_ar"]:
        st.markdown("**الأدلة المتاحة**")
        for item in advisor["evidence_ar"]:
            st.write("• " + item)
    if advisor["conflicts_ar"]:
        st.markdown("**التعارضات المكتشفة**")
        for item in advisor["conflicts_ar"]:
            st.write("• " + item)
    if advisor["missing_evidence_ar"]:
        st.markdown("**الأدلة الناقصة**")
        for item in advisor["missing_evidence_ar"]:
            st.write("• " + item)
    st.caption("المستشار لا يحسب احتمال ربح ولا يحدد سعر دخول/وقف/هدف تنفيذي، ولا يرسل أوامر.")

    st.subheader("حالة كل مؤشر")
    rows = []
    for item in analysis["components"]:
        raw_text = "؛ ".join(f"{key}={value:.6g}" for key, value in item["raw_values"].items() if value is not None)
        rows.append({
            "المؤشر": item["name_ar"], "المجموعة": item["group_ar"],
            "التصويت": item["vote_label_ar"], "الحالة": item["status_ar"],
            "القيم التشخيصية": raw_text or "لا توجد قيم كافية",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    with st.expander("حدود التقرير"):
        for limitation in analysis["limitations_ar"]:
            st.write("• " + limitation)
        st.write("هذا التحليل لا ينفذ صفقة ولا يثبت ربحية استراتيجية. تحقق من مصدر الرمز والتوقيت وحداثة البيانات.")

[executed on device: DESKTOP-BCGR98A (28de460a-0fbe-4532-90a8-ff34da68192c)]