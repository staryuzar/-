# تقرير حالة العمل — Bitcoin Intelligence Lab

**تاريخ التقرير:** 31 أكتوبر 2026  
**المستودع:** [staryuzar/-](https://github.com/staryuzar/-)  
**الفرع:** `bitcoin-intelligence-lab`  
**طلب المراجعة:** [PR #9 — Draft](https://github.com/staryuzar/-/pull/9)  
**آخر commit موثق في هذا التقرير:** `919456c08efe6036b4dd6caf979c6b2d9008b78d`

---

## 1. القرار التنفيذي المعتمد

تم تأجيل ربط خبير MT5 حتى تكتمل محركات البرنامج واللوحة ومركز القرار ويجتازوا التدقيق والاختبارات. لذلك:

- أزيلت من `app.py` جميع استدعاءات جسر MT5 وقراءة حالة الحساب والمراكز ونشر أوامر OPEN/CLOSE والإدارة التلقائية.
- لا تتصل اللوحة حالياً بحساب Headway، ولا تقرأ ملفات MT5، ولا ترسل أي أمر تداول.
- حُذف سير عمل Headway-Demo الآلي من الفرع؛ لا يوجد اتصال أو تجميع EA مطلوب لتطوير النسخة الحالية.
- ملفات EA والجسر وإدارة المراكز محفوظة في المستودع للمرحلة اللاحقة فقط، لكنها غير موصولة بالتطبيق الحالي.
- عندما تكتمل المحركات واللوحة، يكون Headway عبر MT5 وسيط التنفيذ الوحيد. Binance وBybit وOKX وDeribit مصادر بيانات فقط.

## 2. حالة GitHub والاختبارات

- الفرع المستقل: `bitcoin-intelligence-lab`.
- PR #9 مفتوح وDraft ولم يُدمج في الفرع الرئيسي.
- آخر حالة PR عند إعداد التقرير: 76 ملفاً متغيراً ونحو 9,627 إضافة.
- آخر commit برمجي اختُبر بالكامل: `1fe65e4ad4a6c058d85703a2ec3bdfcee1063b0e`.
- CI رقم **#302** نجح على Python 3.12 و3.13، وشغّل **169 اختباراً ناجحاً** لكل إصدار.
- شملت CI: Compile package، واختبارات المحركات والموائمات، وبدء Streamlit smoke test، وفحص مصادر BTC العامة الحية، والتحقق من عدم وجود APIs تنفيذ تداول في موائمات Python.
- بعد commit الاختبار `1fe65e4` تغيرت ملفات توثيق فقط في آخر تحديثين: README وArchitecture. لم يتغير كود البرنامج بعد الاختبار الأخير.

رابط CI الناجح:  
https://github.com/staryuzar/-/actions/runs/41155218329

## 3. المحركات التي تم بناؤها

### أ. بيانات السوق الأساسية
- Binance Spot: شموع مكتملة ودفتر أوامر وصفقات مجمعة.
- Binance USDⓈ-M: Funding وOpen Interest وTaker Buy/Sell وتاريخ OI.
- Bybit V5: مشتقات احتياطية عند تقادم أو تعذر مصادر Binance.
- mempool.space: بيانات الشبكة والتعدين والرسوم والـMempool.
- CFTC TFF: تمركز عقود CME Bitcoin وMicro Bitcoin الأسبوعي.
- Coin Metrics Community: مقاييس شبكة وفق شروط الاستخدام المجتمعي.
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

### و. محرك خيارات Deribit
موجود في `options_surface.py` وموصول بالسياق الأبطأ:
- ATM IV تقريبي لكل expiry.
- 25-delta Risk Reversal من Black-Scholes spot delta.
- Put/Call Open Interest وTotal OI بوحدة BTC.
- Greeks وGamma-weighted OI proxy حسب strike.

**الحدود:** ليس SVI fitted arbitrage-free surface، ولا يقدر مخزون dealer. قيمة Gamma-weighted OI ليست Dealer GEX أو Net Gamma؛ لذلك الخيارات سياق تقلب ومراكز بطيء لا صوت BUY/SELL.

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

### الأولوية 1 — إثبات صحة وتشغيل البيانات
1. تشغيل جامع WebSocket على Windows لفترة طويلة والتحقق من memory/disk/reconnect/resync.
2. قياس تغطية كل Venue وevent rate وheartbeat وtimestamp drift.
3. إضافة سجل Trades مستمر مع dedup إلى SQLite.

### الأولوية 2 — محركات Microstructure وCross-Venue
4. بناء Footprint وCVD لكل منصة وفاصل من تدفق الصفقات المستمر.
5. إنشاء Heatmap تاريخية للعمق وPull/Stack وLiquidity persistence.
6. تطوير Cross-Venue price/basis/funding/OI بعد توحيد نوع العقد والوحدة والعملة.
7. تطوير Liquidation Heatmap سعرياً مع وصف التغطية لكل Venue.

### الأولوية 3 — الخيارات وOn-chain وScreener
8. تطوير Options SVI/Calendar surface history واختبارات No-Arbitrage.
9. إضافة MVRV/NUPL/SOPR/Realized Cap من Bitcoin Core أو مصدر موثق ومرخص، وETF flows إن توفر مصدر صالح.
10. بناء Screener وكواشف أحداث متعددة الأطر؛ كل كاشف يعرض درجة ودليلاً ووقتاً ولا يرسل أمراً.

### الأولوية 4 — تدقيق البرنامج واللوحة
11. مراجعة كل محرك: المدخلات والمخرجات والحداثة والوحدات والـfallback والاختبارات.
12. اختبار توافق/تعارض المحركات وتغطية البيانات المنخفضة.
13. تدقيق حالات stale/error/partial، وزمن التحديث واستهلاك الموارد، وتصدير سجل القرار.
14. تشغيل smoke على Windows للوحة والجامع معاً.

### الأولوية 5 — Headway لاحقاً فقط
15. بعد اعتماد المحركات واللوحة، يعاد فتح ربط EA مع Headway عبر MT5.
16. اختبار Headway-Demo والرمز الحقيقي وخصائص العقد ثم دورة OPEN/ACK/Position/Reversal/CLOSE/ACK.
17. قياس الانزلاق والعمولة وأوقات التعبئة والنتائج قبل أي تقييم ربحية.

## 8. ما لم يثبت بعد

- لم يثبت التشغيل الحي المتواصل لدفاتر WebSocket والتصفية على جهاز Windows الخاص بالمستخدم.
- لم يكتمل Footprint/CVD المستمر وHeatmap التاريخية وPull/Stack.
- لم يكتمل Cross-Venue basis/funding/OI normalization.
- لم يكتمل SVI/Options historical surface ولا On-chain advanced.
- لم ينفذ أي اختبار تداول Headway في المرحلة الحالية؛ وهذا تأجيل مقصود، لا نقص غير معروف.
- لا توجد نتائج ربحية موثقة.

**الخلاصة:** البرنامج الآن لوحة تحليل وقرار مركزي متعدد المجالات، منفصلة عن MT5. تم ربط خمسة مجالات أدلة في القرار، وإضافة مراقب صحة المصادر والـheartbeat، واجتازت النسخة البرمجية الحالية 169 اختباراً على Python 3.12 و3.13. الخطوة التالية هي تشغيل الجامع واللوحة باستمرارية على Windows، ثم تطوير Footprint/CVD وHeatmap وPull/Stack وتوسيع التوحيد بين المنصات. لا يعاد ربط Headway قبل اكتمال هذه المراحل.
