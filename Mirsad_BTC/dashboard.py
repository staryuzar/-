from __future__ import annotations
import sys
import time
import hashlib
import math
import sqlite3
import html
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from mirsad.config import (ROOT,DATA_DIR,DB_PATH,SNAPSHOT_PATH,STATUS_PATH,RISK_STATE_PATH,SYMBOL,PROVIDERS,ENABLE_ORDER_PUBLISH,MT5_COMMON_FILES,COLLECT_INTERVAL_SECONDS,RISK_PER_TRADE,DAILY_LOSS_LIMIT_ENABLED,MAX_DAILY_LOSS_FRACTION,MARKET_MAX_AGE_SECONDS,MT5_HEARTBEAT_MAX_AGE_SECONDS,MT5_QUOTE_MAX_AGE_SECONDS,MT5_MARKET_DATA_MAX_AGE_SECONDS,MT5_MARKET_DIVERGENCE_MAX_PCT,MT5_MAX_SPREAD_PCT)
from mirsad.storage import read_json,load_mt5_deal_history
from mirsad.engines.position_ledger import aggregate_position_cycles
from mirsad.engines.mt5_bridge import MT5BridgeEngine
from mirsad.engines.position_management import BREAK_EVEN_TRIGGER_ATR,TRAILING_ACTIVATION_ATR,TRAILING_DISTANCE_ATR,TRAILING_STEP_ATR
from mirsad.health import build_component_health,summarize_component_health


_STREAMLIT_DATAFRAME = st.dataframe


def _safe_dataframe(data, **kwargs):
    """Render mixed-source tables without Arrow type inference failures."""
    frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    frame = frame.copy()
    kwargs.pop("use_container_width", None)
    kwargs.setdefault("width", "stretch")
    for column in frame.columns:
        series = frame[column]
        if str(series.dtype) != "object":
            continue
        values = [value for value in series.tolist() if value is not None and value is not pd.NA]
        if not values:
            frame[column] = series.astype("string")
            continue
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            frame[column] = pd.to_numeric(series, errors="coerce")
            continue
        mixed_types = len({type(value) for value in values}) > 1
        nested_values = any(isinstance(value, (dict, list, tuple, set)) for value in values)
        if mixed_types or nested_values:
            frame[column] = series.map(
                lambda value: "—" if value is None or value is pd.NA else str(value)
            )
    return _STREAMLIT_DATAFRAME(frame, **kwargs)


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
/* Arabic-capable font fallback and localized text direction */
html, body, .stApp, .stApp button, .stApp input, .stApp textarea,
.stApp select, [data-testid="stAppViewContainer"] {
 font-family: Tahoma, "Segoe UI", Arial, sans-serif !important;
}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stCaptionContainer"],
[data-testid="stAlert"] p,
[data-testid="stWidgetLabel"] p {
 direction: rtl;
 text-align: right;
 unicode-bidi: plaintext;
}
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

