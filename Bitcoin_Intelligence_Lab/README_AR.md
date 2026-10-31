# Bitcoin Intelligence Lab — مختبر ذكاء البيتكوين

برنامج مستقل لتحليل BTC وإصدار قرار مركزي قابل للتفسير، مع لوحة Streamlit وخبير MT5 منفصل لتنفيذ أوامر التداول ومتابعة المراكز على وسيط **Headway**. كل الملفات في هذا المجلد والفرع `bitcoin-intelligence-lab`؛ لا يعدّل هذا العمل برنامج الذهب أو الفرع الرئيسي.

## تقارير المشروع والبحث

- [تقرير حالة العمل: ما أُنجز وما تبقى](WORK_REPORT_AR.md)
- [مراجعة مشاريع GitHub المفتوحة المصدر والتراخيص](OPEN_SOURCE_RESEARCH_AR.md)
- [وثيقة المعمارية](ARCHITECTURE_AR.md)

## الفصل بين بيانات السوق ووسيط التنفيذ

- **Headway هو وسيط التنفيذ الوحيد** من خلال منصة MT5، والخبير يقبل افتراضياً حساب Headway-Demo فقط.
- Binance Spot وBinance Futures وBybit وOKX مصادر مستقلة لقراءة بيانات السوق والسيولة والمشتقات؛ ليست وسطاء تنفيذ لهذا البرنامج.
- رمز البيانات الموحد حالياً هو BTCUSDT، أما تنفيذ الأوامر فيستخدم رمز BTC الفعلي على مخطط Headway الذي يقرأه الخبير من MT5، مثل BTCUSD أو رمز ذي لاحقة يحددها الوسيط.
- قبل نشر الأمر يتحقق جسر Python من خادم Headway-Demo ومن وضع الحساب التجريبي، ويتحقق الخبير مرة أخرى من الوسيط والحساب والرمز وصلاحية التداول.
- لا يُرسل أي أمر إلى Binance أو Bybit أو OKX.

## محركات البرنامج الحالية

1. **Spot:** شموع Binance المكتملة ودفتر الأوامر وصفقات السوق المجمعة.
2. **Futures:** التمويل وOpen Interest وTaker Buy/Sell من Binance USDⓈ-M، مع Bybit V5 كمصدر مشتقات احتياطي.
3. **القرار المركزي:** التحليل الفني والسيولة وتدفق الصفقات والمشتقات تنتج BUY/SELL/HOLD مع الأسباب والحواجز.
4. **التحليل متعدد الأطر:** 1D و4H و1H و15M و5M و1M مع أوزان حسب الدور والتحقق من حداثة كل إطار.
5. **بنية السوق:** Volume Profile للعينة المتاحة وPOC/VAH/VAL/Delta، وVWAP، وRelative Volume، وRealized Volatility وRange Expansion.
6. **سياق أبطأ:** mempool.space، وCFTC TFF، وCoin Metrics Community، وDeribit DVOL.
7. **دفاتر أوامر حية متعددة المنصات:** جامع WebSocket مستقل لـBinance Spot وBybit Linear وOKX Spot، مع قواعد تسلسل خاصة بكل منصة وتخزين تاريخ العمق وحالة الاتصال في SQLite.
8. **تنفيذ ومتابعة MT5:** أوامر OPEN/CLOSE عبر MT5 Common Files، إقرار من الخبير، وملفات حالة المراكز.
9. **إدارة المراكز:** لا يكرر مركزاً في الاتجاه نفسه؛ لا يغلق عند HOLD؛ وعند قرار معاكس صالح يغلق المركز المعاكس أولاً وينتظر تأكيد MT5 قبل الخطوة التالية.

## تثبيت وتشغيل Windows

افتح PowerShell وانتقل إلى مجلد `Bitcoin_Intelligence_Lab` داخل المستودع، ثم:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ui,market-data]"
```

**1. شغّل جامع دفاتر الأوامر في نافذة PowerShell أولى:**

```powershell
python -m bitcoinlab.market_stream --symbol BTCUSDT --venues binance,bybit,okx --depth 50 --db data/market_stream.sqlite
```

**2. شغّل لوحة البرنامج في نافذة PowerShell ثانية:**

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

اللوحة تقرأ قاعدة بيانات الجامع بوضع read-only، وتعرض حالة كل منصة وآخر Bid/Ask والسبريد واختلال دفتر الأوامر. عند توقف جامع WebSocket تتوقف تحديثات العمق، وتوضح اللوحة حالة الاتصال بدلاً من اعتبار البيانات القديمة حية.

**3. خبير Headway عبر MT5**

ضع `BitcoinIntelligenceLabEA.mq5` داخل `MQL5/Experts` ثم افتحه في MetaEditor واجمعه. أرفقه بمخطط البيتكوين الفعلي من Headway. الإصدار الحالي من المصدر هو 1.003، ويتحقق من اسم خادم Headway ووضع الحساب التجريبي ويبلّغ اللوحة بهما. لا تعتمد النسخة الجديدة قبل تجميع هذا الإصدار في MetaEditor والتأكد من ظهور حالة Headway-Demo الصحيحة في اللوحة.

### سياسة التداول

التنفيذ محصور في Headway-Demo افتراضياً عبر `RequireHeadwayDemo=true`. الخبير لا يولّد إشارات مستقلة داخل `OnTick`؛ القرار المركزي للوحة، والخبير منفذ ومبلّغ عن التنفيذ. ويبقى وقف الخسارة والهدف اللذان يرسلهما البرنامج ضمن أمر MT5.

ابدأ بالمراقبة وتحقق من اتصال الجامع واللوحة والخبير قبل تفعيل التنفيذ التلقائي. لا تعتبر نجاح اختبارات Python دليلاً على نجاح صفقة MT5 أو ربحية الاستراتيجية.

## الاختبارات والحدود

```powershell
python -m compileall -q bitcoinlab app.py
python -m unittest discover -s tests -v
```

GitHub Actions يشغّل الاختبارات على Python 3.12 و3.13، ويفحص بدء Streamlit ومصادر BTC العامة. اختبارات WebSocket الحالية تختبر قواعد الرسائل وإعادة المزامنة محلياً؛ لا تثبت وحدها استمرار اتصال الشبكات الحية على جهاز Windows.

Binance Spot وBybit Linear وOKX Spot أسواق مختلفة؛ لا تُجمع أحجامها أو اختلالاتها في تصويت واحد قبل تطبيع نوع السوق ووحدة العقد والعملة المقابلة. كما أن عينة Volume Profile الحالية عينة صفقات حديثة وليست جلسة كاملة، وبيانات CFTC أسبوعية وCoin Metrics Community خاضعة لشروطها. لا توجد نتائج ربحية موثقة حتى الآن.
