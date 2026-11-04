# مرجع استئناف مرصاد BTC — سياق المشروع والملفات

**هذا الملف هو نقطة الاستئناف الدائمة للمحادثات القادمة عن مرصاد.** اقرأه مع تقرير الجاهزية قبل متابعة أي تعديل، ثم تحقق من رأس الفرع الحالي لأن الشيفرة ونتائج GitHub قد تتغير بعد تاريخ هذا المرجع.

## الهوية والمصدر
- المستودع: `staryuzar/-`
- الفرع المعتمد للعمل: `mini` فقط ما لم يطلب المستخدم خلاف ذلك.
- مجلد التطبيق: `Mirsad_BTC/`
- SHA الفرع عند إنشاء هذا المرجع: `84526d781f2bbd3b29997c24393d084e3997f5eb`
- جرد المشروع: **114 ملفاً** تحت `Mirsad_BTC/`، و**9** سير عمل GitHub خاص بمرصاد.
- المرجع التنفيذي للجاهزية: `Mirsad_BTC/reports/ENGINE_READINESS_AUDIT_AR_20261104.md`
- المعمارية: `Mirsad_BTC/ARCHITECTURE_AR.md`
- الاستخدام والتشغيل: `Mirsad_BTC/README_AR.md`
- الأوزان الفعلية: `Mirsad_BTC/reports/ENGINE_WEIGHT_PROFILE_V6_AR_20261104.md`، ملف v6.1 gap-aware.

## توزيع المسؤوليات — لا تخلط ملكية المحركات
1. **E1 استخبارات السوق — 20%:** `mirsad/engines/market_intelligence.py`. الأخبار والتقويم وFear & Greed والمشتقات. مصدر مستقل لا يقرأ MT5 أو OHLC أو نتائج المحركات الأخرى.
2. **E2 الشموع وحركة السعر — 55%:** `mirsad/engines/mt5_chart_candles.py` و`mirsad/engines/mt5_price_action.py`. OHLC أصلي مغلق من MT5 على M1/M5/M15/H1/H4/D1؛ لا صور أو OCR في التصويت.
3. **E3 المؤشرات الفنية — 25%:** `mirsad/engines/indicators.py` مع `mirsad/engines/mt5_native_indicators.py`. يحسب من شموع E2 المغلقة، وCopyBuffer يثبت التطابق ولا يصوت بصورة منفصلة.
4. **E4 القرار والمخاطر والمراكز:** `mirsad/engines/decision.py` و`daily_risk.py` و`position_management.py` و`position_ledger.py`. يجمع E1/E2/E3 بأوزان ثابتة بعد تخفيض الجودة، ويشترط أهلية E2.
5. **E5 جسر MT5 والتنفيذ — 0% اتجاه:** `mirsad/engines/mt5_market.py` و`mirsad/engines/mt5_bridge.py` وخبير التنفيذ. يقدم سعر الوسيط والحساب والاتصال وMIR1 والـACK والمصالحة؛ لا يحدد اتجاه السوق ولا يحسب المخاطرة.

## الأوزان الحالية — لا تستخدم أرقام تقارير v5 القديمة
- E1/E2/E3 = **20/55/25**، مجموعها 100%.
- لا يعاد توزيع حصة المحرك الذي فقد بياناته؛ تضرب حصته الأساسية في جودة الدليل.
- E1: مشتقات 55%، أخبار 40%، Fear & Greed 5%. داخل المشتقات Funding 55% وLong/Short 45%.
- E2: Swing confirmed 65%، BOS/CHOCH 20%، شمعة 10%، سيولة 5%. أطره والأطر الفنية لـE3: 4/8/18/25/30/15.
- E3: اتجاه 30%، زخم 30%، قوة 20%، متذبذبات 10%، حجم 10%.
- E5 لا يصوت اتجاهياً.
- المصدر الحاكم: `ENGINE_WEIGHT_PROFILE_V6_AR_20261104.md` ومعرف v6.1 `mirsad-engine-weights-fixed-share-v6.1-gap-aware-2026-11-04`.
- تم تصحيح نص التقرير التشخيصي في `mirsad/runtime.py` إلى E2=55%. أي ذكر 50% في runtime من نسخة أقدم لا يُعتمد. تقرير `DECISION_WEIGHT_CALIBRATION_AR_20261104.md` محفوظ تاريخياً كملف v5 وتم وضع تنبيه superseded عليه.

