# ملف إدخال المطابقة المباشرة

ارفع إلى هذا المجلد ملف CSV واحدًا فقط من تصدير TradingView:
- TV26_AllTF.csv

يجب إنشاء الملف من مؤشر Pine:
trading-lab/tv26/TradingView_Parity_AllTF_Export.pine

ضع الملف في هذا المسار بالاسم المطابق:
trading-lab/tv26/parity-input/TV26_AllTF.csv

يحتوي التصدير على مخرجات الأطر M1/M5/M15/M30/H1. يفك سير العمل التصويتات الـ26 لكل إطار تلقائيًا، ثم يقارنها بملف تدقيق MT5 الذي ينزّله من أثر GitHub Actions. لا ترفع MT5_Audit.csv يدويًا، ولا ترفع كلمات مرور أو ملف إعدادات الحساب.
