from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

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
<p>بيانات بيتكوين الحقيقية · محركات متعددة · قرار مركزي · تدقيق جودة البيانات</p></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("إعدادات السوق")
    symbol = st.selectbox("رمز السوق الفوري", ["BTCUSDT", "BTCUSDC"], index=0)
    interval = st.selectbox("الفاصل", ["1m", "5m", "15m", "1h", "4h"], index=0)
    st.divider()
    auto_refresh = st.toggle("تحديث بيانات السوق تلقائياً", value=True)
    refresh_seconds = st.select_slider(
        "تكرار التحديث (ثانية)", options=[5, 10, 15, 30], value=15,
        disabled=not auto_refresh,
    )
    refresh_now = st.button("قراءة السوق الآن", type="primary", use_container_width=True)
    st.caption(
        "Binance وBybit وOKX مصادر بيانات فقط. هذه النسخة في مرحلة استكمال المحركات والقرار؛ "
        "لا يوجد اتصال أو إرسال أوامر إلى MT5 في هذه المرحلة."
    )

if "btc_report" not in st.session_state:
    st.session_state["btc_report"] = None

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
    st.subheader("مرحلة تطوير النظام")
    st.info(
        "ربط الخبير بمنصة MT5 مؤجل عمداً حتى اكتمال المحركات وتوصيلها بمركز القرار "
        "والانتهاء من تدقيق واختبار اللوحة. هذه النسخة لا تقرأ ملفات MT5 ولا تنشر "
        "أوامر تداول؛ Headway سيبقى وسيط التنفيذ عند بدء مرحلة الربط لاحقاً."
    )

    st.subheader("تدفق دفاتر الأوامر الحي — Binance / Bybit / OKX")
    stream_state = (
        report.get("market_stream", {})
        if isinstance(report, dict)
        else {"status": "not_started", "reason": "لم تُبنَ لقطة السوق بعد."}
    )
    if stream_state.get("status") == "ok" and stream_state.get("venues"):
        venue_rows = [
            {
                "المنصة": row["venue"],
                "الرمز": row["symbol"],
                "الحالة": row["status"],
                "آخر رسالة UTC": (
                    datetime.fromtimestamp(row["last_message_ms"] / 1000, timezone.utc).isoformat()
                    if row.get("last_message_ms") else "—"
                ),
                "إعادات الاتصال": row["reconnects"],
                "آخر خطأ": row.get("last_error") or "—",
            }
            for row in stream_state["venues"]
        ]
        st.dataframe(venue_rows, use_container_width=True, hide_index=True)
        if stream_state.get("latest_books"):
            st.dataframe(
                [
                    {
                        "المنصة": row["venue"],
                        "Bid": row["best_bid"],
                        "Ask": row["best_ask"],
                        "Spread bps": row["spread_bps"],
                        "Book imbalance": row["imbalance"],
                        "توقيت لقطة UTC": datetime.fromtimestamp(
                            row["observed_at_ms"] / 1000, timezone.utc,
                        ).isoformat(),
                    }
                    for row in stream_state["latest_books"]
                ],
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info(
            "جامع WebSocket لا يعمل أو لم تُنشأ قاعدة بياناته بعد. "
            "شغّل جامع السوق في نافذة طرفية ثانية بالأمر الموضح في README_AR.md. "
            + str(stream_state.get("reason", ""))
        )

    st.subheader("محرك رصد تصفيات المشتقات — آخر 60 دقيقة")
    liquidation_groups = stream_state.get("liquidation_summary", [])
    if liquidation_groups:
        st.caption(
            "التجميع يبقى منفصلاً حسب المنصة ووحدة العقد؛ لا نجمع أحجام BTC والعقود "
            "في رقم واحد، ولا نعد سعر الإفلاس سعر تنفيذ."
        )
        st.dataframe(
            [
                {
                    "المنصة": row["venue"],
                    "نوع السوق": row["market_type"],
                    "الجهة المصفّاة": row["liquidated_side"],
                    "وحدة الحجم": row["quantity_unit"],
                    "عدد الأحداث": row["event_count"],
                    "إجمالي الحجم الأصلي": row["total_native_size"],
                    "Notional USD (البيانات ذات سعر تنفيذ فقط)": row["notional_usd"],
                    "آخر حدث UTC": datetime.fromtimestamp(
                        row["latest_event_time_ms"] / 1000, timezone.utc,
                    ).isoformat(),
                }
                for row in liquidation_groups
            ],
            use_container_width=True,
            hide_index=True,
        )
        recent = stream_state.get("recent_liquidations", [])
        if recent:
            with st.expander("آخر أحداث التصفية المسجلة"):
                st.dataframe(
                    [
                        {
                            "المنصة": row["venue"],
                            "الرمز": row["symbol"],
                            "الجهة المصفّاة": row["liquidated_side"],
                            "Side": row["order_side"],
                            "الحجم": row["raw_size"],
                            "الوحدة": row["quantity_unit"],
                            "السعر المرجعي": row["reference_price"],
                            "نوع السعر": row["reference_price_kind"],
                            "Notional USD": row["notional_usd"],
                            "وقت الحدث UTC": datetime.fromtimestamp(
                                row["event_time_ms"] / 1000, timezone.utc,
                            ).isoformat(),
                        }
                        for row in recent
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
    else:
        st.caption(
            "لا توجد أحداث تصفية مسجلة خلال آخر 60 دقيقة، أو أن جامع التصفيات لم يبدأ بعد. "
            "غياب الأحداث لا يعني غياب التصفية في كامل السوق."
        )

    if not report:
        st.error(
            "لم تتوفر لقطة سوق صالحة بعد. راجع اتصال الإنترنت ورسالة الخطأ أدناه؛ "
            "لن تُنشأ إشارة بديلة من بيانات افتراضية."
        )
        if st.session_state.get("btc_refresh_error"):
            st.code(st.session_state["btc_refresh_error"])
        st.caption(
            "لم تتوفر أي بيانات تداول افتراضية أو محاكاة بديلة."
        )
        return

    decision = report["decision"]
    st.caption(
        f"الرمز: {report['symbol']} · آخر تحديث UTC: {report['as_of_utc']} · "
        f"حالة اللقطة: {report['status']}"
    )

    health = report.get("data_health", {})
    st.subheader("مراقب صحة مصادر البيانات")
    health_cols = st.columns(4)
    health_cols[0].metric("حالة المنظومة", health.get("status", "غير متاح"))
    health_cols[1].metric(
        "المصادر الأساسية الحديثة",
        f"{health.get('fresh_core_count', 0)}/{health.get('core_feed_count', 3)}",
    )
    health_cols[2].metric(
        "دفاتر الأوامر الحية",
        str(len(health.get("live_orderbook_venues", []))),
    )
    health_cols[3].metric(
        "مصادر التصفية المتصلة بلا أحداث حديثة",
        str(len(health.get("connected_quiet_event_feeds", []))),
    )
    if health.get("warnings"):
        st.warning("صحة البيانات: " + " · ".join(health["warnings"]))
    stream_health_rows = health.get("stream_feeds", [])
    if stream_health_rows:
        with st.expander("تفاصيل اتصال كل WebSocket وحالة حداثته"):
            st.dataframe(
                [
                    {
                        "المصدر": row["name"],
                        "الحالة": row["status"],
                        "آخر حدث (ث)": row["last_message_age_seconds"],
                        "عمر heartbeat (ث)": row["heartbeat_age_seconds"],
                        "عمر آخر دفتر (ث)": row["book_age_seconds"],
                        "إعادات الاتصال": row["reconnects"],
                        "آخر خطأ": row["last_error"] or "—",
                    }
                    for row in stream_health_rows
                ],
                use_container_width=True,
                hide_index=True,
            )
    st.caption(
        "مراقب الجودة لا يصوّت للاتجاه. ويعامل تدفقات التصفية كقنوات حدثية قد تبقى متصلة "
        "دون ورود أحداث لفترة، بدلاً من تصنيفها متقادمة بسبب هدوء السوق."
    )

    intelligence = report.get("market_intelligence", {})
    structure_engine = intelligence.get("market_structure_signal", {})
    cross_venue_engine = intelligence.get("cross_venue_orderbook", {})
    liquidation_risk = intelligence.get("liquidation_risk", {})

    st.subheader("الأدلة المضافة إلى مركز القرار")
    engine_cols = st.columns(4)
    engine_cols[0].metric(
        "إشارة بنية السوق",
        f"{structure_engine['score']:+.3f}"
        if structure_engine.get("score") is not None else "غير مكتملة",
    )
    engine_cols[1].metric(
        "توافق دفاتر المنصات",
        f"{cross_venue_engine['score']:+.3f}"
        if cross_venue_engine.get("score") is not None else "منصات غير كافية",
    )
    engine_cols[2].metric(
        "المنصات المتوافقة",
        f"{cross_venue_engine.get('venue_count', 0)}",
    )
    engine_cols[3].metric(
        "أحداث تصفية / 5 دقائق",
        str(liquidation_risk.get("event_count", 0)),
    )
    if cross_venue_engine.get("warnings"):
        st.warning("تعارض/تحذير دفاتر المنصات: " + " · ".join(cross_venue_engine["warnings"]))
    if liquidation_risk.get("warnings"):
        st.warning(
            "ضغط تصفيات حديث — سياق مخاطر فقط: "
            + " · ".join(liquidation_risk["warnings"])
        )
    st.caption(
        "بنية السوق وتوافق الدفاتر يدخلان القرار بأوزان صغيرة بعد التحقق من حداثتهما. "
        "التصفية تعرض ضغط المراكز ولا تُستخدم وحدها كإشارة BUY/SELL."
    )

    st.subheader("القرار المركزي")
    action = decision["action"]
    if action == "BUY":
        st.success("BUY — إشارة اتجاهية صادرة عن المحركات المركزية")
    elif action == "SELL":
        st.warning("SELL — إشارة اتجاهية صادرة عن المحركات المركزية")
    else:
        st.info("HOLD — لا توجد موافقة كافية من الأدلة المتاحة")

    mtf = report.get("multi_timeframe", {})
    st.subheader("محرك الاتجاه متعدد الأطر الزمنية")
    mtf_cols = st.columns(4)
    mtf_cols[0].metric("اتجاه الأطر", mtf.get("direction", "HOLD"))
    mtf_cols[1].metric(
        "اتساع التغطية",
        f"{mtf.get('coverage', {}).get('fresh_frames', 0)}/6",
    )
    mtf_cols[2].metric(
        "الاتجاه الأكبر 1D/4H",
        f"{mtf['macro_score']:+.3f}" if mtf.get("macro_score") is not None else "غير متاح",
    )
    mtf_cols[3].metric(
        "التوافق",
        f"{mtf['alignment_ratio']:.0%}" if mtf.get("alignment_ratio") is not None else "غير متاح",
    )
    mtf_rows = []
    for timeframe in ("1d", "4h", "1h", "15m", "5m", "1m"):
        item = mtf.get("frames", {}).get(timeframe, {})
        mtf_rows.append({
            "الإطار": timeframe,
            "الدور": mtf.get("roles", {}).get(timeframe, item.get("role")),
            "الحالة": item.get("status"),
            "الدرجة": item.get("score"),
            "الاتجاه": item.get("state"),
            "RSI": item.get("rsi14"),
            "الكسر": item.get("breakout"),
            "عمر البيانات (ث)": item.get("age_seconds"),
        })
    st.dataframe(mtf_rows, use_container_width=True, hide_index=True)
    if mtf.get("warnings"):
        st.caption("تنبيهات توافق الأطر: " + " · ".join(mtf["warnings"]))
    if mtf.get("blockers"):
        st.warning("محرك الأطر لم يكتمل: " + " · ".join(mtf["blockers"]))

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

    structure = report.get("market_structure", {})
    bar_structure = structure.get("bars", {})
    structure_cols = st.columns(3)
    structure_cols[0].metric(
        "Relative Volume (20)",
        f"{bar_structure['relative_volume_20']:.2f}×"
        if bar_structure.get("relative_volume_20") is not None else "غير متاح",
    )
    structure_cols[1].metric(
        "VWAP جلسة UTC",
        f"{bar_structure['session_vwap_utc']:.2f}"
        if bar_structure.get("session_vwap_utc") is not None else "غير متاح",
    )
    structure_cols[2].metric(
        "اتساع النطاق",
        f"{bar_structure['range_expansion_vs_prior_median']:.2f}×"
        if bar_structure.get("range_expansion_vs_prior_median") is not None else "غير متاح",
    )
    vp = structure.get("volume_profile", {})
    if vp.get("status") == "ok":
        with st.expander("Volume Profile وFootprint من الصفقات المنفذة"):
            st.caption(
                f"العينة: {vp.get('sample_trade_count')} صفقة مجمعة · "
                f"نافذتها الزمنية: {vp.get('sample_window_seconds')} ثانية. "
                "هذه ليست قيمة يوم كامل؛ إنها عينة الصفقات الحديثة التي جلبها المصدر."
            )
            vp_cols = st.columns(4)
            vp_cols[0].metric("POC", f"{vp['poc']:.2f}")
            vp_cols[1].metric("VAH", f"{vp['vah']:.2f}")
            vp_cols[2].metric("VAL", f"{vp['val']:.2f}")
            vp_cols[3].metric("Delta BTC", f"{vp['delta_btc']:+.4f}")
            st.dataframe(vp.get("bins", []), use_container_width=True, hide_index=True)
    else:
        st.caption("Volume Profile غير مكتمل: " + str(vp.get("reason", "لا تتوفر عينة صفقات صالحة.")))

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

        options = slow["data"].get("options", {})
        if options.get("status") == "ok":
            st.markdown("**هيكل خيارات BTC — Deribit public options**")
            st.caption(
                f"العقود المدرجة في اللقطة: {options.get('option_count', 0)} · "
                f"تواريخ الانتهاء: {options.get('expiry_count', 0)} · "
                f"صفوف مرفوضة لبيانات ناقصة/غير صالحة: {options.get('rejected_count', 0)}"
            )
            st.info(
                "Open Interest هنا بوحدة BTC حسب تعريف Deribit لخيارات BTC، وليس عدداً للعقود. "
                "Gamma-weighted OI غير موقّع؛ لا يعبّر عن صافي GEX أو مراكز صناع السوق."
            )
            expiry_rows = options.get("expiries", [])
            if expiry_rows:
                st.dataframe(
                    [
                        {
                            "Expiry UTC": row["expiry_utc"],
                            "DTE": row["days_to_expiry"],
                            "ATM IV %": row["atm_iv_pct"],
                            "25Δ RR (vol points)": row["risk_reversal_25d_vol_points"],
                            "RR status": row["risk_reversal_status"],
                            "Call OI BTC": row["call_open_interest_btc"],
                            "Put OI BTC": row["put_open_interest_btc"],
                            "Put/Call OI": row["put_call_oi_ratio"],
                            "Total OI BTC": row["total_open_interest_btc"],
                            "Options": row["option_count"],
                        }
                        for row in expiry_rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                iv_rows = [
                    {"Expiry": row["expiry_utc"], "ATM IV %": row["atm_iv_pct"]}
                    for row in expiry_rows if row.get("atm_iv_pct") is not None
                ]
                if len(iv_rows) >= 2:
                    st.markdown("**ATM IV Term Structure**")
                    st.line_chart(iv_rows, x="Expiry", y="ATM IV %", height=220)
                gamma_rows = (
                    options.get("unsigned_gamma_open_interest_btc_proxy_by_strike", [])
                )
                if gamma_rows:
                    with st.expander("أعلى مستويات Gamma-weighted BTC OI (غير موقّع)"):
                        st.dataframe(gamma_rows, use_container_width=True, hide_index=True)
            for note in options.get("limitations", []):
                st.caption("• " + note)
        elif options.get("status") == "empty":
            st.caption("لم تتوفر سلسلة خيارات BTC صالحة من Deribit في هذه القراءة.")
        elif "options" in slow["errors"]:
            st.warning(f"Deribit Options: {slow['errors']['options']}")

        for item in slow["limitations"]:
            st.caption("• " + item)
        for name, error in slow["errors"].items():
            st.warning(f"{name}: {error}")

    with st.expander("حدود اللقطة ومصادرها"):
        for item in report["limitations"]:
            st.write("• " + item)
        st.caption(
            "قرار اللوحة قيد التطوير المركزي، ولا يرسل أوامر تداول. "
            "بيانات COT وOn-chain وDVOL سياق أبطأ ولا تُعامل كتدفق لحظي."
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
