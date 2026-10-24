# المطابقة البصرية بين TradingView وMT5 — المسار المعتمد

## الحالة

**المقارنة الآلية لبيانات السوق المأخوذة من TradingView معطّلة.** سياسة TradingView الحالية تقصر بيانات المنصة على العرض المقروء من الإنسان وتقيّد المعالجة غير المعروضة، ومنها استخدامها في قرارات التداول الآلي. لذلك لا نصدر بيانات الرسم إلى CSV، ولا نرفعها إلى GitHub، ولا ندخلها في اختبار خوارزمي.

المراجع الرسمية:
- [سياسة TradingView](https://www.tradingview.com/policies/)
- [تعريف التقييمات الفنية والمكونات الـ26](https://www.tradingview.com/support/solutions/43000614331-technical-ratings/)

## خطوات المقارنة المرئية

1. افتح رمز الذهب الفوري الذي تريد مراجعته على TradingView، وأضف المؤشر المرئي [TradingView_Visual_Parity_5TF.pine](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TradingView_Visual_Parity_5TF.pine).
2. على MT5، افتح XAUUSD مع لوحة TV26 العربية، وأوقف التداول الآلي أثناء الفحص.
3. ابدأ بوقت آخر شمعة مغلقة، ثم قارن الافتتاح والأعلى والأدنى والإغلاق. بعد ذلك قارن الملخص العام، والمتوسطات الـ15، والمذبذبات الـ11، ثم التصويتات الـ26 عبر M1/M5/M15/M30/H1.
4. إذا اختلف الوقت أو OHLC، فهذه مقارنة بين مصدرين أو محاذاتين مختلفتين؛ لا تُعدّل المعادلات لتجعل الأرقام تتطابق اصطناعيًا. يجب أن يكون المصدر والتوقيت متطابقين قبل الحكم على صيغة أي مؤشر.
5. سجّل الفروق التي تراها يدويًا بالاسم والإطار والشمعة. تطابق عينة واحدة يؤكد تلك العينة فقط، ولا يثبت مطابقة كل التاريخ أو ربحية المستشار.

## حدود ما أثبتناه حتى الآن

- مرجع صيغ TechnicalRating v3 والاختبارات الحسابية على بيانات MT5 اجتازا اختبارات المصدر والتصويتات على تغذية MT5 المسجلة.
- نجاح مترجم Pine وMetaEditor واختبارات Python لا يثبت وحده التطابق الرقمي مع مخطط حي آخر.
- **المطابقة المباشرة مع القيم المرئية على مخطط TradingView ما زالت غير مكتملة**؛ تحتاج مراجعة بشرية للقيم الظاهرة في المنصتين على شموع متطابقة.
- توافق المؤشرات لا يعني أن استراتيجية التداول مربحة. بوابة اختبار الربحية المستقلة لثلاثة أيام لم تجتز بعد.

## ملفات مرجعية

- لوحة العرض فقط: [TradingView_Visual_Parity_5TF.pine](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TradingView_Visual_Parity_5TF.pine)
- تقرير الحالة: [TV26_DIRECT_PARITY_STATUS_2026-10-24.md](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TV26_DIRECT_PARITY_STATUS_2026-10-24.md)
- نتائج اختبار المستشار: [TV26_FOLLOWUP_VALIDATION_2026-10-24.md](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TV26_FOLLOWUP_VALIDATION_2026-10-24.md)

ملفات CSV القديمة ومحوّلها محفوظة كمرجع تقني واختبارات صناعية فقط؛ لا تستخدمها لتصدير أو معالجة بيانات سوق فعلية من TradingView.
