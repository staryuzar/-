from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

from bitcoinlab.automation import run_auto_management_cycle
from bitcoinlab.ea_bridge import (
    current_ack, default_common_files, publish_close_order,
    publish_decision_order, read_ea_status, read_positions,
)
from bitcoinlab.live_snapshot import build_live_snapshot
from bitcoinlab.slow_context import build_slow_context

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
<p>بيانات بيتكوين الحقيقية · محركات متعددة · قرار مركزي · متابعة مراكز وتنفيذ MT5</p></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("إعدادات السوق")
    symbol = st.selectbox("رمز السوق الفوري", ["BTCUSDT", "BTCUSDC"], index=0)
    interval = st.selectbox("الفاصل", ["1m", "5m", "15m", "1h", "4h"], index=0)
    volume = st.number_input(
        "حجم الصفقة باللوت", min_value=0.001, max_value=10.0,
        value=0.01, step=0.001, format="%.3f",
    )
    st.divider()
    auto_refresh = st.toggle("تحديث البيانات وحالة MT5 تلقائياً", value=True)
    refresh_seconds = st.select_slider(
        "تكرار التحديث (ثانية)", options=[5, 10, 15, 30], value=15,
        disabled=not auto_refresh,
    )
    auto_execution = st.toggle(
        "التنفيذ والإدارة التلقائية على Headway-Demo",
        value=True,
        help="الإدارة التلقائية تعمل افتراضياً على Headway-Demo، ويمكن إيقافها من هنا. عند التفعيل، ترسل اللوحة أوامرها تلقائياً: تفتح عند قرار جديد بلا مركز، وتغلق المركز المعاكس عند تأكيد انعكاس الاتجاه. HOLD لا يغلق المركز.",
    )
    refresh_now = st.button("قراءة السوق الآن", type="primary", use_container_width=True)
    st.caption(
        "Binance Spot وUSDⓈ-M Futures هما مدخلا القرار السريع. "
        "البيانات العامة لا تحتاج مفتاح API. التنفيذ محصور في خبير BTC على حساب Headway-Demo."
    )

if "btc_report" not in st.session_state:
    st.session_state["btc_report"] = None
if "btc_auto_state" not in st.session_state:
    st.session_state["btc_auto_state"] = {}
if "btc_last_order_result" not in st.session_state:
    st.session_state["btc_last_order_result"] = None
if "btc_last_close_result" not in st.session_state:
    st.session_state["btc_last_close_result"] = None


@st.cache_data(ttl=900, show_spinner=False)
def cached_slow_context():
    return build_slow_context()


