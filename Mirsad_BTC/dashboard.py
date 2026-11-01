from __future__ import annotations
import sys
import time
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from mirsad.config import CHART_DIR,CHART_METADATA_PATH,SNAPSHOT_PATH,STATUS_PATH
from mirsad.storage import read_json,write_json_atomic

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

STATUS_AR={
 "RUNNING":"يعمل","LIVE":"متصل وبياناته حية","PARTIAL":"اتصال جزئي",
 "OFFLINE":"غير متصل","STALE":"بيانات قديمة","READY":"جاهز",
 "NOT_READY":"غير جاهز","WAITING_FOR_IMAGE":"بانتظار صورة الرسم",
 "DETECTED_UNCALIBRATED":"تم كشف الشموع — بانتظار معايرة المحور",
 "LOW_DETECTION":"اكتشاف ضعيف","CONNECTED":"جسر الخبير متصل",
 "WAITING_FOR_EXPERT":"بانتظار الخبير التنفيذي","NOT_CONFIGURED":"مسار MT5 غير محدد",
 "PUBLISH_DISABLED":"نشر أوامر الخبير معطل","PUBLISHED":"أُرسل أمر للجسر",
 "ALREADY_ACKNOWLEDGED":"الأمر له إقرار سابق","ALREADY_PUBLISHED":"الأمر منشور مسبقاً",
 "PENDING_COMMAND_BLOCKED":"أمر سابق ينتظر التسوية","REJECTED":"الأمر مرفوض","ERROR":"خطأ",
 "FULLY_OPERATIONAL":"المحركات الأربعة جاهزة","PARTIAL_OR_WAITING":"تشغيل جزئي — توجد وصلات تنتظر",
 "WAITING_FOR_ENGINE_2":"بانتظار معايرة الرسم","STALE":"بيانات قديمة — يلزم تحديث الصورة",
 "WAITING_FOR_ENGINE_3_QUOTE":"بانتظار سعر MT5 الحي","BLOCKED":"محجوب حتى تكتمل البيانات"}
def ar(value):
 return STATUS_AR.get(str(value),str(value or "غير متاح"))
def age_text(ts):
 if not ts: return "لا توجد إشارة حياة"
 return f"آخر نبض منذ {max(0,int(time.time()*1000)-int(ts))/1000:.1f} ثانية"