## آخر أدلة مؤكدة — 4 نوفمبر 2026
- [Live validation #1007 — 359 tests OK](https://github.com/staryuzar/-/actions/runs/41819348493) على SHA `3d2250e...`.
- [Engine 2 Native OHLC #372 — PASS](https://github.com/staryuzar/-/actions/runs/41819348545).
- [MT5 Direct Feed #152 — PASS، صور معطلة](https://github.com/staryuzar/-/actions/runs/41819348643).
- [Integrated five-engine runtime #28 — PASS](https://github.com/staryuzar/-/actions/runs/41819216595) على SHA `3136f5a...`: E1 READY، E2 READY لكن mixed، E3 READY، E4 WAITING_FOR_ENGINE_2، E5 CONNECTED. لا أمر دخول في تلك الدورة.
- نتيجة E3 في #152: READY، تغطية 6/6 أطر، جودة 1.0، parity **120/120**.
- نتيجة E2 في #152: الأطر الستة صالحة للتحليل، لكن `MIXED_TIMEFRAME_DIRECTIONS`، score `0.10` أقل من حد `0.20`، لذلك `decision_eligible=false`. هذا يمنع E4 الدخول على نحو صحيح.
- تشخيص E1 الحي: status READY، ثلاثة مكونات اتجاهية صالحة؛ Trading Economics غير مهيأ، وبعض نقاط نهاية المشتقات واجهت HTTP 451 في runner.
- تقرير الدرجات التقديرية الحالية: E1 84%، E2 88%، E3 93%، E4 78%، E5 91% (متوسط 87% تقريباً). هذه جاهزية هندسية لا احتمال ربح ولا تصريحاً بأن هناك إشارة دخول.

## إعدادات تداول حساسة — لا تغيّرها دون توجيه المستخدم
- `RISK_PER_TRADE=0.005` = 0.5%.
- `MAX_DAILY_LOSS_FRACTION=0.02` = 2%، لكن `DAILY_LOSS_LIMIT_ENABLED` معطل افتراضياً في التطوير.
- `ENABLE_ORDER_PUBLISH=1` افتراضياً.
- `InpAllowExecution=true` افتراضياً في `Mirsad_BTC_ExecutionBridge.mq5`.
- لا توجد بوابة تصنيف نوع الحساب.
- سير قبول BUY/CLOSE المنفصل يرسل أوامر حقيقية للحساب المهيأ عند اختياره؛ لا تشغله كاختبار شكلي ولا تفترض أن الحساب تجريبي. لا ترسل صفقة إلا بتفويض واضح، وبوابة E4 جاهزة.
- لم يتم تغيير إعدادات تداول في هذا التدقيق.

## تحديث التحقق الأخير — بعد تصحيح اختبار 50% القديم

- [Live Validation #1010](https://github.com/staryuzar/-/actions/runs/41821833938): 359 tests OK على SHA `1c468ff`.
- [Engine 2 #373](https://github.com/staryuzar/-/actions/runs/41820911528): PASS على `c62effe`.
- [MT5 Direct Feed #153](https://github.com/staryuzar/-/actions/runs/41820911507): PASS؛ E3 parity 120/120، quality 1.0، coverage 100%، E2 mixed score 0.10.
- [Integrated Runtime #29](https://github.com/staryuzar/-/actions/runs/41820911525): PASS على `c62effe`؛ E1 READY، E2 mixed، E3 READY، E4 WAIT، E5 CONNECTED، MIR1 envelopes=0، no acceptance order.
- فشل #1008/#1009 كان بسبب assertion قديم في اختبار runtime يتوقع 50%؛ تم تحديثه إلى 55% في `test_mt5_observer_engine2_integration.py`، ثم اجتازت المجموعة كاملة 359/359 في #1010.

## الأعمال المفتوحة
1. معايرة زمنية خارج العينة لأوزان E1/E2/E3 مع رسوم وانزلاق وEmbargo ومجموعة اختبار نهائية.
2. اختبار E1 عبر دورات متكررة ومزودات متعددة، وتحديد التعامل مع 451 والمصادر غير المهيأة.
3. دراسة E2 عبر حالات سوق صاعدة وهابطة ومتذبذبة مع عدم إضعاف بوابة التوافق.
4. تكرار E3 live parity على جلسات ووسطاء مختلفين؛ parity ليس إثباتاً للربحية.
5. إثبات دورة طبيعية مكتملة E4→E5→MT5: قرار صالح فعلياً، MIR1، ACK، مصالحة المركز وسجل الصفقات، من غير اصطناع إشارة أو تجاوز بوابة.
6. تشغيل runtime ولوحة القيادة بصورة مستمرة في بيئة النشر المستهدفة؛ GitHub Actions runner مؤقت.
7. مراجعة تفعيل حد الخسارة اليومية قبل الاستخدام الممول.

## تعليمات الاستئناف في أي محادثة لاحقة
1. اقرأ هذا الملف ثم `Mirsad_BTC/reports/ENGINE_READINESS_AUDIT_AR_20261104.md`.
2. تحقق من آخر SHA لفرع `mini` ومن نتائج أحدث workflows؛ لا تفترض أن SHA المذكور أعلاه لا يزال HEAD.
3. افتح ملفات المحرك الذي سيُعدّل واختباراته وملفات عقوده قبل أي تغيير.
4. نفّذ إصلاحاً متكاملاً ثم الاختبارات المتأثرة، ولا تعلن الجاهزية 100% بسبب نجاح الاختبارات وحدها.
5. لا تجعل E1 يعيد عمل E2 أو E3، ولا تجعل E5 يصوت اتجاهياً. لا تُدخل الصور أو OCR إلى قرار OHLC المعتمد.
6. عندما تكون أطر E2 مختلطة أو دون عتبة البنية، القرار الصحيح هو WAIT؛ لا تخفّض العتبة لإجبار الصفقة.

## الفهرس الكامل لملفات التطبيق (114 ملفاً)
القائمة التالية هي فهرس الملفات الموجودة في شجرة Git عند إنشاء هذا المرجع. مصدر الشيفرة الكامل هو ملفات المستودع نفسها؛ لا يمكن استبدالها بذاكرة محادثة أو نسخها إلى هذا الملف.

### جذر التطبيق
- `Mirsad_BTC/.gitignore`
- `Mirsad_BTC/ARCHITECTURE_AR.md`
- `Mirsad_BTC/README_AR.md`
- `Mirsad_BTC/dashboard.py`
- `Mirsad_BTC/requirements-chart.txt`
- `Mirsad_BTC/requirements.txt`
- `Mirsad_BTC/run_mirsad.py`

### حزمة Python الأساسية
- `Mirsad_BTC/mirsad/__init__.py`
- `Mirsad_BTC/mirsad/config.py`
- `Mirsad_BTC/mirsad/health.py`
- `Mirsad_BTC/mirsad/runtime.py`
- `Mirsad_BTC/mirsad/storage.py`

### محركات Python
- `Mirsad_BTC/mirsad/engines/__init__.py`
- `Mirsad_BTC/mirsad/engines/chart_classical_patterns.py`
- `Mirsad_BTC/mirsad/engines/chart_continuation_patterns.py`
- `Mirsad_BTC/mirsad/engines/chart_multi_timeframe.py`
- `Mirsad_BTC/mirsad/engines/chart_pattern_evaluation.py`
- `Mirsad_BTC/mirsad/engines/chart_pattern_knowledge.py`
- `Mirsad_BTC/mirsad/engines/chart_structure_evaluation.py`
- `Mirsad_BTC/mirsad/engines/chart_structure_knowledge.py`
- `Mirsad_BTC/mirsad/engines/daily_risk.py`
- `Mirsad_BTC/mirsad/engines/decision.py`
- `Mirsad_BTC/mirsad/engines/indicators.py`
- `Mirsad_BTC/mirsad/engines/market.py`
- `Mirsad_BTC/mirsad/engines/market_intelligence.py`
- `Mirsad_BTC/mirsad/engines/mt5_bridge.py`
- `Mirsad_BTC/mirsad/engines/mt5_chart_candles.py`
- `Mirsad_BTC/mirsad/engines/mt5_market.py`
- `Mirsad_BTC/mirsad/engines/mt5_native_indicators.py`
- `Mirsad_BTC/mirsad/engines/mt5_price_action.py`
- `Mirsad_BTC/mirsad/engines/position_ledger.py`
- `Mirsad_BTC/mirsad/engines/position_management.py`
- `Mirsad_BTC/mirsad/engines/visual_knowledge.py`

### خبراء MT5 وتوثيقها
- `Mirsad_BTC/mt5/BitcoinIntelligence_ReadOnlyBridge.mq5`
- `Mirsad_BTC/mt5/CHART_OBSERVER_DESIGN_AR.md`
- `Mirsad_BTC/mt5/INSTALL_AR.md`
- `Mirsad_BTC/mt5/INSTALL_CHART_OBSERVER_AR.md`
- `Mirsad_BTC/mt5/Mirsad_BTC_ExecutionBridge.mq5`
- `Mirsad_BTC/mt5/Mirsad_ChartObserver.mq5`

### بروتوكولات البيانات
- `Mirsad_BTC/protocol/MIR-CHART-OBSERVATION-1.schema.json`
- `Mirsad_BTC/protocol/MIR1_PROTOCOL_AR.md`

### التقارير
- `Mirsad_BTC/reports/BRANCH_INTEGRATION_REPORT_AR_20261103.md`
- `Mirsad_BTC/reports/DASHBOARD_HEALTH_CENTER_AR.md`
- `Mirsad_BTC/reports/DECISION_WEIGHT_CALIBRATION_AR_20261104.md`
- `Mirsad_BTC/reports/DESKTOP_COMPLETION_NOTEBOOK_AR.md`
- `Mirsad_BTC/reports/ENGINE1_MARKET_INTELLIGENCE_COMPLETION_AR_20261104.md`
- `Mirsad_BTC/reports/ENGINE2_FULL_REDESIGN_BLUEPRINT_AR_20261102.md`
- `Mirsad_BTC/reports/ENGINE2_NATIVE_MT5_DIRECT_FEED_AR_20261103.md`
- `Mirsad_BTC/reports/ENGINE2_NATIVE_OHLC_COMPLETION_REPORT_AR_20261103.md`
- `Mirsad_BTC/reports/ENGINE2_REMAINING_WORK_COMPLETION_PLAN_AR_20261103.md`
- `Mirsad_BTC/reports/ENGINE2_ROOT_REDESIGN_BLUEPRINT_AR_20261103.md`
- `Mirsad_BTC/reports/ENGINE3_INDICATORS_PROGRESS_AR_20261103.md`
- `Mirsad_BTC/reports/ENGINE3_LIVE_PARITY_COMPLETION_AR_20261104.md`
- `Mirsad_BTC/reports/ENGINE_READINESS_AUDIT_AR_20261104.md`
- `Mirsad_BTC/reports/ENGINE_WEIGHT_PROFILE_V6_AR_20261104.md`
- `Mirsad_BTC/reports/FULL_PROGRAM_AUDIT_AND_REPAIR_PLAN_AR_20261104.md`
- `Mirsad_BTC/reports/MIRSAD_AUTOMATION_REVIEW_AR_20261103_0824.md`
- `Mirsad_BTC/reports/MIRSAD_ENGINE_AUDIT_AR_20261103.md`
- `Mirsad_BTC/reports/MIRSAD_INTEGRATION_DIAGNOSTIC_AR_20261103_0928.md`
- `Mirsad_BTC/reports/MIRSAD_PROGRESS_REPORT_AR_20261102.md`
- `Mirsad_BTC/reports/MIRSAD_RUN_STATUS_AR_20261103.md`
- `Mirsad_BTC/reports/MIRSAD_WORK_SESSION_UPDATE_AR_20261103_2030.md`
- `Mirsad_BTC/reports/MIRSAD_WORK_SESSION_UPDATE_AR_20261103_2032.md`
- `Mirsad_BTC/reports/SYNCHRONIZED_ENGINE_READINESS_AR_20261103.md`
- `Mirsad_BTC/reports/WORK_SESSION_START_AR_20261103.md`

### السكربتات
- `Mirsad_BTC/scripts/analyze_mt5_native_price_action.py`
- `Mirsad_BTC/scripts/live_smoke.py`
- `Mirsad_BTC/scripts/mirsad_mt5_demo_compile.ps1`
- `Mirsad_BTC/scripts/mirsad_mt5_direct_feed_run.ps1`
- `Mirsad_BTC/scripts/mirsad_mt5_execution_acceptance.py`
- `Mirsad_BTC/scripts/mirsad_mt5_execution_run.ps1`
- `Mirsad_BTC/scripts/mirsad_mt5_integrated_runtime_run.ps1`
- `Mirsad_BTC/scripts/mirsad_mt5_observer_run.ps1`
- `Mirsad_BTC/scripts/mirsad_runtime_integration_check.py`
- `Mirsad_BTC/scripts/run_structure_study.py`
- `Mirsad_BTC/scripts/validate_engine1_live_sources.py`
- `Mirsad_BTC/scripts/validate_engine2_public_btc.py`
- `Mirsad_BTC/scripts/validate_engine3_mt5_indicator_parity.py`
- `Mirsad_BTC/scripts/validate_mt5_direct_feed.py`

### الاختبارات والبيانات
- `Mirsad_BTC/tests/data/public_chart_manifest.json`
- `Mirsad_BTC/tests/test_chart_classical_patterns.py`
- `Mirsad_BTC/tests/test_chart_continuation_patterns.py`
- `Mirsad_BTC/tests/test_chart_multi_timeframe.py`
- `Mirsad_BTC/tests/test_chart_multi_timeframe_storage.py`
- `Mirsad_BTC/tests/test_chart_pattern_evaluation.py`
- `Mirsad_BTC/tests/test_chart_pattern_knowledge.py`
- `Mirsad_BTC/tests/test_chart_structure_evaluation.py`
- `Mirsad_BTC/tests/test_chart_structure_knowledge.py`
- `Mirsad_BTC/tests/test_daily_risk.py`
- `Mirsad_BTC/tests/test_dashboard_health.py`
- `Mirsad_BTC/tests/test_decision_calibration_storage.py`
- `Mirsad_BTC/tests/test_direct_feed_validator.py`
- `Mirsad_BTC/tests/test_engine2_public_btc_validation.py`
- `Mirsad_BTC/tests/test_engine3_mt5_indicator_parity.py`
- `Mirsad_BTC/tests/test_engine_contracts.py`
- `Mirsad_BTC/tests/test_execution_acceptance.py`
- `Mirsad_BTC/tests/test_indicators.py`
- `Mirsad_BTC/tests/test_market_candle_timezones.py`
- `Mirsad_BTC/tests/test_market_intelligence.py`
- `Mirsad_BTC/tests/test_mt5_chart_candles.py`
- `Mirsad_BTC/tests/test_mt5_deal_ledger.py`
- `Mirsad_BTC/tests/test_mt5_market.py`
- `Mirsad_BTC/tests/test_mt5_native_indicators.py`
- `Mirsad_BTC/tests/test_mt5_observer.py`
- `Mirsad_BTC/tests/test_mt5_observer_engine2_integration.py`
- `Mirsad_BTC/tests/test_mt5_price_action.py`
- `Mirsad_BTC/tests/test_position_ledger.py`
- `Mirsad_BTC/tests/test_position_management.py`
- `Mirsad_BTC/tests/test_run_structure_study.py`
- `Mirsad_BTC/tests/test_runtime_integration_check.py`
- `Mirsad_BTC/tests/test_runtime_observer_flow.py`
- `Mirsad_BTC/tests/test_validate_engine1_live_sources.py`
- `Mirsad_BTC/tests/test_visual_knowledge.py`
- `Mirsad_BTC/tests/test_weight_profile_v6.py`

## مسارات GitHub Actions الخاصة بمرصاد
- `.github/workflows/mirsad-btc-live-validation.yml`
- `.github/workflows/mirsad-btc-mt5-demo.yml`
- `.github/workflows/mirsad-btc-mt5-execution.yml`
- `.github/workflows/mirsad-chart-observer-compile.yml`
- `.github/workflows/mirsad-direct-feed-validation.yml`
- `.github/workflows/mirsad-engine2-native-analysis.yml`
- `.github/workflows/mirsad-engine2-public-btc-validation.yml`
- `.github/workflows/mirsad-live-runtime-integration.yml`
- `.github/workflows/mirsad-mt5-observer-demo.yml`
