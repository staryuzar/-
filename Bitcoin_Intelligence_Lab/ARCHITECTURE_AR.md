# معمارية Bitcoin Intelligence Lab

## المرحلة الحالية والحد الفاصل

**طبقة Headway/MT5 موجودة في الكود كوحدة تنفيذ مستقلة، لكنها لا تبدأ تلقائيًا مع اللوحة.** لوحة Streamlit تعرض القرار ونبض المستشار وحالة حلقة التنفيذ وإقرار الوسيط؛ ولا تنشر أوامر عند تحديث الصفحة. وجود ملف EA أو آخر علامة READY لا يثبت أن حلقة التنفيذ تعمل الآن. تتطلب الحلقة تفعيلًا صريحًا على جهاز Windows الذي تعمل عليه MT5، ويجب أن يكون نبضها حديثًا قبل وصفها بأنها نشطة.

Binance وBybit وOKX وDeribit مصادر بيانات عامة للقراءة فقط. Headway عبر MT5 هو وسيط التنفيذ الوحيد. لا يفحص EA أو الجسر نوع الحساب أو يخزنه؛ يتحققان من خادم Headway واتصال الطرفية وصلاحية التداول وحداثة الحالة ومواصفات الرمز.

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
- `orderflow.py`: يصوّت فقط على دلتا الصفقات المنفذة (Aggressor/Taker Buy-Sell)، ويعرض اختلال الدفتر والسبريد كسياق غير تصويتي. لا يكرر وزن دفتر Spot داخل مجال Cross-Venue.
- `derivatives.py`: Funding وOpen Interest وTaker ratios؛ التمويل وOI سياق تمركز ولا يحددان الاتجاه منفردين.
- `market_structure.py`: Volume Profile لعينة الصفقات المجمعة، VWAP مشتق من الشموع، Relative Volume، Realized Volatility وRange Expansion.
- `market_intelligence.py`: Market Structure يصوّت على موقع السعر بالنسبة إلى Session VWAP فقط؛ عينة Delta تعرض كسياق لا يعاد احتسابه. ويحسب توافق دفاتر الأوامر عبر المنصات وضغط التصفية كتحذير مخاطر.
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
- `live_snapshot.py`: يفصل جلب عمق REST عن جلب الصفقات؛ تعذر العمق لا يلغي صوت Orderflow إذا كانت الصفقات حديثة. كما يعيد إرفاق سياق المشتقات المتعددة بعد اختيار بديل Bybit حتى لا تضيع تحذيراته، ويقرأ حالة الجامع محلياً بوضع read-only.
- `snapshot_runtime.py`: محرك اللقطات المشترك الوحيد؛ يجمع `build_live_snapshot`، وينشر JSON ذرياً في `data/live_snapshot.json`، ويكتب heartbeat منفصلاً ويحافظ على آخر لقطة ناجحة عند فشل دورة لاحقة. يستقبل طلب تحديث من اللوحة دون أن تجعل Streamlit يعيد جلب مصادر السوق.
- `execution_loop.py`: يقرأ اللقطة المشتركة نفسها التي تعرضها اللوحة، ولا يستدعي موائمات السوق أو يبني قراراً مستقلاً. يرفض اللقطة المفقودة/المتقادمة قبل تخطيط OPEN أو CLOSE؛ حد الحداثة الافتراضي 90 ثانية.
- `ea_bridge.py`: يقرأ نبض EA وملف المراكز وإقرار الأمر، ويتحقق من خادم Headway وحداثة السعر، وينشر أوامر OPEN/CLOSE ذرياً إلى Common Files؛ لا يقرأ تصنيف الحساب.
- `command_protocol.py`: يبني رسائل BTCIL1 ذات TTL، ويكتب الأمر ذرّياً ويقرأ ACK.
- `position_manager.py`: يترك المراكز عند HOLD أو الاتجاه الموافق، ويطلب إغلاق تذكرة واحدة عند انعكاس قرار المركز؛ لا يفتح مركزاً إضافياً في الاتجاه نفسه.
- `execution_loop.py`: حلقة مستمرة كل 30 ثانية افتراضياً، تقرأ لقطة السوق والقرار المركزي ثم مركز الخبير؛ تنشر OPEN أو CLOSE فقط إذا كان القرار صالحاً وحديثاً، وتكتب نبضاً ذرياً للوحة. لا تبدأ إلا عند تعيين `BTCIL_ENABLE_EXECUTION=1` صراحةً.
- `mql5/BitcoinIntelligenceLabEA.mq5`: منفذ أوامر فقط؛ لا يصنع إشارات على OnTick. يتحقق من Headway وصلاحية الطرفية والرمز والحجم والوقف وحد المخاطرة، ويستخدم MagicNumber وقفل مثيل وحيد لكل رمز، ويربط ACK برقم request_id الذي يصدره الطرفيـة للطلب، ويستخدم نتيجة MqlTradeResult.volume المؤكدة من الوسيط؛ الطلبات المعلقة/الجزئية تراجع أوامرها وصفقاتها التاريخية قبل الحسم.
- `app.py`: لوحة Streamlit تقرأ `data/live_snapshot.json` المشترك ولا تستدعي مصادر السوق عند إعادة الرسم. تكتب طلب تحديث صغيراً ليستهلكه `snapshot_runtime`، وتقرأ ملفات حالة EA/Execution Loop والمراكز وACK بوضع القراءة فقط؛ لا تنشر أوامر.
- `system_status.py`: يجمع صحة البيانات، المجالات الأساسية الحديثة، قرار المركز، جاهزية Headway، نبض حلقة التنفيذ، المراكز والأوامر المعلقة في عقد جاهزية واحد للوحة. هو قارئ حالة فقط ولا ينشر أو يجيز أوامر.
- `scripts/Start-BitcoinIntelligenceLab.ps1`: مشغّل Windows موحد يعيد استخدام Collector وSnapshot Service وStreamlit القائمة ولا يكررها؛ يفعّل حلقة التنفيذ فقط عند تمرير `-EnableExecution` وبعد تحقق حداثة اللقطة وملف حالة Headway.

