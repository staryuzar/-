# سجل بحث يوتيوب وتجربة ADX 23–30 — GoldLab

تاريخ البحث: 2026-10-23. هذا سجل منهجي لتطبيق ما أمكن التحقق منه من الدروس والوثائق؛ ليس ادعاءً بأن الفيديوهات شوهدت كاملة أو أن لها نتائج ربح مضمونة.

## مواد يوتيوب للمراجعة
1. **MQL5 Tutorial — How to use the Strategy Tester**: https://www.youtube.com/watch?v=MMYwKGAoiYE
2. **René Balke / FX Bot Trading — How To Use The MT5 Strategy Tester For Backtesting (EA Testing Explained)**: https://www.youtube.com/watch?v=lXn4QqNnoRQ
3. **MQL5 Tutorial — Running your first Backtest**: https://www.youtube.com/watch?v=6KSgHWoIIrM
4. **Sending Order in MQL5 using MqlTradeResult and MqlTradeRequest**: https://www.youtube.com/watch?v=oTihO60HX48
5. **MQL5 OrderSend tutorial**: https://www.youtube.com/watch?v=88OepMSenl8

ملاحظة وصول: تعذّر على متصفح البحث فتح بعض صفحات YouTube مباشرة؛ لذلك اعتمد سجل البحث على العناوين والروابط المتاحة، وعلى توثيق MQL5 الرسمي في النقاط التقنية. لا أدعي مشاهدة كاملة أو استخراج تفريغ صوتي لمحتوى غير متاح.

## القواعد التقنية التي طبقناها
- وثائق MT5 الرسمية تشرح أن real ticks أقرب إلى ظروف السوق من توليد ticks من شموع الدقيقة، لكنها لا تضمن اكتمال البيانات أو ربح الاستراتيجية: https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation
- توثيق اختبار الاستراتيجيات يطلب التحقق من صحة تنفيذ المستشار ومن أداء الاستراتيجية التاريخي كلٌّ على حدة: https://www.mql5.com/en/docs/runtime/testing
- نجاح استدعاء OrderSend وحده لا يكفي لإثبات تنفيذ الصفقة؛ يجب فحص نتيجة الطلب ونتيجة الخادم وسجل الصفقات الفعلية: https://www.mql5.com/en/docs/trading/ordersend
- لذلك يحافظ مسار GoldLab على فحوص OrderCheck وOrderSend وOnTradeTransaction، ثم يطابق تقرير MT5 مع سجل الصفقات CSV. طلبات تعديل SL/TP ليست صفقات دخول.

## خط الأساس الموثق
تشغيل GitHub Actions رقم `39876740253`:
- الرابط: https://github.com/staryuzar/-/actions/runs/39876740253
- GoldLabEA v1.014، XAUUSD M5، النموذج 4، الفترة 2026-08-05 إلى 2026-10-20.
- تاريخ التقرير وCSV متطابقان، 100% real ticks، 33 صفقة، صافي +20.76 USD، PF 1.47، أقصى تراجع حقوق ملكية 3.59%.
- 699 فحص OrderCheck ناجحاً و699 طلب OrderSend مقبولاً؛ 699 نتيجة callback، من دون عدم تطابق توقيعات أو ردود غير مقبولة.
- هذه نافذة تطوير واحدة، لا اختباراً مستقلاً ولا دليلاً على ربح مستدام.

## التجربة الجديدة: تغيير واحد فقط
الفرع: `goldlab-adx30-experiment`

- الثابت: المصدر v1.014، XAUUSD M5، الفترة نفسها، Model 4، المخاطرة 0.50%، وقف 0.45 ATR، حد السبريد 100، ADX الأدنى 23، short-only، تأكيد اتجاه الشمعة ورفض EMA مفعّلان.
- المتغير الوحيد: رفع الحد الأعلى لـ ADX من 25 إلى 30.
- الغرض: اختبار ما إذا كانت زيادة نطاق ADX تتيح فرصاً إضافية دون تدهور غير مقبول في التراجع أو جودة التنفيذ.
- معيار القبول: تجميع بلا أخطاء، تأكيد جميع المدخلات من تقرير HTML، تطابق الفترة، 100% real ticks، مطابقة CSV مع التقرير، وعدم وجود أخطاء أو ردود تداول غير معالجة.
- لا نختار الفائز بناءً على صافي الربح وحده؛ نقارن PF، تراجع الرصيد وحقوق الملكية، عدد الصفقات، متوسط الصفقة، سلاسل الخسائر، وتوزيع النتائج زمنياً.
- لا تعديل على نافذة الحجز 2026-10-21 إلى 2026-10-23، ولا على `main` أو الفرع المجمد.

## الحالة
يُحفظ تقرير التجربة وسجلاتها كـ GitHub Actions artifact عند اكتمال التشغيل. لا تُسجل نتيجة ADX 23–30 على أنها ناجحة أو أفضل قبل قراءة التقرير الفعلي ومقارنته بخط الأساس.
