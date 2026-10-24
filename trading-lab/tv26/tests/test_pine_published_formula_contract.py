import re
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
            "rMacd=f_calcRating(macdSignal,macdLine>macdSignal,macdLine<macdSignal)",
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

    def test_parity_workflow_runs_automatically_on_export_upload(self):
        workflow = (ROOT.parents[1] / ".github/workflows/tv26-direct-tradingview-parity.yml").read_text(encoding="utf-8")
        self.assertIn('      - "trading-lab/tv26/parity-input/TV26_AllTF.csv"', workflow)
        self.assertIn("MT5_AUDIT_RUN_ID: ${{ inputs.mt5_audit_run_id || '40077651784' }}", workflow)
        self.assertIn("MT5_UTC_OFFSET_HOURS: ${{ inputs.mt5_utc_offset_hours || '3' }}", workflow)

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

    def test_aggregate_and_closed_bar_contract(self):
        self.assertIn("floattotal=nz(ratingMA,0)+nz(ratingOther,0)", self.source)
        self.assertIn("notna(ratingMA)andnotna(ratingOther)=>total/2", self.source)
        self.assertIn("[packedVotes[1],libTotal[1],libMA[1],libOsc[1],", self.source)
        self.assertEqual(self.source.count("lookahead=barmerge.lookahead_on"), 5)
        self.assertEqual(self.source.count("request.security(syminfo.tickerid"), 5)


if __name__ == "__main__":
    unittest.main()
