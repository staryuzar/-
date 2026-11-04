# نقطة استئناف مرصاد BTC — آخر تحديث 4 نوفمبر 2026

## المستودع والفرع
- Repository: `staryuzar/-`
- فرع العمل الوحيد: `mini`
- آخر SHA موثق: `a0461b13ecd71abeb0a2e95c6659c988187f16c3`
- اقرأ أولاً [سياق المشروع الدائم](MIRSAD_BTC_PROJECT_CONTEXT_AR.md) و[تقرير التدقيق التنفيذي](../Mirsad_BTC/reports/ENGINE_READINESS_AUDIT_AR_20261104.md).

## ما أُصلح في آخر التحديث
1. توحيد تشخيص أوزان E4 إلى 20/55/25 وإضافة اختبار.
2. إضافة بوابة E4 لتغطية الاتجاه الصريح في أطر E2: `directional_frame_coverage >= 0.60`، مع إدخالها في جودة تصويت E2.
3. جعل E5 يفشل مغلقاً إذا كانت قائمة مراكز MT5 مفقودة أو مشوهة.
4. إضافة حواجز EA لحسابات MT5 NETTING/EXCHANGE: منع فتح تعرض جديد فوق مركز/أمر قائم للرمز، والتحقق من تاريخ المركز قبل CLOSE/MODIFY، مع telemetry لنمط الحساب.

## نتائج SHA الحالي
- [Live Data Validation](https://github.com/staryuzar/-/actions/runs/41827798841): SUCCESS، **364/364 tests**.
- [Engine 2 Native OHLC](https://github.com/staryuzar/-/actions/runs/41827798966): SUCCESS.
- [Integrated five-engine MT5 runtime](https://github.com/staryuzar/-/actions/runs/41827798804): SUCCESS؛ EA compile صفر أخطاء/تحذيرات، Observer وExecutionBridge على Common Files مشترك، heartbeat حي، deal history صالح.
- [MT5 EA compile/heartbeat](https://github.com/staryuzar/-/actions/runs/41827798967): SUCCESS؛ compile صفر أخطاء/تحذيرات وheartbeat في وضع read-only.

## النتيجة الحية الدقيقة
في آخر دورة التكامل: E1 READY، E2 READY لكن `MIXED_TIMEFRAME_DIRECTIONS`، E3 READY، E4 WAITING_FOR_ENGINE_2، E5 CONNECTED؛ `action=WAIT`، `entry-eligible=False`، `validated MIR1 envelopes=0`. لم يرسل harness التكامل أمراً للوسيط. هذه دورة ناجحة آمنة وليست اختباراً لدخول طبيعي مكتمل.

## النواقص المثبتة التي تمنع اعتماد 100%
- لا توجد بعد دورة طبيعية من إشارة سوق مؤهلة E4 → MIR1 → ACK → مركز MT5 مطابق → مصالحة صفقة مكتملة.
- لا توجد معايرة خارج العينة مع رسوم وعمولة وانزلاق وبيانات زمنية محفوظة.
- لا يوجد runtime دائم بعد انتهاء GitHub Windows runner؛ بيئة Linux لـLive Validation لا تملك `MIRSAD_MT5_COMMON_FILES` ولذلك تبلغ E5 `NOT_CONFIGURED` هناك، بينما تكامل Windows أثبت اتصاله في بيئته.
- Trading Economics غير مهيأ وبعض endpoints للمشتقات محجوبة في GitHub runner؛ E1 فحص ثلاث مكونات اتجاهية بنجاح لكن لا يصح ادعاء اكتمال جميع المزودات.
- E3 parity 120/120 يثبت المطابقة الحسابية مع MT5 على بيانات متزامنة، وليس ربحية المؤشرات.

## قواعد مواصلة العمل
- لا تعدل خارج فرع `mini`.
- لا تخفض بوابة E2 لتوليد صفقة؛ MIXED أو غير المؤهل = WAIT.
- لا تجعل E1 يكرر عمل E2/E3 ولا تجعل E5 يصوت اتجاهياً.
- لا تغيّر إعدادات المخاطر أو مفاتيح النشر والتنفيذ دون توجيه.
- لا تستخدم نسب جاهزية مئوية قديمة؛ اعرض أدلة الاختبار والتشغيل والنواقص صراحة.
- لا تشغل BUY/CLOSE acceptance كاختبار شكلي؛ هذا المسار قد يرسل أوامر للوسيط المهيأ.

