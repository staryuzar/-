# TV26 Five-Timeframe Arabic EA — Candidate 0.100

## Purpose
A research candidate for XAUUSD in MT5. It calculates 26 Technical-Ratings-style components on five configurable timeframes (defaults M1/M5/M15/M30/H1), shows each component's signal and readiness in Arabic, and displays the aggregate rating and operational count for each timeframe.

## 26 components
**Moving-average group (15):** SMA/EMA 10, 20, 30, 50, 100, 200; Ichimoku Kijun/base line; VWMA 20; Hull MA 9.

**Oscillator group (11):** RSI 14, Stochastic 14/3/3, CCI 20, ADX 14 with +DI/-DI, Awesome Oscillator, Momentum 10, MACD 12/26/9, Stochastic RSI (derived), Williams %R 14, Bulls/Bears Power (50 EMA for TechnicalRating v3 parity; the standalone indicator page defaults to 13), Ultimate Oscillator (7/14/28).

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
This is **not yet a verified bit-for-bit reproduction** of TradingView's proprietary/platform implementation. It is an explicit MQL5 implementation of the 26 familiar component families and a transparent rating framework. Some rating rules (especially Stochastic RSI, Hull MA, Bulls/Bears Power, and Ultimate Oscillator) may differ from TradingView's current source code or data provider. No parity percentage or profitability is claimed.

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
- Stochastic RSI and Bull/Bear Power logic were revised; Bull/Bear Power now uses the 50-period configuration listed by the current public TechnicalRating library.

Reference: TradingView Help Center, Technical Ratings: https://www.tradingview.com/support/solutions/43000614331-technical-ratings/
Reference: current public TechnicalRating library description, updated 2024-11-29: https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/

### Known parity limitations still requiring verification
- Exact current-library internals for Stochastic RSI, Bull/Bear Power, Ichimoku span alignment, and Hull MA must still be compared against the reference implementation.
- TradingView and MT5 feeds can differ in OHLC, tick volume, session boundaries, and indicator initialization; the comparison must use the same symbol/provider and closed-bar timestamp.
- No live TradingView values or user chart screenshots were available during this source audit. Therefore no claim of same-moment equality is made yet.
- Updated EA source compile: **PASS**, GitHub Actions run [39945996760](https://github.com/staryuzar/-/actions/runs/39945996760), source commit `43c169ec291e9216030ebf31e799ceae8f463309`. Compiler report: **0 errors, 0 warnings**, EX5 size 38,670 bytes. Artifact: [12498386430](https://github.com/staryuzar/-/actions/runs/39945996760/artifacts/12498386430). The later commits only add the TradingView reference script and documentation; the EA source itself is unchanged after this successful compile.

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
- The EA uses the official Technical Ratings Help Center condition for ADX sell: +DI < -DI, ADX > 20, and ADX falling versus the previous closed bar. The library page says v3 aligned to Screener methods, but its web description does not disclose every internal condition; verify exact live values.
- For BBP period, the parity target is the public `TechnicalRating/3` library's 50-period component, not the standalone BBP indicator page's default parameter of 13.
- Current MQL5 source is version **1.003**. The latest repository tree passed the MetaEditor compile-only workflow [run 39949116906](https://github.com/staryuzar/-/actions/runs/39949116906): **0 errors, 0 warnings**, generated EX5 size **41,314 bytes**. Report artifact: [tv26-metaeditor-compile-report](https://github.com/staryuzar/-/actions/runs/39949116906/artifacts/12499641976). The installer returned exit code 1, but MetaEditor was present and completed the compile successfully. Compilation does not establish indicator parity or profitability.

### Comparator status

The Pine comparison panel now shifts `calcRatingAll()` output by one bar inside each requested timeframe and uses `lookahead_on` only with those offset values, so it aims to show the prior confirmed bar instead of a developing higher-timeframe value. It displays overall, MA, and oscillator ratings numerically, their Arabic categories, and the timestamp of the corresponding closed candle. The script has **not** been compiled inside TradingView itself; check Pine Editor for acceptance before using it as the comparison oracle.

## TradingView-side reference panel
A Pine Script reference indicator was added at [TradingView_Parity_5TF.pine](https://github.com/staryuzar/-/blob/tv26-five-timeframes-arabic-candidate/trading-lab/tv26/TradingView_Parity_5TF.pine). It imports TradingView's public TechnicalRating v3 library and displays overall, MA and oscillator ratings for M1/M5/M15/M30/H1. It is a summary comparison aid; it does not expose all 26 component states individually.

To use it: open TradingView with the intended XAUUSD data provider, set the chart to **M1**, open Pine Editor, paste the file contents from GitHub, save, and add it to the chart. Compare the three numeric ratings against MT5 for each timeframe at the same candle timestamp (convert timezone labels as needed). If TradingView rejects the script, fix the reported Pine error before comparing; GitHub Actions checks only MQL5, not Pine compilation.

The current GitHub Windows workflow uses MetaEditor only. A successful workflow run is source-compile evidence, not proof of indicator parity, and it cannot inspect the user's private TradingView chart.
