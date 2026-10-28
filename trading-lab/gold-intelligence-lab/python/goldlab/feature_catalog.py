"""Evidence-linked capability catalogue for Gold Intelligence Lab.

Statuses describe the current product code, not vendor quality or trading performance.
No vendor integration is claimed unless an actual supported, licensed adapter exists.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

STATUS_LABELS_AR = {
    "implemented": "منفذ",
    "partial": "منفذ جزئيًا",
    "planned": "مخطط",
    "external_dependency": "يتطلب مصدرًا/ترخيصًا خارجيًا",
    "research_required": "يتطلب بحثًا وتحققًا إضافيين",
}
FEATURES: tuple[dict[str, Any], ...] = (
    {"id":"DATA-001","category_ar":"البيانات","name_ar":"قراءة السعر الحي من طرفية MT5","status":"implemented","detail_ar":"قراءة Bid/Ask وبيانات الرمز دون إرسال أوامر.","sources":["https://www.mql5.com/en/docs/python_metatrader5"]},
    {"id":"DATA-002","category_ar":"البيانات","name_ar":"الشموع المكتملة وفحص جودتها","status":"implemented","detail_ar":"التحقق من القيم والتوقيت وحداثة السعر وعدم ترتيب البيانات بصمت.","sources":["https://www.mql5.com/en/docs/python_metatrader5"]},
    {"id":"DATA-003","category_ar":"البيانات","name_ar":"لقطة واحدة متعددة الأطر","status":"implemented","detail_ar":"M1/M5/M15/M30/H1 مع snapshot id وأخطاء مستقلة لكل إطار.","sources":["https://www.mql5.com/en/docs/python_metatrader5"]},
    {"id":"TECH-001","category_ar":"التحليل الفني","name_ar":"مجموعة تصنيفات فنية ومكونات قابلة للتفسير","status":"implemented","detail_ar":"محرك مستقل يحسب القيم والتصويتات ويعرض الجاهزية؛ لا يدعي التطابق الرقمي الكامل مع أي منصة.","sources":["https://www.tradingview.com/features/"]},
    {"id":"TECH-002","category_ar":"التحليل الفني","name_ar":"ماسح بنية الرسم والقمم/القيعان","status":"partial","detail_ar":"اتجاه وصفي، ATR، محاور مؤكدة، مناطق دعم/مقاومة تقريبية واختراقات ونماذج مختارة؛ تغطية الأنماط غير شاملة.","sources":["https://investor.tradingcentral.com/technical-views","https://help.trendspider.com/kb/scanner/market-scanner"]},
    {"id":"TECH-003","category_ar":"التحليل الفني","name_ar":"سيناريو مفضل وبديل وشروط إبطال","status":"partial","detail_ar":"يعرض الأدلة والتعارضات، لكنه لا يولد بعد خططًا كاملة لكل نمط أو أفق.","sources":["https://investor.tradingcentral.com/technical-views"]},
    {"id":"TECH-004","category_ar":"التحليل الفني","name_ar":"مخططات متعددة وتخطيطات متزامنة","status":"planned","detail_ar":"لوحة الجداول الحالية ليست بعد محرّك رسوم احترافي متعدد اللوحات قابلًا للمزامنة.","sources":["https://www.tradingview.com/features/"]},
    {"id":"SCAN-001","category_ar":"المسح والتنبيهات","name_ar":"ماسح شروط متعددة على عدة رموز وأطر","status":"planned","detail_ar":"المسح الحالي تحليلي لرمز الذهب؛ يلزم محرك شروط قابل للحفظ وتوسيع universe.","sources":["https://help.trendspider.com/kb/scanner/market-scanner","https://www.tradingview.com/support/solutions/43000742436-tradingview-pine-screener-key-features-and-requirements/"]},
    {"id":"SCAN-002","category_ar":"المسح والتنبيهات","name_ar":"قوائم مراقبة محفوظة ومخصصة","status":"planned","detail_ar":"لا يوجد بعد مدير watchlists وشاشات مخصصة كاملة.","sources":["https://help.trendspider.com/kb/scanner/market-scanner","https://www.tradingview.com/features/"]},
    {"id":"ALERT-001","category_ar":"المسح والتنبيهات","name_ar":"تنبيهات السعر واللمس والكسر والارتداد","status":"planned","detail_ar":"تحتاج محرك حالة مستمرًا وجدولة ومخزن تنبيهات؛ لا تعمل في الخلفية حاليًا.","sources":["https://help.trendspider.com/kb/alerts/types-of-alerts","https://www.tradingview.com/features/"]},
    {"id":"ALERT-002","category_ar":"المسح والتنبيهات","name_ar":"تنبيهات متعددة الشروط وعابرة للأطر","status":"planned","detail_ar":"تحتاج منشئ قواعد ونسخًا وإشعارات وسجلًا لاختبار عدم التكرار.","sources":["https://help.trendspider.com/kb/alerts/types-of-alerts"]},
    {"id":"MACRO-001","category_ar":"الاقتصاد الكلي","name_ar":"تقويم مواعيد الإصدارات الأمريكية من BLS","status":"partial","detail_ar":"الموجود يغطي جدول BLS فقط؛ لا يمثل التقويم العالمي ولا يتضمن توقعات السوق أو القيم الفعلية.","sources":["https://www.bls.gov/developers/","https://www.mql5.com/en/docs/calendar"]},
    {"id":"MACRO-002","category_ar":"الاقتصاد الكلي","name_ar":"عائد الخزانة الاسمي والحقيقي والدولار وVIX","status":"partial","detail_ar":"قارئ العوائد الاسمية/الحقيقية من وزارة الخزانة مضاف؛ مؤشر الدولار وVIX اختياريان من FRED وقد لا يتاحان على كل شبكة.","sources":["https://fred.stlouisfed.org/series/DGS10","https://fred.stlouisfed.org/series/DFII10","https://fred.stlouisfed.org/series/DTWEXAFEGS","https://fred.stlouisfed.org/series/VIXCLS"]},
    {"id":"MACRO-003","category_ar":"الاقتصاد الكلي","name_ar":"تقويم عالمي مع السابق والمتوقع والفعلي والمراجعات","status":"external_dependency","detail_ar":"يمكن استخدام موائم رسمي مرخص لمزوّد مثل Trading Economics؛ لم نفعّل حسابًا مدفوعًا أو API key.","sources":["https://docs.tradingeconomics.com/","https://www.fxstreet.com/economic-calendar"]},
    {"id":"MACRO-004","category_ar":"الاقتصاد الكلي","name_ar":"احتمالات قرارات الفائدة من عقود Fed Funds","status":"external_dependency","detail_ar":"CME FedWatch يعرض احتمالات ضمنية وأساليب مقارنة تاريخية؛ الوصول الآلي يتطلب تقييم الإتاحة والترخيص.","sources":["https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool"]},
    {"id":"GOLD-001","category_ar":"أساسيات الذهب","name_ar":"تمركز CFTC COT لعقود الذهب","status":"implemented","detail_ar":"تاريخ مراكز Managed Money الأسبوعية وصافيها والتغير؛ ليست مراكز السوق الفوري أو كل العالم.","sources":["https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"]},
    {"id":"GOLD-002","category_ar":"أساسيات الذهب","name_ar":"تدفقات وحيازات صناديق الذهب ETF","status":"planned","detail_ar":"البيانات العالمية متاحة لدى World Gold Council لكن بعض الرسوم والملفات تتطلب تسجيلًا/قبول شروط؛ يلزم موائم تنزيل موثق.","sources":["https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows"]},
    {"id":"GOLD-003","category_ar":"أساسيات الذهب","name_ar":"احتياطيات البنوك المركزية ومشترياتها","status":"planned","detail_ar":"سلاسل دورية متأخرة نسبيًا؛ يجب عرض تاريخ الرصد والتصحيحات ولا تعامل كسعر لحظي.","sources":["https://www.gold.org/goldhub/data/gold-reserves-by-country"]},
    {"id":"GOLD-004","category_ar":"أساسيات الذهب","name_ar":"عرض وطلب الذهب حسب الدول والقطاعات","status":"planned","detail_ar":"سلاسل فصلية/سنوية تحتاج تنسيق ملفات ومصدر/ترخيص واضحين.","sources":["https://www.gold.org/goldhub/data/gold-demand-by-country"]},
    {"id":"GOLD-005","category_ar":"أساسيات الذهب","name_ar":"بيانات عقود الذهب الآجلة وحجم التداول والفائدة المفتوحة","status":"external_dependency","detail_ar":"بيانات COMEX ليست نفس سعر CFD لدى الوسيط؛ أي دمج يجب أن يعرض أساس العقد وتوقيت المصدر.","sources":["https://www.cmegroup.com/markets/metals/precious/gold.quotes.html"]},
    {"id":"ORDERFLOW-001","category_ar":"التدفق والسيولة","name_ar":"دفتر أوامر/DOM وعمق السوق","status":"external_dependency","detail_ar":"قد تتاح مستويات عبر MT5 market_book؛ لا يضمن ذلك عمقًا مركزيًا ممثلًا لسوق الذهب OTC.","sources":["https://www.mql5.com/en/docs/python_metatrader5","https://bookmap.com/en/features","https://atas.net/modules/smart-dom/"]},
    {"id":"ORDERFLOW-002","category_ar":"التدفق والسيولة","name_ar":"Heatmap وVolume Dots وامتصاص السيولة","status":"external_dependency","detail_ar":"تحتاج بيانات عمق/صفقات متوافقة وتواترًا جيدًا، غالبًا من مصدر بورصة أو مزود متخصص؛ لا نستنتجها من شموع OHLC وحدها.","sources":["https://bookmap.com/en/features"]},
    {"id":"ORDERFLOW-003","category_ar":"التدفق والسيولة","name_ar":"Footprint وVolume Profile وTPO/Market Profile","status":"planned","detail_ar":"غير موجودة في اللوحة الحالية؛ تتطلب بيانات حجم على مستوى السعر لا OHLC فقط.","sources":["https://atas.net/features/","https://www.tradingview.com/features/"]},
    {"id":"NEWS-001","category_ar":"الأخبار والمشاعر","name_ar":"تجميع أخبار اقتصادية/سوقية مع التوقيت والمصدر","status":"planned","detail_ar":"لا يوجد feed أخبار حي موحّد الآن؛ يجب استخدام مصدر مرخّص وتسجيل وقت النشر والاسترجاع.","sources":["https://investor.tradingcentral.com/","https://www.tradingview.com/features/"]},
    {"id":"NEWS-002","category_ar":"الأخبار والمشاعر","name_ar":"تصنيف مشاعر الأخبار وموضوعاتها","status":"research_required","detail_ar":"لا يصنف البرنامج حاليًا الأخبار أو مزاج الجمهور؛ لا بد من قياس الجودة والانحياز والتغطية قبل إضافة درجة.","sources":["https://investor.tradingcentral.com/","https://www.koyfin.com/features/"]},
    {"id":"VISION-001","category_ar":"التحليل البصري والذكاء الاصطناعي","name_ar":"قراءة صورة الرسم أو لقطة الشاشة","status":"research_required","detail_ar":"غير منفذ؛ لا يصح استخراج سعر/مستوى دقيق من الصورة حين تكون بيانات OHLC متاحة، ولا رفع الصور دون اختيار مزود وموافقة.","sources":["https://www.tradingview.com/features/","https://www.tradingcentral.com/tc-products/tc-technical-insight"]},
    {"id":"AI-001","category_ar":"التحليل البصري والذكاء الاصطناعي","name_ar":"مساعد بحث يجيب مع إحالات وسجل أدلة","status":"planned","detail_ar":"لا يوجد ربط حي بنموذج أو محرك استرجاع داخل البرنامج حاليًا؛ أي خدمة سحابية تتطلب مراجعة كلفة وخصوصية.","sources":["https://www.quantconnect.com/docs/v2"]},
    {"id":"RISK-001","category_ar":"المخاطر والتنفيذ","name_ar":"حواجز مخاطرة داخل EA منفصل","status":"partial","detail_ar":"المصدر موجود بحماية افتراضية مغلقة؛ لا يعني ذلك أن التشغيل أو الأداء الاستثماري قد اعتمد.","sources":["https://www.mql5.com/en/docs"]},
    {"id":"RISK-002","category_ar":"المخاطر والتنفيذ","name_ar":"حساب حجم المركز وفق مواصفات الوسيط","status":"partial","detail_ar":"يوجد أساس حسابي في EA، لكن لم يتم بناء حاسبة متكاملة في لوحة البرنامج لكل الرموز/الحالات.","sources":["https://www.mql5.com/en/docs/python_metatrader5"]},
    {"id":"EXEC-001","category_ar":"المخاطر والتنفيذ","name_ar":"تنفيذ آمن مع تحقق الطلب والنتيجة والصفقة","status":"partial","detail_ar":"يوجد ملف EA منفصل؛ الربط التنفيذي من لوحة Python غير مفعل، والتنفيذ الآلي ليس جزءًا من القراءة التحليلية.","sources":["https://www.mql5.com/en/docs/python_metatrader5"]},
    {"id":"LEDGER-001","category_ar":"السجلات والتقارير","name_ar":"سجل تدقيق محلي مع بصمة وسلامة بيانات","status":"implemented","detail_ar":"يحفظ لقطة مختارة محليًا بطلب المستخدم ولا يرفعها تلقائيًا.","sources":["https://www.quantconnect.com/docs/v2"]},
    {"id":"REPORT-001","category_ar":"السجلات والتقارير","name_ar":"تقرير تحليلي شامل قابل للتصدير","status":"partial","detail_ar":"تصدير سجل JSON موجود؛ PDF/HTML/حزمة يومية تلقائية غير مكتملة.","sources":["https://www.tradingview.com/features/","https://www.koyfin.com/features/"]},
    {"id":"RESEARCH-001","category_ar":"البحث والتحقق","name_ar":"سجل نسخ الاستراتيجيات وفرضياتها ونتائجها","status":"planned","detail_ar":"لا توجد قاعدة تجارب كاملة تتابع كل فرضية ومعلماتها ونتائجها على بيانات سوق حقيقية.","sources":["https://www.quantconnect.com/docs/v2","https://www.lean.io/"]},
    {"id":"RESEARCH-002","category_ar":"البحث والتحقق","name_ar":"اختبارات جودة البيانات وقابلية إعادة إنتاج التحليل","status":"partial","detail_ar":"توجد اختبارات عقود ولقطات وتوقيت، لكن تغطية جميع المصادر وسجل معرفة مستمر ما زالا غير مكتملين.","sources":["https://www.quantconnect.com/docs/v2/lean-engine/getting-started"]},
    {"id":"WORKSPACE-001","category_ar":"واجهة ومرونة الاستخدام","name_ar":"لوحة عربية موحدة مع حالة المصادر","status":"partial","detail_ar":"لوحة محلية موجودة، لكن لا تحتوي بعد على كل أقسام المنتج وخيارات ترتيب/حفظ العمل.","sources":["https://www.tradingview.com/features/","https://www.koyfin.com/features/"]},
    {"id":"WORKSPACE-002","category_ar":"واجهة ومرونة الاستخدام","name_ar":"حفظ التخطيطات والفلاتر والتنبيهات","status":"planned","detail_ar":"الإعدادات والمفضلات ليست نظام مساحة عمل محفوظة متكاملًا بعد.","sources":["https://www.tradingview.com/features/","https://www.koyfin.com/features/"]},
    {"id":"INTEGRATION-001","category_ar":"التكاملات","name_ar":"طبقات موائمات مستقلة مع بديل عند انقطاع المصدر","status":"partial","detail_ar":"بعض المصادر منفصلة وتُحدّث يدويًا؛ لا يوجد بعد مدير تكاملات كامل مع health checks موحد.","sources":["https://www.quantconnect.com/docs/v2/lean-engine/getting-started"]},
    {"id":"INTEGRATION-002","category_ar":"التكاملات","name_ar":"تدفق بيانات مدفوع مع اعتماد وترخيص موثقين","status":"research_required","detail_ar":"لا توجد مفاتيح مدفوعة أو اشتراكات مفترضة؛ كل موائم يحتاج تحققًا من الترخيص والتكلفة والاستخدام المسموح.","sources":["https://www.tradingeconomics.com/calendar/api","https://bookmap.com/en/features"]},
)


def get_feature_catalog() -> list[dict[str, Any]]:
    """Return independent dictionaries for safe UI use."""
    return [
        {**item, "sources": list(item["sources"]), "status_ar": STATUS_LABELS_AR[item["status"]]}
        for item in FEATURES
    ]


def summarize_feature_catalog() -> dict[str, Any]:
    counts = Counter(item["status"] for item in FEATURES)
    return {
        "total": len(FEATURES),
        "counts": dict(counts),
        "counts_ar": {STATUS_LABELS_AR[key]: value for key, value in counts.items()},
        "categories": len({item["category_ar"] for item in FEATURES}),
        "implemented": counts.get("implemented", 0),
        "partial": counts.get("partial", 0),
        "planned": counts.get("planned", 0),
        "external_dependency": counts.get("external_dependency", 0),
        "research_required": counts.get("research_required", 0),
    }


__all__ = ["FEATURES", "STATUS_LABELS_AR", "get_feature_catalog", "summarize_feature_catalog"]

[executed on device: DESKTOP-BCGR98A (28de460a-0fbe-4532-90a8-ff34da68192c)]