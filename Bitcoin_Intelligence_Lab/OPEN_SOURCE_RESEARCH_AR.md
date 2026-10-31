# مراجعة مشاريع GitHub مفتوحة المصدر لبرنامج Bitcoin Intelligence Lab

**تاريخ المراجعة:** 2026-10-31  
**نطاق المراجعة:** قراءة README وملفات LICENSE وبنية الملفات، ومراجعة أجزاء منتقاة من الكود والاختبارات.  
**قاعدة الدمج:** نأخذ الوظيفة والدرس الهندسي، ثم نكتب تكاملاً مناسباً لبنية المختبر. لا ننسخ كوداً بلا ترخيص واضح، ولا نضيف مشروعاً ضخماً لمجرد كثرة النجوم.

## أفضل المرشحين للاستخدام

| المشروع | الترخيص الظاهر في GitHub | مؤشرات النشاط عند المراجعة | ما يستحق الاستفادة منه | قرار المختبر |
|---|---|---|---|---|
| [LiquidityMapperFast](https://github.com/liquiditymapperfast/liquiditymapperfast.github.io) | MIT | 74 نجمة؛ آخر دفع تغييرات 2026-10-30 | موائمات WebSocket متعددة المنصات، دفتر أوامر محلي متزامن، تاريخ السيولة، Footprint، Volume Profile، تدفق Delta، تخزين تاريخ depth في SQLite/IndexedDB، وحالة اتصال/إعادة اتصال لكل venue | **المرجع الأول** لمحرك تدفق الأوامر والسيولة. نعيد بناء الأجزاء اللازمة داخل Python، ويمكن الاستفادة من وحدات صغيرة مع حفظ إشعار MIT متى استُخدم كود فعلي |
| [CCXT](https://github.com/ccxt/ccxt) | MIT | نحو 44.6 ألف نجمة؛ دفع تغييرات 2026-10-30 | توحيد أسماء الأسواق والرموز، وواجهات REST العامة لأكثر من 100 منصة، وتحويل order book / OHLCV / funding إلى صيغة مشتركة | **مرجع موائمات متعدد المنصات**. نستخدم واجهات REST المجانية فقط عند الحاجة؛ لا نفترض أن ميزات CCXT Pro/WebSocket المجانية متاحة |
| [Hummingbot](https://github.com/hummingbot/hummingbot) | Apache-2.0 | نحو 20.8 ألف نجمة؛ دفع تغييرات 2026-10-20 | حدود موائمات المنصات، فصل مصدر بيانات السوق عن التنفيذ، إعادة الاتصال وتتبع الاتصال، وتوحيد Spot/Perpetual عبر الموائمات | **مرجع معماري** فقط؛ لا نضيف إطار Hummingbot الكامل ولا محركات صناع السوق إلى البرنامج |
| [Jesse](https://github.com/jesse-ai/jesse) | MIT | نحو 8.7 آلاف نجمة؛ دفع تغييرات 2026-10-30 | مزامنة عدة أطر زمنية ورموز دون Look-ahead، تنظيم المؤشرات، تقارير الأداء والرسوم | استفدنا من مبدأ التحليل Top-down واختبارات عدم تسرب المستقبل في محرك الأطر المتعددة؛ لا نضيف محرك Backtest الخاص به إلى مسار التنفيذ |
| [Crypto Liquidity Terminal](https://github.com/AIUngated/crypto-liquidity-terminal) | MIT | 6 نجوم؛ آخر دفع تغييرات ظاهر في 2026-05-27 | Screener لعدة منصات، Heatmap، 10 كواشف أحداث، Relative Volume، تقلب، اتساع السبريد، اختلال دفتر الأوامر، شذوذ OI/Funding، وتنبيهات | **مرجع إضافي** لمحرك الفاحص والكواشف. نفحص الصيغ والاختبارات قبل نقل أي خوارزمية؛ لا نعتمد المشروع كاعتمادية تشغيلية |
| [Bitcoin Core](https://github.com/bitcoin/bitcoin) | MIT | مشروع مرجعي للبروتوكول والبيانات | RPC محلي وبيانات UTXO/البلوكات كأساس لحساب on-chain بنفسنا | **مصدر مستقبلي** لمحرك السلسلة دون مزود بيانات تجاري؛ يتطلب عقدة كاملة وتخزيناً ومزامنة |

## مشاريع مفيدة للمعرفة لا لإعادة استخدام الكود

| المشروع | الوضع | سبب عدم الدمج المباشر |
|---|---|---|
| [flowdrivenml/market-data-stream-processor](https://github.com/flowdrivenml/market-data-stream-processor) | لا يوجد ملف ترخيص واضح | يشرح تطبيع السوق عبر منصات متعددة، OI/Funding/Liquidations/Options، ويعرض مشكلة أن الدقيقة الهادئة والدقيقة شديدة النشاط لا تحملان كمية المعلومات نفسها. نستفيد من فكرة Volume/Dollar/Imbalance/Event Bars، لا من كوده |
| [TrueNorth Atlas](https://github.com/bwerkman-strive/truenorth-atlas) | لا يوجد ملف ترخيص واضح، والمستودع صغير/حديث | قائمة مؤشرات on-chain مهمة مثل MVRV وMVRV-Z وNUPL وSOPR وCDD وHODL waves وPuell، لكنه يتطلب Bitcoin Core وUTXO snapshots. نأخذ قائمة المؤشرات كخريطة بحث، لا كوداً |
| [duolaAmengweb3/crypto-monitor](https://github.com/duolaAmengweb3/crypto-monitor) | لا يوجد ملف ترخيص واضح | يجمع مراقبة OI والحيتان والتصفية وETF flows عبر منصات؛ لا نعيد استخدام الكود حتى يظهر ترخيص صريح |

## مشاريع مستبعدة من دمج الشفرة

- [Freqtrade](https://github.com/freqtrade/freqtrade): ترخيص GPL-3.0؛ لن ندمج كوده في المختبر ذي البنية المستقلة دون قرار ترخيص واعٍ. لا حاجة لاستيراد إطار Backtest/Hyperopt، خصوصاً أن تركيز المرحلة الحالية على البيانات الحية والتنفيذ التجريبي.
- [Nautilus Trader](https://github.com/nautechsystems/nautilus_trader): LGPL-3.0 ومحرك Rust كبير؛ مفيد كمرجع event-driven، لكنه زائد على احتياج النسخة الحالية وله اعتبارات ترخيص واعتماديات.
- [Depth](https://github.com/ChloePike/depth): GPL-3.0؛ نراجع أفكاره حول جمع 10 منصات، لكن لا ننسخ كوده.
- [TapeDelta Kline Orderbook Chart](https://github.com/tapedelta/kline-orderbook-chart): صفحة المستودع تصف الاستخدام الإنتاجي بأنه برنامج تجاري يتطلب مفتاح ترخيص، رغم ظهور ملف LICENSE بحالة GitHub غير محسومة؛ **مستبعد** من الدمج المجاني.
- لا نخلط بين أن المستودع العام قابل للقراءة وبين أنه مرخّص لإعادة الاستخدام.

## محركات سنضيفها أو نوسعها بناءً على المراجعة

### 1. محرك تدفق البيانات ودفتر الأوامر متعدد المنصات
- WebSocket مستقل لكل منصة مع heartbeat ووقت آخر تحديث وإحصاء reconnects.
- بدء الدفتر من Snapshot ثم تطبيق Delta فقط.
- التعامل مع update IDs / sequence gaps؛ عند وجود فجوة نعيد مزامنة Snapshot ولا نستمر ببيانات دفتر غير موثوقة.
- توحيد الأسعار والأحجام ووحدات العقود قبل مقارنة عمق BTC.
- عرض مساهمة كل منصة ودرجة تغطيتها بدلاً من جمع أحجام غير قابلة للمقارنة.

### 2. محرك السيولة وMicrostructure
- Heatmap تاريخي للعمق، وليس مجرد لقطة REST واحدة.
- Pull/Stack: قياس السيولة المضافة أو المسحوبة في مستوى سعري خلال نافذة زمنية.
- Footprint / Volume-at-Price من الصفقات المنفذة، مع فصل Aggressive Buy عن Aggressive Sell.
- POC وValue Area High/Low وHigh/Low Volume Nodes.
- VWAP وSession VWAP وانحرافات السعر عنها.
- CVD / Delta ضمن نافذة محددة بوضوح؛ لا نسمي عينة آخر 500 صفقة «CVD يوم كامل».

### 3. محرك التصفية وازدحام المشتقات
- بث التصفية الفعلي من المنصات التي تعلنه، وتخزين الحدث والوقت والرمز والاتجاه والحجم والسعر الذي أبلغت عنه المنصة.
- الفصل بين **سعر تنفيذ التصفية** و**سعر الإفلاس/Bankruptcy**؛ فهما ليسا الشيء نفسه.
- تجميع Long/Short Liquidation Clusters وقيمة التصفية خلال 1m/5m/15m/1h.
- إضافة Premium/Basis بين Spot وPerpetual وFunding countdown وOI change وTaker flow.
- لا نستنتج اتجاه السوق من OI منفرداً، ولا نحوّل Funding متطرفاً تلقائياً إلى إشارة عكسية.

### 4. محرك الدورة On-chain وInstitutional
- MVRV/NUPL/SOPR/Realized Cap/HODL cohorts وPuell/Hash Ribbons.
- ETF net flows، وتمركز CME CFTC كبيانات أسبوعية.
- هذا محرك سياقي/دوري مستقل، لا يدخل مباشرة في توقيت الصفقة اللحظي.
- عند عدم وجود مصدر عام مرخّص فعلاً، يكون الحل الأفضل حساب المؤشر من Bitcoin Core محلياً أو إظهار «غير متاح»، وليس اختلاق قيمة أو scraping هش.

### 5. محرك Options / Volatility
- DVOL وحده لا يمثل سطح الخيارات.
- الخطوة التالية هي جمع Option chain العامة وحساب IV term structure وSkew و25-delta risk reversal وPut/Call OI/volume وGreeks بعد اختبار وحدات العقد.
- بيانات الخيارات تستخدم لقياس نظام التقلب/التحوط، لا كتوقع اتجاهي مباشر.

### 6. محرك Screener وتنبيهات
- مراقبة BTC عبر منصات متعددة أولاً، ثم توسيع قائمة العملات.
- Relative volume وvolatility expansion وspread widening وbook imbalance وbreakout وOI/funding anomaly.
- كل detector يصدر اسماً ووقتاً ودرجة وبيانات إثبات؛ ولا يرسل أمر تداول منفرداً. القرار المركزي وحده يجمع الأدلة.

## مصادر API المجانية المراجعة

- Binance Spot/Futures: بيانات عامة للشموع والدفتر والصفقات وFunding وOpen Interest وTaker.
- Bybit V5: Market Tickers وOpen Interest وFunding History وRecent Trades؛ وكذلك قناة WebSocket `allLiquidation.{symbol}` للتصفيات.
- OKX V5: قنوات Public REST/WebSocket للـTicker وOrder Book.
- mempool.space: الشبكة والتعدين والرسوم والـMempool.
- Coin Metrics Community: مقاييس محددة ذات شروط استخدام Community non-commercial؛ لا نعاملها كبيانات تجارية حرة بلا قيود.
- CFTC TFF: تقرير أسبوعي عام لعقود CME؛ ليس تدفقاً لحظياً.
- Deribit Public: DVOL وبيانات سوق الخيارات العامة.

«مجاني» هنا يعني عدم اشتراط رسوم ترخيص للموصل أو نقطة البيانات العامة وقت المراجعة، وليس وعداً بعدم وجود حدود معدل/قيود بلد/تغيّر في واجهة API أو شروط استخدام المصدر.

## ما تم تنفيذه بالفعل في فرع المختبر قبل هذه المراجعة
- محرك أولي متعدد الأطر 1D/4H/1H/15m/5m/1m، مع أوزان للأدوار ورفض الإطار القديم/الناقص.
- موائم Bybit V5 احتياطي لبيانات المشتقات عند فشل Binance.
- محرك إدارة مراكز مركزي ينتظر تأكيد MT5، ولا يغلق على HOLD.
- تحديث دوري للوحة ومصادر السياق الأبطأ.

## ترتيب التنفيذ بعد المراجعة
1. **WebSocket orderbook sync + reconnect + event persistence**.
2. **Cross-venue Spot/Perp monitor + screener**.
3. **Real liquidation stream + stored clusters**.
4. **Volume Profile / VWAP / trade delta / pull-stack**.
5. **Options surface وOn-chain متقدم**.

لا ندّعي أن هذه الخصائص تثبت ربحية الاستراتيجية؛ يلزم رصد فعلي ومقارنة مصادر وتأكيدات التنفيذ.
