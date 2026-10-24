import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compact(source: str) -> str:
    return re.sub(r"\s+", "", source)


class TV26PublishedFormulaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = compact(
            (ROOT / "TradingView_Parity_AllTF_Export.pine").read_text(encoding="utf-8")
        )

    def test_uses_pinned_official_tradingview_libraries(self):
        raw = (ROOT / "TradingView_Parity_AllTF_Export.pine").read_text(encoding="utf-8")
        self.assertIn("import TradingView/ta/9 as tvta", raw)
        self.assertIn("import TradingView/TechnicalRating/3 as tvRating", raw)

    def test_all_15_moving_average_ratings_use_published_inputs(self):
        for n in (10, 20, 30, 50, 100, 200):
            self.assertIn(f"f_calcRatingMA(ta.sma(close,{n}),close)", self.source)
            self.assertIn(f"f_calcRatingMA(ta.ema(close,{n}),close)", self.source)
        self.assertIn("f_calcRatingMA(ta.hma(close,9),close)", self.source)
        self.assertIn("f_calcRatingMA(ta.vwma(close,20),close)", self.source)
        self.assertIn(
            "f_calcRating(lead2,lead1[26]>lead2[26]andbase>lead1[26]andcon>baseandclose>con,"
            "lead1[26]<lead2[26]andbase<lead1[26]andcon<baseandclose<con)",
            self.source,
        )

    def test_all_11_oscillator_conditions_match_v3_contract(self):
        expressions = [
            "rRsi=f_calcRating(rsi[1],rsi<30andrsi[1]<rsi,rsi>70andrsi[1]>rsi)",
            "rStoch=f_calcRating(dStoch[1],kStoch<20anddStoch<20andkStoch>dStoch,"
            "kStoch>80anddStoch>80andkStoch<dStoch)",
            "rCci=f_calcRating(cci[1],cci<-100andcci>cci[1],cci>100andcci<cci[1])",
            "rAdx=f_calcRating(adx,adx>20andadx>adx[1]anddiP>diN,adx>20andadx>adx[1]anddiP<diN)",
            "rAo=f_calcRating(ao[1],ta.crossover(ao,0)or(ao>0andao[1]>0andao>ao[1]andao[2]>ao[1]),"
            "ta.crossunder(ao,0)or(ao<0andao[1]<0andao<ao[1]andao[2]<ao[1]))",
            "rMomentum=f_calcRating(mom[1],mom>mom[1],mom<mom[1])",
            "rMacd=f_calcRating(macdSignal,macdLine>macdSignalandmacdHist>0,macdLine<macdSignalandmacdHist<0)",
            "rStochRsi=f_calcRating(priceAvg,downTrendandkStochRsi<20anddStochRsi<20andkStochRsi>dStochRsi,"
            "upTrendandkStochRsi>80anddStochRsi>80andkStochRsi<dStochRsi)",
            "rWilliams=f_calcRating(wr[1],wr<-80andwr>wr[1],wr>-20andwr<wr[1])",
            "rBullBear=f_calcRating(priceAvg,upTrendandbearPower<0andbearPower>bearPower[1],"
            "downTrendandbullPower>0andbullPower<bullPower[1])",
            "rUo=f_calcRating(uo,uo>70,uo<30)",
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                self.assertIn(expression, self.source)

    def test_direct_parity_workflow_is_a_display_only_guard(self):
        workflow = (ROOT.parents[1] / ".github/workflows/tv26-direct-tradingview-parity.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("Automated TradingView market-data processing is disabled", workflow)
        self.assertIn("TradingView_Visual_Parity_5TF.pine", workflow)
        self.assertIn("Do not export chart data to CSV", workflow)
        self.assertNotIn("gh run list", workflow)
        self.assertNotIn("gh api", workflow)
        self.assertNotIn("compare_tv26_csv.py", workflow)
        self.assertNotIn("MT5_Audit.csv", workflow)
        self.assertNotIn("TV26_AllTF.csv", workflow)
        self.assertNotIn("pull_request:", workflow)
        # No push trigger: chart market data cannot enter this workflow automatically.
        self.assertNotRegex(workflow, r"(?m)^\s{2}push:")


    def test_strategy_diagnostic_counts_deduplicate_mirrored_mt5_events(self):
        script = (ROOT.parents[1] / ".github/scripts/tv26_strategy_backtest.ps1").read_text(encoding="utf-8")
        self.assertIn("HashSet[string]", script)
        self.assertIn("TV26_CONSENSUS;", script)
        self.assertIn("TV26_ENTRY_BLOCK;", script)
        self.assertIn("TV26_ORDER_ACCEPTED;", script)
        self.assertIn("TV26_POSITION_CLOSED;", script)
        self.assertIn("$line.Substring($eventStart).Trim()", script)
        self.assertIn("$diagText = (@($diagEvents | Sort-Object) -join [Environment]::NewLine)", script)
        self.assertNotIn("$diagText += (Get-Content", script)

    def test_legacy_pine_exporters_are_marked_not_for_real_data_processing(self):
        for filename in ("TradingView_Parity_AllTF_Export.pine", "TradingView_Parity_Components_1TF.pine"):
            raw = (ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn("LEGACY FORMULA REFERENCE ONLY", raw)
                self.assertIn("do not export real TradingView chart data to CSV", raw)
                self.assertIn("TradingView_Visual_Parity_5TF.pine", raw)


    def test_exporters_discard_chikou_and_use_macd_histogram_consistently(self):
        for filename in ("TradingView_Parity_AllTF_Export.pine", "TradingView_Parity_Components_1TF.pine"):
            source = (ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn("[con, base, lead1, lead2, _] = tvta.ichimoku()", source)
                self.assertIn("[macdLine, macdSignal, macdHist] = ta.macd(close, 12, 26, 9)", source)
                self.assertIn("macdLine > macdSignal and macdHist > 0", source)
                self.assertIn("macdLine < macdSignal and macdHist < 0", source)
                self.assertNotIn("chikou", source)

    def test_strategy_m1_close_breakout_is_optional_and_auditable(self):
        ea = (ROOT / "TV26_FiveTF_Arabic_CANDIDATE.mq5").read_text(encoding="utf-8")
        script = (ROOT.parents[1] / ".github/scripts/tv26_strategy_backtest.ps1").read_text(encoding="utf-8")
        workflow = (ROOT.parents[1] / ".github/workflows/tv26-strategy-breakout-risk1-diagnostic.yml").read_text(encoding="utf-8")
        self.assertIn("InpRequireM1CloseBreakout = false", ea)
        self.assertIn("decisionClose>priorHigh : decisionClose<priorLow", ea)
        self.assertIn("reason=M1_CLOSE_BREAKOUT_NOT_CONFIRMED", ea)
        self.assertIn("TV26_TEST_REQUIRE_M1_BREAKOUT", script)
        self.assertIn("InpRequireM1CloseBreakout=$testBreakoutText", script)
        self.assertIn("InpRequireM1CloseBreakout=' + [regex]::Escape($testBreakoutText)", script)
        self.assertIn('TV26_TEST_REQUIRE_M1_BREAKOUT: "true"', workflow)
        self.assertIn('TV26_TEST_RISK_PERCENT: "1.00"', workflow)
        self.assertIn('TV26_TEST_STOP_ATR: "2.00"', workflow)
        self.assertIn('TV26_TEST_TARGET_ATR: "3.00"', workflow)
        self.assertIn('TV26_TEST_MODEL: "4"', workflow)

    def test_williams_r_uses_builtin_namespace_in_both_exporters(self):
        for filename in ("TradingView_Parity_AllTF_Export.pine", "TradingView_Parity_Components_1TF.pine"):
            raw = (ROOT / filename).read_text(encoding="utf-8")
            normalized = compact(raw)
            with self.subTest(filename=filename):
                self.assertIn("ta.wpr(14)", normalized)
                self.assertNotIn("tvta.wpr(14)", normalized)

    def test_ci_calls_tradingview_compiler_with_supported_flags(self):
        workflow = (ROOT.parents[1] / ".github/workflows/tv26-parity-tests.yml").read_text(encoding="utf-8")
        self.assertIn("Validate Pine exporters with TradingView compiler endpoint", workflow)
        self.assertIn("--tv --human trading-lab/tv26/TradingView_Parity_AllTF_Export.pine", workflow)
        self.assertIn("--tv --human trading-lab/tv26/TradingView_Parity_Components_1TF.pine", workflow)
        self.assertNotIn("--no-lint", workflow)

    def test_parity_input_docs_forbid_real_tradingview_csv_upload(self):
        for path in (ROOT / "parity-input" / "README.md", ROOT / "parity-input" / "README_AR.md"):
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("display-only" if path.name == "README.md" else "العرض فقط", content)
                self.assertIn("TradingView_Visual_Parity_5TF.pine", content)
                self.assertIn("Do not upload a CSV" if path.name == "README.md" else "لا ترفع", content)
        workflow = (ROOT.parents[1] / ".github/workflows/tv26-direct-tradingview-parity.yml").read_text(encoding="utf-8")
        self.assertNotIn("TV26_AllTF.csv", workflow)


    def test_aggregate_and_closed_bar_contract(self):
        self.assertIn("floattotal=nz(ratingMA,0)+nz(ratingOther,0)", self.source)
        self.assertIn("notna(ratingMA)andnotna(ratingOther)=>total/2", self.source)
        self.assertIn("[packedVotes[1],libTotal[1],libMA[1],libOsc[1],", self.source)
        self.assertEqual(self.source.count("lookahead=barmerge.lookahead_on"), 5)
        self.assertEqual(self.source.count("request.security(syminfo.tickerid"), 5)


if __name__ == "__main__":
    unittest.main()