@st.fragment(run_every=f"{refresh_seconds}s" if auto_refresh else None)
def render_live_dashboard():
    if refresh_now or auto_refresh or st.session_state.get("btc_report") is None:
        with st.spinner("جلب بيانات السوق الحقيقية والتحقق من حداثتها..."):
            try:
                st.session_state["btc_report"] = build_live_snapshot(
                    symbol=symbol, interval=interval,
                )
                st.session_state["btc_refresh_error"] = None
            except Exception as exc:
                st.session_state["btc_refresh_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

    report = st.session_state.get("btc_report")
    common_files = None
    try:
        common_files = default_common_files()
        terminal = read_ea_status(common_files)
        ack = current_ack(common_files)
        managed_positions = read_positions(common_files)
    except Exception as exc:
        terminal = {"status": "unavailable", "reason": str(exc)}
        ack = {}
        managed_positions = []

    st.subheader("اتصال خبير MT5")
    terminal_cols = st.columns(4)
    terminal_cols[0].metric("حالة الخبير", terminal.get("status", "unavailable"))
    terminal_cols[1].metric("رمز الوسيط", terminal.get("symbol", "غير متصل"))
    terminal_cols[2].metric(
        "Bid", f"{terminal['bid']:.2f}" if terminal.get("bid") else "—"
    )
    terminal_cols[3].metric(
        "Ask", f"{terminal['ask']:.2f}" if terminal.get("ask") else "—"
    )
    if terminal.get("reason"):
        st.caption(terminal["reason"])
    if ack:
        st.caption(
            f"آخر إقرار MT5: {ack.get('status')} · الأمر {ack.get('id')} · "
            f"{ack.get('detail', '')}"
        )

    if not report:
        st.error(
            "لم تتوفر لقطة سوق صالحة بعد. راجع اتصال الإنترنت ورسالة الخطأ أدناه؛ "
            "لن تُنشأ إشارة بديلة من بيانات افتراضية."
        )
        if st.session_state.get("btc_refresh_error"):
            st.code(st.session_state["btc_refresh_error"])
        st.caption(
            f"عدد المراكز التي قرأها الخبير: {len(managed_positions)}. "
            "تحديث حالة MT5 يستمر حتى إذا تعذّر جلب السوق."
        )
        return

    decision = report["decision"]
    st.caption(
        f"الرمز: {report['symbol']} · آخر تحديث UTC: {report['as_of_utc']} · "
        f"حالة اللقطة: {report['status']}"
    )

    if auto_execution and common_files is not None:
        cycle = run_auto_management_cycle(
            report=report,
            positions=managed_positions,
            common_files=common_files,
            volume=float(volume),
            state=st.session_state.get("btc_auto_state", {}),
        )
        st.session_state["btc_auto_state"] = cycle["state"]
        if cycle["status"] in {"published", "confirmed"}:
            st.success(cycle["message"])
        elif cycle["status"] in {"rejected", "timeout", "signal_stale"}:
            st.warning(cycle["message"])
        else:
            st.info(cycle["message"])
        if cycle.get("result"):
            st.json(cycle["result"])
    elif auto_execution:
        st.warning("تعذر تحديد مجلد MT5 Common Files؛ لم يتم إرسال أوامر.")

    st.subheader("القرار المركزي")
    action = decision["action"]
    if action == "BUY":
        st.success("BUY — إشارة اتجاهية صادرة عن المحركات المركزية")
    elif action == "SELL":
        st.warning("SELL — إشارة اتجاهية صادرة عن المحركات المركزية")
    else:
        st.info("HOLD — لا توجد موافقة كافية من الأدلة المتاحة")

    price_history = report["spot"].get("price_history", {})
    if price_history.get("time_utc"):
        st.subheader("حركة سعر BTC — الشموع المكتملة")
        st.line_chart(
            price_history,
            x="time_utc",
            y="close",
            height=280,
            use_container_width=True,
        )

    flow_cols = st.columns(3)
    flow_cols[0].metric(
        "اختلال دفتر الأوامر",
        f"{report['order_book']['imbalance']:+.3f}"
        if report.get("order_book") and report["order_book"].get("imbalance") is not None
        else "غير متاح",
    )
    flow_cols[1].metric(
        "دلتا تدفق الصفقات",
        f"{report['trade_flow']['delta']:+.4f}"
        if report.get("trade_flow") and report["trade_flow"].get("delta") is not None
        else "غير متاح",
    )
    flow_cols[2].metric(
        "نسبة Taker Buy/Sell",
        f"{report['derivatives_data']['taker_buy_sell_ratio']:.3f}"
        if report.get("derivatives_data") and report["derivatives_data"].get("taker_buy_sell_ratio") is not None
        else "غير متاح",
    )

    cols = st.columns(4)
    cols[0].metric(
        "التقييم الاتجاهي",
        f"{decision['score']:+.3f}" if decision["score"] is not None else "غير متاح",
    )
    cols[1].metric(
        "السبريد",
        f"{report['order_book']['spread_bps']:.2f} bps"
        if report["order_book"] else "غير متاح",
    )
    cols[2].metric(
        "RSI(14)",
        f"{report['technical']['rsi14']:.1f}"
        if report["technical"].get("rsi14") is not None else "غير متاح",
    )
    cols[3].metric(
        "ATR(14)",
        f"{report['technical']['atr14']:.2f}"
        if report["technical"].get("atr14") is not None else "غير متاح",
    )

    st.subheader("الصفقات المفتوحة التي يديرها الخبير")
    if managed_positions:
        st.dataframe(managed_positions, use_container_width=True, hide_index=True)
    else:
        st.caption("لا توجد حالياً مراكز BTC مرتبطة بهذا الخبير.")

    if not auto_execution:
        send_col, close_col = st.columns(2)
        with send_col:
            send_order = st.button(
                "إرسال القرار الحالي إلى Headway-Demo",
                type="primary",
                disabled=(
                    decision.get("action") not in {"BUY", "SELL"}
                    or bool(decision.get("blockers"))
                    or terminal.get("status") != "fresh"
                ),
                use_container_width=True,
            )
        with close_col:
            tickets = [row["ticket"] for row in managed_positions]
            selected_ticket = st.selectbox(
                "تذكرة المركز للإغلاق",
                tickets,
                format_func=lambda value: f"#{value}",
                disabled=not tickets,
            )
            close_order = st.button(
                "إرسال أمر إغلاق",
                disabled=(not tickets or terminal.get("status") != "fresh"),
                use_container_width=True,
            )
        if send_order:
            try:
                st.session_state["btc_last_order_result"] = publish_decision_order(
                    report=report, volume=float(volume),
                )
            except Exception as exc:
                st.session_state["btc_last_order_result"] = {
                    "status": "error", "reason": f"{type(exc).__name__}: {exc}",
                }
        if close_order:
            try:
                st.session_state["btc_last_close_result"] = publish_close_order(
                    ticket=int(selected_ticket),
                )
            except Exception as exc:
                st.session_state["btc_last_close_result"] = {
                    "status": "error", "reason": f"{type(exc).__name__}: {exc}",
                }
    else:
        st.caption(
            "وضع الإدارة التلقائية فعّال: لا يفتح مركزاً إضافياً في الاتجاه نفسه، "
            "ولا يغلق عند HOLD، ويغلق المركز المعاكس أولاً عند انعكاس قرار اللوحة."
        )

    if st.session_state.get("btc_last_order_result"):
        st.caption("آخر نتيجة إرسال يدوي")
        st.json(st.session_state["btc_last_order_result"])
    if st.session_state.get("btc_last_close_result"):
        st.caption("آخر نتيجة إغلاق يدوي")
        st.json(st.session_state["btc_last_close_result"])

    st.subheader("صحة مصادر البيانات")
    source_rows = [
        {
            "المصدر": name,
            "الحالة": state.get("status"),
            "العمر بالثواني": state.get("age_seconds"),
            "وقت الرصد UTC": state.get("observed_at_utc"),
        }
        for name, state in report["source_states"].items()
    ]
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
        st.json({
            "order_book": report["order_book"],
            "trade_flow": report["trade_flow"],
            "profile": report["orderflow"],
        })
        st.subheader("أسباب القرار والحواجز")
        st.write("الحواجز:", decision["blockers"] or "لا يوجد")
        st.write("الأدلة:", decision["reasons"])
        st.caption(decision.get("interpretation", "التقييم اتجاهي وليس احتمال ربح."))

    with st.expander("سياق الشبكة والتمركز المؤسسي وتقلب الخيارات"):
        with st.spinner("تحديث مصادر السياق الأبطأ (بحد أقصى مرة كل 15 دقيقة)..."):
            slow = cached_slow_context()
        context_states = [
            {"المصدر": name, "الحالة": value.get("status"), "وقت القراءة UTC": value.get("fetched_at_utc")}
            for name, value in slow["source_states"].items()
        ]
        st.dataframe(context_states, use_container_width=True, hide_index=True)

        network = slow["data"].get("network", {})
        if network:
            st.markdown("**الشبكة والتعدين والـMempool — mempool.space**")
            st.json({
                "hashrate": network.get("hashrate"),
                "recommended_fees": network.get("recommended_fees"),
                "mempool": network.get("mempool"),
            })

        cot = slow["data"].get("cftc", {})
        cot_rows = cot.get("rows", []) if isinstance(cot, dict) else []
        if cot_rows:
            st.markdown("**تمركز عقود CME — تقرير CFTC TFF الأسبوعي**")
            st.dataframe(
                [
                    {
                        "العقد": row.get("asset"),
                        "تاريخ التقرير": row.get("report_date"),
                        "Open Interest": row.get("open_interest"),
                        "Leveraged Money Net": row.get("leveraged_money_net"),
                        "Asset Managers Net": row.get("asset_manager_net"),
                        "Dealers Net": row.get("dealer_net"),
                    }
                    for row in cot_rows[:8]
                ],
                use_container_width=True,
                hide_index=True,
            )
        elif "cftc" in slow["errors"]:
            st.warning(f"CFTC: {slow['errors']['cftc']}")
        else:
            st.caption("لا توجد صفوف BTC مطابقة في تقرير CFTC المحمّل.")

        cm = slow["data"].get("coinmetrics", {})
        cm_rows = cm.get("data", []) if isinstance(cm, dict) else []
        if cm_rows:
            st.markdown("**نشاط الشبكة — Coin Metrics Community**")
            latest_cm = max(cm_rows, key=lambda row: str(row.get("time", "")))
            st.json(latest_cm)
            st.caption(cm.get("note", ""))
        elif "coinmetrics" in slow["errors"]:
            st.warning(f"Coin Metrics: {slow['errors']['coinmetrics']}")

        dvol = slow["data"].get("dvol", {})
        dvol_rows = dvol.get("data", []) if isinstance(dvol, dict) else []
        if dvol_rows:
            st.markdown("**تقلب الخيارات الضمني — Deribit DVOL**")
            st.json({"latest_candle": dvol_rows[-1], "source": dvol.get("source")})
        elif "dvol" in slow["errors"]:
            st.warning(f"Deribit DVOL: {slow['errors']['dvol']}")

        for item in slow["limitations"]:
            st.caption("• " + item)
        for name, error in slow["errors"].items():
            st.warning(f"{name}: {error}")

    with st.expander("حدود اللقطة ومصادرها"):
        for item in report["limitations"]:
            st.write("• " + item)
        st.caption(
            "قرار اللوحة مبني على أحدث شموع Spot المكتملة مع تدفق الأوامر والمشتقات "
            "المتاحة. بيانات COT وOn-chain وDVOL سياق أبطأ ولا تُعامل كتدفق لحظي."
        )
        st.download_button(
            "تصدير لقطة JSON",
            data=json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
            file_name=(
                "bitcoin_market_snapshot_"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
            ),
            mime="application/json",
        )


render_live_dashboard()
