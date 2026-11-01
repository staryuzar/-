from __future__ import annotations
import sys
import time
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from mirsad.config import CHART_DIR, SNAPSHOT_PATH, STATUS_PATH
from mirsad.storage import read_json

st.set_page_config(page_title="مرصاد البيتكوين",page_icon="₿",layout="wide")
st.markdown("""
<style>
.stApp {background:#0b1220;color:#e5edf8}
[data-testid="stSidebar"] {background:#101a2b}
div[data-testid="stMetric"] {background:#111d30;border:1px solid #263750;padding:14px;border-radius:12px}
[data-testid="stDataFrame"] {border:1px solid #263750;border-radius:10px}
h1,h2,h3,p,label {color:#e5edf8}
</style>
""",unsafe_allow_html=True)

STATUS_AR={"RUNNING":"يعمل","LIVE":"متصل وبياناته حية","PARTIAL":"اتصال جزئي",
"OFFLINE":"غير متصل","STALE":"بيانات قديمة","READY":"جاهز","NOT_READY":"غير جاهز",
"WAITING_FOR_IMAGE":"بانتظار صورة الرسم","LOW_DETECTION":"اكتشاف ضعيف",
"CONNECTED":"متصل بالخبير","WAITING_FOR_EXPERT":"بانتظار الخبير",
"NOT_CONFIGURED":"لم يحدد مسار MT5","PUBLISH_DISABLED":"إرسال الأوامر معطل",
"ERROR":"خطأ","FULLY_OPERATIONAL":"المحركات الأربعة متصلة",
"PARTIAL_OR_WAITING":"تشغيل جزئي — توجد وصلات تنتظر"}
def ar(value):
    return STATUS_AR.get(str(value),str(value or "غير متاح"))
def freshness(ts):
    if not ts:
        return "لا توجد إشارة حياة"
    return f"آخر نبض منذ {max(0,int(time.time()*1000)-int(ts))/1000:.1f} ثانية"

