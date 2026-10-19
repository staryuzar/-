# المساعد الذكي — Aurora Control Room

واجهة عربية للمساعد المحلي تجمع المحادثة والذاكرة المحلية وأدوات Windows والتحكم في Chrome والتكامل مع MetaTrader 5.

> **للاستئناف في أي محادثة لاحقة:** اقرأ [تقرير الاستئناف الدائم بالعربية](.github/RESUME_REPORT_2026-10-19_AR.md) أولًا؛ يتضمن السجل الزمني الكامل والنتائج وروابط Actions ونقطة العمل التالية. لا تبدأ من الصفر. أبقِ ملفات المختبر وسكربتاته وتقاريره في GitHub.

## أحدث نتائج التطوير — 2026-10-19 (بوابة التوثيق-only مثبتة)

- [Windows validation #122 — SUCCESS](https://github.com/staryuzar/-/actions/runs/39235712400): بوابة تحديد النطاق + Python 3.11 + Python 3.13 + Chrome + MT5 نجحت.
- Python 3.11: **353 حالة ناجحة، 0 failures/errors/skips** (24.44s). [JUnit](https://github.com/staryuzar/-/actions/runs/39235712400/artifacts/12179200947).
- Python 3.13: **353 حالة ناجحة، 0 failures/errors/skips** (23.55s). [JUnit](https://github.com/staryuzar/-/actions/runs/39235712400/artifacts/12179066547).
- Chrome: 7/7 فحوصات محلية + 3/3 فحوصات لأداة المتصفح الحقيقية على `example.com`. [artifact](https://github.com/staryuzar/-/actions/runs/39235712400/artifacts/12179800672).
- MT5 demo: ترجمة عينة EA بـ0 أخطاء/تحذيرات، الطرفية عاشت 15 ثانية، والتفويض إلى Headway demo مؤكد. لم تُفتح صفقات؛ مثبت MetaQuotes أعاد exit code 1 رغم نجاح الفحوص اللاحقة. [artifact](https://github.com/staryuzar/-/actions/runs/39235712400/artifacts/12179620749).
- **بوابة النطاق تم اختبارها في الاتجاهين:** [#122](https://github.com/staryuzar/-/actions/runs/39235712400) شغّل كل الوظائف بعد تغيير workflow وانتهى SUCCESS؛ [#123](https://github.com/staryuzar/-/actions/runs/39236235550) نجح في `documentation_only` وتخطّى وظائف Python/Chrome/MT5 الثقيلة.
- الحزمة المصححة في #122: [artifact 12179275913](https://github.com/staryuzar/-/actions/runs/39235712400/artifacts/12179275913)، الخارجي SHA-256 `da069092bc986ac12cecfe96996a1d4fd0259c3b9ebac8c55bf6a72549a2b1f7`; الداخلي SHA-256 `b4387f06e7290490cd5121dd93a83a4069ca9de7c16fc1f0176aca4cd67c3b2d`. فُحصت 76 بصمة داخلية بدون فقد أو اختلاف.
- **ما لم يُنجز:** E2E حقيقي من رد النموذج إلى فتح وقراءة الموقع ما زال متوقفًا عند 429 السابق؛ لم نتحقق من سر/حصة OpenRouter ولم نشغّل مزودًا بلا موافقة صريحة. التطبيق لم يُختبر بعد على جهاز Windows 10 1909 الفعلي، ولم يُختبر EA الإنتاجي أو Strategy Tester.
- التفاصيل: [تقرير الاستئناف الدائم بالعربية](.github/RESUME_REPORT_2026-10-19_AR.md).
## آخر نتائج الاختبارات المؤكدة — 2026-10-19

- **Windows / Python 3.11:** نجحت 350 من 350 اختبارًا؛ 0 فشل، 0 أخطاء، 0 متخطاة.
- **Windows / Python 3.13:** نجحت 350 من 350 اختبارًا؛ 0 فشل، 0 أخطاء، 0 متخطاة.
- **إصلاح Gemini 503:** أضيفت إعادة محاولة واحدة بعد انتظار ثانيتين لخطأ HTTP 503 فقط. لا يعيد العميل HTTP 429 أو أخطاء المفاتيح/الصلاحيات. اجتازت الاختبارات الثلاثة الجديدة: 503 ثم نجاح، و503 متكرر ثم توقف، و429 دون إعادة.
- **Chrome الفعلي:** نجحت 7/7 فحوصات ضد موقع اختبار مستقل. هذا لا يثبت وحده نجاح تنفيذ أمر عبر النموذج الحقيقي.
- **MetaTrader 5:** أكد تقرير [run 39220175223](https://github.com/staryuzar/-/actions/runs/39220175223) التفويض لخادم Headway التجريبي، وترجمة عينة EA مؤقتة بـ0 أخطاء و0 تحذيرات، وتشغيل terminal64.exe بواسطة أداة المساعد مدة 15 ثانية. **لم تُفتح أي صفقة** ولم يُختبر EA الإنتاجي أو Strategy Tester. أعاد المُثبّت exit code 1 رغم نجاح التحقق اللاحق؛ احتُفظ بهذا التحذير في التقرير.
- **اختبار النموذج/المساعد الحقيقي:** المحاولتان [run 39219078564](https://github.com/staryuzar/-/actions/runs/39219078564) و[run 39219085022](https://github.com/staryuzar/-/actions/runs/39219085022) اجتازتا صحة التطبيق وظهور Chrome وإرسال الطلب، ثم فشلتا بـHTTP 429 / RESOURCE_EXHAUSTED بسبب حصة Gemini المجانية. لا يوجد إثبات لتنفيذ أداة المتصفح؛ E2E يدوي فقط حتى تتوفر حصة فعلية أو مزود صالح.

## أحدث تحقق على Windows

- [run 39220175223 — Windows validation #101 — SUCCESS](https://github.com/staryuzar/-/actions/runs/39220175223): 350/350 اختبارًا على Python 3.11، و350/350 على Python 3.13، وفحص Chrome وMT5 ناجحان.
- [Artifact الحزمة المصححة](https://github.com/staryuzar/-/actions/runs/39220175223/artifacts/12171481197).
- أصلحنا تكرار تشغيل Windows الناتج عن `push` و`pull_request` على الفرع نفسه؛ يجري فحص فرع التطوير عبر Pull Request فقط، وتحديثات التقارير وحدها لا تطلق المختبر.

## روابط العمل

- [تقرير الاستئناف الدائم والتفاصيل ونقطة العمل التالية](.github/RESUME_REPORT_2026-10-19_AR.md)
- [دفتر حالة المشروع التفصيلي](.github/PROJECT_STATE_AR.md)
- [سير فحص Windows وPython وChrome وMT5](.github/workflows/windows-validation.yml)
- [سير الاختبار الحقيقي لـGemini والمساعد (تشغيل يدوي فقط)](.github/workflows/real-world-assistant-e2e.yml)
- [PR #2 — التحقق الشامل](https://github.com/staryuzar/-/pull/2)

## الحزمة المصححة

في أحدث تشغيل ناجح لسير **Aurora Windows validation** افتح قسم **Artifacts** ونزّل **Aurora-Control-Room-v2.4.0-patched**. أحدث Artifact مُتحقق منه في [run 39220175223](https://github.com/staryuzar/-/actions/runs/39220175223/artifacts/12171481197) حجمه الخارجي 212,481 بايت؛ ويحتوي حزمة الإصدار الفعلية بحجم 215,978 بايت وبصمة SHA-256:
**40e873403698b23109a5c0322cdacaea814197043b2affa3f3ea770cb3387e35**.

تبقى الحزمة الأصلية **Aurora_Control_Room_v2_4_0_FIRST_RUN_READY_AR.zip** محفوظة دون استبدال صامت؛ الإصلاحات تُطبّق على نسخة استخراج منفصلة ويُعاد بناء الحزمة المصححة مع ملف بصمات SHA-256.

## الحفاظ على المختبر والأسرار

- لا تحذف ملفات ZIP الأصلية أو ملفات الاختبار أو workflows أو السكربتات أو تقارير النجاح والفشل.
- سير Windows validation يعمل تلقائيًا. اختبار Gemini الحقيقي أصبح **يدويًا فقط** لتجنب استهلاك الحصة عند كل commit؛ اختر **confirm_provider_call=yes** في Actions فقط بعد توفر الحصة أو مزود صالح.
- بيئة GitHub-hosted Windows مؤقتة وتُزال بعد انتهاء التشغيل. ملفات workflow والسكربتات تحفظ وصفة إعادة الإنشاء، وArtifacts محفوظة عادةً حتى 90 يومًا. احتفظ بالتقارير المهمة في ملفات Markdown مُلتزمة في المستودع.
- لا تضع كلمات مرور أو مفاتيح API أو محتويات ملفات .env الفعلية في Git أو التقارير. تُستهلك الأسرار من GitHub Actions secrets فقط.
- الاختبارات الحالية تستخدم Windows Server 2022، ولا تثبت وحدها التوافق الكامل مع جهاز المستخدم Windows 10 1909 أو نجاح تسجيل الدخول/تداول استراتيجية المستشار. لم يُشغّل Strategy Tester ولم تُفتح صفقات.