## أوزان مركز القرار والحواجز

| المجال | الوزن الأساسي | الاستخدام |
|---|---:|---|
| Technical / Multi-timeframe | 35% | الاتجاه من شموع مكتملة متعددة الأطر |
| Orderflow | 25% | Aggressor trade delta وCVD؛ العمق والسبريد سياق فقط |
| Derivatives | 20% | Taker flow مع Funding/OI كسياق |
| Market Structure | 10% | Session VWAP location فقط؛ sampled trade delta سياق غير تصويتي |
| Cross-Venue | 10% | Median normalized imbalance عبر منصتين أو أكثر |

- إذا لم تتوفر بيانات حديثة لمجال اختياري، يعاد توزيع الوزن المتاح على بقية المجالات الصالحة.
- يجب أن يبقى المجال الفني حديثاً وصالحاً، ومعه واحد على الأقل من Orderflow أو Derivatives. يتطلب MTF ثلاث أطر حديثة على الأقل وسياقاً واحداً على الأقل من 1D أو 4H؛ ولا تكفي Market Structure وCross-Venue وحدهما.
- يمنع تكرار نفس متغير العمق كصوت داخل Orderflow وCross-Venue، ويمنع تكرار Trade Delta كصوت داخل Orderflow وMarket Structure. قد يظل Taker ratio في المشتقات مرتبطاً إحصائياً بتدفق CVD؛ لا يعامل Score كمقياس احتمال ولا كأدلة مستقلة إحصائياً.
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
- أحدث خط أساس ناجح: CI #898 على Python 3.12 و3.13 مع 257 اختباراً لكل إصدار. نجح Windows Runtime #898 في تجميع EA الحقيقي بـMetaEditor (0 أخطاء و0 تحذيرات)، وتشغيل WebSocket وSQLite وStreamlit وقراءة اللوحة للقاعدة نفسها. التعديلات اللاحقة الخاصة بتجميع صفقات Order الواحدة والإقرار الجزئي قيد إعادة الاختبار في CI/MetaEditor؛ لا يُنسب إليها نجاح قبل اكتمال هذه الجولة.