@st.fragment(run_every=10)
def render_live_dashboard():
    state=read_json(STATUS_PATH,{})
    st.title("₿ مرصاد البيتكوين")
    st.caption("أربعة محركات — بيانات عامة فعلية — دون ذكاء اصطناعي أو أسعار مصطنعة. تحديث الحالة كل 10 ثوانٍ.")
    a,b=st.columns([3,1])
    with a:
        if state:
            st.metric("الحالة العامة",ar(state.get("overall_status","PARTIAL_OR_WAITING")))
            st.caption(freshness(state.get("heartbeat_at_ms")))
        else:
            st.warning("لم يبدأ محرك التشغيل. شغّل run_mirsad.py في نافذة مستقلة.")
    with b:
        if st.button("تحديث فوري",use_container_width=True):
            st.rerun()

    if state:
        eng=state.get("engines",{})
        cards=[
            ("المحرك الأول — السوق",eng.get("market_data","NOT_STARTED")),
            ("المحرك الثاني — تحليل الرسوم",eng.get("chart_analysis","NOT_STARTED")),
            ("المحرك الثالث — القرار والمخاطر",eng.get("decision_risk","NOT_STARTED")),
            ("المحرك الرابع — ربط MT5",eng.get("mt5_bridge","NOT_STARTED"))]
        cols=st.columns(4)
        for col,(name,status) in zip(cols,cards):
            with col:
                st.metric(name,ar(status))
        st.divider()

    market=read_json(SNAPSHOT_PATH,{})
    if market:
        st.subheader("السوق المباشر")
        m1,m2,m3,m4=st.columns(4)
        m1.metric("BTC/USDT — السعر المرجعي",f"{market.get('price'):,.2f}" if market.get("price") else "غير متاح")
        m2.metric("مصادر متصلة",f"{market.get('venue_count',0)} / 3")
        m3.metric("المصدر الأساسي",market.get("primary_venue") or "غير متاح")
        m4.metric("حالة التجميع",ar(market.get("status")))
        rows=[{"المصدر":n,"الحالة":ar(v.get("status")),"زمن الاستجابة ms":v.get("latency_ms"),"التفاصيل":v.get("error") or "—"}
              for n,v in market.get("venues",{}).items()]
        if rows:
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    else:
        st.info("لم تصل لقطة سوق حقيقية بعد.")

    if state:
        st.subheader("المحرك الثاني — التحليل البصري")
        chart=state.get("chart",{})
        c1,c2,c3=st.columns(3)
        c1.metric("حالة الصورة",ar(chart.get("status")))
        c2.metric("الشموع المرئية المكتشفة",chart.get("detected_bar_count",0))
        c3.metric("الميل البصري",chart.get("recent_visual_bias","—"))
        if chart.get("pattern_candidates"):
            st.write("مرشحات الأنماط المرئية (ليست إشارات مؤكدة):")
            st.dataframe(pd.DataFrame(chart["pattern_candidates"]),use_container_width=True,hide_index=True)
        st.caption("هذا الإصدار يقيس أشكال الألوان والشموع بصرياً. معايرة محور السعر وقراءة القيم الرقمية للمؤشرات لم تكتمل بعد.")

        st.subheader("المحرك الثالث — القرار وإدارة المخاطر")
        decision=state.get("decision",{})
        d1,d2,d3,d4=st.columns(4)
        d1.metric("القرار",{"BUY":"شراء","SELL":"بيع","WAIT":"انتظار"}.get(decision.get("action"),"انتظار"))
        d2.metric("سعر الدخول المرجعي",f"{decision.get('entry_reference'):,.2f}" if decision.get("entry_reference") else "—")
        d3.metric("وقف الخسارة",f"{decision.get('stop_loss'):,.2f}" if decision.get("stop_loss") else "—")
        d4.metric("جني الأرباح",f"{decision.get('take_profit'):,.2f}" if decision.get("take_profit") else "—")
        if decision.get("indicators"):
            st.dataframe(pd.DataFrame([decision["indicators"]]),use_container_width=True,hide_index=True)
        risk=decision.get("risk_plan",{})
        st.write("**حساب حجم المركز:**",ar(risk.get("status","WAITING_FOR_LIVE_MT5_SPECS")))
        st.caption(risk.get("reason") or "لن يُحسب حجم العقد إلا بعد استلام حقوق الحساب ومواصفات الرمز الفعلية من MT5.")
        st.caption(decision.get("reason",""))

        st.subheader("المحرك الرابع — اتصال MT5")
        mt5=state.get("mt5",{})
        st.write("**الحالة:**",ar(mt5.get("status")))
        st.write(mt5.get("message","لا توجد قراءة اتصال."))
        if mt5.get("heartbeat_age_seconds") is not None:
            st.caption(f"عمر نبض الخبير: {mt5['heartbeat_age_seconds']} ثانية")
        st.caption("لا ينفذ هذا الإصدار أي أمر تداول. سيُبنى الخبير التنفيذي بعد اكتمال ربط المحركات والتحقق منها.")

    st.divider()
    st.subheader("إرسال لقطة رسم بياني للتحليل البصري")
    uploaded=st.file_uploader("ارفع صورة شاشة حقيقية من منصة الرسم",type=["png","jpg","jpeg","webp"],accept_multiple_files=False)
    if uploaded is not None:
        if len(uploaded.getvalue())>8*1024*1024:
            st.error("حجم الصورة يتجاوز 8 ميغابايت.")
        else:
            CHART_DIR.mkdir(parents=True,exist_ok=True)
            target=CHART_DIR/("uploaded_chart"+Path(uploaded.name).suffix.lower())
            target.write_bytes(uploaded.getvalue())
            st.success("حُفظت الصورة. سيحللها المحرك البصري في دورة التشغيل التالية.")

    if state and state.get("notices"):
        with st.expander("حدود التشغيل والشفافية"):
            for note in state["notices"]:
                st.write("• "+note)

render_live_dashboard()
