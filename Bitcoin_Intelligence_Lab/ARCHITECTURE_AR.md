# معمارية Bitcoin Intelligence Lab

## المرحلة الحالية والحد الفاصل

**ربط MT5 مؤجل حتى اكتمال المحركات واللوحة وتدقيقهما.** تطبيق Streamlit لا يستورد جسر MT5 ولا يقرأ ملفات MT5 ولا ينشر أوامر. ملفات `ea_bridge.py` و`automation.py` و`position_manager.py` وملف EA محفوظة في المستودع للمرحلة اللاحقة فقط، وليست ضمن مسار التطبيق الحالي.

Binance وBybit وOKX وDeribit مصادر بيانات عامة للقراءة فقط. وسيط التنفيذ المخطط عندما يحين وقت الربط هو Headway عبر MT5 حصراً. لم يعد سير عمل Headway الآلي جزءاً من الفرع الحالي.

## خط التحليل والقرار الحالي

مصادر BTC العامة → adapters وتوحيد الوقت/الرمز/الوحدات → Feed Health Monitor → محركات الاتجاه والأوامر والمشتقات والبنية متعددة المنصات → Screener للأحداث → مركز القرار الخماسي → التفسير والتحذيرات → لوحة Streamlit.

كل محرك يعيد status وscore عند توفرها وevidence وwarnings وlimitations. محرك CVD يندمج داخل Orderflow؛ وScreener وHeatmap وسياق المشتقات المتعدد لا يصوتون مستقلاً. لا يحق لمحرك إرسال أمر تداول ولا يحسم BUY/SELL/HOLD منفرداً.

## خطوط البيانات الحية المساندة

### دفاتر الأوامر
Binance/Bybit/OKX WebSocket → موائم بروتوكول كل منصة → دفتر محلي متزامن → Spread/Depth/Imbalance → عينات SQLite وتاريخ العمق → Cross-Venue Order Book Engine → مركز القرار واللوحة.

### التصفيات
Binance USDⓈ-M forceOrder + Bybit allLiquidation + OKX liquidation-orders → تطبيع جهة المركز المصفّى ووحدة الحجم والسعر المرجعي → إزالة التكرار → SQLite → تجميع آخر 5 دقائق للمخاطر وآخر 60 دقيقة للوحة.
ثم liquidation_heatmap.py تقرأ آخر 60 دقيقة وتجمع نطاقات السعر مع الفصل التام بين Venue/market type/side/quantity unit/reference-price kind؛ ولا تدمج سعر التنفيذ مع سعر الإفلاس ولا العقود مع BTC أو USD. Notional الجزئي موضح صراحة.

### الصفقات وCVD وFootprint
Binance USDⓈ-M aggTrade + Bybit Linear publicTrade + OKX Spot trades → تطبيع جهة Taker والسعر والحجم والوقت → dedup ذري → SQLite trade_flow_minutes + trade_footprint → دلتا متحركة لكل منصة/نوع سوق → CVD 5m متعدد المنصات → يندمج 35% داخل Orderflow القائم عند حداثة منصتين على الأقل.

### تاريخ العمق وHeatmap
لقطات دفاتر الأوامر المتزامنة → SQLite orderbook_snapshots → تجميع مستويات السعر بنطاقات USD → persistence/mean/median/current size → Pull/Stack عند مقارنة النطاق نفسه بين لقطات متتابعة ضمن فجوة زمنية محددة. هذه مؤشرات سيولة ظاهرة وسياقية وليست إثباتاً لإلغاء الأوامر.

### مقارنة المشتقات وScreener
Binance USDⓈ-M + Bybit Linear + OKX SWAP → per-venue Spot/Perpetual basis وMark/Index وFunding موحد إلى 8h حسب فترة التسوية وOI محفوظ بوحدته الأصلية → سياق مشتقات غير تصويتي. ثم يقرأ Screener الإطارات المكتملة وCVD والسبريد والعمق والتمويل والتصفيات ليولد أحداثاً ذات وقت/مصدر/خطورة/دليل، ويرسل التحذيرات عالية/متوسطة إلى مركز القرار دون تغيير الدرجة أو الأوزان.

