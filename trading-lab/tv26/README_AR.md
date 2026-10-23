# TV26 Five-Timeframe Arabic EA — Candidate 1.009

## Purpose
A research candidate for XAUUSD in MT5. It calculates 26 Technical-Ratings-style components on five configurable timeframes (defaults M1/M5/M15/M30/H1), shows each component's signal and readiness in Arabic, and displays the aggregate rating and operational count for each timeframe.

## المطابقة المباشرة مع TradingView

جهزنا أداة مقارنة مباشرة تعتمد على تصدير Pine الحقيقي، لا على إعادة تنفيذ المعادلات فقط:
- الدليل خطوة بخطوة: [DIRECT_TRADINGVIEW_PARITY_GUIDE_AR.md](DIRECT_TRADINGVIEW_PARITY_GUIDE_AR.md)
- أداة المقارنة المجربة: [compare_tv26_csv.py](compare_tv26_csv.py)
- مرجع Pine لتصدير التصويتات الـ26: [TradingView_Parity_Components_1TF.pine](TradingView_Parity_Components_1TF.pine)
- سير عمل GitHub للمقارنة: [tv26-direct-tradingview-parity.yml](../../.github/workflows/tv26-direct-tradingview-parity.yml)

يلزم تصدير CSV واحد لكل إطار من TradingView، وملف تدقيق MT5 من نفس فترة الاختبار. المقارنة تفحص OHLC أولًا ثم درجات الملخص وأصوات المكونات. لا يُدّعى تحقق المطابقة الفعلية قبل توفر ملفات TradingView الصادرة من Pine وتشغيل المقارنة عليها.

## 26 components
**Moving-average group (15):** SMA/EMA 10, 20, 30, 50, 100, 200; Ichimoku Kijun/base line; VWMA 20; Hull MA 9.

**Oscillator group (11):** RSI 14, Stochastic 14/3/3, CCI 20, ADX 14 with +DI/-DI, Awesome Oscillator, Momentum 10, MACD 12/26/9, Stochastic RSI (derived), Williams %R 14, Bulls/Bears Power (EMA(13) as used by TechnicalRating v3 source), Ultimate Oscillator (7/14/28).

Each component returns +1 buy, 0 neutral, or -1 sell. The aggregate is the average of valid component scores. It is explicitly marked **غير مكتمل** and trading is blocked unless all 26 components are ready on every configured timeframe.

## Trading gate
- Entry is evaluated once per new M1 bar.
- Buy only when all five complete timeframe ratings are strictly > +0.50 (شراء قوي).
- Sell only when all five complete timeframe ratings are strictly < -0.50 (بيع قوي).
- Mixed or weaker ratings mean wait; no forced entry.
- One position per symbol + magic number. An opposite aligned signal attempts to close the existing position before reversing.
- Default risk is 0.50% of equity, with M1 ATR(14) stop 2 ATR and target 3 ATR.
- Default demo-only guard prevents sending orders on a real account. Disable it only deliberately after independent validation.
- Spread cap defaults to 100 points. Order return codes are checked and logged.

## Important fidelity limits
This is a source-audited MQL5 implementation of the 26 components in the published TechnicalRating v3 logic, but **not yet verified as a bit-for-bit numerical reproduction** against live TradingView values. The public v3 source snapshot reviewed for this candidate shows an important discrepancy from the library overview/help summary: it calculates Bull/Bear Power using EMA(13), and its sell ADX condition requires ADX to be rising. The EA follows the v3 source expressions on these points. Feed differences, EMA/RMA initialization, platform arithmetic and Pine compilation/behavior still require measured same-bar comparison; no parity percentage or profitability is claimed.

## Acceptance sequence
1. Compile this exact source in MetaEditor and record compiler output.
2. Fix all errors and warnings; inspect Arabic panel rendering.
3. Compare all 26 component signals and aggregate values against TradingView on the same symbol/provider where possible, using closed candles and identical settings.
4. Test at least three separate date windows with real ticks and realistic costs; keep a final untouched holdout.
5. Verify no trades occur with missing indicators, mixed timeframe ratings, real account under demo-only mode, or excessive spread.
6. Only after those gates, consider a demo forward test. Do not infer profitability from compilation or signal parity.

