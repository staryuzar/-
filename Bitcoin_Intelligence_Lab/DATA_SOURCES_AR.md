# سجل المصادر — مراجعة 31 أكتوبر 2026

| المجال | المصدر / نقطة النهاية | الوصول | الحد / التحفظ |
|---|---|---|---|
| Spot candles/depth/trades | Binance Spot `data-api.binance.vision/api/v3` | عام، بلا مفتاح | سوق واحد؛ ليس تجميعًا عالميًا |
| Perpetual funding/OI | Binance USDⓈ-M Futures `fapi.binance.com/fapi/v1` | نقاط سوق عامة | التمويل ومؤشر OI لا يمثلان كل البورصات |
| Taker ratio | Binance Futures `/futures/data/takerlongshortRatio` | عام ضمن حدود الواجهة | تاريخ محدود بحسب توثيق endpoint |
| Mining / fees / mempool | mempool.space REST API | عام | حدود طلبات و429؛ لا يُستخدم لإثبات تدفقات منصات |
| On-chain daily metrics | Coin Metrics Community API | دون API key لمسارات Community | غير تجاري بشروط CC؛ حد الطلب 10 / 6 ثوانٍ؛ تغطية أقل من Pro |
| CME positioning | CFTC Traders in Financial Futures, Futures Only | ملفات أسبوعية عامة | تأخير أسبوعي، فئات TFF ليست كل سوق BTC |
| DVOL | Deribit public API | بيانات عامة | مؤشر تقلب مشتق، لا يضمن تمثيل كل خيارات السوق |
| تنفيذ وسيط المستخدم | MT5 | جلسة الوسيط المحلية | رمز/عقد/سبريد/قيمة tick يختلف حسب الوسيط |

## روابط توثيق مرجعية
- Binance API overview: https://developers.binance.com/en/docs/introduction
- Binance public Spot market data: https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md
- Binance USDⓈ-M futures market data: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
- Coinbase Advanced Trade WebSocket (للتوسعة عبر منصة ثانية): https://help.coinbase.com/en/developer-platform/websocket-feeds/advanced-trade
- CFTC historical compressed reports: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
- CFTC TFF column definitions: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/cotvariablestfm.html
- mempool.space API: https://mempool.space/docs/api/rest
- Coin Metrics API v4: https://docs.coinmetrics.io/api/v4/
- Coin Metrics Community terms: https://github.com/coinmetrics/product-docs/blob/master/docs/packages/coin-metrics-community-data.md
- Deribit API reference: https://docs.deribit.com/

## CFTC fields verified
صفحة المتغيرات الرسمية تعرّف الحقول بحسب ترتيب الأعمدة: Market Name (1)، Report Date (3)، Contract Market Code (4)، Open Interest (8)، Dealer Long/Short (9/10)، Asset Manager Long/Short (12/13)، Leveraged Money Long/Short (15/16)، ثم spreads والتغيرات والنسب. لذلك لا تُقرأ هذه القيم بترتيب ملف Gold disaggregated؛ تقرير TFF له schema مختلف. BTC=133741 وMicro BTC=133742.

## خارج النطاق حتى التحقق
- ETF issuer flows: لا نعتمد scraping غير موثق من مواقع وسيطة كبيانات رسمية. نضيف موائمًا فقط عند وجود ملف رسمي موثق أو ترخيص مناسب.
- Exchange reserve / whale labels: لا نصنف عنوانًا كمحفظة منصة أو حوت دون مصدر entity labels مع provenance.
- Liquidations: لا نخلط التصفية الجزئية من منصة واحدة مع إجمالي سوق المشتقات.
