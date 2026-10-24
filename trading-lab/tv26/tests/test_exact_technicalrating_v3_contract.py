"""Regression checks for the exact published TradingView TechnicalRating v3 contract.

This pins source-level facts so a later edit cannot silently drift toward the
help-page wording when that wording differs from the v3 library source.
It does not claim live-chart parity; that requires chart output from TradingView.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compact(path: str) -> str:
    return re.sub(r"\s+", "", (ROOT / path).read_text(encoding="utf-8"))


class ExactTechnicalRatingV3ContractTests(unittest.TestCase):
    def test_exporter_calls_the_versioned_technical_rating_library(self):
        pine = (ROOT / "TradingView_Parity_AllTF_Export.pine").read_text(encoding="utf-8")
        self.assertIn("import TradingView/TechnicalRating/3 as tvRating", pine)
        self.assertIn("import TradingView/ta/9 as tvta", pine)

    def test_adx_uses_rising_strength_in_both_directions_as_v3_source_does(self):
        # Exact TechnicalRating v3 expression: ADX must rise for BUY and SELL.
        pine = compact("TradingView_Parity_AllTF_Export.pine")
        ea = compact("TV26_FiveTF_Arabic_CANDIDATE.mq5")
        reference = compact("reference_tv26_formulas.py")
        expected_pine = (
            "rAdx=f_calcRating(adx,adx>20andadx>adx[1]anddiP>diN,"
            "adx>20andadx>adx[1]anddiP<diN)"
        )
        expected_ea = (
            "score=(a>20&&b>c&&a>prevADX?1:(a>20&&b<c&&a>prevADX?-1:0));"
        )
        expected_reference = (
            "ax=np.where((adx>20)&(adx>adx.shift(1))&(plus>minus),1,"
            "np.where((adx>20)&(adx>adx.shift(1))&(plus<minus),-1,0))"
        )
        self.assertIn(expected_pine, pine)
        self.assertIn(expected_ea, ea)
        self.assertIn(expected_reference, reference)

    def test_bulls_bears_power_period_is_13_in_all_local_reimplementations(self):
        pine = compact("TradingView_Parity_AllTF_Export.pine")
        ea = compact("TV26_FiveTF_Arabic_CANDIDATE.mq5")
        reference = compact("reference_tv26_formulas.py")
        self.assertIn("bullPower=high-ta.ema(close,13)", pine)
        self.assertIn("bearPower=low-ta.ema(close,13)", pine)
        self.assertIn("iBullsPower(_Symbol,g_tfs[t],13)", ea)
        self.assertIn("iBearsPower(_Symbol,g_tfs[t],13)", ea)
        self.assertIn("bull=h-ema(c,13);bear=l-ema(c,13)", reference)

    def test_rsi_matches_published_rma_recurrence_instead_of_platform_iRSI(self):
        ea = compact("TV26_FiveTF_Arabic_CANDIDATE.mq5")
        self.assertIn("TVRSIFromAverages(doubleavgGain,doubleavgLoss)", ea)
        self.assertIn("g_tvRsiAvgGain[t]=alpha*gain+(1.0-alpha)*g_tvRsiAvgGain[t];", ea)
        self.assertIn("g_tvRsiAvgLoss[t]=alpha*loss+(1.0-alpha)*g_tvRsiAvgLoss[t];", ea)
        self.assertIn("if(!UpdateTVRSIState(t,a,b))returnfalse;", ea)
        # Keep the strict overbought/oversold comparisons from TechnicalRating v3;
        # the RSI recurrence itself must match Pine's Wilder RMA arithmetic.
        self.assertIn("score=(a<30&&a>b?1:(a>70&&a<b?-1:0));", ea)

    def test_risk_and_order_safety_inputs_have_hard_validation(self):
        ea = compact("TV26_FiveTF_Arabic_CANDIDATE.mq5")
        self.assertIn("if(InpRiskPercent<=0||InpRiskPercent>2.0)", ea)
        self.assertIn("if(InpATRPeriod<1||InpStopATR<=0||InpTargetATR<=0||", ea)
        self.assertIn("InpMaxSpreadPoints<0||InpDeviationPoints<0||InpCooldownBarsAfterExit<0)", ea)
        self.assertIn("نسبةالمخاطرةيجبأنتكونأكبرمنصفرولاتتجاوز2.0%", ea)
        # Keep the research/backtest defaults intact: this is a guard on unsafe
        # parameter values, not a change to trading signals or risk sizing.
        self.assertIn("InpRiskPercent=0.50", ea)
        self.assertIn("InpDemoOnly=true", ea)

    def test_netting_account_guard_rejects_foreign_symbol_positions(self):
        ea = compact("TV26_FiveTF_Arabic_CANDIDATE.mq5")
        self.assertIn("boolHasForeignNettingPosition()", ea)
        self.assertIn("mode==ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", ea)
        self.assertIn("if((ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic)returntrue;", ea)
        self.assertIn("if(HasForeignNettingPosition())", ea)
        self.assertIn("FOREIGN_NETTING_POSITION", ea)
        self.assertIn("لميتمتعديلالمركز", ea)

    def test_reverse_close_uses_the_supported_symbol_filling_mode(self):
        ea = compact("TV26_FiveTF_Arabic_CANDIDATE.mq5")
        self.assertIn('req.type_filling=FillMode();req.comment="TV26closeopposite";', ea)
        self.assertIn("ENUM_ORDER_TYPE_FILLINGFillMode()", ea)
        self.assertNotIn('req.type_filling=ORDER_FILLING_IOC;req.comment="TV26closeopposite";', ea)

    def test_all_five_timeframes_use_confirmed_closed_bars_and_timestamp_shift(self):
        pine = compact("TradingView_Parity_AllTF_Export.pine")
        self.assertEqual(pine.count("request.security(syminfo.tickerid"), 5)
        self.assertEqual(pine.count("lookahead=barmerge.lookahead_on"), 5)
        self.assertIn("[packedVotes[1],libTotal[1],libMA[1],libOsc[1],", pine)
        self.assertIn("time[1],open[1],high[1],low[1],close[1]", pine)
        for tf in ("1", "5", "15", "30", "60"):
            self.assertIn(f'syminfo.tickerid,"{tf}"', pine)

    def test_exporter_keeps_independent_formula_aggregates_against_library_outputs(self):
        pine = compact("TradingView_Parity_AllTF_Export.pine")
        self.assertIn("[libTotal,libOsc,libMA]=tvRating.calcRatingAll()", pine)
        self.assertIn("floatratingMA=array.avg(maRatings)", pine)
        self.assertIn("floatratingOther=array.avg(oscRatings)", pine)
        self.assertIn("notna(ratingMA)andnotna(ratingOther)=>total/2", pine)
        self.assertIn("notna(ratingMA)ornotna(ratingOther)=>total", pine)


if __name__ == "__main__":
    unittest.main()
