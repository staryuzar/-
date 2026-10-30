from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

from bitcoinlab.live_snapshot import build_live_snapshot
from bitcoinlab.ea_bridge import current_ack, default_common_files, publish_decision_order, read_ea_status

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
<p>بيانات بيتكوين الحقيقية · محركات متعددة · قرار مركزي · تنفيذ Headway-Demo عبر MT5</p></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("إعدادات السوق")
    symbol = st.selectbox("رمز السوق الفوري", ["BTCUSDT", "BTCUSDC"], index=0)
    interval = st.selectbox("الفاصل", ["1m", "5m", "15m", "1h", "4h"], index=0)
    volume = st.number_input("حجم الصفقة باللوت", min_value=0.001, max_value=10.0, value=0.01, step=0.001, format="%.3f")
    st.caption("المصدر الأساسي Binance Spot وUSDⓈ-M Futures. بيانات الشبكة وCOT والخيارات سياق إضافي.")
    refresh = st.button("قراءة السوق الحقيقية الآن", type="primary", use_container_width=True)
    st.caption("تُعرض البيانات الحقيقية وحالة كل مصدر. اتصال EA يتم عبر MT5 Common Files.")

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

st.subheader("اتصال خبير MT5")
try:
    terminal = read_ea_status(default_common_files())
    ack = current_ack(default_common_files())
except Exception as exc:
    terminal = {"status": "unavailable", "reason": str(exc)}
    ack = {}
terminal_cols = st.columns(4)
terminal_cols[0].metric("حالة الخبير", terminal.get("status", "unavailable"))
terminal_cols[1].metric("رمز الوسيط", terminal.get("symbol", "غير متصل"))
terminal_cols[2].metric("Bid", f"{terminal['bid']:.2f}" if terminal.get("bid") else "—")
terminal_cols[3].metric("Ask", f"{terminal['ask']:.2f}" if terminal.get("ask") else "—")
if terminal.get("reason"):
    st.caption(terminal["reason"])
if ack:
    st.caption(f"آخر إقرار MT5: {ack.get('status')} · الأمر {ack.get('id')} · {ack.get('detail', '')}")
exec_col1, exec_col2 = st.columns([1, 2])
with exec_col1:
    send_order = st.button(
        "إرسال القرار إلى Headway-Demo",
        type="primary",
        disabled=decision.get("action") not in {"BUY", "SELL"} or terminal.get("status") != "fresh",
        use_container_width=True,
    )
with exec_col2:
    st.caption("ينشئ أمرًا حقيقيًا على حساب Headway-Demo المتصل فقط بعد جاهزية EA؛ يعتمد وقف الخسارة والهدف على ATR وسعر الوسيط.")
if send_order:
    try:
        result = publish_decision_order(report=report, volume=float(volume))
        st.session_state["btc_last_order_result"] = result
    except Exception as exc:
        st.session_state["btc_last_order_result"] = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
if st.session_state.get("btc_last_order_result"):
    st.json(st.session_state["btc_last_order_result"])
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
    st.caption("الإرسال متاح عبر Headway-Demo عند اتصال EA. فشل مصدر أو غياب إقرار الوسيط يظهر صراحة ولا يُعتبر تنفيذًا.")
    st.download_button(
        "تصدير لقطة JSON",
        data=json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        file_name=f"bitcoin_market_snapshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
    )
