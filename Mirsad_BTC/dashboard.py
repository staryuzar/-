from __future__ import annotations
import sys
import time
import hashlib
import io
import html
from pathlib import Path
import pandas as pd
import streamlit as st
from PIL import Image, UnidentifiedImageError

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from mirsad.config import CHART_DIR,CHART_METADATA_PATH,SNAPSHOT_PATH,STATUS_PATH,ENABLE_ORDER_PUBLISH
from mirsad.storage import read_json,write_json_atomic
from mirsad.engines.visual_knowledge import visual_knowledge_summary
from mirsad.health import build_component_health,summarize_component_health

st.set_page_config(page_title="مرصاد البيتكوين",page_icon="₿",layout="wide")
st.markdown("""
<style>
:root {
 --mirsad-paper:#F3F1EA; --mirsad-surface:#FAF9F5; --mirsad-ink:#30363A;
 --mirsad-muted:#777F80; --mirsad-line:#E3E0D7; --mirsad-copper:#B66D43;
 --mirsad-copper-tint:#F0E4DA; --mirsad-green:#2D7254; --mirsad-amber:#9A6B24;
 --mirsad-red:#B94E49; --mirsad-safe:#858C8D;
}
.stApp {background:var(--mirsad-paper);color:var(--mirsad-ink)}
[data-testid="stSidebar"] {background:#EAE7DE;border-right:1px solid #D8D4CB}
.block-container {padding-top:1.45rem;padding-bottom:2.5rem;max-width:1660px}
h1,h2,h3,p,label,[data-testid="stMarkdownContainer"] {color:var(--mirsad-ink)}
h1 {font-weight:800;letter-spacing:-.035em}
h2,h3 {font-weight:750;letter-spacing:-.02em}
div[data-testid="stMetric"] {background:var(--mirsad-surface);border:1px solid var(--mirsad-line);padding:15px 16px;border-radius:16px;box-shadow:0 4px 14px rgba(48,54,58,.045)}
div[data-testid="stMetric"] label {color:var(--mirsad-muted)!important;font-size:.82rem}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {color:var(--mirsad-ink)!important;font-weight:750}
[data-testid="stDataFrame"] {border:1px solid var(--mirsad-line);border-radius:13px;overflow:hidden;background:var(--mirsad-surface)}
[data-testid="stVerticalBlockBorderWrapper"] {background:var(--mirsad-surface);border-color:var(--mirsad-line)!important;border-radius:15px}
button[data-baseweb="tab"] {font-weight:700;color:var(--mirsad-muted)}
button[data-baseweb="tab"][aria-selected="true"] {color:var(--mirsad-copper)}
[role="tablist"] {gap:5px;border-bottom:1px solid var(--mirsad-line)}
.stButton>button {border:1px solid var(--mirsad-line);border-radius:11px;background:var(--mirsad-surface);color:var(--mirsad-ink);font-weight:650;transition:transform .16s ease-out,border-color .16s ease-out}
.stButton>button:hover {border-color:var(--mirsad-copper);color:var(--mirsad-copper)}
.stButton>button:active {transform:scale(.98)}
div[data-testid="stAlert"] {border-radius:13px}
div[data-testid="stExpander"] {border:1px solid var(--mirsad-line);border-radius:13px;background:var(--mirsad-surface)}
input,textarea,[data-baseweb="select"] {border-radius:10px!important}
hr {border-color:var(--mirsad-line)}
.mirsad-kicker {font-size:10px;font-weight:800;letter-spacing:.17em;color:var(--mirsad-copper);text-transform:uppercase;margin-bottom:4px}
.mirsad-subtle {font-size:12px;color:var(--mirsad-muted);line-height:1.8}
.mirsad-status {display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:5px 10px;font-weight:700;font-size:11px}
.mirsad-dot {display:inline-block;width:7px;height:7px;border-radius:99px}
@media (max-width: 700px) {
 .block-container {padding-left:1rem;padding-right:1rem;padding-top:1rem}
 div[data-testid="stMetric"] {padding:11px;border-radius:13px}
}
</style>
""",unsafe_allow_html=True)

STATUS_AR={
 "RUNNING":"يعمل","LIVE":"متصل وبياناته حية","PARTIAL":"اتصال جزئي",
 "OFFLINE":"غير متصل","STALE":"بيانات قديمة","READY":"جاهز",
 "NOT_READY":"غير جاهز","WAITING_FOR_IMAGE":"بانتظار صورة الرسم",
 "DETECTED_UNCALIBRATED":"تم كشف الشموع — بانتظار معايرة المحور",
 "LOW_DETECTION":"اكتشاف ضعيف",
 "SKIPPED_UNCALIBRATED":"لم تُشغّل مرجعية الأنماط قبل معايرة الأسعار",
 "UNAVAILABLE":"مكتبة مرجعية غير متاحة",
 "INSUFFICIENT_DATA":"بيانات غير كافية","BLOCKED_QUALITY_GATE":"بوابات جودة الرسم لم تكتمل","IMAGE_METADATA_MISMATCH":"إعدادات المعايرة لا تطابق الصورة","CONNECTED":"جسر الخبير متصل",
 "WAITING_FOR_EXPERT":"بانتظار الخبير التنفيذي","NOT_CONFIGURED":"مسار MT5 غير محدد",
 "PUBLISH_DISABLED":"نشر أوامر الخبير معطل","PUBLISHED":"أُرسل أمر للجسر",
 "ALREADY_ACKNOWLEDGED":"الأمر له إقرار سابق","ALREADY_PUBLISHED":"الأمر منشور مسبقاً",
 "PENDING_COMMAND_BLOCKED":"أمر سابق ينتظر التسوية","REJECTED":"الأمر مرفوض","ERROR":"خطأ",
 "FULLY_OPERATIONAL":"المحركات الموصولة جاهزة","NOT_REPORTED":"لم ترد حالة تشغيل مستقلة بعد","PARTIAL_OR_WAITING":"تشغيل جزئي — توجد وصلات تنتظر",
 "WAITING_FOR_ENGINE_2":"بانتظار معايرة الرسم","STALE":"بيانات قديمة — يلزم تحديث الصورة",
 "WAITING_FOR_ENGINE_3_QUOTE":"بانتظار سعر MT5 الحي","BLOCKED":"محجوب حتى تكتمل البيانات"}
def ar(value):
 return STATUS_AR.get(str(value),str(value or "غير متاح"))
def age_text(ts):
 if not ts: return "لا توجد إشارة حياة"
 return f"آخر نبض منذ {max(0,int(time.time()*1000)-int(ts))/1000:.1f} ثانية"

