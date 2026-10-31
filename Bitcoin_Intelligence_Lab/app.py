from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

from bitcoinlab.live_snapshot import build_live_snapshot
from bitcoinlab.slow_context import build_slow_context
from bitcoinlab.ea_bridge import (
    default_common_files,
    read_ea_status,
    read_execution_loop_status,
    read_positions,
)

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
        "Binance وBybit وOKX مصادر بيانات فقط. Headway عبر MT5 هو منفذ التنفيذ الوحيد؛ "
        "حلقة التنفيذ عملية مستقلة لا تعمل إلا عند تشغيلها صراحةً على الجهاز المتصل بالطرفية."
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
    st.subheader("مركز التنفيذ — Headway / MT5")
    try:
        common_files = default_common_files()
        ea_status = read_ea_status(common_files)
        loop_status = read_execution_loop_status(common_files)
        managed_positions = read_positions(common_files)
        ea_state_label = (
            f"متصل · {ea_status.get('symbol')}"
            if ea_status.get("status") == "fresh" else
            "غير متصل / بيانات قديمة"
        )
        loop_state_label = (
            f"نشطة · {loop_status.get('age_seconds')}s"
            if loop_status.get("status") == "fresh" else
            "متوقفة أو نبضها قديم"
        )
        execution_cols = st.columns(3)
        execution_cols[0].metric("حالة خبير MT5", ea_state_label)
        execution_cols[1].metric("حلقة القرار والتنفيذ", loop_state_label)
        execution_cols[2].metric(
            "مراكز الخبير",
            str(len(managed_positions)) if ea_status.get("status") == "fresh" else "غير متاح",
        )
        if ea_status.get("status") != "fresh":
            st.warning(
                "حالة الخبير: " + str(ea_status.get("status")) + " — "
                + str(ea_status.get("reason", ea_status.get("ea_message", "لا توجد نبضة حديثة")))
            )
        elif not ea_status.get("headway_server_ok"):
            st.error("الخادم المتصل ليس خادم Headway.")
        else:
            st.caption(
                f"الخادم: {ea_status.get('account_server')} · "
                f"عمر النبضة: {ea_status.get('age_seconds')} ثانية · "
                f"حالة الإذن: {ea_status.get('readiness_marker')}"
            )
        if loop_status.get("status") == "fresh":
            st.caption(
                f"آخر دورة: {loop_status.get('updated_at_utc')} · "
                f"النتيجة: {loop_status.get('status')} · "
                f"الإجراء المخطط: {loop_status.get('plan', {}).get('action', 'HOLD')} · "
                f"معرّف الأمر: {loop_status.get('command_id') or 'لا يوجد'}"
            )
        if managed_positions and ea_status.get("status") == "fresh":
            st.dataframe(
                [
                    {
                        "التذكرة": row["ticket"],
                        "الرمز": row["symbol"],
                        "الاتجاه": row["type"],
                        "الحجم": row["volume"],
                        "سعر الفتح": row["price_open"],
                        "السعر الحالي": row["price_current"],
                        "وقف الخسارة": row["stop_loss"],
                        "جني الربح": row["take_profit"],
                        "الربح العائم": row["profit"],
                    }
                    for row in managed_positions
                ],
                use_container_width=True,
                hide_index=True,
            )
    except Exception as exc:
        st.info(
            "تعذر قراءة ملفات حالة MT5 من مجلد Common Files: "
            + f"{type(exc).__name__}: {exc}"
        )
    st.caption(
        "اللوحة تقرأ حالة الطرفية والمراكز للعرض فقط. نشر الأوامر يتم من "
        "bitcoinlab.execution_loop كعملية مستقلة، ولا تُرسل أوامر من إعادة تحميل Streamlit."
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

    st.subheader("خريطة عمق السيولة التاريخية — Heatmap وPull/Stack")
    if isinstance(report, dict):
        liquidity = report.get("liquidity_context", {})
        depth_profiles = liquidity.get("venues", [])
        if depth_profiles:
            st.caption(
                "العرض لكل منصة منفصلة. Heatmap يقيس حجم العمق الظاهر واستمراره في اللقطات؛ "
                "Pull/Stack يقارن السعر نفسه بين لقطتين متتاليتين ولا يعد اختفاء المستوى وحده سحباً مؤكداً."
            )
            st.dataframe(
                [
                    {
                        "المنصة": row["venue"],
                        "نوع السوق": row["market_type"],
                        "الحالة": row["status"],
                        "عدد اللقطات": row["snapshot_count"],
                        "عمر آخر لقطة (ث)": row["last_snapshot_age_seconds"],
                        "تغطية تقريبية": row["sample_coverage_ratio"],
                    }
                    for row in depth_profiles
                ],
                use_container_width=True,
                hide_index=True,
            )
            for profile in depth_profiles:
                with st.expander(
                    f"{profile['venue']} · {profile['market_type']} · {profile['snapshot_count']} لقطة"
                ):
                    for side, label in (("bid", "طلب Bid"), ("ask", "عرض Ask")):
                        levels = sorted(
                            profile.get("heatmap", {}).get(side, []),
                            key=lambda item: item["mean_visible_size_btc"],
                            reverse=True,
                        )[:10]
                        if levels:
                            st.markdown(f"**أكبر مستويات العمق الظاهر — {label}**")
                            st.dataframe(
                                [
                                    {
                                        "نطاق السعر USD": item["price_bucket_usd"],
                                        "متوسط الحجم الظاهر BTC": item["mean_visible_size_btc"],
                                        "الوسيط عند الظهور BTC": item["median_when_visible_btc"],
                                        "نسبة الاستمرار": item["persistence_ratio"],
                                        "الحجم الحالي BTC": item["current_size_btc"],
                                    }
                                    for item in levels
                                ],
                                use_container_width=True,
                                hide_index=True,
                            )
                    changes = profile.get("pull_stack", [])
                    if changes:
                        st.markdown("**Pull/Stack proxy — تغيّر الحجم عند السعر نفسه**")
                        st.dataframe(
                            [
                                {
                                    "الجانب": item["side"],
                                    "نطاق السعر USD": item["price_bucket_usd"],
                                    "أحداث Stack": item["stack_events"],
                                    "أحداث Pull": item["pull_events"],
                                    "حجم Stack BTC": item["stacked_btc"],
                                    "حجم Pull BTC": item["pulled_btc"],
                                    "آخر تغير %": item["last_change_pct"],
                                }
                                for item in changes
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.caption("لم تُرصد تغيرات Pull/Stack تتجاوز حد المقارنة في العينات المتاحة.")
            st.caption("هذا محرك سيولة سياقي؛ لا يضيف صوتاً اتجاهياً مستقلاً إلى مركز القرار.")
        else:
            st.caption(
                "لا توجد بعد عينات عمق تاريخية كافية. شغّل جامع السوق ليحفظ لقطات متتابعة؛ "
                "تحتاج الخريطة إلى ثلاث لقطات حديثة على الأقل لكل منصة."
            )
    else:
        st.caption("سيظهر سجل Heatmap بعد إنشاء لقطة السوق.")

    st.subheader("محرك تدفق الصفقات المستمر — CVD متعدد المنصات")
    if isinstance(report, dict):
        trade_analytics = report.get("trade_analytics", {})
        trade_rows = [
            row for row in trade_analytics.get("trade_flow_summary", [])
            if row.get("timeframe") == "5m" and row.get("status") == "ok"
        ]
        if trade_rows:
            st.caption(
                "الجدول يعرض كل منصة ونوع سوق منفصلين. لا نجمع أحجام Spot مع العقود الدائمة، "
                "ولا نجمع أحجام المنصات بعضها مع بعض."
            )
            st.dataframe(
                [
                    {
                        "المنصة": row["venue"],
                        "نوع السوق": "فوري" if row["market_type"] == "spot" else "دائم خطي",
                        "شراء BTC": row["buy_base_volume_btc"],
                        "بيع BTC": row["sell_base_volume_btc"],
                        "دلتا BTC": row["delta_base_volume_btc"],
                        "دلتا USD": row["delta_notional_usd"],
                        "CVD نسبة": row["delta_notional_ratio"],
                        "عدد الصفقات": row["trade_count"],
                        "آخر صفقة UTC": datetime.fromtimestamp(
                            row["last_trade_time_ms"] / 1000, timezone.utc,
                        ).isoformat() if row.get("last_trade_time_ms") else "—",
                    }
                    for row in trade_rows
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption(
                "لم تكتمل بعد تغطية تدفق الصفقات خلال نافذة 5 دقائق، أو أن الجامع لم يبدأ. "
                "لن يصدر المحرك تصويت CVD حتى تتوفر منصتان حديثتان على الأقل."
            )
        cvd = report.get("streamed_trade_flow", {})
        if cvd.get("status") == "ok":
            cvd_cols = st.columns(3)
            cvd_cols[0].metric("CVD الاتجاهي (5m)", f"{cvd['score']:+.3f}")
            cvd_cols[1].metric("عدد المنصات", str(cvd.get("venue_count", 0)))
            cvd_cols[2].metric("الصفقات المجمعة", str(cvd.get("trade_count", 0)))
            if cvd.get("warnings"):
                st.warning("تنبيهات توافق تدفق الشراء والبيع: " + "، ".join(cvd["warnings"]))
        else:
            st.caption("تصويت CVD غير نشط: " + str(cvd.get("reason", "بيانات غير كافية.")))

        footprint_profiles = report.get("streamed_footprint_profiles", [])
        if footprint_profiles:
            st.markdown("**Footprint المستمر حسب السعر والمنصة — آخر 15 دقيقة**")
            for profile in footprint_profiles:
                label = f"{profile['venue']} · {'Spot' if profile['market_type'] == 'spot' else 'Linear Perpetual'}"
                with st.expander(label):
                    fp_cols = st.columns(4)
                    fp_cols[0].metric("POC", f"{profile['poc']:.2f}")
                    fp_cols[1].metric("VAH", f"{profile['vah']:.2f}")
                    fp_cols[2].metric("VAL", f"{profile['val']:.2f}")
                    fp_cols[3].metric("Delta USD", f"{profile['delta_notional_usd']:+.2f}")
                    st.dataframe(profile.get("bins", []), use_container_width=True, hide_index=True)
    else:
        st.caption("سيظهر محرك CVD وFootprint بعد إنشاء لقطة السوق.")

    st.subheader("خريطة تجمعات التصفية السعرية — آخر 60 دقيقة")
    if isinstance(report, dict):
        liquidation_map = report.get("liquidation_heatmap", {})
        clusters = liquidation_map.get("clusters", [])
        venues = liquidation_map.get("venues", [])
        map_cols = st.columns(3)
        map_cols[0].metric("أحداث ضمن النافذة", str(liquidation_map.get("event_count", 0)))
        map_cols[1].metric("مجموعات سعرية منفصلة", str(liquidation_map.get("cluster_count", 0)))
        map_cols[2].metric("منصات ممثلة", str(len(venues)))
        if clusters:
            st.caption(
                "كل مجموعة تبقى مفصولة حسب المنصة ونوع العقد والجهة ووحدة الحجم ونوع السعر المرجعي. "
                "لا نجمع العقود الخام أو نخلط سعر التنفيذ بسعر الإفلاس."
            )
            st.dataframe(
                [
                    {
                        "المنصة": row["venue"],
                        "السوق": row["market_type"],
                        "المركز المصفّى": row["liquidated_side"],
                        "من": row["price_bucket_low_usd"],
                        "إلى": row["price_bucket_high_usd"],
                        "نوع السعر": row["reference_price_kind"],
                        "عدد الأحداث": row["event_count"],
                        "الحجم": row["total_native_size"],
                        "وحدة الحجم": row["quantity_unit"],
                        "قيمة USD الموثقة": row["priced_notional_usd"],
                        "أحداث لها Notional": row["priced_event_count"],
                        "عمر آخر حدث (ث)": row["latest_event_age_seconds"],
                    }
                    for row in clusters
                ],
                use_container_width=True,
                hide_index=True,
            )
            if venues:
                st.markdown("**تغطية الأحداث وحالة اتصال كل منصة**")
                st.dataframe(
                    [
                        {
                            "المنصة": row["venue"],
                            "عدد الأحداث": row["event_count"],
                            "آخر حدث UTC": datetime.fromtimestamp(
                                row["latest_event_time_ms"] / 1000, timezone.utc,
                            ).isoformat(),
                            "وحدات الحجم": ", ".join(row["quantity_units"]),
                            "أنواع السعر": ", ".join(row["reference_price_kinds"]),
                            "حالة القناة": row["feed_status"],
                            "إعادات الاتصال": row["feed_reconnects"],
                        }
                        for row in venues
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            if liquidation_map.get("warnings"):
                st.warning("قيود تغطية خريطة التصفية: " + "، ".join(liquidation_map["warnings"]))
        else:
            st.caption(
                "لا توجد مجموعات تصفية سعرية في النافذة المختارة أو أن الأحداث لم تصل بعد. "
                "عدم ظهور مجموعة لا يعني عدم وجود تصفيات في السوق كله."
            )
        st.caption(
            "الخريطة دليل مخاطر سياقي فقط؛ بيانات التصفية عيّنية ومتفاوتة بين المنصات، "
            "ولا تنشئ تصويتاً اتجاهياً أو أمراً."
        )
    else:
        st.caption("تظهر خريطة التصفية عند توفر سجل SQLite المحلي.")

    st.subheader("ماسح أحداث السوق والفرص — دون تنفيذ")
    if isinstance(report, dict):
        screener = report.get("screener", {})
        events = screener.get("events", [])
        counts = screener.get("counts_by_severity", {})
        alert_cols = st.columns(4)
        alert_cols[0].metric("الأحداث النشطة", str(screener.get("event_count", 0)))
        alert_cols[1].metric("عالية", str(counts.get("high", 0)))
        alert_cols[2].metric("متوسطة", str(counts.get("medium", 0)))
        alert_cols[3].metric("منخفضة", str(counts.get("low", 0)))
        if events:
            st.caption(
                "هذه كواشف أحداث من شموع مكتملة وبيانات حديثة. لا تنشئ أوامر، "
                "ولا تمثل احتمال نجاح، وجميع الحدود الحالية أولية قابلة للمعايرة."
            )
            st.dataframe(
                [
                    {
                        "الخطورة": row["severity"],
                        "الحدث": row["type"],
                        "الإطار": row["timeframe"],
                        "الاتجاه المرجعي": row.get("direction") or "غير اتجاهي",
                        "القيمة": row["value"],
                        "الحد": row["threshold"],
                        "وقت الرصد UTC": datetime.fromtimestamp(
                            row["observed_at_ms"] / 1000, timezone.utc,
                        ).isoformat(),
                        "المصدر": row["source"],
                        "تنفيذ أمر": "لا",
                    }
                    for row in events
                ],
                use_container_width=True,
                hide_index=True,
            )
            with st.expander("تفاصيل الأدلة والحدود لكل حدث"):
                for row in events:
                    st.markdown(
                        f"**{row['type']} · {row['timeframe']} · {row['severity']}**"
                    )
                    st.write("الأدلة:", row["evidence"])
                    st.caption(row["limitation"])
        else:
            st.caption(
                "لا توجد أحداث تتجاوز العتبات حالياً، أو أن بعض المدخلات غير مكتملة/قديمة. "
                "لن يصطنع الماسح حدثاً من بيانات ناقصة."
            )
        if screener.get("rejected_inputs"):
            with st.expander("مدخلات لم تدخل في كشف الأحداث"):
                st.write(screener["rejected_inputs"])
        st.caption(
            "الأحداث عالية/متوسطة تظهر كتحذيرات مساندة في مركز القرار، "
            "لكنها لا تغير Score أو أوزان المحركات."
        )
    else:
        st.caption("يظهر ماسح الأحداث بعد تكوين لقطة السوق.")

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
    health_cols = st.columns(5)
    health_cols[0].metric("حالة المنظومة", health.get("status", "غير متاح"))
    health_cols[1].metric(
        "المصادر الأساسية الحديثة",
        f"{health.get('fresh_core_count', 0)}/{health.get('core_feed_count', 3)}",
    )
    health_cols[2].metric(
        "دفاتر الأوامر الحية",
        str(len(health.get("live_orderbook_venues", []))),
    )
    live_trade_feeds = [
        row for row in health.get("stream_feeds", [])
        if row.get("feed_type") == "trades" and row.get("status") == "live"
    ]
    health_cols[3].metric("تدفقات الصفقات الحية", str(len(live_trade_feeds)))
    health_cols[4].metric(
        "قنوات التصفية المتصلة بلا أحداث",
        str(len(health.get("connected_quiet_liquidation_feeds", []))),
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
                        "نوع المصدر": row.get("feed_type", "event"),
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
        "مراقب الجودة لا يصوّت للاتجاه. قنوات التصفية حدثية وقد تبقى متصلة بلا تصفيات؛ "
        "أما تدفقات صفقات BTC فهي عالية التردد، ولذلك يصنف غياب الصفقات الحديثة كتقادم "
        "حتى لو ظل heartbeat متصلاً."
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

    # Show the exact five voting domains, each source freshness and normalized weight.
    decision_domains = [
        ("technical", "Technical / Multi-Timeframe", report.get("decision_technical", {})),
        ("orderflow", "Orderflow / CVD", report.get("orderflow", {})),
        ("derivatives", "Derivatives", report.get("derivatives", {})),
        ("market_structure", "Market Structure", structure_engine),
        ("cross_venue", "Cross-Venue Order Book", cross_venue_engine),
    ]
    active_domains = set(decision.get("active_domains", []))
    actual_weights = decision.get("weights", {})
    domain_rows = []
    for key, label, engine in decision_domains:
        state = report.get("source_states", {}).get(key, {})
        is_active = key in active_domains
        domain_rows.append({
            "مجال القرار": label,
            "حالة المصدر": state.get("status", "غير متاح"),
            "حالة المحرك": engine.get("status", "غير متاح"),
            "الدرجة": engine.get("score"),
            "الوزن الفعلي بعد التطبيع": actual_weights.get(key, 0.0) if is_active else 0.0,
            "يشارك في الدرجة": "نعم" if is_active else "لا",
            "سبب النقص": state.get("reason") or engine.get("reason") or "—",
        })
    st.subheader("خريطة تصويت المجالات الخمسة")
    st.dataframe(domain_rows, use_container_width=True, hide_index=True)
    st.caption(
        "الأوزان المعروضة هي الأوزان الفعلية بعد تطبيع المجالات المتاحة والحديثة. "
        "المجال غير الحديث أو غير المكتمل لا يشارك في الدرجة؛ وتحذيرات التصفية والخيارات "
        "والسياق البطيء لا تصبح أصواتاً إضافية."
    )
    if decision.get("blockers"):
        st.warning("موانع القرار المركزي: " + " · ".join(decision["blockers"]))
    if decision.get("warnings"):
        st.caption("تحذيرات القرار المركزي: " + " · ".join(decision["warnings"]))

    mtf = report.get("multi_timeframe", {})
    st.subheader("محرك الاتجاه متعدد الأطر الزمنية")
    mtf_cols = st.columns(4)
    mtf_cols[0].metric("اتجاه الأطر", mtf.get("direction", "HOLD"))
    mtf_cols[1].metric(
        "اتساع التغطية",
        f"{mtf.get('coverage', {}).get('fresh_frames', 0)}/{mtf.get('coverage', {}).get('total_frames', 6)}",
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
        cross_derivatives = report.get("cross_venue_derivatives_context", {})
        st.markdown("**مقارنة المشتقات بين المنصات — سياق غير تصويتي**")
        if cross_derivatives.get("venues"):
            funding_summary = cross_derivatives.get("funding_8h_equivalent", {})
            basis_summary = cross_derivatives.get("perpetual_spot_basis", {})
            oi_rows = cross_derivatives.get("open_interest_by_venue", [])
            cross_cols = st.columns(3)
            cross_cols[0].metric(
                "عدد المنصات الحديثة",
                str(cross_derivatives.get("venue_count", 0)),
            )
            cross_cols[1].metric(
                "وسيط التمويل / 8h",
                (
                    f"{funding_summary['median'] * 100:.4f}%"
                    if funding_summary.get("median") is not None else "غير متاح"
                ),
            )
            cross_cols[2].metric(
                "وسيط Perp-Spot (bps)",
                (
                    f"{basis_summary['median']:+.2f}"
                    if basis_summary.get("median") is not None else "غير متاح"
                ),
            )
            st.dataframe(
                [
                    {
                        "المنصة": row["venue"],
                        "الحالة": row["status"],
                        "Spot Mid": row.get("spot_mid"),
                        "Perp Mid": row.get("perpetual_mid"),
                        "Perp-Spot bps": row.get("perpetual_vs_spot_bps"),
                        "Mark-Index bps": row.get("mark_vs_index_bps"),
                        "Funding الحالي": row.get("funding_rate_per_settlement"),
                        "فترة التمويل (دقيقة)": row.get("funding_interval_minutes"),
                        "Funding مكافئ 8h": row.get("funding_rate_per_8h_equivalent"),
                    }
                    for row in cross_derivatives.get("venues", [])
                ],
                use_container_width=True,
                hide_index=True,
            )
            if oi_rows:
                st.markdown("**الفائدة المفتوحة — وحدات كل مصدر كما وردت**")
                st.dataframe(
                    [
                        {
                            "المنصة": row["venue"],
                            "OI BTC": row.get("open_interest_btc"),
                            "OI Native": row.get("open_interest_native"),
                            "وحدة Native": row.get("open_interest_native_unit"),
                            "قيمة المصدر": row.get("open_interest_quote_value"),
                            "عملة القيمة": row.get("open_interest_quote_currency"),
                        }
                        for row in oi_rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            if cross_derivatives.get("warnings"):
                st.warning("تنبيهات المقارنة: " + "، ".join(cross_derivatives["warnings"]))
        else:
            st.caption("لا تتوفر بعد بيانات كافية من منصتين على الأقل للمقارنة المشتركة.")
        if cross_derivatives.get("fetch_errors"):
            with st.expander("أخطاء مصادر مقارنة المشتقات"):
                st.json(cross_derivatives["fetch_errors"])
        st.caption(
            "هذا المحرك سياقي فقط: لا يضيف صوتاً سادساً إلى القرار. "
            "Funding مطبّع حسب فترة التسوية، وOI يبقى منفصلاً حسب وحدة كل منصة."
        )
    with right:
        st.subheader("محرك السيولة وتدفق الأوامر")
        st.json({
            "order_book": report["order_book"],
            "trade_flow_rest_sample": report["trade_flow"],
            "streamed_multi_venue_cvd": report.get("streamed_trade_flow", {}),
            "streamed_footprint_profiles": report.get("streamed_footprint_profiles", []),
            "historical_depth_liquidity_context": report.get("liquidity_context", {}),
            "integrated_orderflow_profile": report["orderflow"],
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

        onchain = slow["data"].get("onchain", {})
        st.markdown("**مؤشرات السلسلة اليومية — MVRV وNUPL المشتق**")
        if onchain.get("status") in {"ok", "partial", "stale"}:
            if onchain.get("freshness") == "stale":
                st.warning("بيانات السلسلة اليومية قديمة؛ تعرض للسياق فقط ولا تدخل القرار.")
            onchain_cols = st.columns(4)
            onchain_cols[0].metric(
                "MVRV",
                f"{onchain['mvrv']:.3f}" if onchain.get("mvrv") is not None else "غير متاح",
            )
            onchain_cols[1].metric(
                "MVRV Z-Score",
                f"{onchain['mvrv_zscore']:.3f}" if onchain.get("mvrv_zscore") is not None else "غير متاح",
            )
            onchain_cols[2].metric(
                "NUPL مشتق",
                f"{onchain['nupl_derived']:.3f}" if onchain.get("nupl_derived") is not None else "غير متاح",
            )
            onchain_cols[3].metric(
                "Active Addresses",
                f"{onchain['active_addresses']:,.0f}" if onchain.get("active_addresses") is not None else "غير متاح",
            )
            st.dataframe(
                [
                    {
                        "المقياس": "Market Capitalization USD",
                        "القيمة": onchain.get("market_cap_usd"),
                        "التغير 7 أيام %": onchain.get("seven_day_changes_pct", {}).get("market_cap"),
                    },
                    {
                        "المقياس": "Realized Capitalization USD",
                        "القيمة": onchain.get("realized_cap_usd"),
                        "التغير 7 أيام %": onchain.get("seven_day_changes_pct", {}).get("realized_cap"),
                    },
                    {
                        "المقياس": "MVRV",
                        "القيمة": onchain.get("mvrv"),
                        "التغير 7 أيام %": onchain.get("seven_day_changes_pct", {}).get("mvrv"),
                    },
                    {
                        "المقياس": "Block Height",
                        "القيمة": onchain.get("block_height"),
                        "التغير 7 أيام %": None,
                    },
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                f"تاريخ المصدر: {onchain.get('source_time') or 'غير متاح'} · "
                f"عمر البيانات بالساعات: {onchain.get('age_hours') if onchain.get('age_hours') is not None else 'غير متاح'}"
            )
            if onchain.get("warnings"):
                st.warning("قيود مقاييس السلسلة: " + "، ".join(onchain["warnings"]))
            if onchain.get("optional_errors"):
                with st.expander("المقاييس الاختيارية غير المتاحة من Coin Metrics"):
                    st.json(onchain["optional_errors"])
        else:
            st.caption(
                "مقاييس MVRV/Realized Cap غير متاحة حالياً من مستوى Community؛ "
                "لا تُعرض قيم تقديرية أو بدائل مصطنعة."
            )
        st.caption(
            "هذه مقاييس يومية بطيئة؛ NUPL محسوب هنا من (Market Cap − Realized Cap) / Market Cap "
            "وموسوم كمقياس مشتق. SOPR غير معروض لعدم وجود مصدر موثق في هذا المسار. "
            "هذا السياق لا يضيف تصويتاً إلى القرار اللحظي. راجع ترخيص Coin Metrics Community قبل إعادة التوزيع أو الاستخدام التجاري."
        )

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
