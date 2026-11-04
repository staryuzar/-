# نقطة استئناف مرصاد BTC — آخر تحديث 4 نوفمبر 2026

## المستودع والفرع
- Repository: `staryuzar/-`
- فرع العمل الوحيد: `mini`
- آخر SHA للشيفرة التي اجتازت الاختبارات وMT5 compile: `a0461b13ecd71abeb0a2e95c6659c988187f16c3`؛ قد يكون HEAD الحالي أحدث بسبب تحديثات وثائقية.
- اقرأ أولاً [سياق المشروع الدائم](MIRSAD_BTC_PROJECT_CONTEXT_AR.md) و[تقرير التدقيق التنفيذي](../Mirsad_BTC/reports/ENGINE_READINESS_AUDIT_AR_20261104.md).

## ما أُصلح في آخر التحديث
1. توحيد تشخيص أوزان E4 إلى 20/55/25 وإضافة اختبار.
2. إضافة بوابة E4 لتغطية الاتجاه الصريح في أطر E2: `directional_frame_coverage >= 0.60`، مع إدخالها في جودة تصويت E2.
3. جعل E5 يفشل مغلقاً إذا كانت قائمة مراكز MT5 مفقودة أو مشوهة.
4. إضافة حواجز EA لحسابات MT5 NETTING/EXCHANGE: منع فتح تعرض جديد فوق مركز/أمر قائم للرمز، والتحقق من تاريخ المركز قبل CLOSE/MODIFY، مع telemetry لنمط الحساب.

