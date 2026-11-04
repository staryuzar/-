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
from mirsad.config import (ROOT,DATA_DIR,DB_PATH,CHART_DIR,CHART_METADATA_PATH,SNAPSHOT_PATH,STATUS_PATH,RISK_STATE_PATH,SYMBOL,PROVIDERS,ENABLE_ORDER_PUBLISH,MT5_COMMON_FILES,COLLECT_INTERVAL_SECONDS,RISK_PER_TRADE,DAILY_LOSS_LIMIT_ENABLED,MAX_DAILY_LOSS_FRACTION,MARKET_MAX_AGE_SECONDS,MT5_HEARTBEAT_MAX_AGE_SECONDS,MT5_QUOTE_MAX_AGE_SECONDS,MT5_MARKET_DATA_MAX_AGE_SECONDS,MT5_MARKET_DIVERGENCE_MAX_PCT,MT5_MAX_SPREAD_PCT,CHART_MAX_AGE_SECONDS)
from mirsad.storage import read_json,write_json_atomic
from mirsad.engines.visual_knowledge import visual_knowledge_summary
from mirsad.engines.mt5_bridge import MT5BridgeEngine
from mirsad.engines.position_management import BREAK_EVEN_TRIGGER_ATR,TRAILING_ACTIVATION_ATR,TRAILING_DISTANCE_ATR,TRAILING_STEP_ATR
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
 "PUBLISH_DISABLED":"نشر أوامر الخبير معطل","EXECUTION_DISABLED":"تنفيذ خبير MT5 معطّل","EXECUTION_STATE_UNKNOWN":"لم تصل حالة مفتاح تنفيذ الخبير","TERMINAL_NOT_CONNECTED":"طرفية MT5 غير متصلة","PUBLISHED":"أُرسل أمر للجسر",
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



def action_ar(value):
 return {"BUY":"شراء","SELL":"بيع","CLOSE":"إغلاق","MODIFY":"تعديل وقف الحماية","WAIT":"انتظار","HOLD":"الاحتفاظ"}.get(str(value or "").upper(),str(value or "غير متاح"))

def _fmt_money(value):
 try:
  return f"{float(value):,.2f}"
 except (TypeError,ValueError,OverflowError):
  return "—"