def render_engine_dashboard():
 state=read_json(STATUS_PATH,{})
 market=read_json(SNAPSHOT_PATH,{})
 st.title("₿ مرصاد البيتكوين")
 st.caption("نظام بأربعة محركات مترابطة — يعتمد بيانات السوق الفعلية ولا يستخدم الذكاء الاصطناعي أو الصفقات المحاكاة.")
 if state:
  st.metric("الحالة العامة",ar(state.get("overall_status","PARTIAL_OR_WAITING")))
  st.caption(age_text(state.get("heartbeat_at_ms")))
 else:
  st.warning("خدمة البرنامج لم تبدأ بعد. شغّل run_mirsad.py لتشغيل محركات البيانات والتحليل.")
 if state:
  labels=[
   ("1 — السوق والمعلومات","engine_1_market"),
   ("2 — تحليل الرسوم والصور","engine_2_chart"),
   ("3 — جسر MT5 والخبير","engine_3_mt5_bridge"),
   ("4 — القرار وإدارة المخاطر","engine_4_decision")]
  cols=st.columns(4)
  for col,(label,key) in zip(cols,labels):
   with col: col.metric(label,ar(state.get("engines",{}).get(key,"NOT_STARTED")))
  st.divider()

 if market:
  st.subheader("المحرك الأول — السوق والمعلومات")
  cols=st.columns(4)
  cols[0].metric("السعر المرجعي BTC/USDT",f"{market['price']:,.2f}" if market.get("price") else "غير متاح")
  cols[1].metric("مصادر حية",f"{market.get('venue_count',0)} / 3")
  cols[2].metric("المصدر الأساسي",market.get("primary_venue") or "غير متاح")
  cols[3].metric("حالة التجميع",ar(market.get("status")))
  rows=[]
  for name,row in market.get("venues",{}).items():
   rows.append({"المنصة":name,"الاتصال":ar(row.get("status")),
    "الأطر المجمعة":row.get("timeframe_count"),
    "زمن الاستجابة ms":row.get("latency_ms"),"الخطأ":row.get("error") or "—"})
  if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
  for name,row in market.get("venues",{}).items():
   if row.get("status")=="LIVE":
    with st.expander(f"تفاصيل تدفق الصفقات — {name}"):
     flow=row.get("orderflow") or {}
     f1,f2,f3,f4=st.columns(4)
     f1.metric("عدد الصفقات الملتقطة",flow.get("trade_count",0))
     f2.metric("شراء Taker (BTC)",f"{flow.get('taker_buy_quantity',0):.5f}")
     f3.metric("بيع Taker (BTC)",f"{flow.get('taker_sell_quantity',0):.5f}")
     f4.metric("نسبة شراء Taker",f"{flow.get('taker_buy_ratio',0)*100:.1f}%" if flow.get("taker_buy_ratio") is not None else "—")
     st.caption(flow.get("scope",""))
 else:
  st.info("لم تصل بيانات سوق حقيقية بعد.")

 if state:
  chart=state.get("chart",{})
  st.subheader("المحرك الثاني — تحليل الرسوم والصور")
  c1,c2,c3,c4=st.columns(4)
  c1.metric("حالة التحليل",ar(chart.get("status")))
  c2.metric("شموع مكتشفة",chart.get("detected_bar_count",0))
  c3.metric("شموع معايرة سعرياً",chart.get("calibrated_bar_count",0))
  c4.metric("الميل المرئي",chart.get("visual_bias","—"))
  if chart.get("input_age_seconds") is not None:
   st.caption(f"عمر صورة الشارت: {chart['input_age_seconds']} ثانية")
  if chart.get("pattern_candidates"):
   st.dataframe(pd.DataFrame(chart["pattern_candidates"]),use_container_width=True,hide_index=True)
  if chart.get("limitations"):
   st.caption("حدود التحليل: "+" | ".join(chart["limitations"]))

  bridge=state.get("bridge",{})
  st.subheader("المحرك الثالث — جسر البرنامج والخبير")
  b1,b2,b3=st.columns(3)
  b1.metric("حالة الجسر",ar(bridge.get("status")))
  b2.metric("عمر النبض (ثانية)",bridge.get("heartbeat_age_seconds","—"))
  b3.metric("المراكز المبلغ عنها",len(bridge.get("positions",[])))
  st.caption(bridge.get("message",""))
  st.caption("الجسر لا يصنف نوع الحساب ولا يحسب المخاطر. يمرر البيانات والأوامر وإقرارات التنفيذ بين البرنامج والخبير.")
  quote=bridge.get("quote",{})
  if quote:
   st.caption(f"سعر MT5 الحي: Bid {quote.get('bid','—')} / Ask {quote.get('ask','—')} | الرمز: {bridge.get('symbol','—')} | مربوط بسوق: {bridge.get('market_symbol','—')}")

  decision=state.get("decision",{})
  st.subheader("المحرك الرابع — مركز القرار وإدارة المخاطر")
  d1,d2,d3,d4=st.columns(4)
  action=decision.get("action","WAIT")
  d1.metric("القرار",{"BUY":"شراء","SELL":"بيع","CLOSE":"إغلاق مركز معاكس","HOLD":"الاحتفاظ بالمركز","WAIT":"انتظار"}.get(action,action))
  d2.metric("الإشارة من السوق والتحليل",{"BUY":"شراء","SELL":"بيع","WAIT":"انتظار"}.get(decision.get("candidate_action"),"انتظار"))
  d3.metric("درجة توافق الأطر",decision.get("trend_score","—"))
  d4.metric("جاهزية أمر الخبير","جاهز" if decision.get("command_ready") else "غير جاهز")
  scores=decision.get("decision_scores",{})
  weights=decision.get("decision_weights",{})
  s1,s2,s3=st.columns(3)
  s1.metric("المحلل — 80%",f"{scores.get('chart_score',0)*100:.1f} / 100",
   help=f"ثقة القراءة: {scores.get('chart_confidence',0)*100:.1f}%")
  s2.metric("السوق — 20%",f"{scores.get('market_score',0)*100:.1f} / 100")
  s3.metric("النتيجة المركبة",f"{scores.get('combined_score',0)*100:.1f} / 100")
  st.caption(f"توزيع القرار: المحلل {weights.get('engine_2_chart',0.8)*100:.0f}% + السوق {weights.get('engine_1_market',0.2)*100:.0f}%.")
  e1,e2,e3,e4=st.columns(4)
  e1.metric("دخول مرجعي",f"{decision.get('entry_reference'):,.2f}" if decision.get("entry_reference") else "—")
  e2.metric("وقف الخسارة",f"{decision.get('stop_loss'):,.2f}" if decision.get("stop_loss") else "—")
  e3.metric("الهدف",f"{decision.get('take_profit'):,.2f}" if decision.get("take_profit") else "—")
  e4.metric("بوابة الرسم",decision.get("chart_gate","—"))
  q1,q2,q3,q4=st.columns(4)
  divergence=decision.get("broker_market_price_divergence_pct")
  spread=decision.get("broker_spread_pct")
  quote=decision.get("broker_quote") or {}
  q1.metric("فرق سعر MT5 عن السوق",f"{divergence:.3f}%" if divergence is not None else "—")
  q2.metric("سبريد MT5",f"{spread:.3f}%" if spread is not None else "—")
  q3.metric("عمر سعر الوسيط",f"{quote.get('tick_age_seconds')} ثانية" if quote.get("tick_age_seconds") is not None else "—")
  q4.metric("رمز الوسيط",state.get("bridge",{}).get("symbol") or "—")
  if decision.get("timeframes"):
   tf_rows=[{"الإطار":tf,"الاتجاه":item.get("trend"),"حالة البيانات":item.get("status"),
    "عدد الشموع المغلقة":item.get("closed_candles")} for tf,item in decision["timeframes"].items()]
   st.dataframe(pd.DataFrame(tf_rows),use_container_width=True,hide_index=True)
  if decision.get("indicators"):
   st.write("المؤشرات المحسوبة من الشموع المغلقة")
   st.dataframe(pd.DataFrame([decision["indicators"]]),use_container_width=True,hide_index=True)
  risk=decision.get("risk_plan",{})
  st.write("حساب المخاطر وحجم المركز داخل البرنامج:",ar(risk.get("status","WAITING_FOR_ENGINE_3_BRIDGE")))
  if risk.get("volume") is not None:
   st.write(f"الحجم المحسوب: {risk['volume']} | المخاطرة النقدية: {risk.get('risk_cash')} | الخسارة التقديرية عند الوقف: {risk.get('estimated_loss')}")
  st.caption(risk.get("reason") or decision.get("reason",""))
  publication=state.get("command_publish",{})
  st.write("**حالة تمرير الأمر عبر الجسر:**",ar(publication.get("status","NOT_READY")))
  st.caption(publication.get("message","لا يوجد أمر جاهز للإرسال."))
  if decision.get("open_block_reason"): st.caption(decision["open_block_reason"])
  if decision.get("position_ticket"): st.caption(f"تذكرة المركز المطلوب إغلاقه: {decision['position_ticket']}")
  st.caption("لن يرسل أمر إلى MT5 إلا بعد جاهزية القرار ووصول نبض الجسر وسعر MT5 المتطابق والحديث. الإرسال مفعّل وفق تفويض المستخدم، ويمكن تعطيله من إعداد MIRSAD_ENABLE_ORDER_PUBLISH=0.")

 st.divider()
 st.subheader("تهيئة صورة الرسم للمحرك الثاني")
 st.caption("ارفع لقطة حقيقية من الشارت. أدخل أعلى وأدنى سعر ظاهرين على المحور؛ ويمكنك تحديد منطقة الشموع بالبكسل أو تركها افتراضياً على الصورة كلها.")
 saved_meta=read_json(CHART_METADATA_PATH,{})
 with st.form("chart_calibration_form",clear_on_submit=False):
  uploaded=st.file_uploader("صورة الرسم",type=["png","jpg","jpeg","webp"])
  symbol_default=(market.get("symbol") if market else "BTCUSDT")
  syms=st.text_input("رمز الشارت كما يظهر على الصورة",value=saved_meta.get("symbol",symbol_default))
  options=["1m","5m","15m","1h","4h","1d"]
  old_tf=saved_meta.get("timeframe","1m")
  timeframe=st.selectbox("الإطار الزمني الظاهر بالصورة",options,index=options.index(old_tf) if old_tf in options else 0)
  p1,p2=st.columns(2)
  with p1: top_price=st.number_input("أعلى سعر ظاهر على المحور",min_value=0.0,value=float(saved_meta.get("price_top",0.0)),format="%.2f")
  with p2: bottom_price=st.number_input("أدنى سعر ظاهر على المحور",min_value=0.0,value=float(saved_meta.get("price_bottom",0.0)),format="%.2f")
  st.caption("حدود منطقة الرسم بالبكسل (اختيارية). صفر يعني حافة الصورة.")
  q1,q2,q3,q4=st.columns(4)
  with q1: plot_left=st.number_input("يسار",min_value=0,value=int(saved_meta.get("plot_left_px",0)),step=1)
  with q2: plot_top=st.number_input("أعلى",min_value=0,value=int(saved_meta.get("plot_top_px",0)),step=1)
  with q3: plot_right=st.number_input("يمين",min_value=0,value=int(saved_meta.get("plot_right_px",0)),step=1)
  with q4: plot_bottom=st.number_input("أسفل",min_value=0,value=int(saved_meta.get("plot_bottom_px",0)),step=1)
  submitted=st.form_submit_button("حفظ الصورة وإعدادات المعايرة")
 if submitted:
  if uploaded is None: st.error("اختر صورة حقيقية أولاً.")
  elif len(uploaded.getvalue())>8*1024*1024: st.error("حجم الصورة أكبر من 8 ميغابايت.")
  elif not (top_price>bottom_price>0): st.error("أدخل أعلى وأدنى سعر صحيحين من محور الشارت.")
  elif syms.strip().upper()!=symbol_default:
   st.error(f"رمز الصورة ({syms}) يجب أن يطابق رمز محرك السوق ({symbol_default}) حتى لا نخلط بيانات أداة بأخرى.")
  else:
   CHART_DIR.mkdir(parents=True,exist_ok=True)
   target=CHART_DIR/("active_chart"+Path(uploaded.name).suffix.lower())
   target.write_bytes(uploaded.getvalue())
   metadata={"symbol":syms.strip().upper(),"timeframe":timeframe,
    "price_top":float(top_price),"price_bottom":float(bottom_price),
    "plot_left_px":int(plot_left),"plot_top_px":int(plot_top),
    "plot_right_px":int(plot_right),"plot_bottom_px":int(plot_bottom),
    "source_filename":uploaded.name,"saved_at_ms":int(time.time()*1000)}
   write_json_atomic(CHART_METADATA_PATH,metadata)
   st.success("تم حفظ الصورة ومعايرتها. ستدخل نتيجة التحليل في الدورة التالية لمحرك القرار.")

 with st.expander("قواعد وضوابط النظام"):
  st.write("المحرك 1 يقرأ السوق العام. المحرك 2 رؤية حاسوبية تقليدية. المحرك 3 ينقل بيانات وأوامر MT5. المحرك 4 وحده يقرر ويدير المخاطر.")
  st.write("لا ذكاء اصطناعي، ولا بيانات سوق وهمية، ولا صفقات محاكاة.")

 st.divider()
 st.subheader("تقرير الإنجاز والتدقيق التفصيلي")
 report_path=Path(__file__).resolve().parent/"reports"/"MIRSAD_PROGRESS_REPORT_AR_20261102.md"
 with st.expander("فتح تقرير مرصاد الكامل - 2 نوفمبر 2026",expanded=False):
  if report_path.is_file():
   report_text=report_path.read_text(encoding="utf-8")
   st.markdown(report_text)
   st.download_button(
    "تنزيل التقرير بصيغة Markdown",
    data=report_text,
    file_name="MIRSAD_PROGRESS_REPORT_AR_20261102.md",
    mime="text/markdown",
    key="mirsad_progress_report_download",
   )
  else:
   st.error("ملف تقرير الإنجاز غير موجود في مجلد reports.")

@st.fragment(run_every=10)
def live_fragment():
 render_engine_dashboard()
live_fragment()
