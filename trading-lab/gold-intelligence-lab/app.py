"""Gold Intelligence Lab local dashboard — read-only market analysis."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd
import streamlit as st

from goldlab.live_mt5 import LiveMT5Error, analyze_live_mt5

st.set_page_config(page_title="Gold Intelligence Lab", page_icon="📊", layout="wide")
st.title("مختبر ذكاء الذهب — Gold Intelligence Lab")
st.caption("لوحة قراءة وتحليل فقط. لا توجد أزرار لتنفيذ الصفقات، ولا تحتاج مفتاح API خارجيًا.")

with st.sidebar:
    st.header("إعدادات قراءة السوق")
    symbol = st.text_input("رمز الذهب كما يظهر في MT5", value=os.environ.get("GOLDLAB_SYMBOL", "XAUUSD"))
    timeframe = st.selectbox("الإطار الزمني", ["M1", "M5", "M15", "M30", "H1"])
    bars_count = st.number_input("عدد الشموع المكتملة", min_value=260, max_value=5000, value=500, step=100)
    terminal_path = st.text_input(
        "مسار MT5 (اختياري)", value=os.environ.get("GOLDLAB_MT5_PATH", ""),
        help="اتركه فارغًا لاستخدام الطرفية الافتراضية، أو أدخل مسار terminal64.exe للطرفية التي سجلت الدخول فيها.",
    )
    max_quote_age = st.number_input("أقصى عمر للسعر بالثواني", min_value=5, max_value=3600, value=120, step=15)
    refresh = st.button("قراءة السوق وتحليل المؤشرات", type="primary", use_container_width=True)
    st.caption("تُقرأ الأسعار عند الضغط فقط. لا يوجد تحديث آلي مستمر أو تنفيذ أوامر.")

if refresh:
    try:
        with st.spinner("جارٍ قراءة آخر سعر والشموع المكتملة من MT5..."):
            st.session_state["goldlab_latest_report"] = analyze_live_mt5(
                symbol=symbol, timeframe=timeframe, bars_count=int(bars_count),
                terminal_path=terminal_path or None, max_quote_age_seconds=float(max_quote_age),
            )
            st.session_state["goldlab_latest_error"] = None
    except (LiveMT5Error, ValueError, RuntimeError) as exc:
        st.session_state["goldlab_latest_error"] = str(exc)
        st.session_state.pop("goldlab_latest_report", None)

error = st.session_state.get("goldlab_latest_error")
report = st.session_state.get("goldlab_latest_report")
if error:
    st.error(error)
if report is None:
    st.info("افتح MT5 وسجّل الدخول بنفسك، وتأكد من ظهور رمز الذهب في Market Watch، ثم اضغط «قراءة السوق وتحليل المؤشرات».")
    st.stop()

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
    st.dataframe(pd.DataFrame(scanner["support_zones"]), hide_index=True, use_container_width=True)
with s2:
    st.markdown("**أقرب مناطق مقاومة تقريبية**")
    st.dataframe(pd.DataFrame(scanner["resistance_zones"]), hide_index=True, use_container_width=True)

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
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

with st.expander("حدود التقرير"):
    for limitation in analysis["limitations_ar"]:
        st.write("• " + limitation)
    st.write("هذا التحليل لا ينفذ صفقة ولا يثبت ربحية استراتيجية. تحقق من مصدر الرمز والتوقيت وحداثة البيانات.")
