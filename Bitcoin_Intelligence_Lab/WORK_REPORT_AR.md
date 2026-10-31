# تقرير حالة العمل — Bitcoin Intelligence Lab

**تاريخ التقرير:** 31 أكتوبر 2026  
**المستودع:** [staryuzar/-](https://github.com/staryuzar/-)  
**الفرع:** `bitcoin-intelligence-lab`  
**طلب المراجعة:** [PR #9 — Draft](https://github.com/staryuzar/-/pull/9)  
**أحدث تحقق كامل لخط التنفيذ والخبير:** `7ee7ce624802e99db02920c95717ced6b406e8ae` (CI #63852؛ **259 اختباراً ناجحاً على Python 3.12 و259 على Python 3.13**، وWindows Runtime #63881 نجح في اختبارات Windows وتجميع EA الحقيقي بـMetaEditor بصفر أخطاء/تحذيرات وتشغيل WebSocket/SQLite/Streamlit). رأس الفرع الأحدث `03a20b5b9e0e53b3d8d3c20b5f0261b424ae5151` يتضمن فقط توثيق المعمارية بعد تضييق إشارة اكتمال أمر الوسيط إلى ORDER_DELETE، وإعادة CI/Windows الخاصة به ما زالت جارية.

---

## 1. القرار التنفيذي المعتمد

تم توصيل Headway عبر MT5 بطبقة تنفيذ مستقلة بعد اكتمال تدقيق المحركات واللوحة الأساسي. اللوحة لا تنشر الأوامر؛ تعرض حالة الخبير والمراكز وإقرار الوسيط للقراءة فقط. العملية `bitcoinlab.execution_loop` تقرأ قرار المركز وتنشر أوامر OPEN/CLOSE إلى MT5 Common Files، والخبير MQL5 هو المنفذ الوحيد.

- لا يفحص الجسر أو EA تصنيف الحساب أو يخزنه. التحقق يقتصر على هوية خادم Headway، الاتصال وصلاحية التنفيذ، حداثة الأسعار، وصحة الرمز والحجم والوقف.
- EA لا ينشئ إشارات على OnTick؛ القرار المركزي فقط يوجه الأوامر. HOLD لا يغلق مركزاً، وقرار الاتجاه الموافق لا يفتح تكراراً، والانعكاس يطلب إغلاق التذكرة التابعة لـMagicNumber أولاً.
- الحد الافتراضي لخسارة المركز الواحدة 0.5% من Equity وفق OrderCalcProfit، ومركز واحد للخبير، وحجم أمر افتراضي 0.01 لوت مع تحقق broker min/max/step.
- الحلقة مستقلة عن Streamlit ولا تبدأ إلا عند تعيين BTCIL_ENABLE_EXECUTION=1 على الجهاز الذي تعمل عليه MT5.
- لا توجد حتى الآن صفقة فعلية مؤكدة من هذه النسخة على طرفية مستخدم دائمة؛ اختبار Windows على GitHub مؤقت ومخصص للتجميع والتكامل، وليس جلسة متابعة مستمرة. جهاز Windows المتاح عبر Remote Desktop كان Offline عند آخر تحقق.
- Binance وBybit وOKX وDeribit مصادر بيانات فقط؛ Headway عبر MT5 هو وسيط التنفيذ الوحيد.

## 2. حالة GitHub والاختبارات

- الفرع المستقل: `bitcoin-intelligence-lab`.
- PR #9 مفتوح وDraft ولم يُدمج في الفرع الرئيسي.
- حالة PR عند تحديث هذا التقرير: 93 ملفاً متغيراً في الفرع المستقل.
- آخر commit برمجي اختُبر بالكامل: `8bec8939280736eafb1e8e893f21fde5785f898a`.
- بعد إضافة اختبارات مراقبة تدفق الصفقات وتحديث عرض صحة الاتصالات في اللوحة، نجح CI #345 ثم #347/#348 بعدد **221 اختباراً ناجحاً على Python 3.12 و221 على Python 3.13** في كل تشغيل نهائي.
- CI رقم **#340** نجح على Python 3.12 و3.13، وشغّل **219 اختباراً ناجحاً** لكل إصدار.
- شملت CI: Compile package، واختبارات المحركات والموائمات، وبدء Streamlit smoke test، وفحص مصادر BTC العامة الحية، والتحقق من عدم وجود APIs تنفيذ تداول في موائمات Python.
- الاختبار #328 شمل آخر إضافة Screener ووصلتها إلى مركز القرار. اجتازت الحزمة تجميع Python، واختبارات المحركات، وبدء Streamlit، وفحص مصادر BTC العامة الحية، وفحص عدم وجود واجهات تنفيذ تداول.

رابط CI الناجح:  
https://github.com/staryuzar/-/actions/runs/41158793678

### 2.1 فحص لقطة السوق الحقيقية المرفقة بـ CI #340

أُرفق artifact باسم `bitcoin-live-market-check`، وكانت اللقطة عند `2026-10-31T02:11:06Z` بحالة **partial**، وليس اكتمالاً لجميع مصادر السوق:

- Spot من Binance كان حديثاً، مع تغطية الأطر الزمنية الستة 1D/4H/1H/15M/5M/1M.
- عينة Orderflow REST وبنية السوق كانتا حديثتين وقت الفحص.
- مشتقات Binance أعادت HTTP 451، ومشتقات Bybit أعادت HTTP 403؛ لذلك بقي مجال المشتقات الأساسي غير متاح.
- سياق المشتقات متعددة المنصات احتوى منصة واحدة فقط هي OKX SWAP، ولم تتوفر دفاتر أوامر متعددة المنصات في اللقطة.
- CVD المتدفق لم يكن جاهزاً لأنه لم توجد منصتان حديثتان مستوفيتان لحد العينة.
- قاعدة جامع WebSocket وقراءات Trade Analytics وعمق السيولة وخريطة التصفية أظهرت `not_started`؛ أي أن هذا الفحص لم يشغّل جامع WebSocket المستمر.

**تنبيه تفسير CI:** خطوة فحص APIs العامة معرفة في Workflow على أنها `continue-on-error: true`. لذلك نجاح CI #340 يثبت نجاح الاختبارات وتجميع الحزمة وتشغيل Streamlit، لكنه لا يعني أن كل مزودي السوق متاحون أو أن WebSocket يعمل باستمرار.

### 2.2 تحسينات مراقبة الاتصال واللوحة — 31 أكتوبر 2026

- عُدّل `feed_health.py` لتمييز أنواع القنوات: دفاتر أوامر، صفقات، وتصفيات.
- صمت قناة التصفية مع heartbeat حديث يبقى `connected_quiet_ok`، لأن التصفيات أحداث متقطعة.
- تدفق صفقات BTC عالي التردد: إذا تجاوز عمر آخر صفقة 45 ثانية، يصنف `stale` حتى لو ظل heartbeat حياً؛ فلا يُخلط اتصال WebSocket بتدفق بيانات فعلي.
- أضيف اختباران لهذا التمييز، وصار مجموع الاختبارات **221** لكل من Python 3.12 و3.13.
- حدّثت اللوحة لعرض عدد تدفقات الصفقات الحية منفصلاً عن قنوات التصفية المتصلة دون أحداث، ولإظهار نوع كل مصدر في تفاصيل WebSocket.

روابط التحقق بعد الإصلاح:
- [CI #345 — 221 اختباراً على الإصدارين](https://github.com/staryuzar/-/actions/runs/41160035793)
- [CI #347 — نسخة الفرع بعد تحديث اللوحة](https://github.com/staryuzar/-/actions/runs/41160072345)
- [CI #348 — فحص PR بعد تحديث اللوحة](https://github.com/staryuzar/-/actions/runs/41160075991)
- [آخر commit برمجي مختبر](https://github.com/staryuzar/-/commit/8bec8939280736eafb1e8e893f21fde5785f898a)

### 2.3 تدقيق حداثة التصويت الفني في مركز القرار — 31 أكتوبر 2026

- عُدّل `decision.py` كي لا يقبل أي مجال تصويت — بما في ذلك Technical / Multi-Timeframe — إلا إذا كانت حالة مصدره صريحة `fresh`.
- أضاف `live_snapshot.py` حالة مستقلة للمجال الفني تعرض عدد الأطر الحديثة، وعدد الأطر المطلوبة، وأسباب التعذر؛ ولا يعتمد المركز على أن تكون درجة المحرك موجودة فقط.
- عند تقادم/غياب حالة مصدر المجال الفني، يُرجع المركز `HOLD` مع مانع `technical_source_not_fresh` بدلاً من احتساب الدرجة القديمة.
- أضيف اختبار يثبت أن إشارة فنية صالحة شكلياً لكنها متقادمة لا تصوّت. وعُدّلت fixture لاختبار المجالات الأساسية حتى يعزل اختبار نقص Orderflow/Derivatives بدقة.
- نجح CI #358 على Python 3.12 و3.13: **222 اختباراً لكل إصدار**، مع نجاح Compile package وStreamlit health smoke test والتحقق من عدم وجود واجهات تنفيذ تداول في وحدات Python.
- رابط التشغيل: https://github.com/staryuzar/-/actions/runs/41160436165

### 2.4 فحص السوق الحي المرفق بـ CI #358

- وقت اللقطة: `2026-10-31T02:32:34Z`، والحالة العامة `partial`.
- Binance Spot حديث، والأطر الستة 1D/4H/1H/15M/5M/1M حديثة؛ ومجالا Orderflow وMarket Structure حديثان.
- Binance USDⓈ-M أعاد HTTP 451، وBybit Futures أعاد HTTP 403؛ لذلك مجال المشتقات غير متاح في اللقطة. سياق المشتقات متعدد المنصات احتوى OKX SWAP فقط، ودفاتر الأوامر متعددة المنصات لم تستوفِ شرط الحد الأدنى.
- مركز القرار أعاد `SELL` بدرجة اتجاهية `-0.370204` اعتماداً على Technical وOrderflow وMarket Structure فقط، مع إبقاء نقص المشتقات وتغطية Cross-Venue في التحذيرات. هذه قراءة سوق لحظية وليست صفقة منفذة أو احتمال ربح.
- فحص APIs العامة في Workflow ما زال `continue-on-error`; لذلك نجاح CI يثبت صحة الاختبارات والتشغيل البرمجي ولا يضمن توافر كل مزود سوق.
- لم يُثبت بعد تشغيل WebSocket/SQLite لفترة ممتدة على Windows؛ لا يزال هذا بند تحقق منفصلاً قبل اعتماد البرنامج.

### 2.5 عزل Workflow Aurora عن مشروع البيتكوين — 31 أكتوبر 2026

- خلال التدقيق تبيّن أن المستودع يحتوي Workflow مستقلاً باسم `Aurora Windows validation`، وأن شرط النطاق السابق كان يشغّل مهام Aurora عند تحديث ملفات فرع البيتكوين، رغم أن برنامج Bitcoin Intelligence Lab نفسه لا يستدعي MT5.
- في التشغيل #399، نفّذت وظيفة Aurora المنفصلة `MetaTrader 5 install / assistant launch integration` على GitHub-hosted Windows runner: ثبتت MT5 وشغّلت terminal معزولاً، وأكد سجلها نجاح المصادقة بخادم Headway Demo باستخدام سر Actions المخزن في المستودع. النص الختامي في السجل يقول صراحةً: **No orders were placed**. هذا لم يكن اختباراً لبرنامج Bitcoin Intelligence Lab، ولم يكن ينبغي أن يحدث قبل مرحلة MT5 المؤجلة.
- التشغيل #400 بدأ قبل إضافة الحاجز؛ عند آخر فحص كانت خطوة تثبيت/مصادقة MT5 لا تزال `in_progress`. لا تتوفر في موصل GitHub الحالي أداة إلغاء Workflow جارٍ، لذلك لا أزعم أنني أوقفته. يجب مراجعة هذا التشغيل من صفحة Actions وإلغاؤه يدوياً إذا ظل جارياً.
- أضيف حاجز مبكر إلى `.github/workflows/windows-validation.yml`: أي PR مصدره `bitcoin-intelligence-lab` يضع `run_validation=false`، وبالتالي يتخطى وظائف Aurora Windows وBrowser وMT5. هذا الحاجز يخص التحديثات المستقبلية؛ لا يغير تشغيل #399 المكتمل أو #400 الذي بدأ سابقاً.
- نتيجة التدقيق: Workflow الخاص ببرنامج البيتكوين وحده يظل قراءة فقط ولا يثبت MT5 أو يسجل الدخول إلى Headway. ويجب ألا تدمج أي من نتائج Aurora/MT5 مع نتائج اختبارات Bitcoin Intelligence Lab.

### 2.6 تدقيق استقلال أدلة المجالات الخمسة — 31 أكتوبر 2026

- Orderflow يصوّت على Aggressor/Taker trade delta فقط؛ اختلال دفتر Spot والسبريد يظلان سياقاً، لأن صوت العمق مخصص لمجال Cross-Venue Order Book.
- Market Structure يصوّت على موقع السعر بالنسبة إلى Session VWAP فقط؛ عينة Trade Delta تبقى سياقاً لأنها محسوبة في Orderflow. أضيفت اختبارات تثبت أن تغيير عمق الدفتر لا يغيّر صوت Orderflow، وأن عكس عينة الدلتا لا يغيّر صوت VWAP.
- فصل جلب الصفقات عن جلب دفتر REST؛ تعذر دفتر Spot لا يلغي إشارة الصفقات الحديثة.
- بقيت الأوزان الأساسية كما هي: Technical 35%، Orderflow 25%، Derivatives 20%، Market Structure 10%، Cross-Venue 10%. CVD ما زال مكوّناً داخلياً من Orderflow لا صوتاً سادساً.
- حارس التعارض: تعارض 1D/4H المعتبر يفرض HOLD؛ والقرار العكسي للاتجاه الفني يحتاج ثلاثة مجالات مؤيدة ودرجة مطلقة لا تقل عن 0.25، مع السماح بانعكاس قوي عند تحقق هذا الشرط.
- كل حالات HOLD صارت تعيد عقد بيانات موحداً للوحة: المجالات النشطة والمتاحة، الأوزان، المجالات الأساسية، العدّادات والتحذيرات.

### 2.7 مشتقات OKX كبديل ثالث — 31 أكتوبر 2026

- أضيف `providers/okx.py` لمصدر OKX V5 العام على BTC-USDT-SWAP بعد فشل Binance USDⓈ-M وBybit Linear.
- اتجاه المشتقات من نسبة Taker Buy/Sell للصفقات العامة الحديثة ضمن وحدة العقد نفسها؛ لا يجري تحويل أحجام العقود إلى BTC/USD بلا معامل موثق.
- Funding يميز settled عن current-period estimate، وOI يحفظ وحدات BTC/contracts/USD المنشورة دون جمعها بين المنصات.
- ترتيب fallback: Binance ثم Bybit ثم OKX؛ وتظل المقارنة متعددة المنصات سياقاً غير تصويتي يُرفق بالمحرك حتى بعد استبداله بمصدر احتياطي.
- CI #423 اجتاز **244 اختباراً لكل إصدار**. لقطة السوق في 2026-10-31T02:50:50Z أثبتت قراءة 500 صفقة OKX حديثة، Taker Buy/Sell بنحو 2.17، Funding مستقر 0.01% لكل 8 ساعات وOI المنشور بنحو 34,809 BTC؛ بقيت المقارنة جزئية لأن OKX كانت المنصة الوحيدة المتاحة.

### 2.8 إصلاحات Windows / SQLite / لوحة القراءة — 31 أكتوبر 2026

- كشف أول Windows unit run أخطاء `WinError 32` عند حذف قواعد SQLite المؤقتة؛ السبب أن قارئات SQLite كانت تستخدم `with sqlite3.connect(...)` الذي ينهي المعاملة لكنه لا يغلق الاتصال.
- عُدّلت قارئات `trade_analytics.py` و`liquidation_heatmap.py` و`depth_analytics.py` لاستخدام `contextlib.closing`، مثل قارئ `market_store.py`، لتفريغ الملفات على Windows.
- أضيف إعداد `BTCIL_MARKET_DB` إلى `live_snapshot.py`، بحيث يمكن توجيه جميع قارئات الدفاتر والتصفية والصفقات والعمق إلى قاعدة الجامع نفسها. اختبار Windows يضبط المتغير على `data/windows_runtime.sqlite` التي يكتب إليها الجامع.
- أضيف Workflow مستقل `.github/workflows/bitcoin-intelligence-lab-windows.yml` وسكربت `scripts/windows_runtime_smoke.py` على فرع البيتكوين. يتحقق السكربت من WebSocket حي واحد على الأقل، لقطة دفتر محفوظة، تدفق صفقة محفوظ، WAL وSQLite integrity، وعمل Streamlit وقارئه read-only.
- حُذف ملفا Windows المؤقتان من `main` وأُضيفا إلى `bitcoin-intelligence-lab` فقط؛ والتحقق من الشجرة يؤكد عدم وجودهما على `main`.
- خط الأساس الأحدث الذي اجتاز CI وWindows: [CI #63852](https://github.com/staryuzar/-/actions/runs/41163863852) شغّل **259 اختباراً على كل من Python 3.12 و3.13**، و[Windows Runtime #63881](https://github.com/staryuzar/-/actions/runs/41163863881) اجتاز اختبارات Windows وتجميع EA الفعلي بـMetaEditor (0 أخطاء و0 تحذيرات) وتشغيل الجامع الحي وSQLite وStreamlit وقارئ اللوحة.
- في لقطة Windows Runtime كانت Bybit وOKX قناتي دفاتر/صفقات حية، بينما Binance Spot أعادت HTTP 451؛ استمر الجامع مع المصادر المتاحة، وحُفظت البيانات مع SQLite WAL وسلامة integrity.
- بعد هذا الخط الأساسي أُضيفت مطابقة OrderTicket وتجميع أحجام التعبئة وتمييز partial fill؛ ثم ضُيّق إنهاء أمر الوسيط إلى TRADE_TRANSACTION_ORDER_DELETE فقط. إعادة اختبار هذه النسخة الأحدث جارية عبر [CI #66466](https://github.com/staryuzar/-/actions/runs/41163966466) و[Windows Runtime #66205](https://github.com/staryuzar/-/actions/runs/41163966205).
- إعادة إثبات العزل على خط الأساس: [Aurora #63860](https://github.com/staryuzar/-/actions/runs/41163863860) نجح فحص النطاق وتخطّى وظائف MT5 وChrome وGemini. لا يُخلط هذا مع اختبار EA الخاص بالبيتكوين.

### 2.9 ربط Headway وحلقة التنفيذ ومراقبة ACK — 31 أكتوبر 2026

- أزيل أي اعتماد على نوع الحساب من EA والجسر. ملف الحالة يحوي خادم الوسيط فقط، ولا يحوي Account Trade Mode؛ يقبل الجسر أي خادم يعرّف Headway، ويرفض أي وسيط آخر.
- أضيفت `execution_loop.py` كعملية مستمرة منفصلة: تبني لقطة السوق، تقرأ قرار المركز وحواجزه، تقرأ مراكز MagicNumber الخاص بالخبير ثم تنشر OPEN أو CLOSE. HOLD لا يرسل أمراً ولا يغلق مركزاً.
- التشغيل يتطلب صراحةً `BTCIL_ENABLE_EXECUTION=1`، والدورة كل 30 ثانية افتراضياً. هذا البرنامج يعمل على الجهاز الدائم الذي يشغّل MT5، وليس داخل GitHub runner المؤقت.
- حجم OPEN الافتراضي 0.01 لوت، وSL/TP من ATR وسعر الوسيط، وTTL افتراضي 60 ثانية. EA يتحقق من min/max/step والوقف والسبريد الاختياري وسقف خسارة 0.5% من Equity عبر OrderCalcProfit، ومركز واحد للخبير.
- CLOSE يستهدف تذكرة يملكها EA فقط. معرّف CLOSE idempotent حسب التذكرة والحجم المتبقي، فيمنع التكرار ويتيح إعادة المحاولة بعد إغلاق جزئي.
- أضيف قفل Global Variable في MT5 يمنع أكثر من نسخة من EA بالـMagicNumber/الرمز نفسه من التقاط ملف الأمر المشترك.
- أضيف نبض تنفيذ ذري إلى `execution_loop_status.json` وتقرأه اللوحة مع EA status وpositions وACK المطابق لمعرّف آخر أمر؛ Streamlit يظل قارئاً فقط.
- عُدّل MQL ليحتفظ برقم Order الذي أعاده الوسيط ويقبل فقط أحداث DEAL_ADD المطابقة لذلك الرقم مع الرمز وMagicNumber. يجمع حجم التعبئة، ويرسل حالة انتقالية PARTIAL_FILL_PENDING، ولا يصف الأمر مكتملاً إلا عند اكتمال حجم الطلب أو حذف الأمر من جهة الوسيط. الإغلاق الجزئي يعاد تقييمه من الحجم المتبقي.
- أحدث Windows baseline قبل إعادة التحقق الأخيرة اجتاز تجميع EA الفعلي بـMetaEditor بنتيجة 0 أخطاء و0 تحذيرات. لم يسجل هذا الاختبار دخول Headway أو إرسال أي أمر.
- **لم تُنفذ بعد صفقة فعلية من EA على جلسة MT5 دائمة للمستخدم.** لا يمكن اعتبار نجاح تجميع/اختبار GitHub بمنزلة تسجيل دخول أو أمر منفذ. جهاز Windows المتاح حالياً عبر Remote Desktop كان Offline.

## 3. المحركات التي تم بناؤها

### أ. بيانات السوق الأساسية
- Binance Spot: شموع مكتملة ودفتر أوامر وصفقات مجمعة.
- Binance USDⓈ-M: Funding وOpen Interest وTaker Buy/Sell وتاريخ OI.
- Bybit V5: مشتقات احتياطية عند تقادم أو تعذر مصادر Binance.
- mempool.space: بيانات الشبكة والتعدين والرسوم والـMempool.
- CFTC TFF: تمركز عقود CME Bitcoin وMicro Bitcoin الأسبوعي.
- Coin Metrics Community: مقاييس شبكة يومية؛ مجموعات On-chain اختيارية، خاضعة لشروط Community غير التجارية.
- Deribit: DVOL وسلسلة خيارات BTC العامة.

### ب. الاتجاه والتحليل الفني
- EMA وRSI وATR والزخم والكسر من الشموع المكتملة.
- أطر 1D و4H و1H و15M و5M و1M بأوزان مختلفة حسب الدور.
- يتم رفض الأطر القديمة أو الناقصة بدلاً من تحويلها إلى تصويت وهمي.
- محرك Multi-Timeframe هو المدخل الفني الأساسي لمركز القرار.

### ج. تدفق الأوامر وبنية السوق
- Order Book Imbalance وDepth وSpread.
- Aggressor Buy/Sell وTrade Delta من الصفقات المجمعة.
- Volume Profile مع POC وVAH وVAL وDelta وNotional من العينة الحالية.
- VWAP مشتق من الشموع، وRelative Volume، وRealized Volatility، وRange Expansion.
- إشارة بنية السوق في مركز القرار تستخدم موقع السعر بالنسبة إلى Session VWAP ودلتا عينة الصفقات، ولا تعتمد إلا عند كفاية التغطية وحداثة المدخلات.

**الحدود الحالية:** Volume Profile ليس جلسة كاملة؛ هو عينة REST محدودة. وVWAP يحسب من Typical Price للشموع لا من كل تنفيذ منفرد.

### د. دفاتر الأوامر متعددة المنصات
| المنصة | السوق | التزامن |
|---|---|---|
| Binance | BTCUSDT Spot | Snapshot REST + Diff باستخدام U/u |
| Bybit | BTCUSDT Linear Perpetual | Snapshot/Delta وupdate ID |
| OKX | BTC-USDT Spot | Snapshot/Update وseqId/prevSeqId |

- `orderbook_sync.py` يعيد بناء Binance L2 ويكشف فجوات التسلسل.
- `venue_books.py` يطبع رسائل Bybit وOKX وفق اختلاف البروتوكول، بما فيها مستويات OKX ذات الأربعة حقول.
- عند فجوة أو دفتر متقاطع، يبطل الدفتر حتى تتم إعادة المزامنة.
- OKX WebSocket يستخدم المنفذ 443.
- `market_stream.py` يجمع التدفق الحي ويعيد الاتصال بتدرج زمني ويحفظ عينات العمق في SQLite.

### هـ. محرك التصفية
- Binance USDⓈ-M forceOrder.
- Bybit allLiquidation.
- OKX liquidation-orders على BTC-USDT-SWAP.
- تطبيع LONG/SHORT والتمييز بين متوسط تنفيذ Binance وسعر الإفلاس/السعر المرجعي في Bybit وOKX.
- إزالة تكرار الأحداث وحفظها في SQLite؛ ملخص آخر 5 دقائق يستخدم كسياق مخاطر، وآخر 60 دقيقة يعرض في اللوحة.
- لا يجمع المحرك BTC مع عدد العقود، ولا يخترع Notional USD حين لا تتوفر معادلة عقد موثقة.
- التصفية تحذير مخاطر، لا تصويت اتجاهي منفرد ولا ضمان انعكاس.

### مكرر. سياق On-chain يومي

أضيف `onchain.py` وتوسيع `providers/coinmetrics.py` وربطهما مع `slow_context.py` واللوحة:
- قراءة Core metrics اليومية (Active Addresses وBlock Height) بشكل مستقل عن مجموعات MVRV/Realized Cap الاختيارية.
- عند توفر `CapMVRVCur` يعرض المصدر؛ وعند غيابه يمكن اشتقاق MVRV من Market Cap / Realized Cap إذا توفرت القيمتان.
- حساب `NUPL derived` من (Market Cap - Realized Cap) / Market Cap مع وضع وسم واضح بأنه مشتق.
- يعرض MVRV Z-score فقط إذا عاد `CapMVRVZ` من المصدر؛ وإلا يظل غير متاح.
- فشل مجموعات المقاييس الاختيارية لا يمنع Active Addresses أو Block Height؛ تسجل الأخطاء لكل مجموعة.
- يراقب حداثة البيانات اليومية (72 ساعة) ويحسب تغيرات 7 أيام عند وجود baseline تاريخي صالح.
- SOPR غير معروض ولا يجري تقديره. On-chain سياق بطيء منفصل ولا يضيف تصويتاً أو تحذيراً اتجاهياً إلى المركز اللحظي.
- تراعي الواجهة شروط Coin Metrics Community واختلاف توفر المقاييس في مستوى Community.

### و. محرك خيارات Deribit
موجود في `options_surface.py` وموصول بالسياق الأبطأ:
- ATM IV تقريبي لكل expiry.
- 25-delta Risk Reversal من Black-Scholes spot delta.
- Put/Call Open Interest وTotal OI بوحدة BTC.
- Greeks وGamma-weighted OI proxy حسب strike.

**الحدود:** ليس SVI fitted arbitrage-free surface، ولا يقدر مخزون dealer. قيمة Gamma-weighted OI ليست Dealer GEX أو Net Gamma؛ لذلك الخيارات سياق تقلب ومراكز بطيء لا صوت BUY/SELL.

### ح. تدفق الصفقات المستمر وCVD وFootprint

أضيفت وحدات trade_stream.py وtrade_analytics.py وtrade_profile.py:
- بث صفقات Binance USDⓈ-M وBybit Linear وOKX Spot عبر WebSocket مع reconnect وheartbeat مستقل عن وصول الصفقات.
- تطبيع Aggressor/Taker side والسعر والحجم والوقت، مع حفظ الحجم بوحدة BTC عندما تكون وحدة مصدر الصفقات BTC.
- إزالة تكرار event_key ثم تخزين trade-flow minutes وFootprint في SQLite ضمن معاملة ذرية.
- CVD متعدد المنصات بفواصل 1m/5m/15m/1h/4h مع فصل Spot عن Linear Perpetual، وعدم جمع أحجام المنصات في رقم سوقي زائف.
- لا يدخل CVD التصويت قبل وجود منصتين حديثتين على الأقل وخمسة أحداث صفقات في كل منصة ضمن نافذة 5 دقائق.
- يندمج CVD بوزن 35% داخل مجال Orderflow القائم، إلى جانب دفتر الأوامر وعينة REST، وليس صوتاً سادساً.

### ط. Heatmap تاريخية وPull/Stack

أضيف depth_analytics.py لقراءة عينات depth المخزنة:
- نطاقات سعرية ثابتة قابلة للضبط، وMean/Median/Maximum/Current visible size ونسبة استمرار الظهور.
- Pull/Stack proxy يقارن السعر نفسه بين لقطتين متتاليتين ضمن فجوة زمنية محددة.
- اختفاء المستوى من نطاق العرض لا يُعامل كسحب مؤكد. المحرك سياقي ولا يضيف صوتاً اتجاهياً.

### ي. مقارنة مشتقات متعددة المنصات

أضيف cross_venue_derivatives.py وproviders/cross_venue.py:
- Binance USDⓈ-M وBybit Linear وOKX SWAP: Perpetual/Spot basis وMark/Index premium.
- توحيد معدل التمويل إلى مكافئ 8 ساعات بالاعتماد على فترة التسوية الفعلية/الميتاداتا؛ لا يحسب عند غياب فترة معروفة.
- OI محفوظ بحسب المصدر: BTC أو contracts أو USD أو USDT؛ لا يجمع ولا يفترض أن USDT يساوي USD بلا تنبيه.
- أُلحقت التحذيرات إلى مجال المشتقات ومركز القرار بصفة سياقية؛ واختبار القرار يؤكد أن score والأوزان والفعل لا تتغير بسبب هذه التحذيرات.

### ك. ماسح أحداث السوق والفرص

أضيف screener.py وعُرض في لوحة Streamlit:
- اختراقات إغلاق تتجاوز قمم/قيعان 20 شمعة مكتملة لكل إطار زمني حديث.
- Relative Volume surge وRange Expansion على الإطار المختار.
- Extreme order-book imbalance وWide spread عند وجود لقطة حديثة.
- اختلاف CVD بين Spot وPerpetual، وتشتت Funding/Basis/Mark-Index، وضغط التصفية متعدد المنصات.
- لكل حدث نوع وخطورة واتجاه مرجعي/غير اتجاهي وإطار وتوقيت ومصدر وقيمة وحد وحدود واضحة.
- يستخدم عتبات أولية قابلة للمعايرة؛ يرفض المدخلات القديمة أو الناقصة ويتحقق من نطاقات العتبات.
- الأحداث ذات الخطورة المرتفعة/المتوسطة تصل إلى التحذيرات في مركز القرار، دون أن تغير الدرجة أو الأوزان أو تنشئ أمراً.

### ل. خريطة تجمعات التصفية السعرية

أضيف liquidation_heatmap.py مع تكامل live_snapshot.py وعرض منفصل في لوحة Streamlit:
- يقرأ سجل liquidation_events لآخر 60 دقيقة بوضع SQLite read-only.
- يجمّع إلى نطاقات سعرية قابلة للضبط، مع فصل كامل حسب المنصة ونوع السوق والجهة المصفّاة ووحدة الحجم ونوع السعر المرجعي.
- Binance average_fill_price يبقى منفصلاً عن Bybit/OKX bankruptcy_price؛ لا تجمع الأسعار كأنها قياس واحد.
- Bybit venue_reported_contract_units وOKX contracts لا يتحولان إلى BTC أو USD دون مواصفات عقد متحققة.
- Notional USD لا يظهر إلا من قيمة مصدر مدعومة؛ وعند وجود أحداث priced/unpriced في المجموعة نفسها تُعلّم القيمة على أنها جزئية.
- حالة feed وعدد reconnects وعمر آخر حدث تظهر لكل منصة، بينما تبقى الخريطة سياق مخاطر لا تصويتاً اتجاهياً.
- اختبارات 6 حالات: فصل الوحدات والمنصات، Notional الجزئي، نافذة الزمن، feed health، فلترة المجموعة، وعدم إنشاء قاعدة بيانات مفقودة.
### ز. مراقب صحة مصادر البيانات والاتصال

أُضيف `feed_health.py` وربط باللقطة واللوحة. وهو يراقب:
- freshness للمصادر الأساسية Spot وOrderflow وDerivatives.
- عمر آخر دفتر أوامر لكل Venue، وحالة WebSocket وآخر heartbeat وعدد محاولات reconnect.
- التمييز بين `live` و`connected_quiet_ok` و`stale` و`recovering` و`unavailable`.
- تدفقات التصفية Event-driven: غياب حدث تصفية لا يعني تعطل المصدر ما دام heartbeat حياً؛ وإذا تقادم heartbeat تصنف القناة stale.
- المراقب أداة جودة بيانات ولا يصوت للاتجاه.

## 4. مركز القرار — الربط الفعلي

تم ربط خمسة مجالات في `decision.py`:

| المجال | الوزن |
|---|---:|
| Technical / Multi-timeframe | 35% |
| Orderflow | 25% |
| Derivatives | 20% |
| Market Structure | 10% |
| Cross-Venue Order Book | 10% |

- يعيد المركز تطبيع الأوزان وفق المجالات المتاحة والحديثة.
- يجب توافر Technical ومعه واحد على الأقل من Orderflow أو Derivatives. لا تستطيع المحركات الإضافية وحدها إنتاج قرار.
- يقارن Cross-Venue Imbalance بعد التحقق من حداثة دفاتر منصتين على الأقل، ويخفض الثقة عند تعارض Spot مع Perpetual.
- لا تُجمع أحجام الدفاتر غير المتجانسة.
- ضغط التصفية يدخل التحذيرات فقط، لا عدد الأصوات الاتجاهية.
- الخيارات وDVOL وCFTC وOn-chain سياق بطيء لا محفز دخول لحظي.

النتيجة Score اتجاهي قابل للتفسير وليست احتمال ربح إحصائياً.

## 5. اللوحة الحالية

- لوحة Streamlit مستقلة عن MT5 بالكامل.
- تعرض القرار المركزي والأطر الستة وأدلة Technical/Orderflow/Derivatives/Market Structure/Cross-Venue.
- تعرض دفاتر Binance/Bybit/OKX وحالة اتصالها وBid/Ask/Spread/Imbalance.
- تعرض ملخص التصفيات وأحداثها الأخيرة مع الوحدات والأسعار المرجعية.
- تعرض مراقب جودة البيانات مع عمر heartbeat والدفتر وتفاصيل مصادر WebSocket.
- تعرض خيارات Deribit وسياق الشبكة وCFTC وCoin Metrics وDVOL في مساحة السياق الأبطأ.
- لا تحتوي أزرار إرسال أو إغلاق، ولا تقرأ حساب Headway أو حالة MT5.

## 6. البحث عن محركات إضافية

تم توسيع مراجعة المشاريع في `OPEN_SOURCE_RESEARCH_AR.md`:
- **HyperData Terminal — Apache-2.0:** مرجع لبث تصفيات متعدد المنصات، CVD حسب Venue، Heatmap وFeed Health وتمييز LIVE/PARTIAL/STALE/DRIFT وإزالة التكرار بعد reconnect. استفدنا من الدروس الهندسية دون إضافة التطبيق كاملاً.
- **Deribit BTC Options Dashboard — MIT:** مرجع لمعادلات Black-Scholes وSVI وTerm Structure و25-delta Skew وMax Pain والاختبارات الرقمية. افتراض Dealer GEX يحتاج حذراً ولا يعتمد دون بيانات inventory.

## 7. ما تبقى قبل اعتبار البرنامج جاهزاً

### الأولوية 1 — تشغيل ومراقبة البيانات الحية
1. تشغيل الجامع واللوحة على Windows لفترة ممتدة والتحقق من memory/disk/reconnect/resync.
2. قياس تغطية كل Venue وevent rate وheartbeat وtimestamp drift، ومراجعة سلوك SQLite مع كثافة الصفقات.

### الأولوية 2 — معايرة جودة المحركات الجديدة
3. معايرة CVD/Footprint وHeatmap وPull/Stack تاريخياً وقياس الإنذارات الكاذبة ومدى استقرار thresholds.
4. معايرة Screener للأحداث والاختراقات وقيم volume/range/spread عبر الفواصل المختلفة.
5. معايرة تغطية خريطة التصفية السعرية والتحقق من Contract multipliers قبل أي تحويل موسع للأحجام إلى Notional USD.

### الأولوية 3 — توسعة خيارات السوق وOn-chain
6. تطوير Options SVI/Calendar consistency والسطح التاريخي واختبارات no-arbitrage.
7. معايرة سلسلة MVRV/Realized Cap/NUPL اليومية، وإيجاد مصدر موثق ومرخص لـSOPR وETF flows قبل إضافتهما.

### الأولوية 4 — تدقيق البرنامج واللوحة
8. تدقيق حالات stale/error/partial وزمن التحديث واستهلاك الموارد وتصدير سجل القرار.
9. إعادة اختبار تكامل كل المحركات، خصوصاً عند تعارض Technical/CVD/Book/Basis/Funding.
10. تشغيل Smoke على Windows للوحة والجامع معاً.

### الأولوية 5 — Headway لاحقاً فقط
11. بعد اعتماد المحركات واللوحة، يعاد فتح ربط EA مع Headway عبر MT5.
12. اختبار Headway-Demo والرمز وخصائص العقد ثم دورة OPEN/ACK/Position/Reversal/CLOSE/ACK.
13. قياس الانزلاق والعمولة وأوقات التعبئة والنتائج قبل أي تقييم ربحية.
## 8. ما لم يثبت بعد

- لم يثبت التشغيل الحي المتواصل لجامع WebSocket على جهاز Windows الخاص بالمستخدم؛ CI لا يغطي عدة ساعات من التشغيل الحقيقي على جهازه.
- CVD/Footprint وHeatmap وPull/Stack موجودة برمجياً ومختبرة، لكن حدودها لم تُعاير بعد بنتائج سوق تاريخية وميدانية كافية.
- مقارنة Funding/Basis/OI تعمل كطبقة سياقية؛ لا تعني توحيد جميع أنواع العقود أو إمكان جمع أحجامها.
- Screener يعمل على المدخلات الحديثة المكتملة بعتبات أولية؛ ما زال بحاجة إلى قياس false positives وتعديل الحدود حسب الفواصل الزمنية.
- On-chain يقرأ البيانات اليومية ويعرض MVRV/NUPL المشتق ومؤشرات الشبكة عند التوفر؛ يحتاج إلى تقييم تأخير وتغطية Community tier، ومصدر منفصل لـSOPR غير موصول حالياً.
- خريطة التصفية السعرية موجودة برمجياً وتفصل المصادر والوحدات، لكن تحويل أحجام Bybit/OKX إلى Notional USD يتطلب تثبيت Contract multipliers وتغطية المصدر لكل منتج.
- لم ينفذ أي اختبار تداول Headway في المرحلة الحالية؛ وهذا تأجيل مقصود، لا نقص غير معروف.
- لا توجد نتائج ربحية موثقة.

**الخلاصة:** وصل برنامج Bitcoin Intelligence Lab إلى مجموعة تحليل متعددة المجالات: الاتجاه متعدد الأطر، Orderflow مع CVD مستمر، Footprint، Heatmap/Pull-Stack، مشتقات متعددة المنصات، خريطة تجمعات التصفية السعرية، بنية السوق، التصفيات، الخيارات، ومراقب صحة البيانات، مع Screener للأحداث متصل بمركز القرار. بقيت خمسة مجالات تصويت مركزية فقط؛ أما المحركات الإضافية فتغذي الأدلة والتحذيرات ولا تكرر الأصوات. آخر CI #340 اجتاز 219 اختباراً على Python 3.12 و3.13. لا يعاد ربط Headway قبل استكمال تشغيل Windows والمعايرة والتدقيق النهائي.