def render_execution_console(state:dict)->None:
 bridge=state.get("bridge") if isinstance(state.get("bridge"),dict) else {}
 decision=state.get("decision") if isinstance(state.get("decision"),dict) else {}
 controls=state.get("execution_controls") if isinstance(state.get("execution_controls"),dict) else {}
 daily=state.get("daily_risk") if isinstance(state.get("daily_risk"),dict) else bridge.get("daily_risk",{})
 account=bridge.get("account") if isinstance(bridge.get("account"),dict) else {}
 specs=bridge.get("symbol_spec") if isinstance(bridge.get("symbol_spec"),dict) else {}
 command=bridge.get("current_command") if isinstance(bridge.get("current_command"),dict) else {}
 ack=bridge.get("last_order_ack") if isinstance(bridge.get("last_order_ack"),dict) else {}
 reconciliation=bridge.get("position_reconciliation") if isinstance(bridge.get("position_reconciliation"),dict) else {}
 positions=bridge.get("positions") if isinstance(bridge.get("positions"),list) else []
 events=bridge.get("event_log") if isinstance(bridge.get("event_log"),list) else []
 publish_enabled=bool(controls.get("order_publish_enabled",ENABLE_ORDER_PUBLISH))
 terminal_connected=bridge.get("terminal_connected") is True
 expert_execution=bridge.get("execution_enabled")
 bridge_connected=bridge.get("status")=="CONNECTED"
 command_ready=(
  decision.get("status")=="READY"
  and decision.get("command_ready") is True
  and str(decision.get("action","")).upper() in {"BUY","SELL","CLOSE","MODIFY"}
 )
 command_preview=None
 preview_error=None
 if command_ready:
  try:
   command_preview=MT5BridgeEngine._validate_decision(decision)
  except (TypeError,ValueError,OverflowError) as exc:
   preview_error=f"{type(exc).__name__}: {exc}"

 st.divider()
 st.markdown('<div class="mirsad-kicker">ENGINE 4 → ENGINE 5 / MIR1 OPERATIONS</div>',unsafe_allow_html=True)
 st.subheader("مركز أوامر التنفيذ والتحكم الكامل")
 st.caption("يعرض هذا القسم أوامر MIR1 ومفاتيح النشر والتنفيذ والطرفية والأمر الحالي وACK والمصالحة والمراكز وسجل الأحداث وإعدادات المخاطر. لا يرسل أي أمر خارج قرار المحرك الرابع.")

 gate_cols=st.columns(5)
 gate_values=[
  ("نشر الأوامر من البرنامج","مفعّل" if publish_enabled else "معطّل",publish_enabled),
  ("اتصال طرفية MT5","متصل" if terminal_connected else "غير مثبت",terminal_connected),
  ("مفتاح الخبير InpAllowExecution","مفعّل" if expert_execution is True else "معطّل" if expert_execution is False else "غير معروف",expert_execution is True),
  ("جاهزية المحرك الرابع","جاهز" if command_ready and command_preview else "لا يوجد أمر معتمد",bool(command_ready and command_preview)),
  ("مصالحة آخر أمر","مؤكدة" if reconciliation.get("status")=="CONFIRMED" else ar(reconciliation.get("status","NOT_REPORTED")),reconciliation.get("status")=="CONFIRMED"),
 ]
 for col,(label,value,ok) in zip(gate_cols,gate_values):
  with col:
   st.metric(label,value)
   st.caption("اجتاز" if ok else "لم يجتز / غير متاح")

 tabs=st.tabs(["أوامر MIR1 والتحكم","معاينة الأمر والإرسال","الحساب ومواصفات الرمز","المراكز المفتوحة","الإقرارات والمصالحة","سجل الأحداث","إعدادات النظام والحدود"])
 with tabs[0]:
  st.markdown("**جميع أنواع الأوامر المعرفة في بروتوكول MIR1**")
  command_rows=[
   {"الرمز":"BUY","الاسم":"فتح شراء","مصدر القرار":"المحرك الرابع فقط","البيانات الإلزامية":"الرمز والحجم والدخول ووقف الخسارة والهدف","سلوك الخبير":"طلب سوق مع فحص السعر والحجم والوقف والتنفيذ"},
   {"الرمز":"SELL","الاسم":"فتح بيع","مصدر القرار":"المحرك الرابع فقط","البيانات الإلزامية":"الرمز والحجم والدخول ووقف الخسارة والهدف","سلوك الخبير":"طلب سوق مع فحص السعر والحجم والوقف والتنفيذ"},
   {"الرمز":"CLOSE","الاسم":"إغلاق كامل أو جزئي","مصدر القرار":"المحرك الرابع لمركز معاكس","البيانات الإلزامية":"position_ticket والحجم المستهدف","سلوك الخبير":"يقيّد الإغلاق بمركز مرصاد ورقم Magic الخاص به"},
   {"الرمز":"MODIFY","الاسم":"تعديل وقف الحماية","مصدر القرار":"إدارة الوقف الوقائي في المحرك الرابع","البيانات الإلزامية":"position_ticket وSL الجديد وTP الحالي","سلوك الخبير":"لا يسمح بتخفيف الوقف أو تغيير الهدف"},
  ]
  st.dataframe(pd.DataFrame(command_rows),use_container_width=True,hide_index=True)
  st.markdown("**حالات دورة حياة الأمر وإقرار MT5**")
  st.write("RECEIVED: استلم الخبير الأمر · SUBMITTED: أرسل طلب الوسيط · PARTIAL: تنفيذ جزئي · FILLED: أقر الوسيط بالملء · REJECTED: رفض · CANCELLED: أُلغي · EXPIRED: انتهت صلاحيته · UNKNOWN: النتيجة غير محسومة.")
  st.info("لا يوجد أمر CANCEL مستقل أو أوامر Pending / Limit / Stop في MIR1 الحالي. لا توجد أزرار إلغاء شكلية؛ الأوامر المدعومة حالياً هي BUY وSELL وCLOSE وMODIFY فقط.")
  st.markdown("**تسلسل التشغيل**")
  st.write("قرار المحرك الرابع ← حساب المخاطرة والحجم ← التحقق من سعر ومواصفات الوسيط ← مفتاح نشر البرنامج ← مفتاح تنفيذ الخبير ← كتابة command.json ← ACK من الخبير ← نبضة MT5 أحدث ← مطابقة التغير الفعلي في المراكز قبل إعلان CONFIRMED.")
  st.caption("عند وجود مركز معاكس يطلب المحرك CLOSE أولاً وينتظر المزامنة قبل فتح الاتجاه الآخر. لا يسمح بتكرار مركز في الاتجاه نفسه.")

 with tabs[1]:
  active_action=str(decision.get("action","WAIT")).upper()
  st.markdown(f"**تعليمات المحرك الرابع الحالية: {action_ar(active_action)} ({active_action})**")
  st.caption(f"حالة القرار: {ar(decision.get('status','NOT_READY'))} | جاهزية الأمر: {'نعم' if command_ready else 'لا'} | حالة الجسر: {ar(bridge.get('status','NOT_CONFIGURED'))}")
  if preview_error:
   st.error("رفضت معاينة الأمر قبل النشر: "+preview_error)
  elif command_preview:
   st.markdown("**Envelope MIR1 الذي سيُرسل عند تحقق جميع البوابات**")
   st.json(command_preview,expanded=True)
  else:
   st.info("لا يوجد حالياً أمر BUY أو SELL أو CLOSE أو MODIFY معتمد من المحرك الرابع. لا تنشئ اللوحة إشارة يدوية بديلة ولا تتجاوز بوابات المحركات.")
  current_id=command.get("command_id")
  if current_id:
   st.caption(f"آخر ملف أمر موجود: {current_id} | حالته وفق آخر ACK: {ack.get('state','لا يوجد ACK')}")
   st.markdown("**الظرف الكامل الموجود حالياً لدى الجسر**")
   st.json(command,expanded=False)
  else:
   st.caption("لم ينشأ command.json بعد في مجلد Common Files أو لم يصل إلى البرنامج.")
  signal_identity=str(decision.get("signal_id") or "NO_ACTIVE_COMMAND")
  confirmation_token=hashlib.sha256(signal_identity.encode("utf-8")).hexdigest()[:16]
  confirmation_key="mirsad_confirm_engine4_command_"+confirmation_token
  publish_button_key="mirsad_publish_engine4_command_"+confirmation_token
  confirmation=st.checkbox(
   "أؤكد أنني راجعت أمر المحرك الرابع الحالي وأسمح بمحاولة تمريره إلى خبير MT5.",
   value=False,key=confirmation_key,
   help="يتجدد التأكيد تلقائياً عند تغير معرّف الأمر؛ ولا يتجاوز مفاتيح الإيقاف أو بوابات التنفيذ.",
  )
  gates_ok=bool(
   publish_enabled and bridge_connected and terminal_connected
   and expert_execution is True and command_ready and command_preview is not None
  )
  action_columns=st.columns(5)
  publish_clicked_action=None
  for col,target in zip(action_columns[:4],("BUY","SELL","CLOSE","MODIFY")):
   with col:
    clicked=st.button(
     "تمرير "+target,
     key=publish_button_key+"_"+target,
     use_container_width=True,
     disabled=not (gates_ok and confirmation and active_action==target),
     help=("لا يُفعّل إلا عندما يكون هذا النوع هو قرار المحرك الرابع الحالي واجتاز كل البوابات."),
    )
   if clicked:
    publish_clicked_action=target
  with action_columns[4]:
   st.button(
    "CANCEL · غير مدعوم",
    key=publish_button_key+"_CANCEL",
    use_container_width=True,
    disabled=True,
    help="بروتوكول MIR1 الحالي لا يعرّف أمر إلغاء.",
   )
  if publish_clicked_action:
   result=MT5BridgeEngine().publish_decision(decision,bridge)
   status=str(result.get("status","UNKNOWN"))
   if status=="PUBLISHED":
    st.success(f"تمت كتابة أمر {publish_clicked_action} إلى الخبير، والانتظار لإقرار MT5: {result.get('command_id','—')}")
   elif status in {"ALREADY_PUBLISHED","ALREADY_ACKNOWLEDGED"}:
    st.info(ar(status)+" — لم يُنشأ أمر مكرر.")
   else:
    st.warning(f"لم يُنشر الأمر: {ar(status)} | {result.get('message') or result.get('reason') or 'لا توجد تفاصيل إضافية.'}")
   st.json(result,expanded=True)
  if not publish_enabled:
   st.warning("زر الإرسال مقفل لأن MIRSAD_ENABLE_ORDER_PUBLISH=0 في إعداد البرنامج.")
  if not bridge_connected or not terminal_connected:
   st.warning("زر الإرسال مقفل حتى تصل نبضة MIR1 حديثة وتثبت اتصال MT5.")
  if expert_execution is not True:
   reason="InpAllowExecution=false داخل الخبير." if expert_execution is False else "لم يرسل الخبير execution_enabled في نبضة MIR1."
   st.warning("زر الإرسال مقفل: "+reason)
  if not command_ready:
   st.warning("زر الإرسال مقفل لأن المحرك الرابع لم ينتج أمراً مكتمل الشروط.")
  st.caption("لا توجد مدخلات لفرض سعر أو حجم أو اتجاه يدوي. قيم أمر التداول تأتي من المحرك الرابع ومواصفات الوسيط الحية.")

 with tabs[2]:
  account_cols=st.columns(4)
  account_cols[0].metric("Equity",_fmt_money(account.get("equity")))
  account_cols[1].metric("Balance",_fmt_money(account.get("balance")))
  account_cols[2].metric("Free margin",_fmt_money(account.get("free_margin")))
  account_cols[3].metric("عملة الحساب",account.get("currency") or "—")
  login=str(account.get("login") or "")
  login_label=("…" + login[-4:]) if login else "—"
  st.caption(f"الخادم: {account.get('server') or '—'} | الحساب: {login_label} | الرمز: {bridge.get('symbol') or '—'} | رمز السوق: {bridge.get('market_symbol') or '—'} | Magic: {bridge.get('magic_number') or '—'}")
  quote=bridge.get("quote") if isinstance(bridge.get("quote"),dict) else {}
  st.caption(f"Bid: {quote.get('bid','—')} | Ask: {quote.get('ask','—')} | عمر السعر: {quote.get('tick_age_seconds','—')} ثانية | وقت السعر ms: {quote.get('time_ms','—')}")
  spec_rows=[
   {"المواصفة":"Tick size","القيمة":specs.get("tick_size","—")},
   {"المواصفة":"Tick value (loss)","القيمة":specs.get("tick_value_loss","—")},
   {"المواصفة":"Point / Digits","القيمة":f"{specs.get('point','—')} / {specs.get('digits','—')}"},
   {"المواصفة":"Volume min / step / max","القيمة":f"{specs.get('volume_min','—')} / {specs.get('volume_step','—')} / {specs.get('volume_max','—')}"},
   {"المواصفة":"Contract size","القيمة":specs.get("contract_size","—")},
   {"المواصفة":"Stops / Freeze level","القيمة":f"{specs.get('stops_level_points','—')} / {specs.get('freeze_level_points','—')}"},
   {"المواصفة":"Filling / Execution mode","القيمة":f"{specs.get('filling_mode','—')} / {specs.get('execution_mode','—')}"},
   {"المواصفة":"Trade mode","القيمة":specs.get("trade_mode","—")},
  ]
  st.dataframe(pd.DataFrame(spec_rows),use_container_width=True,hide_index=True)
  st.caption("هذه الحقول يقرأها الجسر من status.json الصادر من الخبير. لا يستنتج المحرك الرصيد أو tick value أو حدود الحجم.")

 with tabs[3]:
  st.caption(f"عدد المراكز في آخر نبضة: {len(positions)}. Magic Number يحدد المراكز التي يملكها خبير مرصاد.")
  if positions:
   position_rows=[]
   for item in positions:
    position_rows.append({
     "التذكرة":item.get("ticket"),
     "الرمز":item.get("symbol"),
     "الاتجاه":"شراء" if item.get("type")==0 else "بيع" if item.get("type")==1 else item.get("type"),
     "Magic":item.get("magic"),
     "الحجم":item.get("volume"),
     "سعر الفتح":item.get("price_open"),
     "السعر الحالي":item.get("price_current"),
     "الربح":item.get("profit"),
     "Swap":item.get("swap"),
     "وقف الخسارة":item.get("stop_loss"),
     "الهدف":item.get("take_profit"),
    })
   st.dataframe(pd.DataFrame(position_rows),use_container_width=True,hide_index=True)
  else:
   st.info("لا توجد مراكز أبلغ عنها الخبير في آخر نبضة، أو أن نبضة الخبير لم تصل بعد.")
  plan=decision.get("management_plan") if isinstance(decision.get("management_plan"),dict) else {}
  pm=decision.get("position_management") if isinstance(decision.get("position_management"),dict) else {}
  if plan:
   st.markdown("**خطة إدارة الوقف الوقائي الحالية**")
   st.json(plan,expanded=True)
  else:
   st.caption(f"حالة إدارة المراكز: {ar(pm.get('action','NOT_REQUIRED'))} | لا توجد خطة تعديل وقف جديدة في هذه الدورة.")

 with tabs[4]:
  ack_cols=st.columns(4)
  ack_cols[0].metric("حالة ACK",ack.get("state") or "—")
  ack_cols[1].metric("Retcode",ack.get("retcode","—"))
  ack_cols[2].metric("Deal ticket",ack.get("deal_ticket","—"))
  ack_cols[3].metric("Filled volume",ack.get("filled_volume","—"))
  if ack:
   st.caption(f"Command ID: {ack.get('command_id','—')} | Order ticket: {ack.get('order_ticket','—')} | Fill price: {ack.get('filled_price','—')} | وقت الإقرار ms: {ack.get('ack_at_ms','—')}")
   st.write(ack.get("message") or "لا توجد رسالة من الخبير.")
  else:
   st.info("لا يوجد ملف ack.json مقروء حتى الآن.")
  st.markdown("**مصالحة الإقرار مع المراكز اللاحقة**")
  st.write(f"الحالة: {ar(reconciliation.get('status','NOT_REPORTED'))}")
  st.write(reconciliation.get("reason") or "لم تسجل مصالحة بعد.")
  if reconciliation:
   st.json(reconciliation,expanded=True)
  st.caption("FILLED من الوسيط لا يعد نجاحاً نهائياً حتى تصل نبضة MT5 أحدث ويظهر تغير الحجم أو وقف الحماية المطلوب في المركز المستهدف.")

 with tabs[5]:
  if events:
   event_rows=[{
    "الوقت ms":item.get("time_ms",item.get("timestamp_ms","—")),
    "النوع":item.get("event",item.get("type","—")),
    "Command ID":item.get("command_id","—"),
    "الحالة":item.get("state",item.get("status","—")),
    "التفاصيل":item.get("message",item.get("reason","—")),
   } for item in events]
   st.dataframe(pd.DataFrame(event_rows),use_container_width=True,hide_index=True)
  else:
   st.info("ملف events.jsonl غير موجود أو لا يحتوي أحداثاً قابلة للقراءة.")
  paths=bridge.get("common_files_files") if isinstance(bridge.get("common_files_files"),dict) else {}
  st.caption("مجلد الجسر: "+str(bridge.get("common_files_directory") or "غير مضبوط في بيئة التشغيل"))
  file_rows=[]
  for name,exists in paths.items():
   if not exists:
    status_label="لم يُنشأ"
   elif name=="positions.json":
    status_label="سليم" if bridge.get("positions_file_valid") else "موجود لكن محتواه غير صالح"
   else:
    status_label="موجود"
   file_rows.append({"الملف":name,"الحالة":status_label})
  st.dataframe(pd.DataFrame(file_rows),use_container_width=True,hide_index=True)
  st.caption("Common Files / MirsadBTC: status.json · command.json · ack.json · positions.json · events.jsonl")

 with tabs[6]:
  settings_rows=[
   {"الإعداد":"MIRSAD_SYMBOL","القيمة":SYMBOL,"المعنى":"الرمز المنطقي الذي يعمل عليه محرك السوق داخل البرنامج."},
   {"الإعداد":"MIRSAD_DATA_DIR","القيمة":str(DATA_DIR),"المعنى":"مجلد البيانات المحلية وقاعدة البيانات واللقطات والتقارير التشغيلية."},
   {"الإعداد":"SQLite database","القيمة":str(DB_PATH),"المعنى":"قاعدة بيانات السوق والتاريخ والأرشفة."},
   {"الإعداد":"system_status.json","القيمة":str(STATUS_PATH),"المعنى":"ملف الحالة الموحد الذي تقرأ منه لوحة القيادة."},
   {"الإعداد":"latest_market.json","القيمة":str(SNAPSHOT_PATH),"المعنى":"آخر لقطة سوق كتبها runtime."},
   {"الإعداد":"chart images directory","القيمة":str(CHART_DIR),"المعنى":"مجلد صور الرسوم المرفقة أو الملتقطة للمحرك الثاني."},
   {"الإعداد":"chart_metadata.json","القيمة":str(CHART_METADATA_PATH),"المعنى":"إعدادات الصورة ومعايرة محور السعر وبصمة ملف الصورة."},
   {"الإعداد":"daily_risk_state.json","القيمة":str(RISK_STATE_PATH),"المعنى":"خط أساس حد الخسارة اليومية وحالته المستمرة."},
   {"الإعداد":"MIRSAD_ENABLE_ORDER_PUBLISH","القيمة":"1" if publish_enabled else "0","المعنى":"يسمح للبرنامج بكتابة command.json عند اكتمال القرار."},
   {"الإعداد":"InpAllowExecution داخل الخبير","القيمة":"TRUE" if expert_execution is True else "FALSE" if expert_execution is False else "غير معروف","المعنى":"يسمح للخبير بإرسال طلب الوسيط بعد فحوصه الداخلية."},
   {"الإعداد":"MIRSAD_DAILY_LOSS_LIMIT_ENABLED","القيمة":"1" if DAILY_LOSS_LIMIT_ENABLED else "0","المعنى":"حاجز الخسارة اليومية؛ معطل للتطوير حالياً."},
   {"الإعداد":"MIRSAD_RISK_PER_TRADE","القيمة":RISK_PER_TRADE,"المعنى":"النسبة المستخدمة لحساب مخاطرة الصفقة الواحدة."},
   {"الإعداد":"MIRSAD_MAX_DAILY_LOSS_FRACTION","القيمة":MAX_DAILY_LOSS_FRACTION,"المعنى":"حد الخسارة اليومية المضبوط، لكنه غير مفعل ما دام المفتاح 0."},
   {"الإعداد":"MIRSAD_MT5_MARKET_DIVERGENCE_MAX_PCT","القيمة":MT5_MARKET_DIVERGENCE_MAX_PCT,"المعنى":"أقصى انحراف بين سعر الوسيط ومرجع السوق."},
   {"الإعداد":"MIRSAD_MT5_MAX_SPREAD_PCT","القيمة":MT5_MAX_SPREAD_PCT,"المعنى":"أقصى سبريد مسموح قبل حجب الدخول وإدارة الوقف."},
   {"الإعداد":"MIRSAD_MT5_QUOTE_MAX_AGE","القيمة":MT5_QUOTE_MAX_AGE_SECONDS,"المعنى":"أقصى عمر لسعر Bid/Ask."},
   {"الإعداد":"MIRSAD_MT5_HEARTBEAT_MAX_AGE","القيمة":MT5_HEARTBEAT_MAX_AGE_SECONDS,"المعنى":"أقصى عمر لنبضة الخبير."},
   {"الإعداد":"MIRSAD_MT5_MARKET_DATA_MAX_AGE","القيمة":MT5_MARKET_DATA_MAX_AGE_SECONDS,"المعنى":"أقصى عمر لبيانات المؤشرات والشموع المستخدمة لإدارة الوقف."},
   {"الإعداد":"MIRSAD_MARKET_MAX_AGE","القيمة":MARKET_MAX_AGE_SECONDS,"المعنى":"أقصى عمر للبيانات السوقية."},
   {"الإعداد":"MIRSAD_CHART_MAX_AGE","القيمة":CHART_MAX_AGE_SECONDS,"المعنى":"أقصى عمر لصورة الشارت."},
   {"الإعداد":"MIRSAD_COLLECT_SECONDS","القيمة":COLLECT_INTERVAL_SECONDS,"المعنى":"الفاصل بين دورات runtime بالثانية."},
   {"الإعداد":"MIRSAD_MT5_COMMON_FILES","القيمة":MT5_COMMON_FILES or "غير مضبوط","المعنى":"المجلد الأب الذي يضم Common Files/MirsadBTC بين البرنامج والخبير."},
   {"الإعداد":"InpMagicNumber","القيمة":bridge.get("magic_number","—"),"المعنى":"معرّف المراكز والأوامر التي يملكها خبير مرصاد."},
   {"الإعداد":"مصادر البحث والمقارنة","القيمة":"، ".join(PROVIDERS.keys()),"المعنى":"مصادر بحث/تقييم مهيأة في الكود؛ مصدر القرار والتشغيل الحي يبقى MT5 وفق عقود المحركات."},
  ]
  st.dataframe(pd.DataFrame(settings_rows),use_container_width=True,hide_index=True)
  daily_cols=st.columns(4)
  daily_cols[0].metric("حالة حد الخسارة اليومية",ar(daily.get("status","NOT_REPORTED")))
  daily_cols[1].metric("مفعّل","نعم" if daily.get("enabled") else "لا")
  daily_cols[2].metric("قفل فتح المراكز","نعم" if daily.get("locked") else "لا")
  daily_cols[3].metric("الخسارة اليومية %",f"{float(daily.get('daily_loss_fraction'))*100:.3f}" if daily.get("daily_loss_fraction") is not None else "—")
  st.caption(daily.get("reason") or "حد الخسارة اليومية معطل خلال التطوير؛ بقية ضوابط المخاطر لا تزال قائمة.")
  st.markdown("**إدارة الوقف الوقائي ATR — خطة المحرك الرابع**")
  trail_rows=[
   {"المعلمة":"نقل الوقف إلى سعر الدخول بعد حركة مواتية","القيمة":f"{BREAK_EVEN_TRIGGER_ATR} ATR"},
   {"المعلمة":"بدء التتبع بعد حركة مواتية","القيمة":f"{TRAILING_ACTIVATION_ATR} ATR"},
   {"المعلمة":"مسافة الوقف المتتبع","القيمة":f"{TRAILING_DISTANCE_ATR} ATR"},
   {"المعلمة":"أقل خطوة بين تحديثين","القيمة":f"{TRAILING_STEP_ATR} ATR"},
  ]
  st.dataframe(pd.DataFrame(trail_rows),use_container_width=True,hide_index=True)
  st.caption("إدارة الوقف لا توسع المخاطرة ولا تعدل الهدف؛ تقترح تحديثاً واحداً فقط في الدورة وتبقى خاضعة لتطابق Tick وStops/Freeze لدى الوسيط.")

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

 intel=state.get("market_intelligence",{}) if isinstance(state.get("market_intelligence"),dict) else {}
 if intel:
  st.subheader("استخبارات السوق المستقلة — المحرك الأول")
  score=intel.get("directional_score")
  score_label=(f"{float(score):+.3f}" if isinstance(score,(int,float)) else "غير كافٍ")
  scenario=intel.get("scenario",{}) if isinstance(intel.get("scenario"),dict) else {}
  i1,i2,i3,i4,i5=st.columns(5)
  i1.metric("حالة الاستخبارات",ar(intel.get("status")))
  i2.metric("السيناريو السياقي",scenario.get("label",intel.get("direction","UNKNOWN")))
  i3.metric("درجة السياق",score_label)
  i4.metric("تغطية الأدلة",f"{float(intel.get('evidence_coverage',0) or 0)*100:.0f}%")
  i5.metric("الثقة التفسيرية",f"{float(intel.get('confidence',0) or 0)*100:.0f}%")
  risk_assessment=intel.get("market_risk_assessment",{}) if isinstance(intel.get("market_risk_assessment"),dict) else {}
  r1,r2,r3=st.columns(3)
  risk_label={"HIGH":"مرتفع","ELEVATED":"متوسط / يحتاج حذراً","NORMAL":"اعتيادي وفق البيانات المتاحة","UNKNOWN":"غير كافٍ للتقييم"}.get(risk_assessment.get("level"),"غير متاح")
  r1.metric("تقييم مخاطر السياق",risk_label)
  r2.metric("عوامل المخاطر",len(risk_assessment.get("drivers",[])))
  r3.metric("عناوين مخاطرة حديثة",risk_assessment.get("recent_risk_headline_count",0))
  if risk_assessment.get("drivers"):
   st.caption("عوامل التقييم: "+" · ".join(risk_assessment.get("drivers",[])))
  st.caption("درجة السياق والثقة تقيس تغطية الأدلة المتاحة، ولا تمثل احتمال ربح أو توقعاً إحصائياً معايراً. تقييم المخاطر وصفي ولا ينشئ حاجز دخول مستقل؛ الحاجز التنفيذي الصريح هو تقويم الأحداث عالي الأهمية في المحرك الرابع.")
  source_statuses=intel.get("source_statuses",{}) if isinstance(intel.get("source_statuses"),dict) else {}
  source_rows=[{"المصدر":name,"الحالة":ar(status)} for name,status in source_statuses.items()]
  if source_rows:
   st.markdown("**صحة مصادر استخبارات السوق**")
   st.dataframe(pd.DataFrame(source_rows),use_container_width=True,hide_index=True)
  news_data=intel.get("news",{}) if isinstance(intel.get("news"),dict) else {}
  feed_statuses=news_data.get("sources",{}) if isinstance(news_data.get("sources"),dict) else {}
  if feed_statuses:
   st.markdown("**حالة كل موجز إخباري**")
   feed_rows=[{"الموجز":name,"الحالة":ar(status)} for name,status in feed_statuses.items()]
   st.dataframe(pd.DataFrame(feed_rows),use_container_width=True,hide_index=True)
  components=intel.get("components",{}) if isinstance(intel.get("components"),dict) else {}
  comp_rows=[{"المكوّن":name,"الحالة":ar(value.get("status")),"الدرجة":value.get("score"),"الوزن":value.get("weight"),"الثقة":value.get("confidence"),"يساهم في السياق":("نعم" if value.get("contributes") else "لا")} for name,value in components.items() if isinstance(value,dict)]
  if comp_rows: st.dataframe(pd.DataFrame(comp_rows),use_container_width=True,hide_index=True)
  derivatives=intel.get("derivatives",{}) if isinstance(intel.get("derivatives"),dict) else {}
  derivative_rows=[]
  venue_scores=derivatives.get("venue_scores",{}) if isinstance(derivatives.get("venue_scores"),dict) else {}
  for name,row in (derivatives.get("venues",{}) or {}).items():
   if isinstance(row,dict):
    diagnostic=venue_scores.get(name,{}) if isinstance(venue_scores.get(name),dict) else {}
    funding_stamp=row.get("funding_timestamp_ms")
    ratio_stamp=row.get("long_short_timestamp_ms")
    now_ms=int(time.time()*1000)
    funding_age=round((now_ms-float(funding_stamp))/1000.0,1) if isinstance(funding_stamp,(int,float)) else None
    ratio_age=round((now_ms-float(ratio_stamp))/1000.0,1) if isinstance(ratio_stamp,(int,float)) else None
    derivative_rows.append({"المنصة":name,"الحالة":ar(row.get("status")),"حداثة الدرجة":ar(diagnostic.get("directional_status","NOT_REPORTED")),"حالة التمويل":ar(diagnostic.get("funding_directional_status","NOT_REPORTED")),"عمر التمويل ث":funding_age,"حالة Long/Short":ar(diagnostic.get("long_short_directional_status","NOT_REPORTED")),"عمر Long/Short ث":ratio_age,"عمر الدليل ث":diagnostic.get("age_seconds"),"درجة المساهمة":diagnostic.get("directional_score"),"Funding Rate":row.get("funding_rate"),"Open Interest":row.get("open_interest"),"تغير OI %":row.get("open_interest_change_pct_35m"),"Long/Short":row.get("long_short_ratio"),"Mark Price":row.get("mark_price")})
  if derivative_rows:
   st.markdown("**المشتقات والتموضع — ليس دفتر أوامر السوق الفوري**")
   st.dataframe(pd.DataFrame(derivative_rows),use_container_width=True,hide_index=True)
  sentiment=intel.get("fear_greed",{}) if isinstance(intel.get("fear_greed"),dict) else {}
  global_metrics=intel.get("global_metrics",{}) if isinstance(intel.get("global_metrics"),dict) else {}
  metrics=global_metrics.get("metrics",{}) if isinstance(global_metrics.get("metrics"),dict) else {}
  g1,g2,g3,g4=st.columns(4)
  g1.metric("الخوف والطمع",f"{sentiment.get('value','—')} · {sentiment.get('classification','—')}")
  g2.metric("هيمنة BTC %",metrics.get("bitcoin_dominance_pct","—"))
  g3.metric("القيمة السوقية الكلية $",f"{metrics.get('total_market_cap_usd'):,.0f}" if isinstance(metrics.get("total_market_cap_usd"),(int,float)) else "—")
  g4.metric("حجم السوق 24h $",f"{metrics.get('total_24h_volume_usd'):,.0f}" if isinstance(metrics.get("total_24h_volume_usd"),(int,float)) else "—")
  st.caption(f"حالة Fear & Greed: {ar(sentiment.get('status','NOT_REPORTED'))} · عمر المعلومة: {sentiment.get('freshness_age_seconds','—')} ثانية · {sentiment.get('attribution','')} | المؤشر سياقي contrarian وليس إشارة منفردة.")
  st.caption(f"السوق الكلي: {ar(global_metrics.get('status','NOT_REPORTED'))} · حداثة البيانات: {ar(global_metrics.get('freshness_status','NOT_REPORTED'))} · العمر: {global_metrics.get('freshness_age_seconds','—')} ثانية.")
  st.markdown("**آخر العناوين ذات الصلة**")
  headlines=news_data.get("items",[]) if isinstance(news_data.get("items"),list) else []
  st.caption(f"الأخبار: {ar(news_data.get('status','NOT_REPORTED'))} · عناوين حديثة خلال 72 ساعة: {news_data.get('fresh_count_72h',0)} · عمر أحدث عنوان: {news_data.get('freshest_age_seconds','—')} ثانية · ناشرون مستقلون: {news_data.get('headline_source_count',0)}")
  news_rows=[]
  for item in headlines[:15]:
   if not isinstance(item,dict): continue
   published=item.get("published_at_ms")
   published_label=time.strftime("%Y-%m-%d %H:%M UTC",time.gmtime(published/1000)) if isinstance(published,(int,float)) and published>0 else "وقت غير متاح"
   news_rows.append({"وقت النشر":published_label,"الناشرون":"، ".join(item.get("sources") or [item.get("source","")]),"التكرار":item.get("duplicate_count",1),"العنوان":item.get("title"),"قراءة الكلمات":item.get("sentiment_score"),"علامات المخاطر":", ".join(item.get("risk_flags",[])) or "—","الرابط":item.get("url")})
  if news_rows: st.dataframe(pd.DataFrame(news_rows),use_container_width=True,hide_index=True)
  else: st.info("لم تصل عناوين أخبار صالحة من المصادر المستقلة بعد.")
  calendar=intel.get("economic_calendar",{}) if isinstance(intel.get("economic_calendar"),dict) else {}
  c_events=calendar.get("events",[]) if isinstance(calendar.get("events"),list) else []
  if calendar.get("countries_covered"):
   st.caption("تغطية تقويم Trading Economics: "+"، ".join(calendar.get("countries_covered",[])))
  st.caption("مصادر التقويم: "+", ".join(f"{name}: {ar(status)}" for name,status in (calendar.get("sources",{}) or {}).items()))
  if c_events:
   st.markdown("**الأحداث الاقتصادية القادمة والحديثة**")
   event_rows=[]
   for event in c_events[:30]:
    stamp=event.get("event_time_utc_ms")
    event_rows.append({"الحدث":event.get("name"),"المصدر":event.get("provider"),"الدولة":event.get("country"),"العملة":event.get("currency"),"الأهمية":event.get("importance"),"وقت UTC":time.strftime("%Y-%m-%d %H:%M",time.gmtime(stamp/1000)) if isinstance(stamp,(int,float)) else "—","التوقع":event.get("forecast"),"السابق":event.get("previous"),"الفعلي":event.get("actual"),"جهة الإصدار":event.get("source")})
   st.dataframe(pd.DataFrame(event_rows),use_container_width=True,hide_index=True)
  if calendar.get("high_impact_window_active"):
   st.error("حاجز الحدث الاقتصادي عالي الأهمية نشط: المحرك الرابع يوقف المداخل الجديدة مؤقتاً، ولا يوقف الإغلاق أو الحماية.")
  st.caption("حدود الاستخبارات: لا تقرأ شموعاً أو مؤشرات أو صوراً؛ الأخبار تُقيّم بكلمات مفتاحية قابلة للفحص ولا تعني التحقق من صحة الخبر.")

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
  configured=weights.get("configured",{})
  def _score_label(value):
   return f"{float(value)*100:.1f} / 100" if isinstance(value,(int,float)) else "غير متاح"
  def _weight_label(name):
   return f"أساس {float(configured.get(name,0))*100:.0f}% · فعال {float(weights.get(name,0))*100:.0f}%"
  s1,s2,s3,s4=st.columns(4)
  s1.metric(f"المحرك 1 · {_weight_label('engine_1_market_intelligence')}",
   _score_label(scores.get("engine_1_market_intelligence")),
   help="الأخبار والتقويم والمشتقات والخوف والطمع والسياق الكلي. لا يقرأ الشموع أو الصور.")
  s2.metric(f"المحرك 2 · {_weight_label('engine_2_price_action')}",
   _score_label(scores.get("engine_2_score")),
   help="درجة بنية OHLC متعددة الأطر، مع إضافة الصورة فقط عندما تجتاز المعايرة والتحقق.")
  s3.metric(f"المحرك 3 · {_weight_label('engine_3_indicators')}",
   _score_label(scores.get("engine_3_indicators")),
   help="المؤشرات المحسوبة من سجل الشموع المغلقة الذي يملكه المحرك الثاني.")
  s4.metric("النتيجة المركبة",_score_label(scores.get("combined_score")))
  engine2_internal=weights.get("engine_2_internal",{})
  e2_configured=engine2_internal.get("configured",{})
  e2_applied=engine2_internal.get("applied",{})
  st.caption(
   "النسب الأساسية: المحرك 1 = 20%، المحرك 2 = 50%، المحرك 3 = 30%. "
   "الأوزان الفعالة تتغير بحسب جودة وتغطية الدليل وتُعاد معايرتها إلى 100%. "
   f"داخل المحرك 2: التوزيع المطبق OHLC {float(e2_applied.get('native_ohlc_price_action',1.0))*100:.0f}% "
   f"/ الصورة المعايرة {float(e2_applied.get('calibrated_visual_chart',0.0))*100:.0f}% "
   f"(الأساس {float(e2_configured.get('native_ohlc_price_action',0.70))*100:.0f}% / "
   f"{float(e2_configured.get('calibrated_visual_chart',0.30))*100:.0f}%)."
  )
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
 render_execution_console(state)

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