### الخيارات
Deribit public instruments + book summaries + DVOL → ربط instrument metadata بالـOI والـmark IV والـunderlying price → Greeks وصفية وATM IV Term Structure و25-delta Risk Reversal وPut/Call OI وGamma-weighted OI → سياق خيارات بطيء داخل اللوحة. لا يدخل هذا الإصدار الخيارات كتصويت BUY/SELL.

## مسؤوليات الوحدات

- `providers/`: قراءة Spot/Futures وMempool وCFTC وCoin Metrics وDeribit، دون واجهات تنفيذ تداول.
- `indicators.py`: EMA وRSI وATR والزخم والكسر من شموع مكتملة.
- `multi_timeframe.py`: تحليل 1D/4H/1H/15M/5M/1M بأوزان الدور ورفض الأطر القديمة أو الناقصة.
- `orderflow.py`: Spread وDepth وImbalance وAggressor Buy/Sell ودلتا الصفقات.
- `derivatives.py`: Funding وOpen Interest وTaker ratios؛ التمويل وOI سياق تمركز ولا يحددان الاتجاه منفردين.
- `market_structure.py`: Volume Profile لعينة الصفقات المجمعة، VWAP مشتق من الشموع، Relative Volume، Realized Volatility وRange Expansion.
- `market_intelligence.py`: إشارة موقع السعر بالنسبة إلى Session VWAP وعينة Delta، وتوافق دفاتر الأوامر عبر المنصات، وضغط التصفية كتحذير مخاطر.
- `feed_health.py`: يراجع freshness للمصادر الأساسية، وعمر آخر دفتر، وحالة الاتصال وheartbeat لكل WebSocket. يميز `live` و`connected_quiet_ok` و`stale` و`recovering` و`unavailable`. قنوات التصفية event-driven؛ غياب حدث جديد لا يصنفها stale ما دام heartbeat مستمراً.
- `orderbook_sync.py`: إعادة بناء Binance Spot L2 من REST Snapshot وتحديثات Diff مع كشف فجوات update IDs.
- `venue_books.py`: موائم دفتر Bybit وOKX، مع update ID في Bybit وseqId/prevSeqId في OKX.
- `market_store.py`: تخزين عينات العمق وأحداث التصفية وحالة كل منصة في SQLite وقراءتها بوضع read-only. يمنع تكرار event_key، ويجمع التصفية حسب المنصة والجهة ووحدة العقد.
- `market_stream.py`: عامل WebSocket مستقل لـBinance Spot وBybit Linear وOKX Spot، مع reconnect وتدرج زمني وإعادة مزامنة وتسجيل تاريخ العمق؛ ويطلق `liquidation_stream.py` بالتوازي عند تفعيل التصفية.
- `trade_stream.py`: بث صفقات Binance USDⓈ-M وBybit Linear وOKX Spot، مع reconnect وheartbeat مستقل عن وصول الصفقات.
- `trade_analytics.py`: dedup وتخزين CVD وFootprint ذرياً، وقراءة تاريخ الصفقات بوضع read-only وتطبيق مدة الاحتفاظ.
- `trade_profile.py`: CVD متعدد المنصات بحدود حداثة وعينة دنيا، وفصل Spot/Perpetual وبناء POC/VAH/VAL لكل منصة.
- `depth_analytics.py`: Heatmap تاريخية واستمرار مستويات السعر وPull/Stack proxy من لقطات متتالية مع تغطية وحداثة.
- `cross_venue_derivatives.py` و`providers/cross_venue.py`: مقارنة Basis وMark/Index وFunding 8h وOI حسب الوحدات الأصلية؛ بلا تجميع OI عبر وحدات مختلفة.
- `screener.py`: اكتشاف أحداث متعددة الأطر والبيانات الحية المكتملة؛ لا ينشئ أوامر، ويعيد تحذيرات سياقية فقط إلى مركز القرار.
- `liquidations.py`: يحول رسائل التصفية إلى عقد موحد مع إبقاء وحدة الحجم والسعر المرجعي الخاصين بكل منصة.
- `liquidation_stream.py`: موائمات WebSocket للتصفية من Binance USDⓈ-M وBybit Linear وOKX SWAP.
- `liquidation_heatmap.py`: قراءة SQLite بوضع read-only وبناء price clusters لكل منصة ونوع السوق والجهة ووحدة الحجم ونوع السعر المرجعي، مع تغطية Notional وحالة feed.
- `options_surface.py`: Black-Scholes Delta/Gamma وصفي، وATM IV حسب الانتهاء، و25-delta Risk Reversal، وPut/Call OI وGamma-weighted OI proxy. هذا ليس SVI arbitrage-free ولا dealer GEX.
- `slow_context.py`: يجمع Mempool وCFTC وCoin Metrics وDVOL وخيارات Deribit بشكل مستقل؛ لا يوقف فشل أحدها بقية المصادر، ويبني On-chain daily context منفصلاً عن القرار اللحظي.
- `onchain.py`: يحسب MVRV عند توافره أو يشتقه من Market/Realized Cap، ويعرض NUPL مشتقاً وMVRV Z إن توفر وتغيرات 7 أيام وحداثة بيانات يومية. لا يقدّر SOPR ولا يصوت في مركز القرار.
- `providers/coinmetrics.py`: Core network metrics مع مجموعات MVRV/Realized Cap وMVRV Z اختيارية؛ فشل مجموعة اختيارية لا يسقط نشاط الشبكة الأساسي.
- `decision.py`: يجمع خمسة مجالات: Technical 35%، Orderflow 25%، Derivatives 20%، Market Structure 10%، Cross-Venue 10%. يضيف تحذيرات Cross-Venue derivatives وScreener دون تغيير score أو weights. يعيد تطبيع الأوزان حسب توافر المجالات وحداثتها، ويفرض Technical مع واحد على الأقل من Orderflow أو Derivatives.
- `live_snapshot.py`: يجلب بيانات المصادر السريعة، يحقق حداثتها، يبني كل محركات اللقطة، يقرأ حالة الجامع محلياً بوضع read-only ويرسل أدلة المحركات إلى مركز القرار.
- `app.py`: لوحة Streamlit الحالية، تعرض القرار وأدلة كل محرك ومصادر السوق والتصفية والخيارات، ولا تتصل بـMT5.
- `ea_bridge.py` و`command_protocol.py` و`automation.py` و`position_manager.py` و`mql5/BitcoinIntelligenceLabEA.mq5`: ملفات محفوظة لمرحلة ربط Headway المستقبلية؛ ليست جزءاً من تشغيل اللوحة الآن.