def render_component_health(state:dict)->None:
 items=state.get("component_health") or build_component_health(state)
 summary=state.get("component_health_summary") or summarize_component_health(items)
 st.markdown('<div class="mirsad-kicker">COMMAND CENTER / ENGINE HEALTH</div>',unsafe_allow_html=True)
 st.subheader("مركز مراقبة المحركات والأدوات")
 st.caption("الحالة من آخر دورة تشغيل فعلية؛ غياب القياس يظهر كحالة انتظار، واختلاف هوية الصورة أو تقادم البيانات يظهر كتنبيه.")
 totals=st.columns(4)
 total_cards=[
  ("مكونات تعمل فعلياً","healthy",summary.get("healthy",0),"#E6F0E9","#2D7254","✓"),
  ("بانتظار بيانات أو اتصال","waiting",summary.get("waiting",0),"#F5EDDC","#9A6B24","◷"),
  ("تحتاج متابعة","attention",summary.get("attention",0),"#F7E8E5","#B94E49","!"),
  ("تعطيل آمن مقصود","safe_disabled",summary.get("safe_disabled",0),"#ECEDEA","#858C8D","⌑"),
 ]
 for col,(label,key,value,bg,fg,symbol) in zip(totals,total_cards):
  with col:
   st.markdown(
    f'<div style="background:#FAF9F5;border:1px solid #E3E0D7;border-radius:15px;padding:14px 16px;">'
    f'<div style="display:flex;align-items:center;justify-content:space-between;color:#777F80;font-size:12px;font-weight:650;">{label}'
    f'<span style="width:29px;height:29px;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;background:{bg};color:{fg};font-weight:800">{symbol}</span></div>'
    f'<div style="margin-top:10px;font-size:31px;font-weight:800;color:#30363A;line-height:1.2">{value}'
    f'<span style="font-size:11px;font-weight:500;color:#777F80;margin-right:7px">من {summary.get("total",len(items))}</span></div></div>',
    unsafe_allow_html=True,
   )
 groups=[
  "التشغيل",
  "المحرك الأول — استخبارات السوق",
  "المحرك الثاني — التحليل البصري والسعري",
  "المحرك الثالث — المؤشرات",
  "المحرك الرابع — القرار وإدارة الصفقات",
  "المحرك الخامس — جسر التواصل مع MT5",
 ]
 filter_cols=st.columns([1.25,1.25,2.5])
 with filter_cols[0]:
  health_options=["الكل","HEALTHY","WAITING","ATTENTION","SAFE_DISABLED"]
  health_filter=st.selectbox(
   "تصفية حسب الحالة",health_options,
   format_func=lambda value:{"الكل":"كل الحالات","HEALTHY":"يعمل","WAITING":"بانتظار البيانات","ATTENTION":"تنبيه / خلل","SAFE_DISABLED":"تعطيل آمن"}[value],
   key="mirsad_health_filter",
  )
 with filter_cols[1]:
  engine_options=["الكل"]+groups
  engine_filter=st.selectbox(
   "تصفية حسب المحرك",engine_options,
   format_func=lambda value:"كل المحركات" if value=="الكل" else value,
   key="mirsad_engine_filter",
  )
 with filter_cols[2]:
  search=st.text_input("ابحث في الأدوات والتشخيص","",placeholder="اسم الأداة أو الحالة أو سبب الانتظار…",key="mirsad_health_search")
 filtered=[]
 needle=search.strip().casefold()
 for item in items:
  if health_filter!="الكل" and item.get("health")!=health_filter:
   continue
  if engine_filter!="الكل" and item.get("engine")!=engine_filter:
   continue
  searchable=" ".join(str(item.get(key,"")) for key in ("component","status","status_label","detail","source","engine")).casefold()
  if needle and needle not in searchable:
   continue
  filtered.append(item)
 tabs=st.tabs(["التشغيل","1 · السوق","2 · التحليل","3 · المؤشرات","4 · القرار","5 · الجسر"])
 icons={"HEALTHY":"✓","WAITING":"◷","ATTENTION":"!","SAFE_DISABLED":"⌑"}
 colors={
  "HEALTHY":("#E6F0E9","#2D7254","#2D7254"),
  "WAITING":("#F5EDDC","#9A6B24","#9A6B24"),
  "ATTENTION":("#F7E8E5","#B94E49","#B94E49"),
  "SAFE_DISABLED":("#ECEDEA","#61696A","#858C8D"),
 }
 for tab,group in zip(tabs,groups):
  selected=[item for item in filtered if item.get("engine")==group]
  with tab:
   if not selected:
    st.info("لا توجد أدوات تطابق عوامل التصفية في هذا القسم.")
    continue
   healthy=sum(item.get("health")=="HEALTHY" for item in selected)
   waiting=sum(item.get("health")=="WAITING" for item in selected)
   attention=sum(item.get("health")=="ATTENTION" for item in selected)
   safe=sum(item.get("health")=="SAFE_DISABLED" for item in selected)
   st.caption(f"{len(selected)} مكونات معروضة · يعمل {healthy} · ينتظر {waiting} · يحتاج متابعة {attention} · تعطيل آمن {safe}")
   for start in range(0,len(selected),2):
    cols=st.columns(2)
    for col,item in zip(cols,selected[start:start+2]):
     with col:
      with st.container(border=True):
       level=item.get("health","WAITING")
       bg,fg,dot=colors.get(level,colors["WAITING"])
       component_name=html.escape(str(item.get("component","مكوّن غير مسمى")),quote=True)
       health_label=html.escape(str(item.get("health_label","بانتظار البيانات")),quote=True)
       st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">'
        f'<div style="font-size:14px;font-weight:750;color:#30363A">{component_name}</div>'
        f'<span style="display:inline-flex;align-items:center;gap:6px;border-radius:99px;padding:5px 10px;background:{bg};color:{fg};font-size:11px;font-weight:750;white-space:nowrap">'
        f'<span style="width:7px;height:7px;border-radius:50%;background:{dot};display:inline-block"></span>{health_label}</span></div>',
        unsafe_allow_html=True,
       )
       st.caption(f"حالة المصدر: {item.get('status_label',item.get('status','غير متاح'))}")
       st.write(item.get("detail","لا توجد تفاصيل إضافية."))
       st.caption(f"المحرك: {item.get('engine','—')} · المصدر: {item.get('source','غير محدد')}")


