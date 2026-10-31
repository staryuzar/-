# تقرير حالة العمل — Bitcoin Intelligence Lab

**تاريخ التقرير:** 31 أكتوبر 2026  
**المستودع:** [staryuzar/-](https://github.com/staryuzar/-)  
**الفرع:** `bitcoin-intelligence-lab`  
**طلب المراجعة:** [PR #9 — Draft: Build independent Bitcoin Intelligence Lab](https://github.com/staryuzar/-/pull/9)  
**آخر commit في الفرع:** `38fa3a591c2ced268803487e8c35a07968da7060`

---

## 1. القرار التنفيذي المعتمد

تم اعتماد تأجيل ربط خبير MT5 حتى تكتمل محركات البرنامج واللوحة ومركز القرار وتنجح مراجعة الأكواد والاختبارات. بناءً على ذلك:

- أزيلت من `app.py` جميع استدعاءات جسر MT5 وقراءة حالته ومراكزه ونشر أوامر OPEN/CLOSE والإدارة الآلية.
- لا تقرأ اللوحة حالياً ملفات MT5، ولا تتصل بحساب Headway، ولا ترسل أي أمر تداول.
- حُذف سير عمل Headway-Demo الآلي من فرع المختبر، كي لا يكون ربط الخبير أو تجميعه شرطاً لتطوير بقية البرنامج.
- بقيت ملفات الخبير والجسر وإدارة المراكز محفوظة في المستودع للمراجعة والمرحلة اللاحقة، لكنها غير موصولة بالتطبيق الحالي.
- عند اكتمال البرنامج، يكون Headway عبر MT5 وسيط التنفيذ الوحيد. Binance وBybit وOKX وDeribit مصادر بيانات فقط.

## 2. حالة الفرع والاختبارات

- الفرع: `bitcoin-intelligence-lab`.
- PR #9 ما زال مفتوحاً وDraft، ولم يُدمج في الفرع الرئيسي.
- آخر حالة PR عند تحديث التقرير: 74 ملفاً متغيراً ونحو 9,162 إضافة.
- آخر نسخة برمجية خضعت لاختبار شامل: commit `904e591ef21186669ab5c5604216cf7fa04cd256`.
- CI رقم **#278** اكتمل بنجاح على Python 3.12 و3.13؛ سجل الاختبارات **161 اختباراً ناجحاً**، وشملت الخطوات تجميع Python، والاختبارات، وتشغيل Streamlit smoke test، وقراءة بيانات BTC العامة الحية.
- بعد commit `904e591` تغيرت ثلاثة ملفات توثيق فقط: README وArchitecture وOpen Source Research؛ لا توجد تغييرات كود بين النسخة التي اجتازت 161 اختباراً وآخر رأس الفرع `38fa3a5`.
- شُغلت كذلك CI على تحديثات التوثيق السابقة، وبعض تشغيلات CI للـcommit التوثيقي الأخير كانت لا تزال جارية وقت إعداد التقرير.

رابط CI الذي ثبت فيه رقم 161 اختباراً:  
https://github.com/staryuzar/-/actions/runs/41154681144

## 3. ما تم بناؤه في البرنامج

### أ. محركات البيانات الأساسية

- Binance Spot: شموع مكتملة، دفتر أوامر، وصفقات مجمعة.
- Binance USDⓈ-M: Funding وOpen Interest وTaker Buy/Sell وتاريخ OI.
- Bybit V5: مصدر مشتقات احتياطي عند فشل بيانات Binance أو تقادمها.
- mempool.space: حالة الشبكة والتعدين والرسوم والـMempool.
- CFTC TFF: تمركز عقود CME Bitcoin وMicro Bitcoin الأسبوعي.
- Coin Metrics Community: بيانات شبكة محددة وفق شروط Community non-commercial.
- Deribit: DVOL وبيانات سلسلة خيارات BTC العامة.

### ب. التحليل الفني ومتعدد الأطر

- EMA وRSI وATR والزخم والكسر من الشموع المكتملة.
- الأطر 1D و4H و1H و15M و5M و1M بأوزان حسب الدور.
- التحقق من حداثة كل إطار؛ البيانات الناقصة أو القديمة لا تتحول إلى تصويت صفري أو إيجابي مصطنع.
- الاتجاه متعدد الأطر هو المدخل الفني الأساسي للقرار المركزي، لا مجرد اختيار فاصل واحد.

### ج. السيولة وتدفق الأوامر وبنية السوق

- Order Book Imbalance وDepth وSpread.
- Aggressor Buy/Sell وTrade Delta من الصفقات المجمعة.
- Volume Profile مع POC وVAH وVAL وDelta وNotional من العينة المتاحة.
- VWAP جلسة UTC من Typical Price للشموع، وRelative Volume وRealized Volatility وRange Expansion.
- أضيفت إشارة Market Structure مبنية على موقع السعر بالنسبة إلى Session VWAP ودلتا عينة الصفقات، ولا تعمل إلا عند توافر تغطية وحداثة كافيتين.

**الحد الحالي:** Volume Profile ليس جلسة كاملة؛ هو عينة صفقات REST محدودة. وVWAP محسوب من الشموع، لا من كل تنفيذ منفرد في السوق.

### د. دفاتر أوامر حية متعددة المنصات

| المنصة | السوق | قاعدة المزامنة |
|---|---|---|
| Binance | BTCUSDT Spot | REST Snapshot + Diff باستخدام U/u |
| Bybit | BTCUSDT Linear Perpetual | Snapshot/Delta مع update ID وإعادة Snapshot عند restart |
| OKX | BTC-USDT Spot | Snapshot/Update باستخدام seqId/prevSeqId |

- `orderbook_sync.py` يعيد بناء Binance L2 ويتحقق من فجوات التسلسل.
- `venue_books.py` يعالج اختلافات رسائل Bybit وOKX بما فيها مستويات OKX ذات الأربعة حقول.
- الدفتر المتقاطع أو الذي تعرض لفجوة يُبطل ولا يستخدم كبيانات صالحة حتى إعادة المزامنة.
- يستخدم OKX WebSocket المنفذ العام 443.
- `market_stream.py` يجمع بيانات المنصات ويعيد الاتصال بتدرج زمني ويحفظ عينات العمق في SQLite.

### هـ. التخزين المحلي

- `market_store.py` يحفظ عينات دفتر الأوامر كل نحو خمس ثوانٍ، وحالة الاتصال، والأحداث التي تحتاج حفظاً.
- يحتفظ بسجل SQLite محدود افتراضياً بـ24 ساعة مع تنظيف دوري.
- تقرأ اللقطة واللوحة القاعدة بوضع read-only.
- عولج إغلاق اتصالات SQLite لتجنب قفل الملف على Windows.
- لا يزال تشغيل جامع WebSocket لوقت طويل على جهاز Windows واختبار إعادة الاتصال الحقيقي يحتاج تحققاً ميدانياً؛ نجاح اختبارات الرسائل لا يثبت ذلك.

### و. محرك التصفية

- Binance USDⓈ-M forceOrder.
- Bybit allLiquidation.
- OKX liquidation-orders على BTC-USDT-SWAP.
- تطبيع LONG/SHORT، والتمييز بين متوسط تنفيذ Binance وسعر الإفلاس/السعر المرجعي في Bybit/OKX.
- حفظ الحدث وإزالة التكرار وتجميع آخر 5 دقائق لمخاطر مركز القرار وآخر 60 دقيقة للعرض في اللوحة.
- يمنع المحرك جمع كميات BTC مع عدد العقود، ولا يخترع Notional USD حين لا تتوافر معادلة عقد موثوقة.
- التصفية تحذير مخاطر وسياق، وليست تصويتاً اتجاهياً ولا دليلاً على انعكاس مضمون.

### ز. محرك خيارات Deribit

موجود في `options_surface.py` وموصول بسياق `slow_context.py`، ويشمل:

- ATM IV تقريبياً حسب تاريخ الانتهاء.
- 25-delta Risk Reversal من Black-Scholes spot delta.
- Put/Call Open Interest وTotal OI بوحدة BTC.
- Delta وGamma، وGamma-weighted OI proxy حسب strike.
- اختبارات لحالات صلاحية/رفض السلسلة ووحدات البيانات.

**حدوده:** ليس SVI fitted arbitrage-free surface، ولا يقدّر مخزون dealer، ولا يجوز تسمية Gamma-weighted OI بأنه Dealer GEX أو Net Gamma. لذلك هو سياق تقلب ومراكز بطيء، وليس تصويت BUY/SELL مباشراً.

## 4. مركز القرار — ما تم ربطه فعلياً

تم توصيل المحركات الجديدة داخل `live_snapshot.py` و`decision.py`:

| المحرك | الوزن الأساسي |
|---|---:|
| Technical / Multi-timeframe | 35% |
| Orderflow | 25% |
| Derivatives | 20% |
| Market Structure | 10% |
| Cross-Venue Order Book | 10% |

- يعيد المركز تطبيع الأوزان عندما لا تتوافر أدلة اختيارية حديثة.
- يجب أن يكون المحرك الفني صالحاً ومعه على الأقل Orderflow أو Derivatives. لا تستطيع الإضافات المساندة وحدها إنتاج قرار تداول.
- يقارن محرك Cross-Venue قيم Imbalance بعد التحقق من حداثة دفاتر منصتين على الأقل، ويخفض الثقة عند تعارض Spot مع Perpetual.
- لا يجمع أحجام دفاتر المنصات المختلفة كأنها وحدة واحدة.
- ضغط التصفيات يضاف إلى warnings/risks فقط، ولا يزيد عدد الأصوات الاتجاهية.
- خيارات Deribit وDVOL وCFTC وOn-chain تبقى سياقاً أبطأ، لا محفزاً لحظياً.

الدرجة النهائية Score اتجاهي وقابل للتفسير، وليست احتمال ربح إحصائياً.

## 5. اللوحة الحالية

- لوحة Streamlit مستقلة لتحديث لقطة السوق والاتجاه متعدد الأطر.
- تعرض حالة دفاتر Binance/Bybit/OKX وBid/Ask/Spread/Imbalance.
- تعرض تصفيات آخر ساعة بحسب المنصة والجهة ووحدة الحجم.
- تعرض أدلة Market Structure وCross-Venue وملخص ضغط التصفيات بجوار القرار المركزي.
- تعرض حالة مصادر البيانات وأخطاءها وحدود كل محرك.
- سياق الشبكة وCFTC وCoin Metrics وDVOL وخيارات Deribit يظهر منفصلاً كسياق بطيء.
- لا تعرض حالة MT5 أو الصفقات المفتوحة، ولا تقرأ حساب Headway، ولا تحتوي أزرار إرسال أوامر.

## 6. البحث في محركات ومشاريع إضافية

أضيفت إلى `OPEN_SOURCE_RESEARCH_AR.md` مراجعة ثانية تتضمن:

- **HyperData Terminal — Apache-2.0:** مرجع لبث التصفيات وCVD حسب المنصة وHeatmap وFeed Health وLIVE/PARTIAL/STALE/DRIFT وإزالة التكرار بعد reconnect. لا نضيف التطبيق كاملاً؛ نأخذ الدروس الهندسية.
- **Deribit BTC Options Dashboard — MIT:** مرجع لمعادلات Black-Scholes وSVI وTerm Structure و25-delta Skew وMax Pain والاختبارات الرقمية. لا ننسخ افتراض Dealer GEX دون معلومات مخزون dealer.

محركات الإكمال الإضافية المقترحة من هذه المراجعة:
1. Feed Health Monitor مركزي للتغطية والحداثة وwarmup وdrift ومقارنة المصادر.
2. CVD وFootprint مستمر لكل Venue مع dedup وتوقيتات exchange event.
3. Heatmap تاريخية للعمق وPull/Stack، وليس snapshot فقط.
4. Cross-Venue price/basis monitor وتطبيع العقد ووحدات Spot/Perpetual.
5. تصنيف أحداث السوق/سوق العملات Screener بكواشف متعددة الأطر.
6. خيارات أعمق: SVI fit وsurface history وCalendar consistency بعد تثبيت دقة الوحدات.
7. On-chain MVRV/NUPL/SOPR/Realized Cap من Bitcoin Core أو مصدر موثق ومرخص، وإضافة ETF flows عند وجود مصدر صالح.

## 7. ما تبقى قبل اعتبار البرنامج جاهزاً

### أولوية 1 — جودة البيانات والتشغيل المستمر
1. إنشاء Feed Health Monitor موحد يميز Live/Partial/Stale/Drift/Warmup لكل مصدر.
2. تشغيل جامع WebSocket على Windows لساعات والتحقق من reconnect وresync واستهلاك الذاكرة والقرص.
3. إضافة سجل صفقات مستمر وdedup إلى SQLite.

### أولوية 2 — محركات السوق المتقدمة
4. بناء Footprint وCVD حسب المنصة والفاصل من الصفقات المتصلة.
5. بناء تاريخ عمق Heatmap وPull/Stack وLiquidity persistence.
6. إضافة Cross-Venue price/basis/funding/OI comparison بعد تطبيع أنواع العقود.
7. تطوير Liquidation Heatmap بحسب السعر مع الإبقاء على جودة التغطية والتمييز بين السعر المرجعي وسعر التنفيذ.
8. تطوير Options SVI/term surface/Greeks واختبارات no-arbitrage المناسبة.
9. استكمال On-chain/ETF/Institutional context بمصادر موثقة.

### أولوية 3 — تدقيق مركز القرار واللوحة
10. مراجعة كل محرك على حدة: inputs، outputs، freshness، score، warnings، fallbacks، unit tests.
11. اختبارات توافق وتعارض المحركات ووزن الأدلة المفقودة والتغطية المنخفضة.
12. مراجعة كل عناصر Streamlit، وسلوك stale/error/partial، وزمن التحديث، والذاكرة، وإمكانية تصدير سجل القرار.
13. اختبار smoke على Windows وعلى جلسة تشغيل فعلية للجامع واللوحة.

### أولوية 4 — مرحلة Headway لاحقاً فقط
14. بعد اعتماد البرنامج واللوحة، يعاد فتح ربط EA بوسيط Headway عبر MT5.
15. التحقق من Headway-Demo ونوع الحساب والرمز الحقيقي وخصائص العقد.
16. اختبار دورة OPEN/ACK/position/reversal/CLOSE/ACK على Headway-Demo.
17. تسجيل slippage والعمولة وأوقات التنفيذ ونتائج الصفقات قبل أي ادعاء ربحية.

## 8. ما لم يثبت بعد

- لم يثبت التشغيل الحي المتواصل لدفاتر WebSocket الثلاثة على جهاز Windows للمستخدم.
- لم يكتمل Feed Health Monitor العام، وFootprint/CVD المستمر، وHeatmap التاريخية، وPull/Stack.
- لم يكتمل Cross-Venue basis/funding/OI normalization.
- لم يكتمل Options SVI/Calendar surface history ولا on-chain advanced.
- لم يُنفذ اختبار تداول Headway في المرحلة الحالية؛ وهذا مؤجل عمداً بناءً على خطة التطوير المعتمدة.
- لا توجد نتائج ربحية موثقة.

**الخلاصة:** المختبر الآن برنامج تحليل وقرار مركزي قيد الاستكمال، وليس خبير MT5 نشطاً. تم ربط خمسة مجالات أدلة في القرار، وتم اختبار النسخة البرمجية ذات الصلة بـ161 اختباراً ناجحاً على Python 3.12 و3.13. الأولوية التالية هي تدقيق جودة البيانات والتدفق المستمر ثم إكمال محركات السوق المتقدمة واللوحة. لا يبدأ ربط Headway إلا بعد إتمام هذه المراحل.