## Status — 2026-10-23
- MetaEditor compile: **PASS**, GitHub Actions run [39945310172](https://github.com/staryuzar/-/actions/runs/39945310172), commit `4c16432130ab30893f8ea935113e6431e13819e5`.
- Compiler result: **0 errors, 0 warnings**; generated EX5 size 36,602 bytes. Report artifact: [12498126118](https://github.com/staryuzar/-/actions/runs/39945310172/artifacts/12498126118).
- First compile attempt exposed an unnecessary include dependency (`Trade/Trade.mqh`) and a version metadata warning; both were fixed, and the next compile passed.
- The official installer returned exit code 1, but MetaEditor was present and the compile evidence was independently read from the artifact. This is recorded as an installer quirk, not as a compile failure.
- **Not yet tested:** live chart rendering of Arabic text, indicator-by-indicator parity against TradingView, Strategy Tester, multi-period performance, order execution in a demo tester, and profitability. Compilation only proves the source compiles.


## Parity audit — 2026-10-23 (source review; live-value match still pending)

The first audit found material divergences from TradingView's published Technical Ratings rules. Corrections have been committed to the candidate source:
- Overall rating now averages the MA-group mean and oscillator-group mean, rather than averaging all 26 scores as one undifferentiated pool.
- Category boundaries use strict comparisons: Strong Buy > +0.5; Buy > +0.1 through +0.5; Neutral from -0.1 through +0.1; Sell from -0.5 up to but not including -0.1; Strong Sell < -0.5.
- Ultimate Oscillator direction was reversed in the initial candidate; it is corrected to Buy above 70 and Sell below 30.
- Momentum now compares its current value with its previous value rather than comparing to the fixed level 100.
- RSI, Stochastic, CCI, ADX, AO, Williams %R and Ichimoku now include more of the published directional/turning conditions.
- Stochastic RSI was implemented using RSI(14), Stochastic(14), %K smoothing 3 and %D smoothing 3. The exact v3 source snapshot shows Bull/Bear Power uses EMA(13), while its overview text lists a different period; the EA follows the source code.

Reference: TradingView Help Center, Technical Ratings: https://www.tradingview.com/support/solutions/43000614331-technical-ratings/
Reference: current public TechnicalRating library description, updated 2024-11-29: https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/

### Known parity limitations still requiring verification
- Exact current-library internals for Stochastic RSI, Bull/Bear Power, Ichimoku span alignment, and Hull MA must still be compared against the reference implementation.
- TradingView and MT5 feeds can differ in OHLC, tick volume, session boundaries, and indicator initialization; the comparison must use the same symbol/provider and closed-bar timestamp.
- No live TradingView values or user chart screenshots were available during this source audit. Therefore no claim of same-moment equality is made yet.
- Historical intermediate compile: **PASS**, run [39945996760](https://github.com/staryuzar/-/actions/runs/39945996760), source commit `43c169ec291e9216030ebf31e799ceae8f463309`. This build record is retained for audit history only; the latest source has since received multiple formula, diagnostic and safety updates. See the version and build evidence in the Latest candidate note below.

### Live comparison protocol
For each of M1, M5, M15, M30 and H1, capture the same closed candle timestamp and record:
1. TradingView symbol/provider and candle time.
2. Overall Technical Rating, MA Rating and Oscillator Rating.
3. The 26 component states from the EA panel.
4. Any disagreement, likely cause, correction, and retest result.
Do not enable real-account trading based on this audit alone.


## Latest candidate note — 2026-10-23

- The EA's Arabic panel displays numeric values for overall, MA and oscillator ratings; labels each rating as complete/incomplete; reports readiness as total/26 plus MA/15 and oscillator/11; and prints the opening time of the last closed candle in MT5 server time. An incomplete group shows “—” instead of a misleading partial score.
- Momentum is calculated as `close - close[10]` and the current Momentum value is compared with its previous value; this avoids MT5 `iMomentum`'s ratio-style scaling.
- CCI uses `close` as its input to match the reference formula, rather than MT5 `PRICE_TYPICAL`.
- MACD is now computed as EMA(12) − EMA(26), with an EMA(9) signal line over the MACD series. This avoids relying on MT5's built-in MACD signal averaging, which differs from Pine's default EMA signal line.
- Stochastic RSI trend and Bulls/Bears Power trend filters use the close's position relative to EMA(50), without an extra one-bar RSI-slope test or EMA-slope gate.
- The EA now follows the v3 source expression for ADX: buy when +DI > −DI and ADX > 20 while rising; sell when +DI < −DI and ADX > 20 while also rising. This conflicts with the general Technical Ratings Help Center wording for ADX sell (falling ADX), so exact live value comparison remains essential.
- The EA follows the frozen TechnicalRating v3 source expression: Bull Power = high − EMA(close,13); Bear Power = low − EMA(close,13). This differs from the library overview text that lists period 50. Source mirror inspected: [Tealstreet/tealchart official TradingView library-source snapshot](https://github.com/Tealstreet/tealchart/blob/800dafe10ebb48b8eeba53a191460d011f40a6ca/packages/tealscript/src/officialTradingViewLibrarySources.ts).
- The EA source is now **version 1.009**, source commit `310be1a6b384dbe4591c7ff79570ce55808667b1`. In addition to the v1.008 formula corrections and diagnostics, CSV export now retries a newly closed candle up to 10 two-second timer cycles (about 20 seconds) while any of the 26 components are not ready. It then records the current readiness state once, rather than prematurely logging a one-time startup data-loading delay as the final state. This is compile-only software evidence, not a Strategy Tester result or proof of numerical parity/profitability; the v1.009 build run is [39952338409](https://github.com/staryuzar/-/actions/runs/39952338409).



### Diagnostic CSV export — v1.004+

The EA writes `TV26_Audit_<symbol>_<magic>.csv` to MT5's **Common\Files** directory, shown at the top of the EA chart panel. It appends one record for each newly closed candle per configured timeframe; MT5 must have history available for all five timeframes. In v1.009, if a candle is not yet fully ready, export retries at each 2-second timer cycle up to 10 times (about 20 seconds); if components remain unavailable, it writes one incomplete record instead of postponing it indefinitely.

Columns:
- `bar_open_time_server`: opening timestamp of the closed candle in broker/server time.
- `symbol`, `broker_company`, `broker_server`, `timeframe`: identify the price feed and timeframe being compared.
- `component`, `readiness`, `vote`: component name, whether it calculated successfully, and its -1/0/+1 vote.
- `value_a` through `value_e`: raw indicator values used by the vote. Their exact meanings vary by component; see below.
- `candle_open`, `candle_high`, `candle_low`, `candle_close`, `tick_volume`: feed context to compare with the same TradingView candle.

Raw-value mapping: MA rows store (MA, close); Ichimoku stores (conversion line, base line, Span A[26], Span B[26], close); VWMA/Hull store (average, close); RSI/CCI/Williams store (current, previous); Stochastic stores (K,D); ADX stores (ADX,+DI,-DI,previous ADX); AO stores (current, previous, two-bars-back); Momentum stores (current Momentum, previous Momentum, close, close[10]); MACD stores (MACD line, signal, EMA12, EMA26); Stochastic RSI stores (K,D,close,EMA50); Bulls/Bears stores (bull current,bull previous,bear current,bear previous,EMA50 trend filter; candle_close is in the OHLC columns); Ultimate Oscillator stores its value. Summary rows contain overall/MA/oscillator ratings (blank if incomplete), readiness counts and OHLCV.

### Entry/reversal safety — v1.006

- Last executed strong-direction state is persisted in a terminal Global Variable per symbol + magic number.
- After a same-direction position exits, the EA will not reopen the same strong signal repeatedly until consensus ceases to be strong.
- A reversal is not treated as complete after a partial close while the old position ticket still exists.

### Exact v3-source corrections — 1.007+

The inspected TechnicalRating v3 source snapshot makes the following conditions explicit:
- Ichimoku evaluates the current conversion/base lines and close, but compares leading spans at `[26]`. With MT5 evaluating closed candle shift 1, the EA reads those raw span buffers at shift 27.
- ADX buy requires +DI > −DI and ADX > 20 with ADX rising; the v3 source also requires ADX rising for sell when +DI < −DI. This is not the same as the general Help Center's sell wording, so the implementation follows v3 source behavior and flags the documentation conflict rather than mixing the two rule sets.
- Bull/Bear Power is calculated as high − EMA(close,13) and low − EMA(close,13). The library overview text's parameter summary differs from the actual v3 source expression; the EA follows the source expression.

The inspected source snapshot is in [Tealstreet/tealchart](https://github.com/Tealstreet/tealchart/blob/800dafe10ebb48b8eeba53a191460d011f40a6ca/packages/tealscript/src/officialTradingViewLibrarySources.ts), which embeds the TradingView library text. It is a source mirror, not the TradingView website itself.

### Comparator status

The Pine comparison panel now shifts `calcRatingAll()` output by one bar inside each requested timeframe and uses `lookahead_on` only with those offset values, so it aims to show the prior confirmed bar instead of a developing higher-timeframe value. It displays overall, MA, and oscillator ratings numerically, their Arabic categories, and the timestamp of the corresponding closed candle. The script has **not** been compiled inside TradingView itself; check Pine Editor for acceptance before using it as the comparison oracle.

## TradingView-side reference panel
A Pine Script reference indicator was added at [TradingView_Parity_5TF.pine](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TradingView_Parity_5TF.pine). It imports TradingView's public TechnicalRating v3 library and displays overall, MA and oscillator ratings for M1/M5/M15/M30/H1. It is a summary comparison aid; it does not expose all 26 component states individually.

To use it: open TradingView with the intended XAUUSD data provider, set the chart to **M1**, open Pine Editor, paste the file contents from GitHub, save, and add it to the chart. Compare the three numeric ratings against MT5 for each timeframe at the same candle timestamp (convert timezone labels as needed). If TradingView rejects the script, fix the reported Pine error before comparing; GitHub Actions checks only MQL5, not Pine compilation.

### Component-by-component Pine audit

A second Pine diagnostic was added: [TradingView_Parity_Components_1TF.pine](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TradingView_Parity_Components_1TF.pine). It reproduces the published v3 component rating expressions, shows the three numeric summary ratings plus all 26 individual votes, and offsets the values to the prior confirmed candle in the selected timeframe.

Use it to identify which component disagrees, not as a claim that the EA has already matched live TradingView values:
1. Open TradingView on the same XAUUSD provider or symbol you plan to compare with MT5.
2. Open Pine Editor, paste the entire component audit script from the link, save, and add it to the chart.
3. Select the timeframe to audit (M1, M5, M15, M30 or H1) in the script settings.
4. In the chart's top menu, choose **Export chart data / Download chart data** and save the CSV. The audit script outputs `TV26.total`, `TV26.ma`, `TV26.osc`, `TV26.bar_open_time`, `TV26.open`, `TV26.high`, `TV26.low`, `TV26.close`, `TV26.volume`, and one `TV26.*` series for each of the 26 component votes. The OHLCV values and timestamp all refer to the same prior confirmed candle. `display.data_window` keeps these outputs out of the chart pane while preserving them for export. See TradingView's [official export documentation](https://www.tradingview.com/pine-script-docs/faq/indicators/).
5. Compare the TradingView CSV with the EA's `TV26_Audit_<symbol>_<magic>.csv` on the same symbol/provider and timeframe. First match the closed candle using `TV26.bar_open_time` plus `TV26.open/high/low/close/volume`; do not match only against the CSV row's current chart-bar time. If the quote feed differs, mismatched OHLCV can itself explain later indicator-score differences. If server and chart time zones differ, align the timestamp using the same candle's OHLCV before judging indicator mismatches.
6. The audit script uses the imported `TradingView/ta/9` library and has **not** been compiled in TradingView itself yet. If Pine Editor reports an error, correct that first; if the CSV omits the `TV26.*` columns, confirm the script compiled, was added to the chart, and is enabled.

The GitHub workflow has static regression checks for the MQL5 source and key expressions in both Pine scripts. It does not compile Pine and cannot access the user's private TradingView session.
The current GitHub Windows workflow uses MetaEditor only. A successful workflow run is source-compile evidence, not proof of indicator parity, and it cannot inspect the user's private TradingView chart.


## Headless cloud audit — MT5 without using the local PC

The workflow [TV26 headless cloud MT5 indicator audit](https://github.com/staryuzar/-/actions/workflows/tv26-cloud-audit.yml) runs MT5 Strategy Tester on a GitHub-hosted Windows runner. The EA input InpEnableTrading=false and tester setting AllowLiveTrading=0 are used deliberately: this run exports indicator diagnostics, not orders.

The diagnostic window is **2026-09-01 through 2026-09-03 inclusive**, on XAUUSD/M1 with rating frames M1/M5/M15/M30/H1. The tester uses **1-minute OHLC model**, not real ticks. It downloads the official MT5 installer, compiles the checked-out EA, runs the tester, and attempts to export TV26_Audit_XAUUSD_26102326.csv and a run summary as a GitHub Actions artifact. The repository's mt5 Actions secret supplies the account connection; the password/configuration file is not included in artifacts. If the secret is missing or tester history/audit output is unavailable, the workflow must be treated as failed/incomplete.

### What this cloud test proves — and does not prove

- It can produce the EA's actual MT5 indicator diagnostics on a hosted Windows runner without launching the user's local MT5.
- It is **not** a live TradingView comparison: GitHub Actions cannot execute a private TradingView chart or compile the user's Pine script. The audit CSV is MT5-side evidence only.
- It is **not** a profitability test. Trading is explicitly disabled, and the model is 1-minute OHLC rather than real ticks.
- A numerical parity claim requires a TradingView component-export CSV from the same symbol/provider and candle timestamps, then a successful report from the comparator below.

### Compare the two CSVs when a TradingView export is available

The comparator is compare_tv26_csv.py. It aligns the prior closed candle by timestamp (using the explicit MT5 server UTC offset), checks OHLC consistency, compares overall/MA/oscillator ratings, and compares all 26 component votes. It writes a Markdown summary and a row-by-row CSV. Unmatched candles and missing component values cannot silently pass.

Example (replace 3 only if MT5 server timestamps are actually UTC+3; determine the broker server offset rather than assuming Yemen local time equals broker server time):

    python trading-lab/tv26/compare_tv26_csv.py --mt5 MT5_AUDIT.csv --tv TV26_TRADINGVIEW_EXPORT.csv --timeframe M1 --mt5-utc-offset-hours 3 --min-bars 10

Run separately for M5, M15, M30 and H1, with the TradingView Pine input and comparison timeframe set to the same frame. PASS is limited to the two files and timeframe tested; it does not prove profitability. Use a mismatch report to isolate the component and candle before changing any formula.


## Verified cloud run record — 2026-10-23

The first successful hosted MT5 audit and manual post-run integrity review are recorded in [TV26_CLOUD_AUDIT_2026-10-23.md](TV26_CLOUD_AUDIT_2026-10-23.md). The run itself is [GitHub Actions 39955800878](https://github.com/staryuzar/-/actions/runs/39955800878), with raw artifact [12502193295](https://github.com/staryuzar/-/actions/runs/39955800878/artifacts/12502193295). It exported 5,432 complete summary candles across the five frames and 141,232 ready component votes. Recalculation of the three summary scores from the exported component votes found zero internal arithmetic mismatches.

The script validate_tv26_mt5_audit.py now independently checks CSV structure, all 26 votes per candle, readiness, timestamp format, duplicate rows, OHLC sanity, and the relationship between component votes and aggregate scores. Its tests cover complete data, a missing vote, a wrong aggregate score and an invalid vote. The cloud workflow now runs this validator and saves its Markdown/JSON findings as evidence.

**Important:** the above is an MT5 data-export and internal-consistency result. No actual TradingView-export CSV was available in that run, so the status is **not yet TradingView parity** and not a profitability finding.


## فحص مستقل لقواعد التصويت الـ26 على الأطر الخمسة

أضيفت أداة مستقلة تعيد تنفيذ صيغ المؤشرات المنشورة بدل الاكتفاء بالتحقق من أن المجاميع الحسابية تساوي متوسط التصويتات. الأداة هي reference_tv26_formulas.py وتعالج ملف OHLCV التمهيدي مع سجل MT5 ثم تقارن كل تصويت على كل شمعة في M1 وM5 وM15 وM30 وH1.

التقرير التفصيلي لآخر تحليل على بيانات الاختبار محفوظ في [TV26_FORMULA_AUDIT_2026-10-23.md](TV26_FORMULA_AUDIT_2026-10-23.md). جرى فحص **141,232 تصويتًا** عبر **5,432 شمعة ملخص**: صفر اختلافات وصفر قيم مفقودة في الأطر الخمسة، مع تطابق OHLC للشموع المتداخلة بين ملف التهيئة والسجل. مرجع تشغيل MT5 والملفات الخام: [GitHub Actions 39961042587](https://github.com/staryuzar/-/actions/runs/39971143665).

سير العمل [TV26 headless cloud MT5 indicator audit](https://github.com/staryuzar/-/actions/workflows/tv26-cloud-audit.yml) يشغّل الآن هذه الخطوات آليًا: تثبيت الاعتماديات، تشغيل MT5 على Windows السحابي مع تعطيل التداول، التحقق من بنية السجل والدرجات العامة، ثم مقارنة الصيغ على التصويتات الـ26. يُفترض أن يحمل الأثر الناتج تقرير سلامة CSV وتقرير مطابقة الصيغ وملفات التفاصيل بصيغ Markdown وJSON وCSV.

**حدود الاستنتاج:** هذه نتيجة مطابقة لقواعد TradingView المنشورة مع تصويت MT5 على شموع Headway-Demo. ليست تصديرًا مباشرًا من مخطط TradingView الحي، ولا إثباتًا للربحية أو لأداء Real Ticks. عند توفر تصدير Pine فعلي من TradingView، تبقى أداة compare_tv26_csv.py مطلوبة للتحقق من الشمعة ومزود البيانات والتوقيت ثم مقارنة كل مكوّن مباشرة.


## أول اختبار صفقات فعلي داخل Strategy Tester — 23 أكتوبر 2026

نتيجة الاختبار الأولي لثلاثة أيام محفوظة في [TV26_STRATEGY_BACKTEST_2026-10-23.md](TV26_STRATEGY_BACKTEST_2026-10-23.md). التشغيل: https://github.com/staryuzar/-/actions/runs/39972607072، والأثر: https://github.com/staryuzar/-/actions/artifacts/12510365482.

النتيجة ليست ربحية: **صفقة واحدة، خسارة 2.42 دولار، عامل ربح 0.00، وتراجع أقصى لحقوق الحساب 0.88%** على رصيد ابتدائي 500 دولار. الصفقة بيع XAUUSD بحجم 0.01، دخلت عند 4427.54 وخرجت بوقف الخسارة عند 4429.96 بعد 18 دقيقة و20 ثانية. العينة قصيرة جدًا ولا يصح الاستنتاج منها بأن الاستراتيجية ناجحة أو فاشلة نهائيًا.

التداول كان مسموحًا داخل Strategy Tester فقط بإعداد InpTesterOnly=true، مع بقاء InpDemoOnly=true. النموذج 1-minute OHLC وليس Real Ticks. تم إعداد متابعة أطول إلى عشرة أيام (1–10 سبتمبر 2026) بنفس قواعد المخاطرة لتحديد إن كان توافق الأطر الخمسة ينتج عددًا كافيًا من الصفقات قبل تعديل قواعد الدخول.