## أوزان مركز القرار والحواجز

| المجال | الوزن الأساسي | الاستخدام |
|---|---:|---|
| Technical / Multi-timeframe | 35% | الاتجاه من شموع مكتملة متعددة الأطر |
| Orderflow | 25% | تدفق الصفقات ودفتر Spot وSpread |
| Derivatives | 20% | Taker flow مع Funding/OI كسياق |
| Market Structure | 10% | VWAP location + sampled trade delta |
| Cross-Venue | 10% | Median normalized imbalance عبر منصتين أو أكثر |

- إذا لم تتوفر بيانات حديثة لمجال اختياري، يعاد توزيع الوزن المتاح على بقية المجالات الصالحة.
- يجب أن يبقى المجال الفني صالحاً، ومعه واحد على الأقل من Orderflow أو Derivatives. لا تكفي Market Structure وCross-Venue وحدهما.
- الدليل القوي المتعارض من أكثر من مجال يفرض HOLD.
- التصفية تعرض ضغط LONG/SHORT عبر المنصات كتحذير مخاطر؛ لا تضيف صوتاً اتجاهياً ولا تضمن انعكاساً.
- خيارات Deribit وDVOL وCFTC وOn-chain سياق أبطأ؛ لا تُستخدم كمحفز دخول لحظي.
- النتيجة Score اتجاهي وليست win probability.

