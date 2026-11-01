# بروتوكول MIR1 — مرصاد البيتكوين

## مسؤوليات القناة
- برنامج Mirsad BTC (Engine 4): ينشئ القرار ويحسب حجم المركز والوقف والهدف ومبلغ المخاطرة.
- Engine 3: ينقل أمر MIR1 إلى مجلد MT5 Common Files ويقرأ الحالة والإقرار والمراكز.
- Expert Advisor MQL5: ينفذ قيم الأمر كما استلمها بعد تحقق بنيوي وتشغيلي؛ لا يعيد حساب المخاطر ولا يختار الحجم أو الوقف أو الهدف، ولا يصنف نوع الحساب.

## مجلد الطرفية
Common\\Files\\MirsadBTC\\

الملفات:
- status.json: نبض الخبير والحساب وخصائص الرمز والمراكز.
- command.json: آخر أمر من المحرك الرابع.
- ack.json: آخر إقرار للبرنامج.
- positions.json: المراكز المفتوحة.
- events.jsonl: سجل الأحداث.

## Envelope MIR1
- schema: MIR1.
- command_id: معرف فريد لا يتكرر.
- created_at_ms و expires_at_ms: وقت الإنشاء والانتهاء UTC بالميلي ثانية.
- symbol: الرمز الحرفي كما يرسله البرنامج.
- action: BUY أو SELL أو CLOSE.
- volume: الحجم الذي حسبه المحرك الرابع.
- entry_reference: السعر المرجعي.
- stop_loss و take_profit: المستويان اللذان حسبهما المحرك الرابع.
- position_ticket: مطلوب عند CLOSE.

## Status heartbeat
schema=MIR1, terminal_connected, heartbeat_at_ms, account, symbol, symbol_spec, positions.
account يحمل equity وbalance وfree_margin وcurrency وserver وlogin عند توافرها. لا يستنتج الخبير أو الجسر نوع الحساب.
symbol_spec يحمل tick_size وtick_value_loss وvolume_min وvolume_step وvolume_max وdigits وpoint وcontract_size وtrade_mode وفق خصائص MT5.

## ACK
schema=MIR1, command_id, state, retcode, order_ticket, deal_ticket, filled_volume, filled_price, message, ack_at_ms.
الحالات: RECEIVED, REJECTED, SUBMITTED, PARTIAL, FILLED, CANCELLED, EXPIRED, UNKNOWN. SUBMITTED لا يعني أن التنفيذ النهائي قد تم.

## منع التكرار
يحتفظ الخبير بمعرفات الأوامر التي رآها، ولا يعيد إرسال الأمر نفسه بعد إعادة التشغيل. إذا كانت نتيجة طلب سابق غير حاسمة، يرسل UNKNOWN ويترك المصالحة للبرنامج بدلاً من تكرار الطلب.

## ضوابط
- CI لا يرسل صفقة ولا ينشئ صفقة محاكاة.
- لا توجد حسابات مخاطر داخل الخبير.
- لا توجد بوابة نوع حساب داخل الخبير أو الجسر.
- نشر الأوامر معطل افتراضياً حتى يكتمل EA ويجتاز فحوص الاستلام والإقرار.