def render_engine_dashboard():
 state=read_json(STATUS_PATH,{})
 market=read_json(SNAPSHOT_PATH,{})
 st.title("₿ مرصاد البيتكوين")
 st.caption("مرصاد منظومة بخمسة محركات مترابطة: السوق، التحليل البصري، المؤشرات، القرار ومتابعة الصفقات، وربط التواصل مع خبير MT5. لا يستخدم الخبير لاتخاذ القرار؛ دوره تنفيذ التوجيهات المعتمدة وإعادة حالة التنفيذ.")
 if state:
  st.metric("الحالة العامة",ar(state.get("overall_status","PARTIAL_OR_WAITING")))
  st.caption(age_text(state.get("heartbeat_at_ms")))
 else:
  st.warning("خدمة البرنامج لم تبدأ بعد. شغّل run_mirsad.py لتشغيل محركات البيانات والتحليل.")
 if state:
  labels=[
   ("1 — السوق والمعلومات","engine_1_market"),
   ("2 — التحليل البصري","engine_2_chart"),
   ("3 — المؤشرات","engine_3_indicators"),
   ("4 — القرار ومتابعة الصفقات","engine_4_decision"),
   ("5 — ربط البرنامج بالخبير","engine_5_communication_bridge")]
  engine_states=state.get("engines",{})
  cols=st.columns(5)
  for col,(label,key) in zip(cols,labels):
   status=engine_states.get(key)
   if key=="engine_5_communication_bridge" and status is None:
    status=engine_states.get("engine_3_mt5_bridge",engine_states.get("engine_5_mt5_bridge","NOT_STARTED"))
   with col: col.metric(label,ar(status or "NOT_REPORTED"))
  st.divider()
  render_component_health(state)
  st.divider()

 if market:
  st.subheader("المحرك الأول — استخبارات السوق")
  cols=st.columns(4)
  cols[0].metric("السعر المرجعي BTC/USDT",f"{market['price']:,.2f}" if market.get("price") else "غير متاح")
  cols[1].metric("مصدر التشغيل",f"{market.get('venue_count',0)} / 1 — MT5")
  cols[2].metric("الطرفية",market.get("primary_venue") or "غير متاح")
  cols[3].metric("حالة السوق",ar(market.get("status")))
  rows=[]
  for name,row in market.get("venues",{}).items():
   pulse=row.get("microstructure") or {}
   rows.append({"المصدر":name,"الاتصال":ar(row.get("status")),"معدل التحديث/دقيقة":pulse.get("tick_rate_per_minute"),"توازن عروض الأسعار":pulse.get("quote_direction_balance"),"السبريد %":pulse.get("current_spread_pct"),"التقويم":ar((row.get("economic_calendar") or {}).get("status","NOT_AVAILABLE")),"الخطأ":row.get("error") or "—"})
  if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
  for name,row in market.get("venues",{}).items():
   if row.get("status")=="LIVE":
    with st.expander(f"تفاصيل نبض السوق والأحداث الاقتصادية — {name}"):
     pulse=row.get("microstructure") or {}
     p1,p2,p3,p4,p5=st.columns(5)
     p1.metric("تحديثات السعر",pulse.get("tick_count","—"))
     p2.metric("تحديثات صاعدة",pulse.get("upticks","—"))
     p3.metric("تحديثات هابطة",pulse.get("downticks","—"))
     p4.metric("اتزان التحديثات",pulse.get("quote_direction_balance","—"))
     p5.metric("تغير منتصف السعر %",pulse.get("midpoint_change_pct","—"))
     st.caption(pulse.get("scope","تحديثات عروض الأسعار وليست صفقات منفذة."))
     calendar=row.get("economic_calendar") or {}
     st.markdown("**تقويم MT5 الاقتصادي**")
     st.caption("المصدر: تقويم الوسيط عبر MT5؛ ليس موجز عناوين أخبار BTC.")
     events=calendar.get("events") or []
     if events:
      event_rows=[{"الحدث":event.get("name"),"العملة":event.get("currency"),"الأهمية":event.get("importance"),"وقت UTC":time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(event.get("event_time_utc_ms",0)/1000))} for event in events]
      st.dataframe(pd.DataFrame(event_rows),use_container_width=True,hide_index=True)
     else:
      st.info("تقويم الأحداث غير متاح من وسيط MT5 حالياً.")
 else:
  st.info("لم تصل بيانات سوق حقيقية بعد.")

 if state:
  chart=state.get("chart",{})
  st.subheader("المحرك الثاني — تحليل الرسوم والصور")
  c1,c2,c3,c4,c5=st.columns(5)
  c1.metric("حالة التحليل",ar(chart.get("status")))
  c2.metric("شموع مكتشفة",chart.get("detected_bar_count",0))
  c3.metric("شموع معايرة سعرياً",chart.get("calibrated_bar_count",0))
  c4.metric("شموع مؤكدة",chart.get("confirmed_bar_count",chart.get("calibrated_bar_count",0)))
  c5.metric("الميل المرئي",chart.get("visual_bias","—"))
  latest_state="مغلقة" if chart.get("last_candle_closed") else "قيد التكوين / غير مؤكدة"
  st.caption(f"حالة آخر شمعة: {latest_state} | الشمعة غير المؤكدة تبقى معروضة، لكنها لا تدخل في قياس الاتجاه والبنية المؤكدين.")
  a1,a2,a3=st.columns(3)
  a1.metric("درجة المحلل",f"{chart.get('analysis_score',0)*100:.1f} / 100")
  a2.metric("مؤشر جودة الأدلة",f"{chart.get('analysis_confidence',0)*100:.1f}%")
  a2.caption("مؤشر إرشادي وليس احتمالاً إحصائياً لصحة التوقع.")
  a3.metric("الزخم البصري",chart.get("momentum",{}).get("score","—"))
  structure=chart.get("market_structure",{})
  st.caption(
   f"بنية السوق في الصورة: {structure.get('direction','غير كافية')} | "
   f"دعم مرئي: {structure.get('support','—')} | مقاومة مرئية: {structure.get('resistance','—')}"
  )
  event_labels={
   "BOS_BULLISH":"كسر بنية صاعد","BOS_BEARISH":"كسر بنية هابط",
   "CHOCH_BULLISH":"تغير بنية إلى صاعد","CHOCH_BEARISH":"تغير بنية إلى هابط",
   "HIGH_LIQUIDITY_SWEEP":"كنس سيولة فوق قمة","LOW_LIQUIDITY_SWEEP":"كنس سيولة تحت قاع",
  }
  structural_rows=[
   {"الحدث":event_labels.get(item.get("event"),item.get("event")),"الاتجاه":item.get("side"),
    "المستوى":item.get("level"),"شمعة التأكيد":item.get("confirmation_index"),
    "شرط التأكيد":item.get("confirmation")}
   for item in structure.get("structure_events",[])
  ]
  if structural_rows:
   st.markdown("**أحداث بنية السعر المؤكدة**")
   st.dataframe(pd.DataFrame(structural_rows),use_container_width=True,hide_index=True)
  sweep_rows=[
   {"الحدث":event_labels.get(item.get("event"),item.get("event")),"الأثر":item.get("side"),
    "المستوى":item.get("level"),"شمعة التأكيد":item.get("confirmation_index")}
   for item in structure.get("liquidity_sweeps",[])
  ]
  if sweep_rows:
   st.markdown("**عمليات كنس السيولة من الذيل والإغلاق**")
   st.dataframe(pd.DataFrame(sweep_rows),use_container_width=True,hide_index=True)
  equal_rows=[
   {"المنطقة":"قمم متساوية","من":zone.get("lower"),"إلى":zone.get("upper"),
    "اللمسات":zone.get("touches"),"المسافة %":zone.get("distance_pct")}
   for zone in structure.get("equal_high_zones",[])
  ]+[
   {"المنطقة":"قيعان متساوية","من":zone.get("lower"),"إلى":zone.get("upper"),
    "اللمسات":zone.get("touches"),"المسافة %":zone.get("distance_pct")}
   for zone in structure.get("equal_low_zones",[])
  ]
  if equal_rows:
   st.markdown("**مناطق القمم والقيعان المتساوية**")
   st.dataframe(pd.DataFrame(equal_rows),use_container_width=True,hide_index=True)
  watch_rows=[]
  if structure.get("entry_zone"):
   zone=structure["entry_zone"]
   watch_rows.append({"المنطقة":"مراقبة دخول","النوع":zone.get("kind"),"من":zone.get("lower"),"إلى":zone.get("upper"),"الحالة":zone.get("status")})
  if structure.get("exit_zone"):
   zone=structure["exit_zone"]
   watch_rows.append({"المنطقة":"مراقبة خروج","النوع":zone.get("kind"),"من":zone.get("lower"),"إلى":zone.get("upper"),"الحالة":zone.get("status")})
  if watch_rows:
   st.markdown("**مناطق المراقبة التي حددها المحلل**")
   st.dataframe(pd.DataFrame(watch_rows),use_container_width=True,hide_index=True)
  components=chart.get("analysis_components",{})
  st.caption(
   f"مكونات قراءة المحلل - اتجاه: {components.get('trend','—')} | "
   f"بنية: {components.get('structure','—')} | زخم: {components.get('momentum','—')} | "
   f"أنماط: {components.get('patterns','—')}"
  )
  if chart.get("input_age_seconds") is not None:
   st.caption(f"عمر صورة الشارت: {chart['input_age_seconds']} ثانية")
  if chart.get("pattern_candidates"):
   st.markdown("**أنماط الرؤية الهندسية من الصورة**")
   st.dataframe(pd.DataFrame(chart["pattern_candidates"]),use_container_width=True,hide_index=True)
  header_ocr=chart.get("header_ocr") or {}
  if header_ocr.get("status") not in {None,"DISABLED"}:
   header_status_ar={
    "SUGGESTIONS_FOUND":"تم استخراج اقتراحات",
    "NO_METADATA":"لم تُقرأ بيانات تعريف واضحة",
    "OCR_UNAVAILABLE":"خدمة OCR غير متاحة",
    "INVALID_IMAGE":"صورة غير صالحة",
    "INVALID_HEADER_REGION":"منطقة عنوان غير صالحة",
   }.get(header_ocr.get("status"),header_ocr.get("status"))
   st.caption(
    f"حالة قراءة عنوان الصورة: {header_status_ar} | "
    f"ثقة OCR النصية المتوسطة: {header_ocr.get('mean_ocr_score','—')}"
   )
   st.caption(
    f"اقتراحات بيانات عنوان الصورة: الرمز {header_ocr.get('symbol_suggestion') or 'غير واضح'} | "
    f"الإطار {header_ocr.get('timeframe_suggestion') or 'غير واضح'} | "
    f"البورصة {header_ocr.get('exchange_suggestion') or 'غير واضحة'} | "
    f"مطابقة رمز السوق: {header_ocr.get('expected_symbol_match','—')}"
   )
   st.caption("هذه اقتراحات OCR للمراجعة فقط؛ لا تستبدل البيانات المدخلة، ولا تستخدم لمعايرة السعر أو أهلية القرار.")
  reference_patterns=chart.get("reference_patterns") or {}
  st.markdown("**مرجع الأنماط الحسابي المستقل — TA-Lib على OHLC المعاير**")
  st.caption(
   f"الحالة: {ar(reference_patterns.get('status','NOT_AVAILABLE'))} | "
   f"التعريفات: {reference_patterns.get('pattern_definition_count',0)} | "
   f"الأحداث: {reference_patterns.get('event_count',0)} | "
   f"مكتبة: {reference_patterns.get('version','—')}"
  )
  st.caption("هذه مطابقة حسابية ثانية للأنماط وليست تصويتاً إضافياً أو احتمال نجاح. اختلافها عن الرؤية الهندسية يظهر للمراجعة.")
  if reference_patterns.get("events"):
   ref_rows=[{
    "النمط":item.get("pattern"),
    "الاتجاه":item.get("side"),
    "الحالة":item.get("state"),
    "شمعة الحدث":item.get("bar_index"),
    "قيمة TA-Lib":item.get("talib_value"),
    "حد الإبطال":item.get("invalidation_level"),
    "سبب الإبطال":item.get("invalidation_reason"),
   } for item in reference_patterns["events"]]
   st.dataframe(pd.DataFrame(ref_rows),use_container_width=True,hide_index=True)
  elif reference_patterns.get("error"):
   st.caption(reference_patterns["error"])
  extraction=chart.get("extraction_diagnostics") or {}
  slot_extraction=extraction.get("slot_guided_extraction") or {}
  st.caption(
   f"مسار استخراج الشموع: {extraction.get('segmentation_mode','projection_groups')} | "
   f"الشموع المستخرجة: {chart.get('detected_bar_count',0)} | "
   f"المواضع التي أعطت دليلاً: {slot_extraction.get('occupied_slots',0)} من "
   f"{slot_extraction.get('slots_considered',0)}"
  )
  if slot_extraction:
   st.caption(
    f"استخدام التقسيم الموجّه: {'نعم' if slot_extraction.get('adopted') else 'لا'} | "
    f"نقاوة ألوانه المتوسطة: {slot_extraction.get('mean_colour_purity','—')} | "
    f"المواضع المرفوضة لضعف الدليل: {slot_extraction.get('rejected_component_quality',0) + slot_extraction.get('rejected_low_activity',0)}"
   )
  st.markdown("**قاعدة معرفة المحرك البصري — الشموع وبنية السوق**")
  knowledge_db=chart.get("visual_knowledge_database") or {}
  # Research runs may be launched outside the live collector process. Read the
  # SQLite summary on each dashboard refresh so their new records appear here.
  try:
   knowledge_db={**knowledge_db,**visual_knowledge_summary()}
  except Exception as exc:
   knowledge_db={**knowledge_db,"live_summary_status":"ERROR",
    "live_summary_error":f"{type(exc).__name__}: {exc}"}
  k1,k2,k3,k4=st.columns(4)
  k1.metric("تعريفات الشموع",knowledge_db.get("candle_pattern_definitions",0))
  k2.metric("تعريفات بنية السوق",knowledge_db.get("market_structure_definitions",0))
  k3.metric("رصدات الأنماط",knowledge_db.get("pattern_observations",0))
  k4.metric("تقييمات تجريبية متحققة",knowledge_db.get("validated_evaluation_records",0))
  st.caption(
   f"إصدار القاعدة: {knowledge_db.get('version','—')} | "
   f"الحالة التجريبية: {knowledge_db.get('empirical_status','UNVALIDATED')} | "
   "التعريفات الموثقة لا تعني أن فعاليتها على BTC قد ثبتت."
  )
  st.caption(
   f"سجلات تقييم الأنماط: {knowledge_db.get('pattern_evaluation_records',0)} | "
   "لا تتحول التعريفات إلى نتائج متحققة إلا بعلامات بشرية واختبار مستقل."
  )
  recent_evaluations=knowledge_db.get("recent_pattern_evaluations") or []
  if recent_evaluations:
   evaluation_rows=[{
    "النمط":item.get("pattern_id"),
    "الرمز":item.get("symbol"),
    "الإطار":item.get("timeframe"),
    "النظام السوقي":item.get("market_regime"),
    "العينات":item.get("sample_count"),
    "Precision":item.get("precision"),
    "Recall":item.get("recall"),
    "F1":item.get("f1"),
    "العائد بعد التكاليف %":item.get("fee_adjusted_expectancy_pct"),
    "أفق القياس (شموع)":item.get("primary_horizon_bars"),
    "الحالة":item.get("validation_status"),
   } for item in recent_evaluations]
   st.dataframe(pd.DataFrame(evaluation_rows),use_container_width=True,hide_index=True)
  else:
   st.caption("لم تُسجل بعد نتائج تقييم إحصائي لأنماط الشموع.")

  st.markdown("**دراسة نتائج التراكيب السعرية التاريخية — سجل المحرك الثاني**")
  s1,s2,s3=st.columns(3)
  s1.metric("سجلات تقييم التراكيب",knowledge_db.get("structure_evaluation_records",0))
  s2.metric("نوافذ Train / Validation / Test",knowledge_db.get("evaluation_split_windows",0))
  s3.metric("سجلات متحققة",knowledge_db.get("validated_structure_evaluations",0))
  st.caption(
   f"الحالة التجريبية للتراكيب: {knowledge_db.get('structure_empirical_status','UNVALIDATED')} | "
   "الدراسة وصفية، ولا تعد اختبار محفظة أو إشارة تداول."
  )
  recent_structure=knowledge_db.get("recent_structure_evaluations") or []
  if recent_structure:
   structure_rows=[{
    "التركيب":item.get("structure_id"),
    "الرمز":item.get("symbol"),
    "المنصة":item.get("venue"),
    "الإطار":item.get("timeframe"),
    "التقسيم":item.get("data_split"),
    "العينات":item.get("sample_count"),
    "أفق القياس":item.get("primary_horizon_bars"),
    "متوسط العائد %":item.get("mean_return_pct"),
    "متوسط العائد الصافي %":item.get("fee_adjusted_expectancy_pct"),
    "الحالة":item.get("validation_status"),
   } for item in recent_structure]
   st.dataframe(pd.DataFrame(structure_rows),use_container_width=True,hide_index=True)
  else:
   st.caption("لا توجد حتى الآن سجلات تقييم محفوظة للتراكيب السعرية؛ شغّل scripts/run_structure_study.py بعد اكتمال أرشيف الشموع.")

  split_windows=knowledge_db.get("recent_evaluation_split_windows") or []
  if split_windows:
   st.markdown("**سجل نوافذ تقسيم البيانات وبصماتها**")
   split_rows=[{
    "مجموعة البيانات":item.get("dataset_id"),
    "الرمز":item.get("symbol"),
    "المنصة":item.get("venue"),
    "الإطار":item.get("timeframe"),
    "التقسيم":item.get("data_split"),
    "بداية النافذة ms":item.get("split_start_ms"),
    "نهاية النافذة ms":item.get("split_end_ms"),
    "شموع الحظر":item.get("embargo_bars"),
   } for item in split_windows]
   st.dataframe(pd.DataFrame(split_rows),use_container_width=True,hide_index=True)

  candle_knowledge=chart.get("candle_knowledge") or {}
  st.caption(
   f"محلل OHLC المعرفي: {ar(candle_knowledge.get('status','NOT_AVAILABLE'))} | "
   f"مرشحات الأنماط: {candle_knowledge.get('count',0)}"
  )
  if candle_knowledge.get("detected"):
   pattern_rows=[{
    "النمط":item.get("pattern_id"),
    "الاتجاه الوصفي":item.get("direction"),
   "العائلة":item.get("family"),
   "بنية الحدود":item.get("geometry"),
    "اتجاه سابق":item.get("prior_trend"),
    "مطابقة السياق":item.get("context_match"),
    "حالة الشمعة":item.get("confirmation_state"),
    "من شمعة":item.get("start_index"),
    "إلى شمعة":item.get("end_index"),
   } for item in candle_knowledge["detected"]]
   st.dataframe(pd.DataFrame(pattern_rows),use_container_width=True,hide_index=True)
  advanced=chart.get("advanced_structure_knowledge") or {}
  st.caption(
   f"تحليل بنية السوق متعدد المقاييس: {ar(advanced.get('status','NOT_AVAILABLE'))} | "
   f"الاتجاه البنيوي: {advanced.get('structure_direction','—')} | "
   f"أحداث BOS/CHOCH: {len(advanced.get('bos_choch_events',[]))} | "
   f"سحب السيولة: {len(advanced.get('liquidity_sweeps',[]))} | "
   f"فجوات سعرية: {len(advanced.get('fair_value_gaps',[]))} | "
   f"أنماط سعرية متعددة القمم: {len(advanced.get('classical_patterns',[]))}"
  )
  classical_rows=[{
   "النمط":{
    "double_top":"قمة مزدوجة",
    "double_bottom":"قاع مزدوج",
    "head_and_shoulders":"الرأس والكتفين",
    "inverse_head_and_shoulders":"الرأس والكتفين المعكوس",
    "ascending_triangle":"مثلث صاعد",
    "descending_triangle":"مثلث هابط",
    "symmetrical_triangle":"مثلث متماثل",
    "rising_wedge":"وتد صاعد",
    "falling_wedge":"وتد هابط",
    "rising_channel":"قناة صاعدة",
    "falling_channel":"قناة هابطة",
    "horizontal_channel":"قناة أفقية",
    "bull_flag":"علم صاعد",
    "bear_flag":"علم هابط",
    "bull_pennant":"راية صاعدة",
    "bear_pennant":"راية هابطة",
   }.get(item.get("pattern_id"),item.get("pattern_id")),
   "الحالة":ar(item.get("status","—")),
   "الاتجاه الوصفي":item.get("direction"),
   "قمم/قيعان التكوين":", ".join(str(x) for x in item.get("pivot_indices",[])),
   "اكتمال تأكيد القمم":item.get("formation_confirmed_at"),
   "شمعة كسر خط العنق":item.get("confirmation_index"),
   "خط العنق":f"{item.get('neckline_left','—')} → {item.get('neckline_right','—')}",
   "مستوى الإبطال":item.get("invalidation_level"),
   "جهة الاختراق":item.get("breakout_direction"),
   "شمعة الاختراق":item.get("breakout_index"),
  } for item in advanced.get("classical_patterns",[])]
  if classical_rows:
   st.dataframe(pd.DataFrame(classical_rows),use_container_width=True,hide_index=True)
   st.caption("هذه الأنماط هندسية وصفية فقط؛ اتجاه المثلث أو الوتد لا يتنبأ بجهة الاختراق. لا تدخل النتائج في قرار التداول ولم تثبت فائدتها الإحصائية على BTC بعد.")
  else:
   st.caption("لم يتأكد تكوين قمة/قاع مزدوج أو رأس وكتفين في بيانات الشموع المؤكدة الحالية.")
  st.caption(
   f"كتل أوامر مرشحة مرتبطة بكسر مؤكد: {len(advanced.get('order_block_candidates',[]))} "
   "| هذه مناطق سعرية مرشحة وليست دليلاً على أوامر مؤسسات."
  )
  block_rows=[{
   "الاتجاه":item.get("direction"),
   "الحالة":item.get("status"),
   "شمعة المصدر":item.get("source_candle_index"),
   "شمعة الكسر":item.get("break_index"),
   "منطقة السعر":f"{item.get('zone_low','—')} – {item.get('zone_high','—')}",
  } for item in advanced.get("order_block_candidates",[]) if item.get("structure_id")]
  if block_rows:
   st.dataframe(pd.DataFrame(block_rows),use_container_width=True,hide_index=True)
  scale_rows=[{
   "المقياس داخل الإطار":"داخلي" if key=="internal" else "تأرجح" if key=="swing" else "خارجي",
   "الحالة":value.get("status"),
   "قمم محورية":len(value.get("swing_highs",[])),
   "قيعان محورية":len(value.get("swing_lows",[])),
   "التسلسل":value.get("direction"),
  } for key,value in (advanced.get("scales") or {}).items()]
  if scale_rows:
   st.dataframe(pd.DataFrame(scale_rows),use_container_width=True,hide_index=True)
  archive=chart.get("visual_observation_archive") or {}
  st.caption(
   f"أرشيف هذه الصورة: {archive.get('status','DISABLED')} | "
   f"رصدات شموع مسجلة: {archive.get('pattern_observations_written',0)} | "
   f"رصدات بنية مسجلة: {archive.get('structure_observations_written',0)}"
  )
  if advanced.get("limitations"):
   st.caption("حدود التحليل البنيوي: "+" | ".join(advanced["limitations"]))

  engine2_mtf=state.get("engine_2_multi_timeframe_structure") or chart.get("engine_2_multi_timeframe_structure") or {}
  st.markdown("**بنية السعر متعددة الأطر — من سجل شموع المحرك الثاني الأصلي في MT5**")
  mtf_alignment=engine2_mtf.get("alignment","INSUFFICIENT_TIMEFRAME_CONFLUENCE")
  mtf_alignment_ar={
   "BULLISH_TIMEFRAME_CONFLUENCE":"توافق بنيوي صاعد",
   "BEARISH_TIMEFRAME_CONFLUENCE":"توافق بنيوي هابط",
   "MIXED_TIMEFRAME_STRUCTURE":"تضارب بين الأطر الزمنية",
   "INSUFFICIENT_TIMEFRAME_CONFLUENCE":"بيانات غير كافية للتوافق",
  }.get(mtf_alignment,mtf_alignment)
  st.caption(
   f"الحالة: {ar(engine2_mtf.get('status','NOT_AVAILABLE'))} | "
   f"المصدر: {engine2_mtf.get('source','—')} | "
   f"الأطر المؤهلة: {', '.join(engine2_mtf.get('eligible_timeframes',[])) or '—'} | "
   f"النتيجة: {mtf_alignment_ar}"
  )
  mtf_rows=[]
  for tf,frame in (engine2_mtf.get("timeframe_reports") or {}).items():
   mtf_rows.append({
    "الإطار":tf,
    "الحالة":frame.get("status"),
    "الشموع المؤكدة":frame.get("confirmed_bars",0),
    "الاتجاه البنيوي":frame.get("structure_direction","—"),
    "انتظام الشموع":"متصل" if frame.get("data_continuity")=="CONTIGUOUS" else "فجوات",
    "عدد الفجوات":len(frame.get("candle_gaps",[])),
    "عمر آخر إغلاق (ث)":round(frame.get("staleness_ms",0)/1000,1),
   })
  if mtf_rows:
   st.dataframe(pd.DataFrame(mtf_rows),use_container_width=True,hide_index=True)
  mtf_errors=engine2_mtf.get("errors") or {}
  if mtf_errors:
   st.caption("أطر مستبعدة من التوافق: "+" | ".join(f"{tf}: {reason}" for tf,reason in mtf_errors.items()))
  st.caption("هذا توافق بنيوي وصفي من شموع MT5 الأصلية، وليس إشارة تداول مستقلة.")
 
  axis_ocr=chart.get("axis_ocr") or {}
  calibration_info=chart.get("calibration") or {}
  st.caption(f"معايرة محور السعر: {calibration_info.get('source','غير متاح')} | نوع المحور: {calibration_info.get('price_scale_type','—')}")
  if axis_ocr:
   fit_info=axis_ocr.get("fit") or {}
   st.caption(f"OCR المحور: {axis_ocr.get('status','—')} | تدريجات مقروءة: {len(axis_ocr.get('ticks',[]))} | ثقة الملاءمة: {fit_info.get('confidence','—')} | {axis_ocr.get('reason','') or fit_info.get('reason','')}")
   if axis_ocr.get("ticks"):
    st.dataframe(pd.DataFrame(axis_ocr["ticks"]),use_container_width=True,hide_index=True)
  if chart.get("quality_gates"):
   gate_rows=[{"بوابة الجودة":name,"النتيجة":"اجتازت" if passed else "لم تجتز"} for name,passed in chart["quality_gates"].items()]
   st.dataframe(pd.DataFrame(gate_rows),use_container_width=True,hide_index=True)
  if chart.get("confidence_components"):
   st.caption("تفصيل مؤشر جودة الأدلة: "+ " | ".join(f"{k}: {v}" for k,v in chart["confidence_components"].items()))
  if chart.get("limitations"):
   st.caption("حدود التحليل: "+" | ".join(chart["limitations"]))

  indicators=state.get("indicators",{})
  st.subheader("المحرك الثالث — المؤشرات")
  i1,i2,i3,i4,i5=st.columns(5)
  indicator_values=indicators.get("values",{})
  i1.metric("حالة المؤشرات",ar(indicators.get("status","NOT_REPORTED")))
  i2.metric("EMA 20 / 1m",f"{indicator_values.get('ema20_1m'):,.2f}" if indicator_values.get("ema20_1m") is not None else "—")
  i3.metric("EMA 50 / 1m",f"{indicator_values.get('ema50_1m'):,.2f}" if indicator_values.get("ema50_1m") is not None else "—")
  i4.metric("RSI 14 / 1m",f"{indicator_values.get('rsi14_1m'):.2f}" if indicator_values.get("rsi14_1m") is not None else "—")
  i5.metric("ATR 14 / 5m",f"{indicator_values.get('atr14_5m'):,.2f}" if indicator_values.get("atr14_5m") is not None else "—")
  if indicators.get("timeframes"):
   indicator_rows=[{
    "الإطار":tf,"الحالة":ar(item.get("status")),
    "الاتجاه":item.get("trend"),"EMA 20":item.get("ema20"),
    "EMA 50":item.get("ema50"),"الشموع المغلقة":item.get("closed_candles")
   } for tf,item in indicators["timeframes"].items()]
   st.dataframe(pd.DataFrame(indicator_rows),use_container_width=True,hide_index=True)
  st.caption(indicators.get("reason") or "المؤشرات تحسب من سجل الشموع المكتملة الذي يملكه المحرك الثاني؛ ولا تصدر أوامر أو تصويتاً مستقلاً.")
 
  candle_state=state.get("engine_2_candles",{})
  st.subheader("تغذية الشموع الأصلية — ملكية المحرك الثاني")
  st.metric("حالة سجل الشموع",ar(candle_state.get("status","NOT_REPORTED")))
  if candle_state.get("timeframes"):
   st.dataframe(pd.DataFrame([{"الإطار":tf,"عدد الشموع":count,"الشموع المغلقة":(candle_state.get("closed_candles") or {}).get(tf,"—")} for tf,count in candle_state["timeframes"].items()]),use_container_width=True,hide_index=True)
  if candle_state.get("reason"):
   st.caption(candle_state["reason"])

  observer=state.get("chart_observer",{})
  observer_pipeline=observer.get("pipeline_component","engine2_mt5_chart_image_pipeline")
  visual_result=chart
  st.subheader("استقبال صور MT5 داخل المحرك الثاني")
  st.caption(f"المكوّن المسؤول: {observer_pipeline} | مصدر الصور: مجلد خبير MT5 الحالي")
  o1,o2,o3,o4=st.columns(4)
  o1.metric("حالة حزمة الصورة",ar(observer.get("status","NOT_CONFIGURED")))
  o2.metric("عمر آخر لقطة (ثانية)",observer.get("age_seconds","—"))
  o3.metric("الرمز / الإطار",f"{observer.get('chart',{}).get('symbol','—')} / {observer.get('chart',{}).get('timeframe','—')}")
  o4.metric("شموع OHLC المرفقة",observer.get("bar_count","—"))
  st.caption(
   f"نتيجة تحليل الصورة داخل المحرك الثاني: {ar(visual_result.get('status','NOT_REPORTED'))} | "
   f"أهلية الصورة للقرار: {'نعم' if visual_result.get('decision_eligible') else 'لا'}"
  )
  if observer.get("capture_id"):
   st.caption(f"Capture ID: {observer.get('capture_id')} | SHA-256: {observer.get('image_sha256','—')}")
  if observer.get("status")=="READY_FOR_ENGINE_2_VALIDATION":
   st.caption("اجتازت الصورة فحص النقل وفك الترميز؛ وتُعرض أهلية التحليل بصورة مستقلة أعلاه بعد المعايرة ومطابقة مرساة OHLC.")
  elif observer.get("status") not in {"WAITING_FOR_CAPTURE","NOT_CONFIGURED"}:
   st.warning(observer.get("message") or observer.get("reason") or "أحدث حزمة صور لم تجتز التحقق؛ لم يُسمح بالرجوع إلى لقطة أقدم.")
  else:
   st.caption(observer.get("message") or observer.get("reason") or "بانتظار وصول أول صورة من خبير MT5.")
  image_path=observer.get("image_path")
  if image_path and Path(image_path).is_file():
   st.image(image_path,width=520,caption="الصورة الأخيرة المستلمة من مجلد خبير MT5")
  if observer.get("image_directory"):
   st.caption(f"مجلد الصور الذي يقرأه المحرك الثاني: {observer.get('image_directory')}")
 
  bridge=state.get("bridge",{})
  st.subheader("المحرك الخامس — جسر التواصل بين البرنامج والخبير")
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
  st.subheader("المحرك الرابع — اتخاذ القرار ومتابعة الصفقات وإدارة المخاطر")
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
  risk=decision.get("risk_plan",{})
  st.write("حساب المخاطر وحجم المركز داخل البرنامج:",ar(risk.get("status","WAITING_FOR_ENGINE_5_BRIDGE")))
  if risk.get("volume") is not None:
   st.write(f"الحجم المحسوب: {risk['volume']} | المخاطرة النقدية: {risk.get('risk_cash')} | الخسارة التقديرية عند الوقف: {risk.get('estimated_loss')}")
  st.caption(risk.get("reason") or decision.get("reason",""))
  publication=state.get("command_publish",{})
  st.write("**حالة تمرير الأمر عبر الجسر:**",ar(publication.get("status","NOT_READY")))
  st.caption(publication.get("message","لا يوجد أمر جاهز للإرسال."))
  if decision.get("open_block_reason"): st.caption(decision["open_block_reason"])
  if decision.get("position_ticket"): st.caption(f"تذكرة المركز المطلوب إغلاقه: {decision['position_ticket']}")
  if ENABLE_ORDER_PUBLISH:
   st.warning("نشر أوامر MIR1 مفعّل في إعداد البرنامج. هذا لا يثبت أن تنفيذ الخبير نفسه مسموح، ولا يغيّر إعداد InpAllowExecution داخل MT5.")
  else:
   st.info("نشر أوامر MIR1 معطّل افتراضياً في إعداد البرنامج (MIRSAD_ENABLE_ORDER_PUBLISH=0). لا يُرسل البرنامج أوامر إلى الخبير في هذه الحالة.")

 st.divider()
 st.subheader("تهيئة صورة الرسم للمحرك الثاني")
 st.caption("ارفع لقطة حقيقية من الشارت. أدخل أعلى وأدنى سعر ظاهرين على المحور؛ ويمكنك تحديد منطقة الشموع بالبكسل أو تركها افتراضياً على الصورة كلها.")
 saved_meta=read_json(CHART_METADATA_PATH,{})
 with st.form("chart_calibration_form",clear_on_submit=False):
  uploaded=st.file_uploader("صورة الرسم",type=["png","jpg","jpeg","webp"])
  symbol_default=(market.get("symbol") if market else "BTCUSDT")
  syms=st.text_input("رمز الشارت كما يظهر على الصورة",value=saved_meta.get("symbol",symbol_default))
  options=["1m","5m","15m","1h","4h","1d","1w"]
  old_tf=saved_meta.get("timeframe","1m")
  timeframe=st.selectbox("الإطار الزمني الظاهر بالصورة",options,index=options.index(old_tf) if old_tf in options else 0)
  palette_labels={
   "auto":"تلقائي: أخضر/تركوازي/أزرق مقابل أحمر/برتقالي",
   "green_red":"أخضر مقابل أحمر",
   "blue_orange":"أزرق مقابل برتقالي",
   "teal_magenta":"تركوازي مقابل أرجواني",
  }
  palette_keys=list(palette_labels)
  old_palette=saved_meta.get("palette_mode","auto")
  palette_mode=st.selectbox(
   "ألوان الشموع في هذا الشارت",
   palette_keys,
   index=palette_keys.index(old_palette) if old_palette in palette_keys else 0,
   format_func=lambda key:palette_labels[key],
  )
  scale_labels={"linear":"خطي","logarithmic":"لوغاريتمي"}
  scale_keys=list(scale_labels)
  old_scale=saved_meta.get("price_scale_type","linear")
  price_scale_type=st.selectbox(
   "نوع مقياس الأسعار على المحور",scale_keys,
   index=scale_keys.index(old_scale) if old_scale in scale_keys else 0,
   format_func=lambda key:scale_labels[key],
  )
  auto_axis_ocr=st.checkbox(
   "استخراج تدريجات محور السعر تلقائياً من الصورة (OCR)",
   value=bool(saved_meta.get("auto_axis_ocr",True)),
   help="يحتاج المحرك إلى أربع تدريجات رقمية متناسقة على الأقل. عند فشل القراءة لن يخمّن الأسعار.",
  )
  auto_header_ocr=st.checkbox(
   "اقتراح الرمز والإطار الزمني من شريط عنوان الصورة (OCR)",
   value=bool(saved_meta.get("auto_header_ocr",False)),
   help="قراءة مساعدة من أعلى الصورة فقط. لا تستبدل الرمز أو الفاصل المدخلين ولا تستخدم لمعايرة السعر أو قرار التداول.",
  )
  last_candle_closed=st.checkbox(
   "آخر شمعة في الصورة مغلقة ومكتملة",
   value=bool(saved_meta.get("last_candle_closed",False)),
   help="اتركه غير محدد إن لم تكن متأكداً؛ سيصنف المحرك الأنماط على آخر شمعة كأنها قيد التكوين حتى لا يؤكد شمعة مفتوحة.",
  )
  persist_knowledge_observations=st.checkbox(
   "أرشفة نتائج المحلل البصري لهذه الصورة في قاعدة المعرفة",
   value=bool(saved_meta.get("persist_knowledge_observations",True)),
   help="يحفظ رصدات الشموع والبنية مع بصمة للصورة. لا يحوّل المرشحات إلى نتائج إحصائية متحققة.",
  )
  expected_candle_count=st.number_input(
   "عدد الشموع الظاهرة تقريباً (0 = غير معروف)",
   min_value=0,max_value=500,value=int(saved_meta.get("expected_candle_count",0) or 0),step=1,
  )
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
  elif (top_price>0 or bottom_price>0) and not (top_price>bottom_price>0): st.error("أدخل أعلى وأدنى سعر صحيحين، أو اترك الاثنين صفراً لتفعيل OCR.")
  elif top_price==0 and bottom_price==0 and not auto_axis_ocr: st.error("أدخل نطاق المحور يدوياً أو فعّل استخراج تدريجات السعر تلقائياً.")
  elif syms.strip().upper()!=symbol_default:
   st.error(f"رمز الصورة ({syms}) يجب أن يطابق رمز محرك السوق ({symbol_default}) حتى لا نخلط بيانات أداة بأخرى.")
  else:
   payload=uploaded.getvalue()
   try:
    with Image.open(io.BytesIO(payload)) as preview:
     image_width,image_height=preview.size
     preview.verify()
    if image_width<64 or image_height<64 or image_width*image_height>40_000_000:
     raise ValueError("أبعاد الصورة خارج حدود التحليل الآمن.")
   except (UnidentifiedImageError,OSError,ValueError) as exc:
    st.error(f"الصورة غير صالحة للتحليل: {exc}")
    payload=None
   if payload is not None:
    CHART_DIR.mkdir(parents=True,exist_ok=True)
    target=CHART_DIR/("active_chart"+Path(uploaded.name).suffix.lower())
    target.write_bytes(payload)
    metadata={"schema_version":2,"symbol":syms.strip().upper(),"timeframe":timeframe,
     "price_top":float(top_price),"price_bottom":float(bottom_price),
     "price_scale_type":price_scale_type,"auto_axis_ocr":bool(auto_axis_ocr),"auto_header_ocr":bool(auto_header_ocr),"last_candle_closed":bool(last_candle_closed),
     "persist_knowledge_observations":bool(persist_knowledge_observations),"expected_candle_count":int(expected_candle_count),
     "plot_left_px":int(plot_left),"plot_top_px":int(plot_top),
     "plot_right_px":int(plot_right),"plot_bottom_px":int(plot_bottom),
     "source_filename":uploaded.name,"source_sha256":hashlib.sha256(payload).hexdigest(),
     "palette_mode":palette_mode,"saved_at_ms":int(time.time()*1000)}
    write_json_atomic(CHART_METADATA_PATH,metadata)
    st.success("تم حفظ الصورة والتحقق من سلامتها ومعايرة مقياسها. ستدخل نتيجة التحليل في الدورة التالية.")

 with st.expander("قواعد وضوابط النظام"):
  st.write("المحرك 1 يقرأ نبض السوق والسبريد وتقويم MT5 الاقتصادي ولا يقرأ أي شموع. المحرك 2 يملك المخططات والصور وسجل OHLC متعدد الأطر. المحرك 3 يحسب المؤشرات من شموع المحرك 2 فقط. المحرك 4 يتخذ القرار ويتابع الصفقات ويدير المخاطر. المحرك 5 يربط البرنامج بخبير MT5 للتنفيذ وإعادة بيانات الحالة.")
  st.write("لا يوجد نموذج توليدي أو نموذج ذكاء اصطناعي لاتخاذ قرار التداول. RapidOCR المحلي يقرأ تدريجات محور السعر عند تفعيله، ويمكنه اقتراح بيانات عنوان الصورة اختيارياً؛ لا يعتمد المحرك السعر أو القرار على هذه الاقتراحات. الاتجاه والأنماط تُحلّل بقواعد هندسية واضحة.")

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
 research_path=Path(__file__).resolve().parent/"reports"/"OPEN_SOURCE_VISUAL_ENGINE_RESEARCH_AR_20261102.md"
 with st.expander("نتائج البحث الخارجي عن أدوات ومشاريع جاهزة للمحرك البصري",expanded=False):
  if research_path.is_file():
   research_text=research_path.read_text(encoding="utf-8")
   st.markdown(research_text)
   st.download_button(
    "تنزيل تقرير البحث الخارجي",
    data=research_text,
    file_name="OPEN_SOURCE_VISUAL_ENGINE_RESEARCH_AR_20261102.md",
    mime="text/markdown",
    key="mirsad_visual_research_download",
   )
  else:
   st.warning("تقرير البحث الخارجي غير موجود في مجلد reports.")

@st.fragment(run_every=10)
def live_fragment():
 render_engine_dashboard()
live_fragment()