## بروتوكولات دفتر الأوامر

### Binance Spot
- يشترك في `<symbol>@depth@100ms` ويخزن Diff مؤقتاً.
- يجلب REST Snapshot بعمق 5000 مستوى.
- يتخلص من الرسائل التي `u <= lastUpdateId` ثم يعبر Snapshot بأول نطاق تحديث صالح.
- إذا تجاوز `U` آخر update ID المحلي + 1، يبطل الدفتر ويعيد جلب Snapshot.

### Bybit Linear
- يشترك في `orderbook.50.BTCUSDT` أو `orderbook.200.BTCUSDT`.
- يبدأ من Snapshot ثم يطبق Delta: صفر يحذف المستوى والقيمة الجديدة تستبدل الحجم.
- عند رسالة إعادة Snapshot/restart يبدل الدفتر المحلي.
- لا يفرض تتابعاً متتالياً على Cross Sequence؛ يعتمد update ID ويعيد المزامنة عند إعادة الضبط.

### OKX Spot
- يشترك في قناة `books` للأداة `BTC-USDT`.
- Snapshot يبدل الدفتر بالكامل.
- كل Update لاحق يجب أن يحقق `prevSeqId == last seqId`; عند الاختلاف يبطل الدفتر ويعاد الاتصال.
- يستخدم رابط WebSocket العام عبر المنفذ الافتراضي 443، لا 8443.

## محرك التصفية وتطبيع الوحدات

- **Binance USDⓈ-M:** يستخدم حجم التنفيذ التراكمي `z` ومتوسط التنفيذ `ap` فقط لحساب Notional USD. SELL يعني تصفية LONG، وBUY تصفية SHORT. المصدر محدود بلقطة أحدث حدث لكل رمز في نافذة 1000ms؛ ليس سجلاً كاملاً لكل التصفيات.
- **Bybit Linear:** `S=Buy` يعني تصفية Long و`S=Sell` يعني تصفية Short. `p` سعر الإفلاس وليس سعر تنفيذ، والحجم يحفظ بوحدته المعلنة.
- **OKX SWAP:** يرشح `BTC-USDT-SWAP`. يستخدم `posSide` متى توفرت جهة صريحة؛ وفي وضع net يحدد جهة المركز من أمر الإغلاق. `bkPx` سعر مرجعي، و`sz` عدد عقود؛ لا يحول إلى USD قبل معرفة معامل العقد.
- تعرض اللوحة آخر 60 دقيقة، بينما يأخذ ملخص المخاطر في مركز القرار آخر 5 دقائق. لا تجمع أحجام BTC مع العقود ولا تساوي سعر الإفلاس بسعر التنفيذ.

## سياق On-chain اليومي — Coin Metrics Community

- `CapMVRVCur` إذا كان متاحاً، وإلا يمكن اشتقاق MVRV = Market Cap / Realized Cap عندما تتوفر القيمتان.
- NUPL معروض باسم `nupl_derived` ومشتق من (Market Cap - Realized Cap) / Market Cap؛ ليس حقلاً مباشراً من المصدر في هذا المسار.
- MVRV Z-score يعرض فقط عند عودة `CapMVRVZ` من Community API؛ وإلا تبقى القيمة غير متاحة دون تخمين.
- MVRV/Realized Cap الاختيارية تجلب بصورة مستقلة؛ فشلها لا يسقط Active Addresses أو Block Height.
- المصدر يومي ويصنّف stale بعد 72 ساعة، ويحسب تغيرات 7 أيام فقط عند وجود baseline تاريخي صحيح.
- SOPR غير موصول ولا يستنتج من بيانات أخرى؛ On-chain كامل يبقى slow context only ولا يدخل مركز القرار اللحظي.
- راجع شروط Coin Metrics Community؛ مستوى Community محدود ومخصص للاستخدام غير التجاري.

## محرك خيارات Deribit — الحدود الرياضية

