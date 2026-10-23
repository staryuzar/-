# سجل تجارب GoldLab — سجل قبول/رفض

**آخر تحديث:** 2026-10-23 UTC  
**الفرع المعزول:** `goldlab-request-result-candidate`  
**EA baseline:** GoldLabEA v1.014, source SHA-256 `149e0e84be72c92246ffca6be1a8c566d4b99645f941d12ebebc3aff0bd4755c`.

## قواعد القبول قبل قراءة النتائج
1. لا نقبل نتيجة دون Compile 0 errors / 0 warnings، تقرير HTML، بيانات حركات كافية، CSV صفقات، ومصالحة مستقلة للتاريخ وعدد الصفقات وصافي الربح.
2. النتيجة المقبولة مبدئياً في التطوير يلزمها 100% real ticks، 10,000 شمعة على الأقل، 1,000,000 tick على الأقل، صفر صفقات خارج فترة التطوير.
3. تعديل معلمة واحدة فقط في كل تجربة. لا يُدمج تغيير إلا إذا حسّن PF دون زيادة تراجع حقوق الملكية مقارنة بالخط الأساسي على نفس النافذة، ثم يبقى بحاجة لفترات مستقلة.
4. لا تُستخدم فترة 2026-10-21 إلى 2026-10-23 لضبط المعلمات قبل 2026-10-24 12:00 UTC. بعد فتحها، تُشغّل نسخة واحدة مجمدة لمرة واحدة فقط. نتيجة holdout ليست طريقة تحسين للمعلمات.
5. الطلبات وcallbacks ليست صفقات. عدد الصفقات يُؤخذ من HTML وCSV deal history، لا من عدد OrderSend.

## التجارب

| ID | المتغير | نافذة الاختبار | صافي الربح | PF | تراجع حقوق الملكية | الصفقات (رابحة/إجمالي) | القرار |
|---|---|---|---:|---:|---:|---:|---|
| BASE-25 | خط الأساس: ADX 23–25، ExecutionMode=0 | 2026-08-05 إلى 2026-10-19 (MT5 ToDate=2026-10-20 حصري) | +$20.76 | 1.47 | 3.59% | 10/33 (30.30%) | قبول مؤقت داخل نافذة التطوير فقط |
| ADX27 | رفع InpMaxADX من 25 إلى 27 فقط | نفس نافذة BASE-25 | -$0.62 | 0.99 | 6.22% | 14/59 (23.73%) | مرفوض؛ لا يُدمج |
| RANDOM-DELAY | إبقاء مدخلات EA كما في BASE-25، وتغيير ExecutionMode من 0 إلى -1 فقط | نفس نافذة التطوير | لم تُثبت بعد | — | — | — | قيد الفحص / لا قرار بعد |

### BASE-25 — أدلة
- MT5 run [39878677693](https://github.com/staryuzar/-/actions/runs/39878677693).
- Compile: 0 errors, 0 warnings.
- 14,820 شمعة، 31,440,931 tick، 100% real ticks.
- 33 صفقة، 66 deal و66 ID فريداً في CSV؛ 33 دخولاً/33 خروجاً؛ HTML صافي +$20.76 يطابق CSV؛ صفر deals خارج النافذة.
- OrderCheck: 699 ناجح/0 فشل؛ OrderSend: 699 مقبول/0 فشل؛ callbacks: 699 مقبولة؛ 698 معرفاً غير صفرياً مطابقاً وfallback واحداً بهوية صفرية مطابقاً، دون mismatch.
- هذه ليست إثباتاً لربحية مستدامة. إعداد التطوير short-only، والعينة ليست holdout.

### ADX27 — أدلة وقرار
- MT5 run [39879772469](https://github.com/staryuzar/-/actions/runs/39879772469); artifact SHA-256: `4862b37ec7647b11880847b98efd078fccaf19f533e9e5584766405f7b1f4896`.
- Compile: 0 errors, 0 warnings. 100% real ticks؛ 14,820 شمعة و31,440,931 tick.
- 59 صفقة/118 deal؛ 59 دخولاً و59 خروجاً؛ CSV/HTML صافي -$0.62 متطابق، صفر صفقات خارج النافذة.
- OrderCheck: 1040 ناجح/0 فشل؛ OrderSend: 1040 مقبول/0 فشل؛ callbacks: 1040 مقبولة. هذه طلبات وليست صفقات.
- فشل معيار القبول: PF 0.99 أقل من 1.47، تراجع حقوق الملكية 6.22% أعلى من 3.59%، وصافي الربح تحول لسالب. القرار ثابت: **مرفوض، لا دمج**.

### RANDOM-DELAY — حالة الدليل
- Static gate passed on run [39880673597](https://github.com/staryuzar/-/actions/runs/39880673597).
- Test run [39880639847](https://github.com/staryuzar/-/actions/runs/39880639847) was still reported by GitHub as in progress at the last check; no artifact or final MT5 report was available yet. Its first predecessor [39880564746](https://github.com/staryuzar/-/actions/runs/39880564746) failed in preflight because of a mislabeled diagnostic gate and did not enter Strategy Tester; do not use it as performance evidence.
- Baseline inputs remain unchanged. Only tester ExecutionMode differs (0 → -1 Random Delay). The source and all EA inputs remain pinned; report/CSV/date gate must pass before comparing performance.
- Known limitation: MT5 Random Delay changes execution timing and may alter the fills/behavior; this tests execution robustness, not a new strategy input.

## Holdout — محفوظ ولم يُستهلك
- Frozen source commit: `b3ff34caa837ce07e5d2caeee1a4bdb?` — use the authoritative manifest for the exact commit/hash. EA source SHA-256 remains as recorded above.
- Period: FromDate `2026.10.21`, ToDate `2026.10.24` exclusive; this covers 21–23 October only.
- Unlock: 2026-10-24 12:00 UTC / 15:00 Aden.
- Do not create `HOLDOUT_RUN_TRIGGER.md` before unlock. No `HOLDOUT_CONSUMED.json` exists; no holdout run has occurred.
- One-time workflow: [goldlab-holdout-evaluation.yml](https://github.com/staryuzar/-/blob/goldlab-request-result-candidate/.github/workflows/goldlab-holdout-evaluation.yml), baseline manifest: [GOLDLAB_V1014_HOLDOUT_BASELINE.json](https://github.com/staryuzar/-/blob/goldlab-request-result-candidate/trading-lab/gold-xauusd/GOLDLAB_V1014_HOLDOUT_BASELINE.json).

## Decision log
- Never promote ADX27 because its metrics failed the predeclared comparison.
- Do not change GoldLabEA source/inputs based on the holdout.
- If RANDOM-DELAY fails or is inconclusive, keep its result as a robustness limitation; don't retune baseline using holdout.
- Keep `main` and `gold-xauusd-expert-lab` unchanged.
