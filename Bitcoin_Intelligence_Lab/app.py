from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

from bitcoinlab.live_snapshot import build_live_snapshot

st.set_page_config(page_title="Bitcoin Intelligence Lab", page_icon="₿", layout="wide")

st.markdown("""
<style>
.stApp {background: linear-gradient(180deg,#f1f5f9,#ffffff 42%,#f8fafc);}
.block-container {max-width: 1600px; padding-top: 1.25rem;}
.hero {background: linear-gradient(120deg,#101f35,#1e4265); color:#f8fafc; padding:26px 30px; border-radius:20px; margin-bottom:18px;}
.hero h1 {color:white; margin:0;}
.hero p {color:#d9e5ef; margin:.5rem 0 0;}
div[data-testid="stMetric"] {background:white; border:1px solid #e2e8f0; border-radius:14px; padding:12px;}
</style>
<div class="hero"><h1>₿ Bitcoin Intelligence Lab</h1>
<p>من بيانات بيتكوين الحقيقية إلى قراءة متعددة المحركات وقرار مركزي قابل للتفسير. وضع القراءة فقط؛ لا تُرسل هذه اللوحة أوامر تداول.</p></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("إعدادات السوق")
    symbol = st.selectbox("رمز السوق الفوري", ["BTCUSDT", "BTCUSDC"], index=0)
    interval = st.selectbox("الفاصل", ["1m", "5m", "15m", "1h", "4h"], index=0)
    st.caption("المصدر الأساسي Binance Spot وUSDⓈ-M Futures. بيانات الشبكة وCOT والخيارات سياق إضافي.")
    refresh = st.button("قراءة السوق الحقيقية الآن", type="primary", use_container_width=True)
    st.caption("لا توجد أسعار افتراضية. عند فشل مصدر يظهر كغير متاح أو خطأ.")

if "btc_report" not in st.session_state:
    st.session_state["btc_report"] = None

if refresh:
    with st.spinner("جلب بيانات السوق العامة والتحقق من حداثتها..."):
        try:
            st.session_state["btc_report"] = build_live_snapshot(symbol=symbol, interval=interval)
        except Exception as exc:
            st.error(f"فشل بناء لقطة السوق: {type(exc).__name__}: {exc}")

report = st.session_state.get("btc_report")
if not report:
    st.info("اضغط «قراءة السوق الحقيقية الآن» لجلب أول لقطة. لا يعرض البرنامج بيانات سوق مخزنة أو مولّدة بدل البيانات الحية.")
    st.stop()

st.caption(f"الرمز: {report['symbol']} · آخر تحديث: {report['as_of_utc']} · حالة اللقطة: {report['status']}")
decision = report["decision"]
action = decision["action"]
if action == "BUY":
    st.success("القرار التحليلي: BUY — ليس أمر تداول")
elif action == "SELL":
    st.warning("القرار التحليلي: SELL — ليس أمر تداول")
else:
    st.info("القرار التحليلي: HOLD — لا توجد موافقة كافية")

cols = st.columns(4)
cols[0].metric("التقييم الاتجاهي", f"{decision['score']:+.3f}" if decision["score"] is not None else "غير متاح")
cols[1].metric("السبريد", f"{report['order_book']['spread_bps']:.2f} bps" if report["order_book"] else "غير متاح")
cols[2].metric("RSI(14)", f"{report['technical']['rsi14']:.1f}" if report["technical"].get("rsi14") is not None else "غير متاح")
cols[3].metric("ATR(14)", f"{report['technical']['atr14']:.2f}" if report["technical"].get("atr14") is not None else "غير متاح")

st.subheader("صحة مصادر البيانات")
source_rows = []
for name, state in report["source_states"].items():
    source_rows.append({
        "المصدر": name, "الحالة": state.get("status"),
        "العمر بالثواني": state.get("age_seconds"),
        "وقت الرصد UTC": state.get("observed_at_utc"),
    })
st.dataframe(source_rows, use_container_width=True, hide_index=True)
for name, error in report["errors"].items():
    st.error(f"{name}: {error}")

left, right = st.columns(2)
with left:
    st.subheader("محرك التحليل الفني")
    st.json(report["technical"])
    st.subheader("محرك المشتقات")
    st.json(report["derivatives"])
with right:
    st.subheader("محرك السيولة وتدفق الأوامر")
    st.json({"order_book": report["order_book"], "trade_flow": report["trade_flow"], "profile": report["orderflow"]})
    st.subheader("أسباب القرار والحواجز")
    st.write("الحواجز:", decision["blockers"] or "لا يوجد")
    st.write("الأدلة:", decision["reasons"])
    st.caption(decision.get("interpretation", "التقييم اتجاهي وليس احتمال ربح."))

with st.expander("حدود اللقطة ومصادرها"):
    for item in report["limitations"]:
        st.write("• " + item)
    st.caption("لا يوجد في هذه النسخة تنفيذ تلقائي أو تداول تجريبي اصطناعي. المخرجات قراءة وتحليل بيانات حقيقية من واجهات السوق.")
    st.download_button(
        "تصدير لقطة JSON",
        data=json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        file_name=f"bitcoin_market_snapshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
    )