:root {
 --mirsad-paper:#F3F5F8; --mirsad-surface:#FFFFFF; --mirsad-ink:#0F172A;
 --mirsad-muted:#64748B; --mirsad-line:#E2E8F0; --mirsad-copper:#B7791F;
 --mirsad-copper-tint:#FEF3C7; --mirsad-green:#047857; --mirsad-amber:#B45309;
 --mirsad-red:#BE123C; --mirsad-safe:#64748B;
}
.mirsad-simple-decision {
 background:linear-gradient(135deg,#0F172A 0%,#172554 100%);
 border:1px solid #1E293B; border-radius:22px; padding:24px 26px;
 color:#FFFFFF; box-shadow:0 16px 36px rgba(15,23,42,.12); margin:12px 0 20px 0;
}
.mirsad-simple-decision * { color:#FFFFFF !important; }
.mirsad-simple-decision .decision-eyebrow {
 font-size:12px; font-weight:700; color:#CBD5E1 !important; margin-bottom:10px;
}
.mirsad-simple-decision .decision-value {
 font-size:34px; line-height:1.2; font-weight:900; letter-spacing:-.02em; margin:4px 0 10px 0;
}
.mirsad-simple-decision .decision-reason {
 font-size:14px; line-height:1.9; color:#CBD5E1 !important; max-width:900px;
}
.mirsad-simple-decision .decision-tag {
 display:inline-block; border:1px solid rgba(251,191,36,.4);
 background:rgba(251,191,36,.12); color:#FDE68A !important;
 border-radius:99px; padding:5px 11px; font-size:11px; font-weight:800;
}

</style>
""",unsafe_allow_html=True)

STATUS_AR={
 "RUNNING":"يعمل","LIVE":"متصل وبياناته حية","PARTIAL":"اتصال جزئي",
 "OFFLINE":"غير متصل","STALE":"بيانات قديمة","READY":"جاهز",
 "BULLISH":"صاعد","BEARISH":"هابط","NEUTRAL":"محايد","UNKNOWN":"غير محدد",
 "ACTIVE":"نشط","INACTIVE":"غير نشط",
 "NOT_READY":"غير جاهز","INSUFFICIENT_DATA":"بيانات غير كافية",
 "UNAVAILABLE":"غير متاح","CONNECTED":"جسر الخبير متصل",
 "CONFIRMED":"تمت المصالحة",
 "CONFIRMED_FROM_DEAL_HISTORY":"تأكيد من سجل صفقات MT5",
 "POSITION_CLOSED_AFTER_MODIFY":"\u0623\u064f\u063a\u0644\u0642 \u0627\u0644\u0645\u0631\u0643\u0632 \u0644\u0627\u062d\u0642\u0627\u064b \u0648\u062a\u0623\u0643\u062f \u0645\u0646 MT5",
 "ACK_PENDING":"نتيجة الإقرار قيد التحقق",
 "WAITING_FOR_EXPERT":"بانتظار الخبير التنفيذي","NOT_CONFIGURED":"مسار MT5 غير محدد",
 "PUBLISH_DISABLED":"نشر أوامر الخبير معطل","EXECUTION_DISABLED":"تنفيذ خبير MT5 معطّل","EXECUTION_STATE_UNKNOWN":"لم تصل حالة مفتاح تنفيذ الخبير","TERMINAL_NOT_CONNECTED":"طرفية MT5 غير متصلة","PUBLISHED":"أُرسل أمر للجسر",
 "ALREADY_ACKNOWLEDGED":"الأمر له إقرار سابق","ALREADY_PUBLISHED":"الأمر منشور مسبقاً",
 "PENDING_COMMAND_BLOCKED":"أمر سابق ينتظر التسوية","REJECTED":"الأمر مرفوض","ERROR":"خطأ",
 "FULLY_OPERATIONAL":"التشغيل مكتمل؛ الدخول عند تحقق شروط السوق","NOT_REPORTED":"لم ترد حالة تشغيل مستقلة بعد","PARTIAL_OR_WAITING":"تشغيل جزئي — توجد وصلات تنتظر",
 "WAITING_FOR_ENGINE_2":"بانتظار توافق بنية السعر بين الأطر",
 "MIXED_TIMEFRAME_DIRECTIONS":"اتجاهات الأطر متعارضة",
 "BULLISH_STRUCTURE_CONFLUENCE":"توافق بنيوي صاعد",
 "BEARISH_STRUCTURE_CONFLUENCE":"توافق بنيوي هابط",
 "NO_CLEAR_STRUCTURE_CONFLUENCE":"لا يوجد توافق بنيوي واضح",
 "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE":"بانتظار توافق بنية السعر من المحرك الثاني",
 "WAITING_FOR_ENGINE_2_CANDLE_PATTERN_CONFLUENCE":"بانتظار توافق نماذج الشموع",
 "CANDLE_PATTERN_DIRECTION_CONFLICT":"نمط الشموع يعارض اتجاه البنية",
 "MIXED_CANDLE_PATTERN_EVIDENCE":"أدلة نماذج الشموع متعارضة",
 "MIXED_OR_NO_CONFLUENCE":"لا يوجد توافق بنيوي كافٍ",
 "INSUFFICIENT_DIRECTIONAL_FRAME_COVERAGE":"تغطية الأطر ذات الاتجاه المؤكد غير كافية",
 "INSUFFICIENT_STRUCTURE_EVIDENCE_QUALITY":"جودة أدلة بنية السعر غير كافية",
 "WAITING_FOR_ENGINE_3_QUOTE":"بانتظار سعر MT5 الحي",
 "WAITING_FOR_ENGINE_5_QUOTE":"يلزم سعر MT5 حي ومواصفات الرمز لحساب الحجم",
 "NOT_REQUIRED":"غير مطلوب في هذه الدورة",
 "DISABLED_FOR_DEVELOPMENT":"معطّل بإعداد التطوير",
 "NOT_AVAILABLE":"غير متاح لدى المصدر",
 "FRESHNESS_UNKNOWN":"حداثة البيانات غير معروفة",
 "REPORTED_DISABLED":"أبلغ الخبير أن التنفيذ معطّل",
 "INCOMPLETE_HISTORY":"سجل تاريخي غير مكتمل",
 "PASS":"اجتاز الفحص","FAIL":"فشل الفحص",
 "WAITING":"بانتظار البيانات","UNKNOWN":"غير معروف",
 "MITIGATED":"تمت ملامسة المنطقة بعد تكوّنها",
 "UNMITIGATED_AT_SAMPLE_END":"لم تُلامس حتى نهاية العينة",
 "INVALIDATED":"أُبطلت المنطقة",
 "NO_OPPOSING_CANDLE":"لا توجد شمعة معاكسة",
 "BLOCKED":"محجوب حتى تكتمل البيانات"}
def ar(value):
 return STATUS_AR.get(str(value),str(value or "غير متاح"))
def age_text(ts):
 if not ts: return "لا توجد إشارة حياة"
 return f"آخر نبض منذ {max(0,int(time.time()*1000)-int(ts))/1000:.1f} ثانية"

def utc_ms_text(value):
 try:
  stamp=float(value)
  if not math.isfinite(stamp) or stamp<=0:
   return "—"
  return time.strftime("%Y-%m-%d %H:%M:%S UTC",time.gmtime(stamp/1000.0))
 except (TypeError,ValueError,OverflowError,OSError):
  return "—"

def render_component_health(state:dict)->None:
 # Rebuild from the latest status snapshot so source metadata and health
 # classifications cannot remain stale in a persisted component summary.
 items=build_component_health(state)
 summary=summarize_component_health(items)
 st.markdown('<div class="mirsad-kicker">COMMAND CENTER / ENGINE HEALTH</div>',unsafe_allow_html=True)
 st.subheader("مركز مراقبة المحركات والأدوات")
 st.caption("الحالة من آخر دورة تشغيل فعلية؛ غياب القياس يظهر كحالة انتظار، واختلاف رمز الوسيط أو مصدر البيانات أو تقادم الشموع والسعر يظهر كتنبيه.")
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
  "المحرك الثاني — الشموع وبنية السعر الأصلية",
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
  ("\u0645\u0635\u0627\u0644\u062d\u0629 \u0622\u062e\u0631 \u0623\u0645\u0631", "\u0645\u063a\u0644\u0642\u0629 \u0644\u0627\u062d\u0642\u0627\u064b \u0648\u0645\u0624\u0643\u062f\u0629 \u0645\u0646 MT5" if reconciliation.get("status")=="POSITION_CLOSED_AFTER_MODIFY" else "\u0645\u0624\u0643\u062f\u0629 \u0645\u0646 MT5" if reconciliation.get("status")=="CONFIRMED_FROM_DEAL_HISTORY" else "\u0645\u0624\u0643\u062f\u0629" if reconciliation.get("status")=="CONFIRMED" else ar(reconciliation.get("status","NOT_REPORTED")), reconciliation.get("status") in {"CONFIRMED","CONFIRMED_FROM_DEAL_HISTORY","POSITION_CLOSED_AFTER_MODIFY","NO_PENDING_COMMAND"}),
 ]
 for col,(label,value,ok) in zip(gate_cols,gate_values):
  with col:
   st.metric(label,value)
   if label=="مصالحة آخر أمر" and reconciliation.get("status")=="NO_PENDING_COMMAND":
    st.caption("لا يوجد أمر معلّق — حالة طبيعية")
   else:
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
  _safe_dataframe(pd.DataFrame(command_rows),width="stretch",hide_index=True)
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
     width="stretch",
     disabled=not (gates_ok and confirmation and active_action==target),
     help=("لا يُفعّل إلا عندما يكون هذا النوع هو قرار المحرك الرابع الحالي واجتاز كل البوابات."),
    )
   if clicked:
    publish_clicked_action=target
  with action_columns[4]:
   st.button(
    "CANCEL · غير مدعوم",
    key=publish_button_key+"_CANCEL",
    width="stretch",
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
  _safe_dataframe(pd.DataFrame(spec_rows),width="stretch",hide_index=True)
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
   _safe_dataframe(pd.DataFrame(position_rows),width="stretch",hide_index=True)
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
   _safe_dataframe(pd.DataFrame(event_rows),width="stretch",hide_index=True)
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
  _safe_dataframe(pd.DataFrame(file_rows),width="stretch",hide_index=True)
  st.caption("Common Files / MirsadBTC: status.json · command.json · ack.json · positions.json · events.jsonl")

 with tabs[6]:
  settings_rows=[
   {"الإعداد":"MIRSAD_SYMBOL","القيمة":SYMBOL,"المعنى":"الرمز المنطقي الذي يعمل عليه محرك السوق داخل البرنامج."},
   {"الإعداد":"MIRSAD_DATA_DIR","القيمة":str(DATA_DIR),"المعنى":"مجلد البيانات المحلية وقاعدة البيانات واللقطات والتقارير التشغيلية."},
   {"الإعداد":"SQLite database","القيمة":str(DB_PATH),"المعنى":"قاعدة بيانات السوق والتاريخ والأرشفة."},
   {"الإعداد":"system_status.json","القيمة":str(STATUS_PATH),"المعنى":"ملف الحالة الموحد الذي تقرأ منه لوحة القيادة."},
   {"الإعداد":"latest_market.json","القيمة":str(SNAPSHOT_PATH),"المعنى":"آخر لقطة سوق كتبها runtime."},
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
   {"الإعداد":"MIRSAD_COLLECT_SECONDS","القيمة":COLLECT_INTERVAL_SECONDS,"المعنى":"الفاصل بين دورات runtime بالثانية."},
   {"الإعداد":"MIRSAD_MT5_COMMON_FILES","القيمة":MT5_COMMON_FILES or "غير مضبوط","المعنى":"المجلد الأب الذي يضم Common Files/MirsadBTC بين البرنامج والخبير."},
   {"الإعداد":"InpMagicNumber","القيمة":bridge.get("magic_number","—"),"المعنى":"معرّف المراكز والأوامر التي يملكها خبير مرصاد."},
   {"الإعداد":"مصادر البحث والمقارنة","القيمة":"، ".join(PROVIDERS.keys()),"المعنى":"مصادر بحث/تقييم مهيأة في الكود؛ مصدر القرار والتشغيل الحي يبقى MT5 وفق عقود المحركات."},
  ]
  _safe_dataframe(pd.DataFrame(settings_rows),width="stretch",hide_index=True)
  daily_cols=st.columns(4)
  daily_status=("DISABLED_FOR_DEVELOPMENT" if daily.get("enabled") is False or daily.get("mode")=="DISABLED_FOR_DEVELOPMENT" else daily.get("status","NOT_REPORTED"))
  daily_cols[0].metric("حالة حد الخسارة اليومية",ar(daily_status))
  daily_cols[1].metric("مفعّل","نعم" if daily.get("enabled") else "لا")
  daily_cols[2].metric("قفل فتح المراكز","نعم" if daily.get("locked") else "لا")
  daily_cols[3].metric("الخسارة اليومية %",f"{float(daily.get('daily_loss_fraction'))*100:.3f}" if daily.get("daily_loss_fraction") is not None else "—")
  st.caption(daily.get("reason") or "حد الخسارة اليومية معطّل بإعداد التطوير، لذلك لا يُحتسب حاجز حماية نشطاً. وتُعرض بقية ضوابط المخاطر بحسب حالتها ونتيجة فحصها في الدورة الحالية.")
  st.markdown("**إدارة الوقف الوقائي ATR — خطة المحرك الرابع**")
  trail_rows=[
   {"المعلمة":"نقل الوقف إلى سعر الدخول بعد حركة مواتية","القيمة":f"{BREAK_EVEN_TRIGGER_ATR} ATR"},
   {"المعلمة":"بدء التتبع بعد حركة مواتية","القيمة":f"{TRAILING_ACTIVATION_ATR} ATR"},
   {"المعلمة":"مسافة الوقف المتتبع","القيمة":f"{TRAILING_DISTANCE_ATR} ATR"},
   {"المعلمة":"أقل خطوة بين تحديثين","القيمة":f"{TRAILING_STEP_ATR} ATR"},
  ]
  _safe_dataframe(pd.DataFrame(trail_rows),width="stretch",hide_index=True)
  st.caption("إدارة الوقف لا توسع المخاطرة ولا تعدل الهدف؛ تقترح تحديثاً واحداً فقط في الدورة وتبقى خاضعة لتطابق Tick وStops/Freeze لدى الوسيط.")

def render_detailed_engine_dashboard():
 state=read_json(STATUS_PATH,{})
 market=read_json(SNAPSHOT_PATH,{})
 st.title("₿ مرصاد البيتكوين")
 st.caption("مرصاد منظومة بخمسة محركات مترابطة: استخبارات سوق مستقلة، شموع وحركة سعر من OHLC الأصلي، مؤشرات فنية، قرار ومخاطر، وجسر MT5.")
 if state:
  st.metric("الحالة العامة",ar(state.get("overall_status","PARTIAL_OR_WAITING")))
  st.caption(age_text(state.get("heartbeat_at_ms")))
  runtime_error=str(state.get("runtime_error") or "").strip()
  if runtime_error:
   st.error("سبب فشل آخر دورة تشغيل: "+runtime_error)
  elif str(state.get("overall_status") or "").upper()=="ERROR":
   st.error("أعلن البرنامج فشل آخر دورة تشغيل، لكن لم تصل تفاصيل الخطأ في ملف الحالة.")
 else:
  st.warning("خدمة البرنامج لم تبدأ بعد. شغّل run_mirsad.py لتشغيل محركات البيانات والتحليل.")
 if state:
  labels=[
   ("1 — استخبارات السوق","engine_1_market_intelligence"),
   ("2 — الشموع وبنية السعر","engine_2_price_action"),
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
  st.subheader("المحرك الخامس — سعر الوسيط وتغذية التنفيذ")
  cols=st.columns(4)
  cols[0].metric("السعر المرجعي BTC/USDT",f"{market['price']:,.2f}" if market.get("price") else "غير متاح")
  cols[1].metric("مصدر السعر",f"{market.get('venue_count',0)} / 1 — MT5")
  cols[2].metric("الطرفية",market.get("primary_venue") or "غير متاح")
  cols[3].metric("حالة السوق",ar(market.get("status")))
  rows=[]
  for name,row in market.get("venues",{}).items():
   pulse=row.get("microstructure") or {}
   rows.append({"المصدر":name,"الاتصال":ar(row.get("status")),"معدل التحديث/دقيقة":pulse.get("tick_rate_per_minute"),"توازن عروض الأسعار":pulse.get("quote_direction_balance"),"سبريد مراقب MT5 الحالي %":pulse.get("current_spread_pct"),"الخطأ":row.get("error") or "—"})
  if rows: _safe_dataframe(pd.DataFrame(rows),width="stretch",hide_index=True)
  for name,row in market.get("venues",{}).items():
   if row.get("status")=="LIVE":
    with st.expander(f"تفاصيل نبض سعر الوسيط — {name}"):
     pulse=row.get("microstructure") or {}
     p1,p2,p3,p4,p5=st.columns(5)
     p1.metric("تحديثات السعر",pulse.get("tick_count","—"))
     p2.metric("تحديثات صاعدة",pulse.get("upticks","—"))
     p3.metric("تحديثات هابطة",pulse.get("downticks","—"))
     p4.metric("اتزان التحديثات",pulse.get("quote_direction_balance","—"))
     p5.metric("تغير منتصف السعر %",pulse.get("midpoint_change_pct","—"))
     st.caption(pulse.get("scope","تحديثات عروض الأسعار وليست صفقات منفذة."))
     st.caption("هذه التغذية خاصة بسعر الوسيط وتحديثات Bid/Ask والسبريد، ولا تدخل في تصويت المحرك الأول.")
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
  i4.metric("تغطية مكونات التصويت",f"{float(intel.get('evidence_coverage',0) or 0)*100:.0f}%",help="نسبة أوزان مكونات استخبارات السوق المتاحة (المشتقات والأخبار والخوف والطمع)، وليست اكتمال كل حقل أو كل مزود بيانات.")
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
   _safe_dataframe(pd.DataFrame(source_rows),width="stretch",hide_index=True)
  news_data=intel.get("news",{}) if isinstance(intel.get("news"),dict) else {}
  feed_statuses=news_data.get("sources",{}) if isinstance(news_data.get("sources"),dict) else {}
  if feed_statuses:
   st.markdown("**حالة كل موجز إخباري**")
   feed_rows=[{"الموجز":name,"الحالة":ar(status)} for name,status in feed_statuses.items()]
   _safe_dataframe(pd.DataFrame(feed_rows),width="stretch",hide_index=True)
  components=intel.get("components",{}) if isinstance(intel.get("components"),dict) else {}
  comp_rows=[{"المكوّن":name,"الحالة":ar(value.get("status")),"الدرجة":value.get("score"),"الوزن":value.get("weight"),"الثقة":value.get("confidence"),"يساهم في السياق":("نعم" if value.get("contributes") else "لا")} for name,value in components.items() if isinstance(value,dict)]
  if comp_rows: _safe_dataframe(pd.DataFrame(comp_rows),width="stretch",hide_index=True)
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
    derivative_rows.append({"المنصة":name,"الحالة":ar(row.get("status")),"حداثة الدرجة":ar(diagnostic.get("directional_status","NOT_REPORTED")),"حالة التمويل":ar(diagnostic.get("funding_directional_status","NOT_REPORTED")),"عمر التمويل ث":funding_age,"حالة Long/Short":ar(diagnostic.get("long_short_directional_status","NOT_REPORTED")),"عمر Long/Short ث":ratio_age,"عمر الدليل ث":diagnostic.get("age_seconds"),"درجة المساهمة":diagnostic.get("directional_score"),"Funding Rate":row.get("funding_rate"),"أساس التمويل":row.get("funding_basis",""),"Open Interest":row.get("open_interest"),"وحدة OI":row.get("open_interest_unit",""),"Open Interest USD":row.get("open_interest_usd"),"تغير OI %":row.get("open_interest_change_pct_35m"),"Long/Short":row.get("long_short_ratio"),"Mark Price":row.get("mark_price"),"حالة نقاط API":row.get("endpoint_statuses",{}),"أخطاء API":row.get("endpoint_errors",{})})
  if derivative_rows:
   st.markdown("**المشتقات والتموضع — ليس دفتر أوامر السوق الفوري**")
   _safe_dataframe(pd.DataFrame(derivative_rows),width="stretch",hide_index=True)
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
   news_rows.append({"وقت النشر":published_label,"الناشرون":"، ".join(item.get("sources") or [item.get("source","")]),"التكرار":item.get("duplicate_count",1),"العنوان":item.get("title"),"درجة نبرة العنوان":item.get("sentiment_score"),"علامات المخاطر":", ".join(item.get("risk_flags",[])) or "—","الرابط":item.get("url")})
  if news_rows: _safe_dataframe(pd.DataFrame(news_rows),width="stretch",hide_index=True)
  else: st.info("لم تصل عناوين أخبار صالحة من المصادر المستقلة بعد.")
  calendar=intel.get("economic_calendar",{}) if isinstance(intel.get("economic_calendar"),dict) else {}
  c_events=calendar.get("events",[]) if isinstance(calendar.get("events"),list) else []
  if calendar.get("countries_covered"):
   st.caption("تغطية التقويم الاقتصادي المستقل: "+"، ".join(calendar.get("countries_covered",[])))
  st.caption("مصادر التقويم: "+", ".join(f"{name}: {ar(status)}" for name,status in (calendar.get("sources",{}) or {}).items()))
  if c_events:
   st.markdown("**الأحداث الاقتصادية — القادمة والسابقة**")
   event_rows=[]
   now_ms=int(time.time()*1000)
   for event in c_events[:30]:
    stamp=event.get("event_time_utc_ms")
    event_stage=("قادم" if stamp>=now_ms else "وقع بالفعل") if isinstance(stamp,(int,float)) else "وقت غير محدد"
    event_rows.append({"الحالة الزمنية":event_stage,"الحدث":event.get("name"),"المصدر":event.get("provider"),"الدولة":event.get("country"),"العملة":event.get("currency"),"الأهمية":event.get("importance"),"وقت UTC":utc_ms_text(stamp),"التوقع":event.get("forecast"),"السابق":event.get("previous"),"الفعلي":event.get("actual"),"جهة الإصدار":event.get("source")})
   _safe_dataframe(pd.DataFrame(event_rows),width="stretch",hide_index=True)
  if calendar.get("high_impact_window_active"):
   st.error("حاجز الحدث الاقتصادي عالي الأهمية نشط: المحرك الرابع يوقف المداخل الجديدة مؤقتاً، ولا يوقف الإغلاق أو الحماية.")
  st.caption("حدود الاستخبارات: لا تقرأ شموعاً أو مؤشرات أو صوراً؛ الأخبار تُقيّم بكلمات مفتاحية قابلة للفحص ولا تعني التحقق من صحة الخبر.")

 if state:
  price_action=state.get("engine_2_price_action",{}) if isinstance(state.get("engine_2_price_action"),dict) else {}
  summary=price_action.get("summary",{}) if isinstance(price_action.get("summary"),dict) else {}
  candle_state=state.get("engine_2_candles",{}) if isinstance(state.get("engine_2_candles"),dict) else {}
  st.subheader("المحرك الثاني — تحليل الشموع وبنية السعر من OHLC الأصلي")
  p1,p2,p3,p4,p5=st.columns(5)
  p1.metric("حالة التحليل",ar(price_action.get("status","NOT_REPORTED")))
  p2.metric("الاتجاه البنيوي",ar(price_action.get("direction","NOT_REPORTED")))
  score=price_action.get("structure_score")
  p3.metric("درجة أدلة السعر",f"{float(score):+.3f}" if isinstance(score,(int,float)) else "—")
  p4.metric("اتجاه البنية بين الأطر",ar(summary.get("timeframe_alignment","NOT_REPORTED")))
  p5.metric("أطر التحليل المكتمل",f"{summary.get('eligible_timeframe_count',0)}/6")
  st.caption(f"توفر بيانات الأطر للتحليل: {summary.get('eligible_timeframe_count',0)}/6 · الأطر ذات اتجاه بنيوي مؤكد: {summary.get('directional_frame_count',0)} · نسبة اتفاق الاتجاهات المؤكدة: {float(summary.get('directional_structure_agreement',0) or 0)*100:.0f}%.")
  if summary.get("timeframe_alignment")=="MIXED_TIMEFRAME_DIRECTIONS":
   st.warning("اكتمل تحليل الأطر، لكن الاتجاهات البنيوية المؤكدة متعارضة؛ لذلك لا تتحول جاهزية التحليل إلى إشارة دخول.")
  st.caption("التحليل من شموع MT5 المكتملة فقط. القمم والقيعان المؤكدة هي الأساس، وتساندها كسر/تغير البنية ونماذج الشموع وعمليات سحب السيولة؛ لا صور أو مؤشرات فنية داخل المحرك الثاني.")
  if price_action.get("reason"):
   st.caption(price_action["reason"])
  evidence_weights=summary.get("directional_evidence_weights",{})
  if evidence_weights:
   st.caption("الأوزان الداخلية لأدلة المحرك الثاني: "+" · ".join(
    f"{name}: {float(weight)*100:.0f}%"
    for name,weight in evidence_weights.items()
   ))
  timeframe_rows=[]
  candle_rows=[]
  event_rows=[]
  sweep_rows=[]
  zone_rows=[]
  for timeframe,frame in (price_action.get("timeframes") or {}).items():
   structure=frame.get("structure") or {}
   candle_analysis=frame.get("candle_analysis") or {}
   data_quality=frame.get("data_quality") or {}
   timeframe_rows.append({
    "الإطار":timeframe,
    "الحالة":ar(frame.get("status")),
    "الاتجاه البنيوي":frame.get("structure_direction",frame.get("direction","—")),
    "درجة أدلة الإطار":frame.get("directional_evidence_score"),
    "الشموع المستخدمة في تحليل البنية":frame.get("closed_bars",0),
    "قوة التأرجح":frame.get("structure_strength","—"),
    "فجوات البيانات":data_quality.get("gap_count",0),
   })
   for item in candle_analysis.get("latest_candle_patterns",[]):
    candle_rows.append({
     "الإطار":timeframe,
     "النمط":item.get("pattern_id"),
     "الاتجاه":item.get("direction"),
     "سياق الاتجاه":item.get("context_match"),
     "حالة التأكيد":item.get("confirmation_state"),
    })
   for item in (structure.get("bos_choch_events") or [])[-5:]:
    event_name=str(item.get("event") or "")
    event_direction=(
     "صاعد" if event_name.endswith("_BULLISH")
     else "هابط" if event_name.endswith("_BEARISH")
     else item.get("side","—")
    )
    event_label={
     "BOS_BULLISH":"كسر بنية صاعد","BOS_BEARISH":"كسر بنية هابط",
     "CHOCH_BULLISH":"تغير بنية صاعد","CHOCH_BEARISH":"تغير بنية هابط",
    }.get(event_name,event_name or "—")
    event_rows.append({
     "الإطار":timeframe,
     "الحدث":event_label,
     "الاتجاه":event_direction,
     "المستوى":item.get("level"),
     "وقت التأكيد (UTC)":utc_ms_text(item.get("confirmation_time_utc_ms")),
    })
   for item in (structure.get("liquidity_sweeps") or [])[-5:]:
    sweep_name=str(item.get("event") or "")
    sweep_rows.append({
     "الإطار":timeframe,
     "الحدث":{"HIGH_LIQUIDITY_SWEEP":"سحب سيولة من القمم","LOW_LIQUIDITY_SWEEP":"سحب سيولة من القيعان"}.get(sweep_name,sweep_name or "—"),
     "الاتجاه":{"BULLISH_REJECTION":"رفض صاعد","BEARISH_REJECTION":"رفض هابط"}.get(str(item.get("side") or ""),item.get("side","—")),
     "المستوى":item.get("level"),
     "وقت التأكيد (UTC)":utc_ms_text(item.get("confirmation_time_utc_ms")),
    })
   for item in (structure.get("fair_value_gaps") or [])[-5:]:
    fvg_id=str(item.get("structure_id") or "")
    zone_rows.append({
     "الإطار":timeframe,"النوع":"FVG",
     "الاتجاه":{"bullish_fvg":"صاعد","bearish_fvg":"هابط"}.get(fvg_id,"غير محدد"),
     "الحد الأدنى":item.get("zone_low"),"الحد الأعلى":item.get("zone_high"),
     "منتصف المنطقة":item.get("midpoint"),
     "وقت التكوين (UTC)":utc_ms_text(item.get("time_utc_ms")),
     "الحالة":ar(item.get("status")),
    })
   for item in (structure.get("order_block_candidates") or [])[-5:]:
    zone_rows.append({
     "الإطار":timeframe,"النوع":"Order Block",
     "الاتجاه":{"BULLISH":"صاعد","BEARISH":"هابط"}.get(str(item.get("direction") or ""),item.get("direction","—")),
     "الحد الأدنى":item.get("zone_low"),"الحد الأعلى":item.get("zone_high"),
     "الحالة":ar(item.get("status")),
    })
  if timeframe_rows:
   st.markdown("**ملخص الأطر الزمنية الستة**")
   _safe_dataframe(pd.DataFrame(timeframe_rows),width="stretch",hide_index=True)
   st.caption("عدد الشموع المستخدمة في حساب بنية كل إطار يُعرض منفصلاً عن عدد الشموع المحفوظة في سجل OHLC؛ فهما قياسان مختلفان ولا يُفترض تطابقهما.")
  if candle_rows:
   st.markdown("**نماذج الشموع على أحدث شمعة مغلقة**")
   _safe_dataframe(pd.DataFrame(candle_rows),width="stretch",hide_index=True)
  if event_rows:
   st.markdown("**أحداث BOS / CHOCH المؤكدة**")
   _safe_dataframe(pd.DataFrame(event_rows),width="stretch",hide_index=True)
  if sweep_rows:
   st.markdown("**مناطق سحب السيولة المؤكدة**")
   _safe_dataframe(pd.DataFrame(sweep_rows),width="stretch",hide_index=True)
  if zone_rows:
   st.markdown("**الفجوات السعرية وكتل الأوامر المرشحة**")
   _safe_dataframe(pd.DataFrame(zone_rows),width="stretch",hide_index=True)
  if summary.get("warnings"):
   st.caption("تنبيهات جودة الأطر: "+" | ".join(summary.get("warnings",[])))
  st.markdown("**تغذية الشموع الأصلية التي يملكها المحرك الثاني**")
  st.metric("حالة سجل OHLC",ar(candle_state.get("status","NOT_REPORTED")))
  if candle_state.get("timeframes"):
   _safe_dataframe(pd.DataFrame([{
    "الإطار":tf,"إجمالي الشموع":count,
    "الشموع المغلقة في السجل":(candle_state.get("closed_candles") or {}).get(tf,"—")
   } for tf,count in candle_state["timeframes"].items()]),width="stretch",hide_index=True)
  if candle_state.get("reason"):
   st.caption(candle_state["reason"])

  indicators=state.get("indicators",{})
  st.subheader("المحرك الثالث — المؤشرات")
  i1,i2,i3,i4,i5,i6,i7=st.columns(7)
  indicator_values=indicators.get("values",{})
  signal_score=indicators.get("signal_score")
  signal_quality=indicators.get("signal_quality")
  i1.metric("حالة المؤشرات",ar(indicators.get("status","NOT_REPORTED")))
  i2.metric("التصويت الفني المركب",f"{float(signal_score):+.3f}" if isinstance(signal_score,(int,float)) else "—")
  i3.metric("جودة التصويت",f"{float(signal_quality)*100:.0f}%" if isinstance(signal_quality,(int,float)) else "—")
  i4.metric("EMA 20 / 1m",f"{indicator_values.get('ema20_1m'):,.2f}" if indicator_values.get("ema20_1m") is not None else "—")
  i5.metric("EMA 50 / 1m",f"{indicator_values.get('ema50_1m'):,.2f}" if indicator_values.get("ema50_1m") is not None else "—")
  i6.metric("RSI 14 / 1m",f"{indicator_values.get('rsi14_1m'):.2f}" if indicator_values.get("rsi14_1m") is not None else "—")
  i7.metric("ATR 14 / 5m",f"{indicator_values.get('atr14_5m'):,.2f}" if indicator_values.get("atr14_5m") is not None else "—")
  if indicators.get("timeframes"):
   indicator_rows=[{
    "الإطار":tf,"الحالة":ar(item.get("status")),
    "الاتجاه":item.get("trend"),"EMA 20":item.get("ema20"),
    "EMA 50":item.get("ema50"),"الشموع المغلقة":item.get("closed_candles")
   } for tf,item in indicators["timeframes"].items()]
   _safe_dataframe(pd.DataFrame(indicator_rows),width="stretch",hide_index=True)
  detailed_indicators=indicators.get("indicators_by_timeframe",{}) if isinstance(indicators.get("indicators_by_timeframe"),dict) else {}
  if detailed_indicators:
   with st.expander("تفاصيل المؤشرات العشرين عبر الأطر الزمنية الستة",expanded=False):
    detail_rows=[]
    for timeframe,values in detailed_indicators.items():
     for indicator_name,value in values.items():
      detail_rows.append({"الإطار":timeframe,"المؤشر":indicator_name,"القيمة":value,"الحالة":"READY" if isinstance(value,(int,float)) and math.isfinite(float(value)) else "INSUFFICIENT"})
    _safe_dataframe(pd.DataFrame(detail_rows),width="stretch",hide_index=True)
  signal_frames=indicators.get("signal_components_by_timeframe",{}) if isinstance(indicators.get("signal_components_by_timeframe"),dict) else {}
  if signal_frames:
   with st.expander("تفصيل التصويت الفني حسب العائلات والأطر الزمنية",expanded=False):
    group_rows=[]
    for timeframe,signal in signal_frames.items():
     for group_name,details in (signal.get("groups",{}) or {}).items():
      group_rows.append({"الإطار":timeframe,"عائلة الدليل":group_name,"الدرجة":details.get("score"),"التغطية":details.get("coverage"),"الوزن الأساسي":details.get("base_weight"),"الوزن الفعال":details.get("effective_weight"),"الحالة":ar(signal.get("status"))})
    if group_rows:
     _safe_dataframe(pd.DataFrame(group_rows),width="stretch",hide_index=True)
    group_weights=indicators.get("signal_group_weights",{})
    if isinstance(group_weights,dict):
     st.caption("الأوزان الداخلية: "+" · ".join(f"{name}: {float(weight)*100:.0f}%" for name,weight in group_weights.items()))
    st.caption("تُحسب عائلة الاتجاه والزخم وقوة الاتجاه والمتذبذبات وتدفق الحجم مرةً لكل مجموعة؛ المؤشرات المترابطة لا تُحسب أصواتاً مستقلة. ATR مقياس تقلب وتطبيع فقط، وليس تصويتاً اتجاهياً.")
    st.caption("أساس عائلة الحجم: "+str(indicators.get("signal_volume_basis","غير محدد")))
  if indicators.get("missing_signal_timeframes"):
   st.warning("تغطية التصويت الفني غير مكتملة في: "+", ".join(indicators.get("missing_signal_timeframes",[])))
  native_indicators=state.get("mt5_native_indicators",{}) if isinstance(state.get("mt5_native_indicators"),dict) else {}
  parity_report=indicators.get("mt5_native_parity",{}) if isinstance(indicators.get("mt5_native_parity"),dict) else {}
  parity_frames=parity_report.get("timeframes",{}) if isinstance(parity_report.get("timeframes"),dict) else {}
  parity_passed=sum(
   1 for frame in parity_frames.values()
   for metric in (frame.get("metrics",{}) or {}).values()
   if isinstance(metric,dict) and metric.get("status")=="PASS"
  )
  parity_total=sum(
   len((frame.get("metrics",{}) or {}))
   for frame in parity_frames.values() if isinstance(frame,dict)
  )
  parity_label=f"{parity_passed}/{parity_total} · {ar(parity_report.get('status','NOT_REPORTED'))}" if parity_total else ar(parity_report.get("status","NOT_REPORTED"))
  st.markdown("**التحقق المستقل من مؤشرات MT5 الأصلية — CopyBuffer**")
  n1,n2,n3,n4,n5=st.columns(5)
  n1.metric("تغذية MT5",ar(native_indicators.get("status","NOT_REPORTED")))
  n2.metric("الأطر الجاهزة",f"{native_indicators.get('ready_timeframe_count',0)}/6")
  n3.metric("تزامن الشموع",ar(native_indicators.get("bar_alignment_status","NOT_CHECKED")))
  n4.metric("تطابق Engine 3 / MT5",parity_label)
  n5.metric("عمر اللقطة (ث)",native_indicators.get("age_seconds","—"))
  native_frames=native_indicators.get("timeframes",{}) if isinstance(native_indicators.get("timeframes"),dict) else {}
  native_alignment=native_indicators.get("bar_alignment",{}) if isinstance(native_indicators.get("bar_alignment"),dict) else {}
  if native_frames:
   native_rows=[]
   for timeframe,frame in native_frames.items():
    values=frame.get("values",{}) if isinstance(frame.get("values"),dict) else {}
    ready_count=sum(1 for value in values.values() if isinstance(value,dict) and value.get("status")=="READY")
    missing=", ".join(frame.get("missing_required_indicators",[])) or "—"
    native_rows.append({"الإطار":timeframe,"حالة الإطار":ar(frame.get("status")),"المؤشرات الجاهزة":f"{ready_count}/20","المؤشرات الأساسية الناقصة":missing,"مطابقة توقيت الشمعة":ar((native_alignment.get(timeframe) or {}).get("status","NOT_CHECKED"))})
   _safe_dataframe(pd.DataFrame(native_rows),width="stretch",hide_index=True)
  if native_indicators.get("reason"):
   st.caption(native_indicators["reason"])
  st.caption(indicators.get("reason") or "المؤشرات تحسب من سجل الشموع المغلقة الذي يملكه المحرك الثاني؛ CopyBuffer للمقارنة المستقلة فقط ولا يصدر أوامر أو تصويتاً مستقلاً.")
 
  bridge=state.get("bridge") if isinstance(state.get("bridge"),dict) else {}
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

  st.subheader("دفتر صفقات Mirsad الموثّق من MT5")
  deal_meta=bridge.get("deal_history",{}) if isinstance(bridge.get("deal_history"),dict) else {}
  deal_store=state.get("mt5_deal_ledger",{}) if isinstance(state.get("mt5_deal_ledger"),dict) else {}
  l1,l2,l3,l4=st.columns(4)
  l1.metric("حالة سجل الوسيط",ar(deal_meta.get("status","NOT_REPORTED")))
  l2.metric("إجمالي تنفيذات Mirsad ضمن الفترة",deal_meta.get("history_matching_total",deal_meta.get("deal_count",0)))
  st.caption(f"الصفقات المعادة حالياً: {deal_meta.get('deal_count',0)} | الحد الأقصى للعرض من MT5: 1000 صفقة | نافذة السجل: 90 يوماً حسب إعداد الخبير.")
  l3.metric("حفظ SQLite",ar(deal_store.get("status","NOT_REPORTED")))
  l4.metric("التاريخ مقطوع؟","نعم" if deal_meta.get("truncated") else "لا")
  if deal_meta.get("reason"):
   st.caption(str(deal_meta.get("reason")))
  if deal_store.get("reason"):
   st.caption(str(deal_store.get("reason")))
  try:
   ledger_magic=int(bridge.get("magic_number",0) or 0)
   ledger_symbol=str(bridge.get("symbol") or "").strip()
  except (TypeError,ValueError,OverflowError):
   ledger_magic=0;ledger_symbol=""
  if ledger_magic>0 and ledger_symbol:
   try:
    deal_rows=load_mt5_deal_history(magic_number=ledger_magic,symbol=ledger_symbol,limit=1000)
   except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
    st.warning(f"تعذر قراءة دفتر صفقات Mirsad المحفوظ: {type(exc).__name__}: {exc}")
   else:
    if deal_rows:
     cycles=aggregate_position_cycles(deal_rows)
     if cycles:
      cycle_frame=pd.DataFrame(cycles)
      cycle_frame["حالة المركز"]=cycle_frame["state"].map({
       "CLOSED":"مغلق — سجل دورة مكتمل",
       "OPEN_FROM_CAPTURED_ENTRY":"مفتوح — من دخول مرصود",
       "INCOMPLETE_HISTORY":"سجل ناقص — لا يُستنتج الإغلاق",
      }).fillna("غير محدد")
      cycle_direction=(cycle_frame["entry_direction"] if "entry_direction" in cycle_frame.columns else cycle_frame["direction"])
      cycle_frame["الاتجاه"]=cycle_direction.map({
       "LONG":"شراء","SHORT":"بيع",
      }).fillna("غير محدد")
      cycle_columns={
       "position_id":"معرّف المركز","حالة المركز":"الحالة","الاتجاه":"الاتجاه",
       "opened_volume":"حجم الدخول","closed_deal_volume":"حجم الخروج",
       "remaining_signed_volume":"الحجم الصافي المتبقي",
       "realized_deal_profit":"ربح تنفيذات الخروج",
       "commission":"العمولة","swap":"المقايضة","fee":"الرسوم",
       "net_deal_cashflow":"صافي التدفق النقدي","currency":"العملة",
       "deal_count":"عدد التنفيذات",
      }
      st.subheader("دورات المراكز المستنتجة من سجل الوسيط")
      _safe_dataframe(
       cycle_frame.rename(columns=cycle_columns)[list(cycle_columns.values())].head(50),
       width="stretch",hide_index=True,
      )
      st.caption(f"عدد دورات المراكز في السجل المحفوظ: {len(cycles)} · عدد التنفيذات ضمن هذه الدورات: {sum(int(row.get('deal_count',0) or 0) for row in cycles)}. الدورة المغلقة تحتفظ باتجاه الدخول الأصلي؛ أما FLAT فيصف صافي الحجم بعد الإغلاق وليس اتجاه الصفقة.")
      st.caption("الدورة المفتوحة تعرض أرباح التنفيذات المحققة حتى الآن فقط ولا تشمل الربح العائم. السجل الذي يبدأ بخروج دون دخول مرصود يُعلّم كسجل ناقص ولا يُعرض كدورة مكتملة.")
     deal_frame=pd.DataFrame(deal_rows)
     deal_frame["أساس الوقت"]=deal_frame["time_basis"].map({"MT5_SERVER_TIME":"توقيت خادم MT5","LEGACY_UTC_NORMALIZED":"UTC — سجل قديم"}).fillna("غير محدد")
     deal_frame["وقت السجل"]=pd.to_datetime(deal_frame["time_server_ms"],unit="ms",errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
     deal_frame["نوع العملية"]=deal_frame["deal_type"].map({0:"شراء",1:"بيع",2:"رصيد",3:"ائتمان",4:"رسوم",5:"تصحيح",6:"مكافأة",7:"عمولة",8:"عمولة يومية",9:"عمولة شهرية",10:"عمولة وكيل",11:"فائدة",12:"شراء ملغى",13:"بيع ملغى",14:"توزيع",15:"توزيع معفى",16:"ضريبة"}).fillna("نوع آخر")
     deal_frame["نوع الدخول"]=deal_frame["deal_entry"].map({0:"دخول",1:"خروج",2:"عكس",3:"إغلاق مقابل"}).fillna("غير محدد")
     deal_frame["صافي التدفق"]=pd.to_numeric(deal_frame["net_cashflow"],errors="coerce")
     currency=str(deal_rows[0].get("currency") or (bridge.get("account") or {}).get("currency") or "عملة الحساب")
     total_net=float(deal_frame["صافي التدفق"].fillna(0).sum())
     st.metric(f"صافي التدفقات في السجل المحفوظ (حتى 1000 صفقة) — {currency}",f"{total_net:,.2f}")
     display_columns=["وقت السجل","أساس الوقت","deal_ticket","position_id","نوع العملية","نوع الدخول","volume","price","profit","commission","swap","fee","صافي التدفق","currency"]
     _safe_dataframe(deal_frame.sort_values("time_server_ms",ascending=False)[display_columns].head(50),width="stretch",hide_index=True)
     st.caption("يعرض الدفتر الصفقات المرتبطة برقم Magic الخاص بمرصاد والرمز المحدد فقط، ولا يضم الصفقات اليدوية أو مستشاري الخبراء الآخرين. يظهر أساس الوقت لكل صف، حتى لا تختلط سجلات UTC القديمة بأوقات خادم MT5 الجديدة.")
     if deal_meta.get("truncated"):
      st.warning("سجل الوسيط محدود من طرف MT5؛ المحصلة المعروضة تخص السجل المحفوظ فقط وليست ضماناً بأنها تشمل كامل التاريخ القديم.")
    else:
     st.caption("لا توجد صفقات Mirsad محفوظة لهذا الرمز ورقم Magic حتى الآن.")
  else:
   st.caption("سيظهر دفتر الصفقات بعد وصول نبضة MIR1 مكتملة تتضمن رمز الوسيط ورقم Magic.")

  decision=state.get("decision") if isinstance(state.get("decision"),dict) else {}
  st.subheader("المحرك الرابع — اتخاذ القرار ومتابعة الصفقات وإدارة المخاطر")
  d1,d2,d3,d4=st.columns(4)
  action=decision.get("action","WAIT")
  d1.metric("القرار",{"BUY":"شراء","SELL":"بيع","CLOSE":"إغلاق مركز معاكس","HOLD":"الاحتفاظ بالمركز","WAIT":"انتظار"}.get(action,action))
  d2.metric("الإشارة من السوق والتحليل",{"BUY":"شراء","SELL":"بيع","WAIT":"انتظار"}.get(decision.get("candidate_action"),"انتظار"))
  trend_score=decision.get("trend_score")
  d3.metric("اتجاه EMA للمحرك الثالث",f"{float(trend_score):+.3f}" if isinstance(trend_score,(int,float)) and math.isfinite(float(trend_score)) else "—",help="درجة اتجاه EMA الموزونة عبر الأطر في المحرك الثالث؛ ليست نسبة توافق بنية الأطر في المحرك الثاني.")
  d4.metric("جاهزية أمر الخبير","جاهز" if decision.get("command_ready") else "غير جاهز")
  engine2_context=decision.get("engine_2_native_price_action_context") if isinstance(decision.get("engine_2_native_price_action_context"),dict) else {}
  def _decision_fraction(value):
   try:
    number=float(value)
   except (TypeError,ValueError,OverflowError):
    return "—"
   return f"{number*100:.0f}%" if math.isfinite(number) and 0.0<=number<=1.0 else "—"
  e2a,e2b,e2c,e2d=st.columns(4)
  raw_structure_score=engine2_context.get("structure_score")
  e2a.metric("درجة بنية OHLC قبل بوابة الأهلية",f"{float(raw_structure_score):+.3f}" if isinstance(raw_structure_score,(int,float)) and math.isfinite(float(raw_structure_score)) else "—")
  e2b.metric("اتفاق الاتجاهات البنيوية المؤكدة — محرك 2",_decision_fraction(engine2_context.get("directional_structure_agreement")))
  e2c.metric("تغطية الأطر ذات الاتجاه المؤكد — محرك 2",_decision_fraction(engine2_context.get("directional_frame_coverage")))
  e2d.metric("تغطية أدلة بنية OHLC — محرك 2",_decision_fraction(engine2_context.get("directional_evidence_coverage")))
  st.caption("درجة OHLC الخام لا تدخل في الوزن الفعّال إلا بعد اجتياز بوابة الأهلية. نسبة الاتفاق تُحسب بين الأطر ذات الاتجاه المؤكد فقط؛ التغطية تقيس نسبتها من الأطر القابلة للتحليل، وجودة الأدلة تقيس اكتمال أدلة OHLC.")
  engine2_report=state.get("engine_2_price_action") if isinstance(state.get("engine_2_price_action"),dict) else {}
  watch=engine2_report.get("early_setup_watch") if isinstance(engine2_report.get("early_setup_watch"),dict) else {}
  watch_frames=watch.get("timeframes") if isinstance(watch.get("timeframes"),dict) else {}
  if watch.get("status") == "WATCH_ACTIVE" and watch_frames:
   watch_rows=[]
   for timeframe, item in watch_frames.items():
    if not isinstance(item,dict): continue
    side={"BEARISH":"\u0645\u0631\u0627\u0642\u0628\u0629 \u0628\u064a\u0639","BULLISH":"\u0645\u0631\u0627\u0642\u0628\u0629 \u0634\u0631\u0627\u0621","MIXED":"\u0645\u0631\u0627\u0642\u0628\u0629 \u0645\u062a\u0639\u0627\u0631\u0636\u0629"}.get(item.get("direction"),str(item.get("direction","?")))
    drop=item.get("sell_drop_pct"); rise=item.get("buy_rise_pct")
    move=(f"\u0647\u0628\u0648\u0637 {float(drop):.3f}%" if item.get("direction")=="BEARISH" and isinstance(drop,(int,float)) else f"\u0635\u0639\u0648\u062f {float(rise):.3f}%" if isinstance(rise,(int,float)) else "?")
    data_quality="\u0641\u062c\u0648\u0627\u062a \u0645\u0648\u062c\u0648\u062f\u0629" if item.get("material_gap_count",0) else "\u0628\u064a\u0627\u0646\u0627\u062a \u0645\u062a\u0635\u0644\u0629"
    timing="\u0627\u0646\u062a\u0638\u0627\u0631 \u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631" if item.get("entry_timing")=="WAIT_FOR_PULLBACK_OR_RETEST" else "\u0645\u0631\u0627\u0642\u0628\u0629 \u0627\u0644\u062a\u0623\u0643\u064a\u062f"
    age=item.get("setup_age_in_observed_bars")
    age_valid=isinstance(age,(int,float)) and math.isfinite(float(age)) and age>=0
    age_count=f"{int(age)} \u0634\u0645\u0639\u0629" if age_valid else "\u063a\u064a\u0631 \u0645\u062a\u0627\u062d"
    age_phase="\u062d\u062f\u064a\u062b\u0629" if age_valid and age<=3 else "\u0645\u0645\u062a\u062f\u0629" if age_valid else "\u063a\u064a\u0631 \u0645\u062d\u062f\u062f\u0629"
    age_label=f"{age_phase} \u00b7 {age_count}"
    support_label="\u0643\u0633\u0631 \u062f\u0639\u0645 \u0645\u0631\u0635\u0648\u062f" if item.get("support_break_observed") else "\u0644\u0627 \u064a\u0648\u062c\u062f \u0643\u0633\u0631 \u0645\u0624\u0643\u062f"
    watch_rows.append({"\u0627\u0644\u0625\u0637\u0627\u0631":timeframe,"\u0627\u0644\u0645\u0631\u0627\u0642\u0628\u0629":side,"\u0627\u0644\u062d\u0631\u0643\u0629":move,"\u0639\u0645\u0631 \u0627\u0644\u062d\u0631\u0643\u0629":age_label,"\u062f\u0644\u064a\u0644 \u0627\u0644\u0633\u0639\u0631":support_label,"\u062c\u0648\u062f\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a":data_quality,"\u0627\u0644\u062a\u0648\u062c\u064a\u0647":timing})
   st.warning("\u0645\u0631\u0627\u0642\u0628\u0629 \u0645\u0628\u0643\u0631\u0629 \u0644\u062d\u0631\u0643\u0629 \u0642\u0635\u064a\u0631\u0629 \u0627\u0644\u0623\u062c\u0644. \u0647\u0630\u0647 \u0645\u0644\u0627\u062d\u0638\u0629 \u0648\u0644\u064a\u0633\u062a \u0623\u0645\u0631 \u062a\u062f\u0627\u0648\u0644; \u0634\u0631\u0648\u0637 \u0627\u0644\u062a\u0646\u0641\u064a\u0630 \u0648\u0627\u0644\u0645\u062e\u0627\u0637\u0631 \u0645\u0633\u062a\u0642\u0644\u0629.")
   if watch_rows: _safe_dataframe(pd.DataFrame(watch_rows),width="stretch",hide_index=True)
  else:
   st.caption("\u0644\u0627 \u064a\u0648\u062c\u062f \u062d\u0627\u0644\u064a\u0627\u064b \u0625\u0639\u062f\u0627\u062f \u0642\u0635\u064a\u0631 \u0627\u0644\u0623\u062c\u0644 \u0642\u064a\u062f \u0627\u0644\u0645\u0631\u0627\u0642\u0628\u0629.")
  macro_gate=decision.get("macro_event_gate") if isinstance(decision.get("macro_event_gate"),dict) else {}
  active_macro_events=macro_gate.get("active_events") if isinstance(macro_gate.get("active_events"),list) else []
  m1,m2,m3=st.columns(3)
  m1.metric("حاجز الأحداث عالية الأهمية",ar(macro_gate.get("status","NOT_REPORTED")))
  m2.metric("المداخل الجديدة","متوقفة مؤقتاً" if macro_gate.get("new_entries_paused") else "غير محجوبة")
  m3.metric("رصدات الأحداث النشطة",len(active_macro_events))
  if active_macro_events:
   macro_rows=[]
   for event in active_macro_events:
    if not isinstance(event,dict): continue
    minutes=event.get("minutes_to_event")
    relative=(f"قبل {float(minutes):.1f} دقيقة" if float(minutes)>=0 else f"بعد {abs(float(minutes)):.1f} دقيقة") if isinstance(minutes,(int,float)) and math.isfinite(float(minutes)) else "وقت غير محدد"
    macro_rows.append({"الحدث":event.get("name","غير محدد"),"العملة":event.get("currency","—"),"المصدر":event.get("provider","—"),"وقت UTC":utc_ms_text(event.get("event_time_utc_ms")),"التوقيت النسبي":relative})
   if macro_rows: _safe_dataframe(pd.DataFrame(macro_rows),width="stretch",hide_index=True)
  if macro_gate.get("new_entries_paused"):
   st.caption("الحاجز يوقف فتح المراكز الجديدة خلال نافذة الحدث؛ تبقى أوامر الإغلاق وتحديثات الوقف الوقائي متاحة وفق ضوابط التنفيذ.")
  scores=decision.get("decision_scores") if isinstance(decision.get("decision_scores"),dict) else {}
  weights=decision.get("decision_weights") if isinstance(decision.get("decision_weights"),dict) else {}
  configured=weights.get("configured") if isinstance(weights.get("configured"),dict) else {}
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
   help="درجة بنية السعر من شموع MT5 الأصلية المكتملة فقط؛ الصور التشخيصية لا تدخل القرار.")
  s3.metric(f"المحرك 3 · {_weight_label('engine_3_indicators')}",
   _score_label(scores.get("engine_3_indicators")),
   help="المؤشرات المحسوبة من سجل الشموع المغلقة الذي يملكه المحرك الثاني.")
  s4.metric("النتيجة المركبة",_score_label(scores.get("combined_score")))
  def _configured_weight_text(name):
   value=configured.get(name)
   return f"{float(value)*100:.0f}%" if isinstance(value,(int,float)) else "غير وارد"
  base_weight_text="، ".join((
   f"المحرك 1 = {_configured_weight_text('engine_1_market_intelligence')}",
   f"المحرك 2 = {_configured_weight_text('engine_2_price_action')}",
   f"المحرك 3 = {_configured_weight_text('engine_3_indicators')}",
  ))
  st.caption("الأوزان الأساسية الفعلية الواردة من المحرك الرابع: "+base_weight_text+". تُعرض الأوزان الداخلية لأدلة OHLC في قسم المحرك الثاني؛ لا يوجد تصويت بصري.")
  e1,e2,e3,e4=st.columns(4)
  e1.metric("دخول مرجعي",f"{decision.get('entry_reference'):,.2f}" if decision.get("entry_reference") else "—")
  e2.metric("وقف الخسارة",f"{decision.get('stop_loss'):,.2f}" if decision.get("stop_loss") else "—")
  e3.metric("الهدف",f"{decision.get('take_profit'):,.2f}" if decision.get("take_profit") else "—")
  e4.metric("بوابة أهلية بنية السعر",ar(decision.get("engine_2_confluence_gate") or decision.get("chart_gate","NOT_REPORTED")))
  if decision.get("status") == "WAITING_FOR_ENGINE_2":
   gate_code = engine2_context.get("gate") or decision.get("engine_2_confluence_gate") or decision.get("chart_gate")
   gate_messages = {
    "MIXED_OR_NO_CONFLUENCE": "اتجاهات البنية المؤكدة بين الأطر ليست متوافقة بما يسمح بتصويت اتجاهي للمحرك الثاني.",
    "INSUFFICIENT_DIRECTIONAL_FRAME_COVERAGE": "عدد الأطر ذات الاتجاه البنيوي المؤكد أقل من الحد المطلوب.",
    "INSUFFICIENT_STRUCTURE_EVIDENCE_QUALITY": "جودة أو اكتمال أدلة بنية OHLC أقل من الحد المطلوب.",
    "CANDLE_PATTERN_DIRECTION_CONFLICT": "نمط الشموع الأخير يعارض اتجاه البنية البنيوية.",
    "MIXED_CANDLE_PATTERN_EVIDENCE": "أدلة نماذج الشموع الأخيرة متعارضة بين الأطر.",
   }
   pattern_code = engine2_context.get("latest_candle_pattern_alignment")
   pattern_message = {
    "MIXED_CANDLE_PATTERN_EVIDENCE": "أدلة نماذج الشموع متعارضة بين الأطر.",
    "BEARISH_CANDLE_PATTERN_EVIDENCE": "نماذج الشموع الأخيرة تميل للهبوط.",
    "BULLISH_CANDLE_PATTERN_EVIDENCE": "نماذج الشموع الأخيرة تميل للصعود.",
    "NO_DIRECTIONAL_CANDLE_PATTERN": "لا توجد نماذج شموع اتجاهية حديثة مؤكدة.",
   }.get(pattern_code, ar(pattern_code) if pattern_code else "لم يرد ملخص مستقل لنماذج الشموع.")
   st.warning("سبب انتظار المحرك الرابع: " + gate_messages.get(gate_code, ar(gate_code)) + " حالة نماذج الشموع: " + pattern_message)
  q1,q2,q3,q4=st.columns(4)
  divergence=decision.get("broker_market_price_divergence_pct")
  spread=decision.get("broker_spread_pct")
  quote=decision.get("broker_quote") or {}
  q1.metric("فرق سعر MT5 عن السوق",f"{divergence:.3f}%" if divergence is not None else "—")
  q2.metric("سبريد جسر تنفيذ MT5",f"{spread:.3f}%" if spread is not None else "—")
  q3.metric("عمر سعر الوسيط",f"{quote.get('tick_age_seconds')} ثانية" if quote.get("tick_age_seconds") is not None else "—")
  q4.metric("رمز الوسيط",bridge.get("symbol") or "—")
  risk=decision.get("risk_plan")
  if isinstance(risk,dict):
   st.write("حساب المخاطر وحجم المركز داخل البرنامج:",ar(risk.get("status","NOT_REPORTED")))
   if risk.get("volume") is not None:
    st.write(f"الحجم: {risk['volume']} | ميزانية المخاطرة: {risk.get('risk_cash')} | خسارة السعر: {risk.get('estimated_stop_loss')} | العمولة: {risk.get('estimated_commission')} | الإجمالي مع العمولة: {risk.get('estimated_loss')}")
   st.caption(risk.get("reason") or decision.get("open_block_reason") or "")
  else:
   st.write("حساب المخاطر وحجم المركز داخل البرنامج:","لم يبدأ — لا توجد إشارة دخول مؤهلة")
   if action in {"BUY","SELL"}:
    st.error("خطة المخاطر غير متاحة؛ لن يُمرّر أمر دخول قبل اكتمالها.")
   st.caption(decision.get("open_block_reason") or "تُحسب الكمية والمخاطرة بعد اجتياز بوابة الاتجاه وتوافر سعر MT5 ومواصفات الرمز.")
  publication=state.get("command_publish") if isinstance(state.get("command_publish"),dict) else {}
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
 with st.expander("قواعد وضوابط النظام"):
  st.write("المحرك 1 يجمع استخبارات السوق والتقويمات العامة والأخبار والمشتقات بصورة مستقلة. المحرك 2 يحلل شموع OHLC الأصلية والقمم والقيعان وكسر البنية ونماذج الشموع والسيولة. المحرك 3 يحسب المؤشرات من الشموع المغلقة للمحرك الثاني. المحرك 4 يدمج الأوزان الأساسية 20/55/25 (المحرك 1/2/3) ويتخذ القرار ويدير المخاطر والمراكز. المحرك 5 يملك تغذية سعر الوسيط وجسر MIR1 وسجل صفقات Mirsad.")
  st.write("لا يستخدم مرصاد نموذجاً توليدياً لاتخاذ قرار التداول؛ يعتمد التحليل على بيانات السوق والشموع والمؤشرات الأصلية وقواعد قابلة للفحص.")

 st.divider()
 st.subheader("تقرير الإنجاز والتدقيق التفصيلي")
 report_path=Path(__file__).resolve().parent/"reports"/"MIRSAD_PROGRESS_REPORT_AR_20261102.md"
 with st.expander("الأرشيف التاريخي لتقرير مرصاد — 2 نوفمبر 2026",expanded=False):
  if report_path.is_file():
   report_text=report_path.read_text(encoding="utf-8")
   st.info("هذه نسخة مؤرخة من سجل التقدم السابق، وليست تقرير الحالة الحية للبرنامج.")
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





def _simple_number(value, digits=2, suffix=""):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "\u063a\u064a\u0631 \u0645\u062a\u0627\u062d"
    if not math.isfinite(number):
        return "\u063a\u064a\u0631 \u0645\u062a\u0627\u062d"
    return f"{number:,.{digits}f}{suffix}"


def _simple_direction_score(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "\u063a\u064a\u0631 \u0645\u062a\u0627\u062d"
    if not math.isfinite(number):
        return "\u063a\u064a\u0631 \u0645\u062a\u0627\u062d"
    if number <= -0.15:
        direction = "\u0645\u064a\u0644 \u0647\u0627\u0628\u0637"
    elif number >= 0.15:
        direction = "\u0645\u064a\u0644 \u0635\u0627\u0639\u062f"
    else:
        direction = "\u0645\u062d\u0627\u064a\u062f"
    return f"{number:+.2f} \u2014 {direction}"


def render_simple_dashboard():
    state = read_json(STATUS_PATH, {})
    state = state if isinstance(state, dict) else {}
    market = read_json(SNAPSHOT_PATH, {})
    market = market if isinstance(market, dict) else {}

    st.title("\u20bf \u0645\u0631\u0635\u0627\u062f \u0627\u0644\u0628\u064a\u062a\u0643\u0648\u064a\u0646")
    st.caption("\u0644\u0648\u062d\u0629 \u0645\u0628\u0633\u0637\u0629 \u0644\u0645\u062a\u0627\u0628\u0639\u0629 \u062d\u0627\u0644\u0629 \u0627\u0644\u0645\u062d\u0631\u0643\u0627\u062a \u0648\u0642\u0631\u0627\u0631 \u0627\u0644\u062a\u062f\u0627\u0648\u0644 \u0648\u0627\u0644\u0635\u0641\u0642\u0627\u062a \u0648\u062d\u0645\u0627\u064a\u0629 \u0627\u0644\u062d\u0633\u0627\u0628.")

    if not state:
        st.error("\u0644\u0645 \u062a\u0635\u0644 \u0628\u064a\u0627\u0646\u0627\u062a \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0645\u0631\u0635\u0627\u062f \u0628\u0639\u062f. \u062a\u0623\u0643\u062f \u0645\u0646 \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0628\u0631\u0646\u0627\u0645\u062c.")
        return

    overall = str(state.get("overall_status") or "PARTIAL_OR_WAITING").upper()
    if overall == "FULLY_OPERATIONAL":
        st.success("\u0627\u0644\u0628\u0631\u0646\u0627\u0645\u062c \u064a\u0639\u0645\u0644\u061b \u0641\u062a\u062d \u0627\u0644\u0635\u0641\u0642\u0627\u062a \u0645\u0634\u0631\u0648\u0637 \u0628\u062a\u062d\u0642\u0642 \u0627\u0644\u0625\u0634\u0627\u0631\u0629 \u0648\u062c\u0645\u064a\u0639 \u0636\u0648\u0627\u0628\u0637 \u0627\u0644\u062d\u0645\u0627\u064a\u0629.")
    elif overall == "ERROR":
        st.error("\u062d\u062f\u062b \u062e\u0637\u0623 \u0641\u064a \u062f\u0648\u0631\u0629 \u0627\u0644\u062a\u0634\u063a\u064a\u0644. \u0631\u0627\u062c\u0639 \u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0641\u0646\u064a\u0629 \u0642\u0628\u0644 \u0627\u0644\u0627\u0639\u062a\u0645\u0627\u062f \u0639\u0644\u0649 \u0627\u0644\u062d\u0627\u0644\u0629.")
    else:
        st.warning("\u0627\u0644\u0628\u0631\u0646\u0627\u0645\u062c \u064a\u0639\u0645\u0644\u060c \u0644\u0643\u0646 \u062a\u0648\u062c\u062f \u0634\u0631\u0648\u0637 \u0623\u0648 \u0627\u062a\u0635\u0627\u0644\u0627\u062a \u062a\u0646\u062a\u0638\u0631 \u0627\u0644\u0627\u0643\u062a\u0645\u0627\u0644. \u0644\u0627 \u064a\u0639\u0646\u064a \u0630\u0644\u0643 \u0648\u062c\u0648\u062f \u0625\u0634\u0627\u0631\u0629 \u062f\u062e\u0648\u0644.")
    st.caption(age_text(state.get("heartbeat_at_ms")))

    engines = state.get("engines") if isinstance(state.get("engines"), dict) else {}
    engine_items = [
        ("\u0627\u0644\u0645\u062d\u0631\u0643 1 \u00b7 \u0627\u0633\u062a\u062e\u0628\u0627\u0631\u0627\u062a \u0627\u0644\u0633\u0648\u0642", "engine_1_market_intelligence"),
        ("\u0627\u0644\u0645\u062d\u0631\u0643 2 \u00b7 \u062d\u0631\u0643\u0629 \u0627\u0644\u0633\u0639\u0631", "engine_2_price_action"),
        ("\u0627\u0644\u0645\u062d\u0631\u0643 3 \u00b7 \u0627\u0644\u0645\u0624\u0634\u0631\u0627\u062a", "engine_3_indicators"),
        ("\u0627\u0644\u0645\u062d\u0631\u0643 4 \u00b7 \u0627\u0644\u0642\u0631\u0627\u0631", "engine_4_decision"),
        ("\u0627\u0644\u0645\u062d\u0631\u0643 5 \u00b7 \u0627\u062a\u0635\u0627\u0644 MT5", "engine_5_communication_bridge"),
    ]
    engine_translation = {
        "READY": "\u062c\u0627\u0647\u0632",
        "CONNECTED": "\u0645\u062a\u0635\u0644",
        "LIVE": "\u0628\u064a\u0627\u0646\u0627\u062a \u062d\u064a\u0629",
        "WAITING_FOR_ENGINE_2": "\u064a\u0646\u062a\u0638\u0631 \u062a\u0648\u0627\u0641\u0642 \u0627\u0644\u0633\u0639\u0631",
        "LOCKED": "\u0627\u0644\u062d\u0645\u0627\u064a\u0629 \u0645\u0641\u0639\u0651\u0644\u0629",
        "WAIT": "\u0627\u0646\u062a\u0638\u0627\u0631",
        "NOT_STARTED": "\u0644\u0645 \u064a\u0628\u062f\u0623",
        "PARTIAL": "\u062c\u0632\u0626\u064a",
        "ERROR": "\u062e\u0637\u0623",
    }
    columns = st.columns(5)
    for col, (label, key) in zip(columns, engine_items):
        value = engines.get(key)
        if key == "engine_5_communication_bridge" and value is None:
            value = engines.get("engine_3_mt5_bridge", engines.get("engine_5_mt5_bridge"))
        shown = engine_translation.get(str(value or "NOT_REPORTED").upper(), ar(value or "NOT_REPORTED"))
        with col:
            st.metric(label, shown)

    st.divider()
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    bridge = state.get("bridge") if isinstance(state.get("bridge"), dict) else {}
    daily = state.get("daily_risk") if isinstance(state.get("daily_risk"), dict) else {}
    account = bridge.get("account") if isinstance(bridge.get("account"), dict) else {}
    positions = bridge.get("positions") if isinstance(bridge.get("positions"), list) else []
    quote = bridge.get("quote") if isinstance(bridge.get("quote"), dict) else {}

    action = str(decision.get("action") or "WAIT").upper()
    action_label = {
        "BUY": "\u0634\u0631\u0627\u0621",
        "SELL": "\u0628\u064a\u0639",
        "CLOSE": "\u0625\u063a\u0644\u0627\u0642",
        "MODIFY": "\u062a\u0639\u062f\u064a\u0644 \u0627\u0644\u0648\u0642\u0641 \u0623\u0648 \u0627\u0644\u0647\u062f\u0641",
        "HOLD": "\u0627\u0644\u0627\u062d\u062a\u0641\u0627\u0638 \u0628\u0627\u0644\u0635\u0641\u0642\u0629",
        "WAIT": "\u0627\u0646\u062a\u0638\u0627\u0631",
    }.get(action, action)
    context = decision.get("engine_2_native_price_action_context")
    context = context if isinstance(context, dict) else {}
    gate = str(context.get("gate") or decision.get("engine_2_confluence_gate") or decision.get("chart_gate") or "").upper()
    wait_explanations = {
        "CANDLE_PATTERN_DIRECTION_CONFLICT": "\u0646\u0645\u0648\u0630\u062c \u0627\u0644\u0634\u0645\u0648\u0639 \u0627\u0644\u0623\u062e\u064a\u0631 \u0644\u0627 \u064a\u062a\u0641\u0642 \u0645\u0639 \u0627\u062a\u062c\u0627\u0647 \u0628\u0646\u064a\u0629 \u0627\u0644\u0633\u0639\u0631\u061b \u0644\u0630\u0644\u0643 \u064a\u0646\u062a\u0638\u0631 \u0627\u0644\u0645\u0631\u0635\u0627\u062f \u0648\u0644\u0627 \u064a\u0641\u062a\u062d \u0635\u0641\u0642\u0629 \u062c\u062f\u064a\u062f\u0629.",
        "MIXED_CANDLE_PATTERN_EVIDENCE": "\u0623\u062f\u0644\u0629 \u0646\u0645\u0627\u0630\u062c \u0627\u0644\u0634\u0645\u0648\u0639 \u0645\u062a\u0639\u0627\u0631\u0636\u0629\u061b \u064a\u0646\u062a\u0638\u0631 \u0627\u0644\u0645\u0631\u0635\u0627\u062f \u062d\u062a\u0649 \u062a\u062a\u0636\u062d \u0627\u0644\u0625\u0634\u0627\u0631\u0629.",
        "MIXED_OR_NO_CONFLUENCE": "\u0627\u0644\u0623\u0637\u0631 \u0627\u0644\u0632\u0645\u0646\u064a\u0629 \u0644\u0627 \u062a\u0642\u062f\u0645 \u062a\u0648\u0627\u0641\u0642\u0627\u064b \u0643\u0627\u0641\u064a\u0627\u064b \u0641\u064a \u062d\u0631\u0643\u0629 \u0627\u0644\u0633\u0639\u0631.",
        "INSUFFICIENT_DIRECTIONAL_FRAME_COVERAGE": "\u0639\u062f\u062f \u0627\u0644\u0623\u0637\u0631 \u0627\u0644\u0632\u0645\u0646\u064a\u0629 \u0630\u0627\u062a \u0627\u0644\u0627\u062a\u062c\u0627\u0647 \u0627\u0644\u0645\u0624\u0643\u062f \u063a\u064a\u0631 \u0643\u0627\u0641\u064d.",
        "INSUFFICIENT_STRUCTURE_EVIDENCE_QUALITY": "\u0627\u0643\u062a\u0645\u0627\u0644 \u0623\u062f\u0644\u0629 \u062d\u0631\u0643\u0629 \u0627\u0644\u0633\u0639\u0631 \u0623\u0648 \u062c\u0648\u062f\u062a\u0647\u0627 \u063a\u064a\u0631 \u0643\u0627\u0641\u064d \u0644\u0644\u062f\u062e\u0648\u0644.",
        "WAITING_FOR_ENGINE_2": "\u0627\u0644\u0645\u062d\u0631\u0643 \u0627\u0644\u0631\u0627\u0628\u0639 \u064a\u0646\u062a\u0638\u0631 \u062a\u0623\u0643\u064a\u062f \u062d\u0631\u0643\u0629 \u0627\u0644\u0633\u0639\u0631 \u0645\u0646 \u0627\u0644\u0645\u062d\u0631\u0643 \u0627\u0644\u062b\u0627\u0646\u064a.",
        "WAITING_FOR_ENGINE_3_QUOTE": "\u064a\u0646\u062a\u0638\u0631 \u0627\u0644\u0645\u0631\u0635\u0627\u062f \u0633\u0639\u0631\u0627\u064b \u062d\u062f\u064a\u062b\u0627\u064b \u0645\u0646 MT5 \u0642\u0628\u0644 \u0627\u0639\u062a\u0645\u0627\u062f \u0627\u0644\u0642\u0631\u0627\u0631.",
        "WAITING_FOR_ENGINE_5_QUOTE": "\u064a\u0646\u062a\u0638\u0631 \u0627\u0644\u0645\u0631\u0635\u0627\u062f \u0633\u0639\u0631\u0627\u064b \u062d\u064a\u0627\u064b \u0648\u0645\u0648\u0627\u0635\u0641\u0627\u062a \u0627\u0644\u0631\u0645\u0632 \u0645\u0646 MT5.",
    }


    if action == "WAIT":
        decision_message = wait_explanations.get(gate, "\u0644\u0627 \u062a\u0648\u062c\u062f \u062d\u0627\u0644\u064a\u0627\u064b \u0625\u0634\u0627\u0631\u0629 \u062f\u062e\u0648\u0644 \u0627\u062c\u062a\u0627\u0632\u062a \u062c\u0645\u064a\u0639 \u0634\u0631\u0648\u0637 \u0645\u0631\u0635\u0627\u062f. \u0627\u0644\u0627\u0646\u062a\u0638\u0627\u0631 \u0642\u0631\u0627\u0631 \u0645\u0642\u0635\u0648\u062f \u0644\u062d\u0645\u0627\u064a\u0629 \u0627\u0644\u062d\u0633\u0627\u0628.")
        decision_tag = "\u0644\u0627 \u064a\u0648\u062c\u062f \u0623\u0645\u0631 \u062c\u062f\u064a\u062f \u062c\u0627\u0647\u0632"
    elif action in {"BUY", "SELL"}:
        decision_message = "\u0635\u062f\u0631\u062a \u0625\u0634\u0627\u0631\u0629 \u062f\u062e\u0648\u0644. \u064a\u062c\u0628 \u0623\u0646 \u062a\u062c\u062a\u0627\u0632 \u0628\u0648\u0627\u0628\u0627\u062a \u0627\u0644\u0645\u062e\u0627\u0637\u0631 \u0648\u0627\u0644\u062a\u0646\u0641\u064a\u0630 \u0642\u0628\u0644 \u0625\u0631\u0633\u0627\u0644\u0647\u0627 \u0644\u0640 MT5."
        decision_tag = "\u0625\u0634\u0627\u0631\u0629 \u062a\u062d\u062a\u0627\u062c \u0644\u0644\u062a\u062d\u0642\u0642 \u0645\u0646 \u062c\u0627\u0647\u0632\u064a\u0629 \u0627\u0644\u062a\u0646\u0641\u064a\u0630"
    elif action in {"CLOSE", "MODIFY"}:
        decision_message = "\u0647\u0646\u0627\u0643 \u0625\u062c\u0631\u0627\u0621 \u0644\u0625\u062f\u0627\u0631\u0629 \u0645\u0631\u0643\u0632 \u0642\u0627\u0626\u0645."
        decision_tag = "\u0625\u062f\u0627\u0631\u0629 \u0645\u0631\u0643\u0632"
    else:
        decision_message = "\u0644\u0627 \u064a\u0648\u062c\u062f \u0625\u062c\u0631\u0627\u0621 \u062c\u062f\u064a\u062f \u0645\u0637\u0644\u0648\u0628 \u062d\u0627\u0644\u064a\u0627\u064b."
        decision_tag = "\u0645\u0631\u0627\u0642\u0628\u0629"

    safe_action = html.escape(action_label, quote=True)
    safe_message = html.escape(decision_message, quote=True)
    safe_tag = html.escape(decision_tag, quote=True)
    st.markdown(
        f"""
        <section class="mirsad-simple-decision">
          <div class="decision-eyebrow">\u0642\u0631\u0627\u0631 \u0627\u0644\u0645\u062d\u0631\u0643 \u0627\u0644\u0631\u0627\u0628\u0639 \u0627\u0644\u0622\u0646</div>
          <span class="decision-tag">{safe_tag}</span>
          <div class="decision-value">{safe_action}</div>
          <div class="decision-reason">{safe_message}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    scores = decision.get("decision_scores") if isinstance(decision.get("decision_scores"), dict) else {}
    intelligence = state.get("market_intelligence") if isinstance(state.get("market_intelligence"), dict) else {}
    price_action = state.get("engine_2_price_action") if isinstance(state.get("engine_2_price_action"), dict) else {}
    indicators = state.get("indicators") if isinstance(state.get("indicators"), dict) else {}
    score_rows = [
        {"\u0627\u0644\u0645\u062d\u0631\u0643": "1 \u00b7 \u0627\u0633\u062a\u062e\u0628\u0627\u0631\u0627\u062a \u0627\u0644\u0633\u0648\u0642", "\u062f\u0631\u062c\u0629 \u0627\u0644\u0627\u062a\u062c\u0627\u0647": _simple_direction_score(scores.get("engine_1_market_intelligence", intelligence.get("directional_score"))), "\u0627\u0644\u0645\u0639\u0646\u0649": "\u0627\u0644\u0623\u062e\u0628\u0627\u0631 \u0648\u0627\u0644\u0645\u0634\u062a\u0642\u0627\u062a \u0648\u0627\u0644\u0633\u064a\u0627\u0642 \u0627\u0644\u0639\u0627\u0645"},
        {"\u0627\u0644\u0645\u062d\u0631\u0643": "2 \u00b7 \u0628\u0646\u064a\u0629 \u0627\u0644\u0633\u0639\u0631", "\u062f\u0631\u062c\u0629 \u0627\u0644\u0627\u062a\u062c\u0627\u0647": _simple_direction_score(scores.get("engine_2_native_ohlc_score", price_action.get("structure_score"))), "\u0627\u0644\u0645\u0639\u0646\u0649": "\u0645\u064a\u0644 \u0628\u0646\u064a\u0629 \u0627\u0644\u0634\u0645\u0648\u0639 \u0642\u0628\u0644 \u0628\u0648\u0627\u0628\u0629 \u0627\u0644\u062f\u062e\u0648\u0644"},
        {"\u0627\u0644\u0645\u062d\u0631\u0643": "3 \u00b7 \u0627\u0644\u0645\u0624\u0634\u0631\u0627\u062a", "\u062f\u0631\u062c\u0629 \u0627\u0644\u0627\u062a\u062c\u0627\u0647": _simple_direction_score(scores.get("engine_3_indicators", indicators.get("signal_score"))), "\u0627\u0644\u0645\u0639\u0646\u0649": "\u0645\u064a\u0644 \u0627\u0644\u0645\u0624\u0634\u0631\u0627\u062a \u0627\u0644\u0645\u062d\u0633\u0648\u0628\u0629 \u0645\u0646 \u0627\u0644\u0634\u0645\u0648\u0639"},
    ]
    with st.expander("\u0634\u0631\u062d \u062f\u0631\u062c\u0627\u062a \u0627\u0644\u0645\u062d\u0631\u0643\u0627\u062a \u0648\u0627\u0644\u0623\u0631\u0642\u0627\u0645 \u0627\u0644\u0633\u0627\u0644\u0628\u0629", expanded=False):
        _safe_dataframe(pd.DataFrame(score_rows), width="stretch", hide_index=True)
        st.info("\u0627\u0644\u0633\u0627\u0644\u0628 \u0641\u064a \u062f\u0631\u062c\u0629 \u0627\u0644\u0645\u062d\u0631\u0643 \u064a\u0639\u0646\u064a \u0645\u064a\u0644\u0627\u064b \u0647\u0627\u0628\u0637\u0627\u064b\u060c \u0648\u0627\u0644\u0645\u0648\u062c\u0628 \u064a\u0639\u0646\u064a \u0645\u064a\u0644\u0627\u064b \u0635\u0627\u0639\u062f\u0627\u064b\u060c \u0648\u0627\u0644\u0642\u0631\u064a\u0628 \u0645\u0646 \u0627\u0644\u0635\u0641\u0631 \u064a\u0639\u0646\u064a \u062d\u064a\u0627\u062f\u0627\u064b. \u0647\u0630\u0647 \u062f\u0631\u062c\u0627\u062a \u062a\u062d\u0644\u064a\u0644 \u0648\u0644\u064a\u0633\u062a \u062f\u0648\u0644\u0627\u0631\u0627\u062a \u0623\u0648 \u0646\u0633\u0628 \u0646\u062c\u0627\u062d \u0623\u0648 \u0627\u062d\u062a\u0645\u0627\u0644\u0627\u062a \u0631\u0628\u062d. \u0644\u0627 \u064a\u0635\u062f\u0631 \u0627\u0644\u0645\u0631\u0635\u0627\u062f \u0623\u0645\u0631 \u0634\u0631\u0627\u0621 \u0623\u0648 \u0628\u064a\u0639 \u0625\u0644\u0627 \u0628\u0639\u062f \u0627\u062c\u062a\u064a\u0627\u0632 \u0628\u0648\u0627\u0628\u0627\u062a \u0627\u0644\u0623\u0647\u0644\u064a\u0629.")

    st.divider()
    st.subheader("\u0627\u0644\u0635\u0641\u0642\u0627\u062a \u0627\u0644\u0645\u0641\u062a\u0648\u062d\u0629 \u0627\u0644\u0622\u0646")
    currency = str(account.get("currency") or "USD")
    if positions:
        position_rows = []
        floating_by_currency = {}
        for position in positions:
            if not isinstance(position, dict):
                continue
            position_currency = str(position.get("profit_currency") or currency)
            try:
                floating = float(position.get("profit", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                floating = float("nan")
            if math.isfinite(floating):
                floating_by_currency[position_currency] = floating_by_currency.get(position_currency, 0.0) + floating
            raw_type = position.get("type", position.get("direction", ""))
            side = "\u0634\u0631\u0627\u0621" if raw_type in (0, "0", "BUY", "LONG") else "\u0628\u064a\u0639" if raw_type in (1, "1", "SELL", "SHORT") else str(raw_type or "\u063a\u064a\u0631 \u0645\u062d\u062f\u062f")
            position_rows.append({
                "\u0627\u0644\u0627\u062a\u062c\u0627\u0647": side,
                "\u0627\u0644\u062d\u062c\u0645": position.get("volume", "\u2014"),
                "\u0633\u0639\u0631 \u0627\u0644\u062f\u062e\u0648\u0644": _simple_number(position.get("price_open")),
                "\u0648\u0642\u0641 \u0627\u0644\u062e\u0633\u0627\u0631\u0629": _simple_number(position.get("stop_loss")),
                "\u0627\u0644\u0647\u062f\u0641": _simple_number(position.get("take_profit")),
                "\u0627\u0644\u0631\u0628\u062d \u0623\u0648 \u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u0639\u0627\u0626\u0645\u0629": f"{floating:+.2f} {position_currency}" if math.isfinite(floating) else "\u063a\u064a\u0631 \u0645\u062a\u0627\u062d",
                "\u0631\u0642\u0645 \u0627\u0644\u0645\u0631\u0643\u0632": position.get("ticket", position.get("position_id", "\u2014")),
            })
        position_cols = st.columns(3)
        position_cols[0].metric("\u0639\u062f\u062f \u0645\u0631\u0627\u0643\u0632 \u0645\u0631\u0635\u0627\u062f \u0627\u0644\u0645\u0641\u062a\u0648\u062d\u0629", len(position_rows))
        for index, (ccy, total) in enumerate(sorted(floating_by_currency.items())[:2]):
            position_cols[index + 1].metric(f"\u0627\u0644\u0631\u0628\u062d \u0623\u0648 \u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u0639\u0627\u0626\u0645\u0629 \u00b7 {ccy}", f"{total:+,.2f}", help="\u0646\u062a\u064a\u062c\u0629 \u063a\u064a\u0631 \u0645\u062d\u0642\u0642\u0629 \u062a\u062a\u063a\u064a\u0631 \u0645\u0639 \u0627\u0644\u0633\u0648\u0642 \u062d\u062a\u0649 \u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u0645\u0631\u0643\u0632.")
        _safe_dataframe(pd.DataFrame(position_rows), width="stretch", hide_index=True)
        st.caption("\u0627\u0644\u0633\u0627\u0644\u0628 \u0647\u0646\u0627 \u064a\u0639\u0646\u064a \u062e\u0633\u0627\u0631\u0629 \u0639\u0627\u0626\u0645\u0629 \u062d\u0627\u0644\u064a\u0629\u060c \u0648\u0627\u0644\u0645\u0648\u062c\u0628 \u064a\u0639\u0646\u064a \u0631\u0628\u062d\u0627\u064b \u0639\u0627\u0626\u0645\u0627\u064b. \u0647\u0630\u0647 \u0627\u0644\u0646\u062a\u064a\u062c\u0629 \u062a\u062a\u063a\u064a\u0631 \u0645\u0639 \u062d\u0631\u0643\u0629 \u0627\u0644\u0633\u0648\u0642 \u0648\u0644\u064a\u0633\u062a \u0646\u0647\u0627\u0626\u064a\u0629.")
    else:
        st.info("\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0631\u0627\u0643\u0632 \u0645\u0641\u062a\u0648\u062d\u0629 \u0645\u0633\u062c\u0644\u0629 \u0628\u0627\u0633\u0645 \u0645\u0631\u0635\u0627\u062f \u062d\u0627\u0644\u064a\u0627\u064b.")

    st.subheader("\u0645\u0644\u062e\u0635 \u0627\u0644\u062d\u0633\u0627\u0628")
    account_cols = st.columns(3)
    account_cols[0].metric("\u0631\u0635\u064a\u062f \u0627\u0644\u062d\u0633\u0627\u0628", f"{_simple_number(account.get('balance'))} {currency}")
    account_cols[1].metric("\u0642\u064a\u0645\u0629 \u0627\u0644\u062d\u0633\u0627\u0628 \u0627\u0644\u062d\u0627\u0644\u064a\u0629", f"{_simple_number(account.get('equity'))} {currency}")
    account_cols[2].metric("\u0627\u0644\u0647\u0627\u0645\u0634 \u0627\u0644\u062d\u0631", f"{_simple_number(account.get('free_margin'))} {currency}")
    if quote:
        st.caption(f"سعر MT5 الحالي: Bid {_simple_number(quote.get('bid'))} · Ask {_simple_number(quote.get('ask'))} · عمر آخر سعر: {_simple_number(quote.get('tick_age_seconds'), 1)} ثانية")

    st.divider()
    st.subheader("\u062d\u0645\u0627\u064a\u0629 \u0627\u0644\u062d\u0633\u0627\u0628 \u2014 \u062d\u062f \u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u064a\u0648\u0645\u064a\u0629")
    daily_fraction = daily.get("max_daily_loss_fraction", MAX_DAILY_LOSS_FRACTION)
    try:
        limit_pct = float(daily_fraction) * 100.0
    except (TypeError, ValueError, OverflowError):
        limit_pct = MAX_DAILY_LOSS_FRACTION * 100.0
    risk_cols = st.columns(3)
    risk_cols[0].metric("\u062d\u062f \u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u064a\u0648\u0645\u064a", f"{limit_pct:.0f}%")
    risk_cols[1].metric("\u0627\u0644\u062d\u0645\u0627\u064a\u0629 \u0645\u0641\u0639\u0651\u0644\u0629", "\u0646\u0639\u0645" if daily.get("enabled", DAILY_LOSS_LIMIT_ENABLED) else "\u0644\u0627")
    recorded_loss = daily.get("daily_loss_fraction")
    if isinstance(recorded_loss, (int, float)) and math.isfinite(float(recorded_loss)):
        loss_label = f"{float(recorded_loss) * 100:.2f}%"
    else:
        loss_label = "\u0644\u0645 \u064a\u064f\u062d\u0633\u0628 \u0628\u0639\u062f"
    risk_cols[2].metric("\u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u064a\u0648\u0645\u064a\u0629 \u0627\u0644\u0645\u0633\u062c\u0644\u0629", loss_label)

    if daily.get("baseline_pending") or daily.get("status") == "BASELINE_UNAVAILABLE":
        st.warning("\u062d\u062f \u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u064a\u0648\u0645\u064a 20% \u0645\u0641\u0639\u0651\u0644\u060c \u0644\u0643\u0646 \u0642\u064a\u0645\u0629 \u0627\u0644\u062d\u0633\u0627\u0628 \u0639\u0646\u062f \u0628\u062f\u0627\u064a\u0629 \u0627\u0644\u064a\u0648\u0645 \u0644\u0645 \u062a\u064f\u0633\u062c\u0651\u0644 \u0628\u0635\u0648\u0631\u0629 \u0645\u0648\u062b\u0648\u0642\u0629 \u0628\u0639\u062f. \u0644\u0630\u0644\u0643 \u064a\u0645\u0646\u0639 \u0627\u0644\u0628\u0631\u0646\u0627\u0645\u062c \u0641\u062a\u062d \u0635\u0641\u0642\u0627\u062a \u062c\u062f\u064a\u062f\u0629 \u0645\u0624\u0642\u062a\u0627\u064b \u062d\u062a\u0649 \u0628\u062f\u0627\u064a\u0629 \u064a\u0648\u0645 UTC \u0627\u0644\u062a\u0627\u0644\u064a. \u0647\u0630\u0627 \u0644\u0627 \u064a\u0639\u0646\u064a \u0623\u0646\u0643 \u062e\u0633\u0631\u062a 20%.")
    elif daily.get("new_entries_blocked") or daily.get("locked"):
        st.warning("\u0627\u0644\u062d\u0645\u0627\u064a\u0629 \u062a\u0645\u0646\u0639 \u0641\u062a\u062d \u0635\u0641\u0642\u0627\u062a \u062c\u062f\u064a\u062f\u0629 \u062d\u0627\u0644\u064a\u0627\u064b. \u0631\u0627\u062c\u0639 \u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0641\u0646\u064a\u0629 \u0644\u0645\u0639\u0631\u0641\u0629 \u0627\u0644\u0633\u0628\u0628.")
    elif daily.get("enabled"):
        st.success("\u062d\u0645\u0627\u064a\u0629 \u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u064a\u0648\u0645\u064a\u0629 \u0645\u0641\u0639\u0651\u0644\u0629 \u0648\u062e\u0637 \u0627\u0644\u0623\u0633\u0627\u0633 \u0627\u0644\u064a\u0648\u0645\u064a \u0645\u062a\u0648\u0641\u0631.")
    else:
        st.error("\u062a\u0646\u0628\u064a\u0647: \u062d\u062f \u0627\u0644\u062e\u0633\u0627\u0631\u0629 \u0627\u0644\u064a\u0648\u0645\u064a\u0629 \u063a\u064a\u0631 \u0645\u0641\u0639\u0651\u0644.")

    with st.expander("\u0623\u062f\u0648\u0627\u062a \u0627\u0644\u062a\u062d\u0643\u0645 \u0648\u0627\u0644\u062a\u0646\u0641\u064a\u0630 \u0641\u064a MT5", expanded=False):
        st.caption("\u0647\u0630\u0647 \u0627\u0644\u0623\u062f\u0648\u0627\u062a \u0644\u0627 \u062a\u0646\u0634\u0626 \u0642\u0631\u0627\u0631\u0627\u064b \u062c\u062f\u064a\u062f\u0627\u064b\u061b \u062a\u0639\u0631\u0636 \u0642\u0631\u0627\u0631 \u0627\u0644\u0645\u062d\u0631\u0643 \u0627\u0644\u0631\u0627\u0628\u0639 \u0648\u062a\u062a\u064a\u062d \u062a\u0623\u0643\u064a\u062f \u062a\u0645\u0631\u064a\u0631\u0647 \u0628\u0639\u062f \u0627\u062c\u062a\u064a\u0627\u0632 \u0628\u0648\u0627\u0628\u0627\u062a \u0627\u0644\u062a\u0646\u0641\u064a\u0630.")
        render_execution_console(state)


def render_engine_dashboard():
    view = st.radio(
        "\u0637\u0631\u064a\u0642\u0629 \u0639\u0631\u0636 \u0627\u0644\u0644\u0648\u062d\u0629",
        ["\u0627\u0644\u0648\u0627\u062c\u0647\u0629 \u0627\u0644\u0645\u0628\u0633\u0637\u0629", "\u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0641\u0646\u064a\u0629 \u0627\u0644\u0643\u0627\u0645\u0644\u0629"],
        horizontal=True,
        key="mirsad_dashboard_view_mode",
    )
    if view == "\u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0641\u0646\u064a\u0629 \u0627\u0644\u0643\u0627\u0645\u0644\u0629":
        render_detailed_engine_dashboard()
    else:
        render_simple_dashboard()



@st.fragment(run_every=10)
def live_fragment():
 render_engine_dashboard()
live_fragment()