## حلقة تنفيذ Headway — الوضع التشغيلي والقيود

1. القرار المركزي وحده يختار BUY/SELL/HOLD. لا ينشئ EA إشارات مستقلة داخل OnTick.
2. `execution_loop.py` يقرأ اللقطة كل 30 ثانية افتراضياً؛ HOLD أو أي blocker لا ينشئ أمراً ولا يغلق مركزاً.
3. عند عدم وجود مركز للخبير، ينشر أمر OPEN بمهلة 60 ثانية، ويحسب SL/TP من ATR وسعر الوسيط. الافتراضي 0.01 لوت؛ يرفض EA الحجم إن خالف min/max/step أو تجاوزت الخسارة المحسوبة 0.5% من حقوق الحساب.
4. عند انعكاس القرار، ينشر CLOSE لتذكرة يملكها EA فقط. لا يفتح مركزاً عكسياً قبل ظهور حالة المركز بعد الإغلاق؛ والإغلاق الجزئي يعاد تقييمه حسب الحجم المتبقي.
5. معرّف CLOSE الأساسي مربوط بالتذكرة والحجم المتبقي. لا يعاد نشر الأمر بعد إقرار إغلاق ناجح؛ وعند رفض الوسيط النهائي أو إلغائه يُنشأ معرّف محاولة جديد متسلسل (-R1 ثم -R2...) كي لا يظل المركز عالقاً بسبب idempotency. أما الأمر المعلّق أو ذو الإقرار المفقود فلا يعاد إرساله؛ يُنتظر الحسم أو المصالحة. بعد الإغلاق الجزئي يتغير الحجم المتبقي، ويستخدم له معرف حجم مستقل.
6. EA يقفل مثيلاً واحداً لكل رمز/MagicNumber، ويربط الصفقات برقم Order الصادر عن الوسيط. الإقرار يميز SUBMITTED_PENDING وPARTIAL_FILL_PENDING وOPEN/CLOSE_PARTIAL_FILL_CONFIRMED عن التنفيذ الكامل.
7. اللوحة تقرأ نبض EA وExecution Loop والمراكز وACK للعرض فقط. لا ترسل أوامر عند تحديث Streamlit.
8. شغّل الحلقة على الجهاز الدائم نفسه الذي تعمل عليه MT5. GitHub-hosted Windows runner مؤقت ويصلح للتجميع والاختبارات فقط؛ لا يظل متصلاً بعد انتهاء المهمة ولا يصلح لمراقبة مراكز حية.

أمر التشغيل من مجلد `Bitcoin_Intelligence_Lab` بعد تشغيل جامع البيانات واللوحة وفتح MT5 على رمز BTC لدى Headway:
```powershell
$env:BTCIL_ENABLE_EXECUTION = "1"
python -m bitcoinlab.execution_loop --interval-seconds 30 --volume 0.01
```
للتأكد من دورة واحدة فقط أضف `--once`. دون متغير التفعيل، ترفض الحلقة البدء. لا توجد حتى الآن صفقة حقيقية مؤكدة من هذه النسخة، ولا يدّعي CI أنه سجل الدخول أو وضع أوامر.

## نقاط التطوير التالية

1. تشغيل WebSocket الحي على Windows والتحقق من التغطية الفعلية ومدة التشغيل والذاكرة والقرص وإعادة الاتصال.
2. معايرة حدود Screener وCVD/Footprint وHeatmap تاريخياً، وقياس الإنذارات الكاذبة وتكرار الإشارات قبل اعتماد قيم تشغيل نهائية.
3. معايرة تغطية خريطة التصفية السعرية، والتحقق من Contract multipliers لكل منتج قبل أي توسيع لتحويل الأحجام إلى Notional USD.
4. رفع محرك خيارات Deribit إلى SVI/Calendar consistency وسجل تاريخي واختبارات no-arbitrage.
5. معايرة سلسلة MVRV/Realized Cap/NUPL اليومية والتحقق من التغطية والحدود والتأخير؛ العثور على مصدر مرخص لـSOPR وETF flows قبل توصيلهما.
6. تدقيق شامل للوحة والمصادر وحالات stale/error/partial وسجل القرار، ثم فقط فتح مرحلة Headway.


