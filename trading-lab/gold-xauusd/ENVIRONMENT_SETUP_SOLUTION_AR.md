# تجهيز بيئة GoldLab على GitHub — خطة تنفيذ موثّقة

## الحقيقة التقنية
أجهزة `windows-2022` في GitHub Actions مؤقتة وتُزال بعد كل تشغيل. الحل العملي الفوري هو إنشاء بيئة MT5 آلياً لكل تشغيل، وتجميع اختبار دخاني، والتحقق من تسجيل الدخول التجريبي دون تداول. الحل الدائم يتطلب Windows VM/VPS مخصصاً يعمل كـ self-hosted GitHub Actions runner؛ هذا الخادم يجب توفيره وتشغيله وصيانته، ولا تمنح hosted runners جهازاً دائماً.

## الملفات المضافة
- `.github/workflows/goldlab-environment-preflight.yml`: فحص يدوي لا يشغّل استراتيجية الذهب ولا Strategy Tester.
- `.github/scripts/goldlab_environment_preflight.ps1`: تنزيل MT5، التحقق من Terminal وMetaEditor، تجميع EA بسيط مستقل، ثم محاولة تسجيل الدخول التجريبي وفحص السجل.
- لا يعدل الفحص GoldLabEA أو إعداداته ولا يرسل أوامر تداول.

## التشغيل
1. يلزم وجود GitHub Actions secret باسم `mt5` بصيغة JSON تحتوي `login`, `password`, `server` أو الصيغة النصية التي يقبلها مشغل المختبر.
2. من Actions اختر `GoldLab Environment Preflight (no strategy test)` ثم Run workflow على الفرع `goldlab-request-result-candidate`.
3. راجع artifact `goldlab-environment-preflight-<run_id>`. يجب أن يظهر نجاح تجميع الاختبار الدخاني ونجاح تسجيل الدخول كلٌّ على حدة.

## حدود الإثبات
PASS يثبت جاهزية تلك الجلسة المؤقتة فقط، ولا يثبت استمرار الاتصال بعد انتهاء التشغيل أو ربحية المستشار. لا تُشغّل اختبارات استراتيجية على الفترة المحجوزة 2026-10-21 إلى 2026-10-23 قبل الموعد المسجل للمشروع.