## نتائج SHA الحالي
- [Live Data Validation](https://github.com/staryuzar/-/actions/runs/41827798841): SUCCESS، **364/364 tests**.
- [Engine 2 Native OHLC](https://github.com/staryuzar/-/actions/runs/41827798966): SUCCESS.
- [Integrated five-engine MT5 runtime](https://github.com/staryuzar/-/actions/runs/41827798804): SUCCESS؛ EA compile صفر أخطاء/تحذيرات، Observer وExecutionBridge على Common Files مشترك، heartbeat حي، deal history صالح.
- [MT5 EA compile/heartbeat](https://github.com/staryuzar/-/actions/runs/41827798967): SUCCESS؛ compile صفر أخطاء/تحذيرات وheartbeat في وضع read-only.

## النتيجة الحية الدقيقة
في آخر دورة التكامل: E1 READY، E2 READY لكن `MIXED_TIMEFRAME_DIRECTIONS`، E3 READY، E4 WAITING_FOR_ENGINE_2، E5 CONNECTED؛ `action=WAIT`، `entry-eligible=False`، `validated MIR1 envelopes=0`. لم يرسل harness التكامل أمراً للوسيط. هذه دورة ناجحة آمنة وليست اختباراً لدخول طبيعي مكتمل.

## النواقص المثبتة التي تمنع اعتماد 100%
- لا توجد بعد دورة طبيعية من إشارة سوق مؤهلة E4 → MIR1 → ACK → مركز MT5 مطابق → مصالحة صفقة مكتملة.
- لا توجد معايرة خارج العينة مع رسوم وعمولة وانزلاق وبيانات زمنية محفوظة.
- لا يوجد runtime دائم بعد انتهاء GitHub Windows runner؛ بيئة Linux لـLive Validation لا تملك `MIRSAD_MT5_COMMON_FILES` ولذلك تبلغ E5 `NOT_CONFIGURED` هناك، بينما تكامل Windows أثبت اتصاله في بيئته.
- Trading Economics غير مهيأ وبعض endpoints للمشتقات محجوبة في GitHub runner؛ E1 فحص ثلاث مكونات اتجاهية بنجاح لكن لا يصح ادعاء اكتمال جميع المزودات.
- E3 parity 120/120 يثبت المطابقة الحسابية مع MT5 على بيانات متزامنة، وليس ربحية المؤشرات.

## فصل الأعمال: ما يُنجز في GitHub الآن وما يُؤجّل للتثبيت المحلي

### أ. أعمال GitHub المسموح والمنطقي إنجازها الآن
1. **E1 — موثوقية المصادر:** مراجعة تكاملات الأخبار والتقويم وFunding وLong/Short، إضافة بدائل للمصادر التي تحجب runner عند الحاجة، وفصل حالة كل مزود وتوقيت آخر بياناته. لا تُضاف مفاتيح API إلى الملفات؛ تستخدم GitHub Secrets اختيارياً. تبقى المصادر الاختيارية غير المهيأة ظاهرة كـNOT_CONFIGURED ولا تتحول إلى بيانات متخيلة.
2. **E2 — تغطية OHLC:** توسيع اختبارات الفجوات والشموع المغلقة والقمم/القيعان وBOS/CHOCH والأنماط وتعارض الأطر باستخدام fixtures وبيانات تاريخية موثقة. لا تُخفّض عتبة البنية ولا بوابة التغطية 0.60 لإجبار قرار.
3. **E3 — المؤشرات:** توسيع اختبارات جميع العائلات والأطر والبيانات الناقصة والتوقيت، وحفظ تكافؤ MT5 كاختبار انحدار. أي دراسة على بيانات بديلة تُوسم بوضوح ولا تُسمى MT5 parity.
4. **E4 — القرار والمخاطر:** اختبار جميع حالات القرار وحدود التغطية وجودة الأدلة وحجم العقد والوقف وإدارة المركز، باستخدام mocks/fixtures فقط ودون بث أوامر للوسيط. لا تغيير للأوزان أو حدود المخاطر دون نتيجة بحث موثقة ومراجعة.
5. **E5 — البروتوكول:** اختبار MIR1 وACK والرفض وانتهاء الصلاحية والتكرار وإعادة التشغيل والمصالحة باستخدام جسر محاكى وملفات Common Files اختبارية. يُسمح بترجمة EA وفحص heartbeat read-only؛ لا تُشغّل BUY/CLOSE acceptance كاختبار آلي.
6. **المعايرة التاريخية:** بناء/تحسين مسار walk-forward زمني مع train/validation/test منفصلة وembargo ومنع التسرب، وإضافة spread/commission/slippage كمدخلات صريحة. لا تُعلن أفضلية إحصائية قبل وجود بيانات كافية وتقرير نتائج قابل لإعادة الإنتاج.
7. **التشغيل والتوثيق:** تحسين health checks، سجلات التشخيص، إدارة الإعدادات والأسرار، اختبارات بدء التشغيل، وتوثيق خطوات التثبيت والاستعادة. يمكن اختبار البناء على Windows runner، لكن لا يثبت ذلك استمرار تشغيل جهاز المستخدم.

### ب. أعمال تتطلب MT5 وجهاز Windows المحلي وتؤجل إلى ما بعد التثبيت
1. تحديد مسار `Terminal\\Common\\Files` الحقيقي وربط `MIRSAD_MT5_COMMON_FILES` به والتحقق من ملفات status/market/positions/ack على الطرفية المحلية.
2. التحقق من الرمز الفعلي لدى الوسيط ومواصفات العقد وحجم الخطوة والحدود والسبريد ووقت الخادم ونمط الحساب NETTING/HEDGING وصلاحيات Algo Trading.
3. تشغيل Observer وExecutionBridge على الطرفية المحلية والتحقق من استمرار heartbeat وتحديث الأسعار والشموع والمؤشرات عند تشغيل الجهاز.
4. التحقق من دورة MIR1 → ACK → تأكيد المركز → سجل الصفقات → المصالحة → الإغلاق على بيئة الحساب المقصودة، بعد وجود إشارة مؤهلة وبلا اصطناع إشارة أو تجاوز بوابة E2. لا تُعتبر اختبارات GitHub المؤقتة بديلاً عن هذا الإثبات المحلي.
5. إعداد التشغيل المستمر وإعادة التشغيل التلقائي ومراقبة انقطاع MT5 والشبكة على جهاز Windows المستهدف.
6. إعادة التحقق من تكاليف الوسيط الفعلية والانزلاق والتنفيذ؛ تستخدم نتائجها لاحقاً لتأكيد المعايرة التاريخية.

### ج. حدود لا يجوز تجاوزها أثناء المسارين
- لا تُعدّل خارج فرع `mini`.
- لا تخفض بوابة E2 لتوليد صفقة؛ MIXED أو غير المؤهل = WAIT.
- لا تجعل E1 يكرر عمل E2/E3 ولا تجعل E5 يصوت اتجاهياً.
- لا تغيّر `RISK_PER_TRADE=0.005` أو حد الخسارة اليومي أو مفاتيح النشر والتنفيذ ضمن أعمال الفصل هذه.
- لا تضع أسراراً أو بيانات حساب في Git أو artifacts أو تقارير عامة.
- لا تُشغّل BUY/CLOSE acceptance كاختبار شكلي ولا ترسل أوامر وسيط من CI بغرض جعل الاختبار أخضر.
- لا تستخدم نسب جاهزية مئوية تقديرية؛ اعرض لكل محرك أدلة الكود والاختبارات والبيانات والتشغيل والنواقص منفصلة.

## قواعد مواصلة العمل
- لا تعدل خارج فرع `mini`.
- لا تخفض بوابة E2 لتوليد صفقة؛ MIXED أو غير المؤهل = WAIT.
- لا تجعل E1 يكرر عمل E2/E3 ولا تجعل E5 يصوت اتجاهياً.
- لا تغيّر إعدادات المخاطر أو مفاتيح النشر والتنفيذ دون توجيه.
- لا تستخدم نسب جاهزية مئوية قديمة؛ اعرض أدلة الاختبار والتشغيل والنواقص صراحة.
- لا تشغل BUY/CLOSE acceptance كاختبار شكلي؛ هذا المسار قد يرسل أوامر للوسيط.


## تحديث القبول الشامل — 4 نوفمبر 2026 — SHA `515f56a`

- آخر رأس فرع عند التوثيق: `515f56aebad56514e02518a6564f9ebf3d0e2df9`.
- **Live Data Validation:** نجح **366/366 اختباراً** على SHA `7519521d0734f536e94ecc36bb7a751d1c67066a`. يتضمن ذلك اختبار E1→E5 لمحاكاة BUY ثم MIR1 وACK ونبضة MT5 لاحقة وتأكيد المركز؛ واختبار SELL وإنشاء MIR1؛ واختبار تعارض أطر E2 الذي يجب أن ينتج WAIT بلا `command.json`.
- [سجل 366 اختباراً — Live Data Validation](https://github.com/staryuzar/-/actions/runs/41832459018).
- [اختبارات OHLC للمحرك الثاني](https://github.com/staryuzar/-/actions/runs/41832459080): SUCCESS.
- [أول بوابة قبول كاملة — PASS](https://github.com/staryuzar/-/actions/runs/41831584563) على SHA `a5f245eee06f2678f9c14aced40c1d0de5a0e475`: البناء وكل الاختبارات، التحقق المستقل لبيانات BTC، MT5 direct feed read-only، وتكامل المحركات الخمسة؛ final acceptance artifact سجل PASS. هذه النسخة كانت قبل إضافة سيناريو SELL/WAIT وقبل قفل خادم الحساب في اختبار الوسيط.
- التحقق الحي لـMT5 في البوابة الأولى: Observer read-only، صور معطلة، OHLC أصلي على الأطر الستة، وE3 parity **120/120**. كان E2 `MIXED_TIMEFRAME_DIRECTIONS` مع 3 أطر اتجاهية و3 مختلطة؛ لذا E4 أعاد `WAIT` ولم يرسل أمرًا. هذا نجاح سلامة وليس إشارة دخول.
- بيانات E1 في فحص المصدر: 112 خبرًا حديثًا من 4 مصادر؛ Fear & Greed والتقويم العام وglobal metrics جاهزة؛ OKX وGate.io مشتقات جاهزة، بينما Binance واجه HTTP 451 وBybit HTTP 403، وTrading Economics غير مهيأ. لا تُسجل هذه المزودات غير المتاحة على أنها جاهزة.
- دراسة BTC العامة على 3,000 شمعة ساعة: 191 حدثًا، Train 128 / Validation 28 / Test 35. `empirical_status=UNVALIDATED` و`costs_applied=false`؛ لا تستخدم هذه العينة لتعديل الأوزان أو ادعاء الربحية.
- أُضيف سير القبول الشامل `.github/workflows/mirsad-btc-full-acceptance.yml`، ويجمع build+كل الاختبارات، public BTC, direct feed MT5 read-only، والتكامل الخماسي على مجلد Common Files واحد. نتيجته PASS تعني اتساق هذه الطبقات فقط؛ لا تعني أن لقطة السوق مؤهلة لدخول.
- أُضيف قفل لحساب اختبار الوسيط في `mirsad_mt5_execution_run.ps1`: اختبار BUY/CLOSE لا يُسمح له بالعمل إلا عبر المضيف `mt5.demo.trade-hw.online` ومع تأكيد telemetry أن خادم الحساب هو `Headway-Demo`. أمر الاختبار محدود بـ0.5% من حقوق الحساب وبقيمة اسمية قصوى 1,000 USD، ويرفض المتابعة إذا كان هناك مركز BTC قائم. يستخدم Magic مرصاد ويؤكد الإغلاق ومصالحة سجل الصفقات.
- [تشغيل قبول الوسيط المقيد لمرة واحدة](https://github.com/staryuzar/-/actions/runs/41832938582) على SHA `515f56a`: **تحقق من نتيجته قبل أي ادعاء**. لا تعتبر فتح/إغلاق الصفقة مكتملاً إلا إذا انتهى التشغيل SUCCESS وأظهر DEAL cycle CLOSED وentry/exit counts.
- [بوابة القبول الشاملة بعد قفل حساب الاختبار](https://github.com/staryuzar/-/actions/runs/41832938347) على SHA `515f56a`: انتهت **FAIL**؛ الوظائف الثلاث الأولى نجحت، لكن وظيفة التكامل الخماسي داخل هذا الـworkflow أعادت engine5/terminal/execution permissions=false رغم نجاح قراءة telemetry في PowerShell. السبب الدقيق لم يُثبت بعد.
- [التكامل الخماسي بعد قفل حساب الاختبار](https://github.com/staryuzar/-/actions/runs/41832938246) على SHA `515f56a`: **SUCCESS**؛ E1 READY، E2 READY لكن MIXED_TIMEFRAME_DIRECTIONS، E3 READY، E4 WAITING_FOR_ENGINE_2، E5 CONNECTED، action=WAIT، entry-eligible=false. لا توجد صفقة/إشارة مؤهلة في تلك اللقطة، وهذا انتظار آمن.

## لا يزال غير مثبت
1. المعايرة الإحصائية خارج العينة بعد الرسوم والعمولة والانزلاق وبيانات وسيط حقيقية متنوعة.
2. استمرارية خدمة runtime بعد انتهاء Windows runner؛ Runner GitHub مؤقت ولا يثبت تشغيلًا دائمًا.
3. التثبيت على Windows المحلي، مسار Common Files المحلي، والتحقق من حساب MT5 الفعلي بعد التثبيت.
4. تأكيد الدورة الحية على الوسيط من BUY/ACK ومركز ومصالحة ثم CLOSE وسجل deal مغلق — استخدم نتيجة التشغيل المقيد أعلاه، ولا تخلطها بالاختبار المحاكى.
5. الأوزان v6.1 ما تزال baseline تشغيلية وليست أمثلية مثبتة.

**لا تغيّر** أوزان 20/55/25 أو عتبات E2 أو `RISK_PER_TRADE=0.005` أو حد الخسارة اليومية أو مفاتيح النشر والتنفيذ أثناء متابعة هذه الاختبارات. لا تُشغّل اختبار وسيط آخر بالتوازي مع قبول BUY/CLOSE المقيد.

## تحديث حالة التحقق بعد إغلاق تشغيل Headway — 4 نوفمبر 2026

- رأس الفرع الوثائقي الحالي: `88d2b6172d97a1921c4543910175ac7f68e58fe9`؛ آخر تغيير برمجي تشغيلي لاختبار الوسيط: `515f56aebad56514e02518a6564f9ebf3d0e2df9`.
- [Live Data Validation على 515f56a](https://github.com/staryuzar/-/actions/runs/41832938223): SUCCESS، **366/366**.
- [MT5 broker acceptance على 515f56a](https://github.com/staryuzar/-/actions/runs/41832938582): SUCCESS. تحقق المضيف `mt5.demo.trade-hw.online` وهوية الحساب `Headway-Demo`، EA compile صفر أخطاء/تحذيرات، heartbeat وصلاحيات التداول سليمة؛ جسر Python نشر BUY ثم CLOSE؛ سجل broker deal history أثبت entry+exit لنفس position_id؛ الصافي `-0.28 USD` ولا بقي مركز اختبار مفتوح. هذه الصفقة كانت على MT5 Windows runner سحابي مؤقت، لا على جهاز المستخدم.
- [Integrated five-engine MT5 Runtime على 515f56a](https://github.com/staryuzar/-/actions/runs/41832938246): SUCCESS؛ E1 READY، E2 READY/MIXED، E3 READY، E4 WAITING_FOR_ENGINE_2، E5 CONNECTED، action=WAIT، no MIR1 envelope. لا يجوز اعتبار WAIT فشلًا ولا اعتباره دخولًا.
- [Full Program Acceptance على 515f56a](https://github.com/staryuzar/-/actions/runs/41832938347): **FAIL** رغم نجاح jobs الخاصة بالاختبارات، public BTC، وMT5 direct-feed. وظيفة integrated runtime داخل هذا الـworkflow فقط رأت `engine5_bridge_connected=false`, `mt5_terminal_connected=false`, `mt5_execution_permissions_enabled=false`, و`engine5_command_gate_ready=false` مع أن PowerShell قبلها أكد heartbeat والصلاحيات والملفات المشتركة. وظيفة التكامل المنفصلة على الالتزام نفسه نجحت. هذا تناقض تشخيص/توقيت أو مسار قراءة لم يُحسم؛ لا تحوّله إلى PASS، وأضف telemetry تشخيصية ثم أصلحه وأعد تشغيل Full Program Acceptance.
- آخر عينة BTC العامة في البوابة: 3,000 شمعة ساعة، 191 حدثًا، Train 128 / Validation 28 / Test 35، `empirical_status=UNVALIDATED`. هذا لا يثبت edge تداولية.
- الحالة الحالية لكل محرك: E1 مزوداته الأساسية تصل جزئيًا مع مزودين للمشتقات محجوبين وTrading Economics غير مهيأ؛ E2 يعمل تحليلًا على 6 أطر لكن اللقطة الحية Mixed وغير مؤهلة للدخول؛ E3 READY ومطابقة CopyBuffer 120/120 في الفحص الحي؛ E4 يجتاز سيناريوهات BUY/SELL/WAIT ومصالحة القرار المحاكية لكنه ينتظر E2 في اللقطة الحية؛ E5 اجتاز اتصال MT5 السحابي واختبار BUY/CLOSE ومصالحة الصفقة.
- لا يزال غير مثبت: runtime مستمر على الجهاز المحلي، اختبار نفس بيئة Windows/MT5 للمستخدم، ومعايرة خارج العينة بعد spread/commission/slippage. لا تستخدم نسب مئوية تقديرية.