## مراجعة النظام الشاملة — تحديث 31 أكتوبر 2026

### الفصل بين جاهزية الإدارة وجاهزية فتح مركز جديد
- **Management readiness:** تتطلب نبضة EA الأساسية المكتملة (15 حقلاً) وحداثتها، اتصال الطرفية وخادم Headway وصلاحية التداول، وصحة بيانات الخسارة اليومية، وخدمة اللقطة، وحداثة اللقطة نفسها، وحلقة تنفيذ لها نتيجة دورة صالحة، وملف مراكز EA صالحاً.
- **Entry readiness:** تضيف إلى ذلك مواصفات الوسيط الست الصحيحة (21 حقلاً)، وأن تكون الخسارة اليومية دون حدها، وقرار BUY/SELL حديثاً بلا blockers، وعدم وجود مركز BTC يديره الخبير أو أمر سابق لم تتم مصالحته.
- نقص حقول تسعير/حجم العقد الست لا يمنع قراءة المراكز وإدارة إغلاقها؛ لكنه يمنع حساب حجم صفقة جديدة.
- بلوغ حد الخسارة اليومية يمنع المداخل الجديدة، ولا يعطل مسار إغلاق المراكز القائمة متى بقيت بيانات الحساب والاتصال وصلاحية الطرفية صالحة.
- هوية خادم Headway مطلوبة، لكن تصنيف Demo/Live لا يشكل حاجزاً مستقلاً في المشرف. تبقى كل حدود المخاطر والتحقق من العقد والاتصال سارية على أي خادم Headway.

### عقد ملف المراكز وأوامر الجسر
- ملف positions.tsv مطلوب وليس اختيارياً. غيابه أو فساد ترويسته أو أي صف فيه يجعل لقطة المراكز غير موثوقة؛ فيتوقف القرار التنفيذي عن إرسال أي أمر بدلاً من تفسير الحالة على أنها صفر مراكز.
- publish_decision_order وpublish_close_order يحترمان حالة الأمر المعلق مباشرة، وليس اعتماداً على أن المستدعي هو execution_loop فقط؛ لا يُستبدل ملف الأمر ما دام ACK النهائي أو المصالحة لم يكتمل.
- ACK نهائي مرفوض/ملغى لإغلاق يسمح بمحاولة جديدة بمعرف مختلف. ACK إغلاق ناجح يبقى idempotent، والإغلاق الجزئي يعاد تقييمه مع الحجم المتبقي.
- heartbeat حلقة التنفيذ لا يعد سليماً لمجرد أن توقيته حديث؛ يلزم أن يحتوي نتيجة دورة صالحة. كما لا تعد خدمة اللقطات جاهزة إلا إذا كانت اللقطة ذاتها أحدث من حد التنفيذ (90 ثانية افتراضياً).

### شروط الأمان التي لم تتغير
- قرار مركزي واحد؛ EA منفذ فقط ولا ينتج إشارات مستقلة على OnTick.
- لا أوامر على HOLD أو قرار محجوب أو بيانات متقادمة.
- حجم Python افتراضياً مبني على 0.25% من Equity، وسقف EA المستقل 0.5% لكل صفقة؛ والحد اليومي 2%، مع احترام min/max/step الفعلية للوسيط وحد حجم الحلقة.
- لا يجبر النظام نفسه على التداول. لم تُحقن مواصفات وسيط افتراضية ولم تُخفّض متطلبات 21 حقلاً للدخول.
- Score اتجاهي وليس احتمال ربح. الأوزان والعتبات ما زالت بحاجة إلى اختبار تاريخي/خارج العينة قبل ادعاء أداء إحصائي.

التفاصيل، الملفات المعدلة، وحدود الإثبات المحلي موثقة في SYSTEM_AUDIT_AR_20261031.md.
