# GoldLab — مواصفات الاختبار الثابت

## إعداد الاختبار الأساسي
- Expert: GoldLabEA
- Symbol: XAUUSD (الاسم الدقيق يقرأ من الوسيط؛ قد يوجد لاحقة)
- Period: M5
- Date: 2026.09.01 إلى 2026.09.01
- Model: Every tick based on real ticks (MT5 model value 4) إذا كانت بيانات التيكات الحقيقية متوفرة
- Deposit: 500 USD
- Leverage: 1:1000 (للمقارنة مع حساب Headway التجريبي المذكور سابقًا)
- Risk per trade: 0.50% من Equity
- Initial SL: 1.8 ATR; TP: 2.4 ATR; trailing: 1.4 ATR
- لا توجد DailyLossLimit أو MaxTradesPerDay أو تعطيل بعد خسائر متتابعة.
- يجب تفعيل التكلفة/العمولة والسبريد المتاحين من إعدادات الرمز/الوسيط، وتوثيقها.

## النتائج المطلوبة من كل تشغيل
1. HTML report الأصلي من Strategy Tester.
2. Journal وExperts logs.
3. قائمة الصفقات/الصفقات المنفذة مع وقت الدخول والخروج والاتجاه والحجم والسعر والربح والعمولة والسواب وسبب الخروج.
4. Summary: Net Profit, Gross Profit/Loss, Profit Factor, Expected Payoff, Recovery Factor, equity/balance drawdown, trades, win/loss counts, average win/loss, longest losing streak.
5. ملف إعدادات SET وبصمة SHA-256 للمصدر/الملف التنفيذي.
6. فحص اكتمال بيانات الفترة ووجود real ticks؛ إذا تعذر ذلك فالنتيجة غير صالحة للمقارنة مع تشغيل حقيقي ببيانات مختلفة.

## قاعدة التعديل
لا تغيّر أكثر من فرضية رئيسية واحدة في كل جولة. اكتب سبب التعديل قبل الاختبار. لا تختار معلمات من يوم الاختبار نفسه باعتبارها نهائية؛ يوم الاختبار الثابت يستخدم للتشخيص والمقارنة فقط، وبعده يلزم اختبار مستقل خارج العينة.