- `mark_iv` يحول من نقاط مئوية إلى قيمة عشرية قبل حساب Greeks.
- أقرب أربع strikes إلى spot تعطي ATM IV تقريبياً لكل expiry، ولا يوجد fit لمنحنى SVI في هذا المحرك.
- 25-delta Risk Reversal يعتمد أقرب call delta إلى +0.25 وput delta إلى -0.25 مع Black-Scholes spot delta وتقريب zero rates.
- Open Interest الخاص بخيارات BTC يحفظ بوحدة BTC بحسب المصدر، ولا يحدد أي جانب يملكه dealer.
- Gamma-weighted OI قيمة إجمالية غير موقعة؛ لا تسمى dealer GEX أو Net Gamma Exposure.

## التخزين والتحقق

- SQLite في WAL mode، ويحفظ عينات العمق تقريباً كل خمس ثوانٍ، وأحداث التصفية بعد إزالة التكرار.
- تنظيف البيانات الأقدم من مدة الاحتفاظ يجري دورياً؛ الافتراضي 24 ساعة والحد الأقصى 30 يوماً.
- اللوحة ولقطة السوق تقرآن SQLite بوضع read-only.
- وحدات التصفية والخيارات والدفتر ومراقب صحة المصادر لها اختبارات بيانات مصطنعة deterministic، وCI يتحقق من Python compile واختبارات الوحدات وبدء Streamlit واستدعاء بيانات BTC العامة. الاختبارات الأخيرة غطت حالات توقف heartbeat مع استمرار صمت أحداث التصفية.
- CI #340 يمر على Python 3.12 و3.13 مع 219 اختباراً، ويفحص Python compile وبدء Streamlit ومصادر BTC العامة وعدم وجود واجهات تنفيذ تداول. هذا لا يثبت اتصالاً حياً مستقراً لساعات على Windows؛ يجب قياس مدة التشغيل والذاكرة والقرص والتغطية والتعافي من انقطاع الشبكة على جهاز المستخدم.

## مرحلة MT5 المستقبلية — ليست نشطة الآن

عندما تُعتمد المحركات واللوحة بعد التدقيق، يعاد ربط الخبير وفق هذا الفصل:
1. القرار المركزي فقط ينشئ أمر OPEN/CLOSE.
2. Headway عبر MT5 هو وسيط التنفيذ الوحيد.
3. التحقق من خادم Headway-Demo والحساب والرمز وخصائص العقد والأسعار والوقف.
4. انتظار ACK ومطابقة حالة المراكز قبل إرسال أمر تالٍ.
5. لا يغلق HOLD مركزاً، ولا يضاف مركز في الاتجاه نفسه، ويُغلق المركز المعاكس ويؤكد اختفاؤه أولاً.
6. قياس الانزلاق والعمولات والتعبئة والسحب والنتائج بعد اختبار فعلي.

لا تُشغّل هذه المرحلة الآن؛ كودها محفوظ لكنه غير موصول بتطبيق Streamlit.

## نقاط التطوير التالية

1. تشغيل WebSocket الحي على Windows والتحقق من التغطية الفعلية ومدة التشغيل والذاكرة والقرص وإعادة الاتصال.
2. معايرة حدود Screener وCVD/Footprint وHeatmap تاريخياً، وقياس الإنذارات الكاذبة وتكرار الإشارات قبل اعتماد قيم تشغيل نهائية.
3. معايرة تغطية خريطة التصفية السعرية، والتحقق من Contract multipliers لكل منتج قبل أي توسيع لتحويل الأحجام إلى Notional USD.
4. رفع محرك خيارات Deribit إلى SVI/Calendar consistency وسجل تاريخي واختبارات no-arbitrage.
5. معايرة سلسلة MVRV/Realized Cap/NUPL اليومية والتحقق من التغطية والحدود والتأخير؛ العثور على مصدر مرخص لـSOPR وETF flows قبل توصيلهما.
6. تدقيق شامل للوحة والمصادر وحالات stale/error/partial وسجل القرار، ثم فقط فتح مرحلة Headway.
