from pathlib import Path
import re
import unittest


class HeadwayEAContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_path = (
            Path(__file__).resolve().parents[1]
            / "mql5" / "BitcoinIntelligenceLabEA.mq5"
        )
        cls.source = cls.source_path.read_text(encoding="utf-8")

    def test_ea_is_self_contained_and_does_not_depend_on_trade_mqh(self):
        self.assertNotIn("#include <Trade/Trade.mqh>", self.source)
        self.assertIn("MqlTradeRequest request", self.source)
        self.assertIn("OrderSend(request,result)", self.source)
        self.assertNotIn("CTrade trade", self.source)

    def test_headway_broker_is_mandatory_without_account_mode_gate(self):
        self.assertIn('StringFind(server, "headway")', self.source)
        self.assertIn('StringFind(server, "trade-hw.online")', self.source)
        self.assertNotIn("RequireHeadwayServer", self.source)
        self.assertNotIn("ACCOUNT_TRADE_MODE", self.source)
        self.assertNotIn("demo", self.source.lower())

    def test_daily_loss_readout_is_published_in_ea_status_line(self):
        self.assertIn("CurrentDailyDrawdownPercent(),MaxDailyLossPercent", self.source)
        self.assertIn("double CurrentDailyDrawdownPercent()", self.source)
        self.assertIn("daily equity loss limit reached; new entries paused", self.source)

    def test_default_position_and_equity_risk_limits_are_conservative(self):
        self.assertIn("input double MaxRiskPercent = 0.50;", self.source)
        self.assertIn("input int    MaxOpenPositions = 1;", self.source)

    def test_headway_server_identity_is_published_without_account_classification(self):
        self.assertIn("string accountServer=AccountInfoString(ACCOUNT_SERVER)", self.source)
        self.assertIn("accountServer,CurrentDailyDrawdownPercent(),MaxDailyLossPercent,", self.source)
        self.assertIn("equity,tickSize,tickValueLoss,volumeMin,volumeStep,volumeMax);", self.source)
        self.assertNotIn("ACCOUNT_TRADE_MODE", self.source)
        self.assertIn('"TRADE_READY":"TRADE_BLOCKED"', self.source)

    def test_open_is_blocked_when_foreign_position_exists_on_same_symbol(self):
        self.assertIn("bool HasForeignPositionsOnSymbol()", self.source)
        self.assertIn("HasForeignPositionsOnSymbol()", self.source)
        self.assertIn("another position exists on this symbol outside BTCIL MagicNumber", self.source)
        self.assertIn("POSITION_MAGIC)!=MagicNumber", self.source)

    def test_daily_equity_loss_cap_blocks_new_entries_only(self):
        self.assertIn("input double MaxDailyLossPercent = 2.00;", self.source)
        self.assertIn("bool DailyRiskAllowsNewEntry()", self.source)
        open_body = self.source.split("bool OpenBoardPosition(", 1)[1].split("void PollProgramCommand()", 1)[0]
        close_body = self.source.split("bool CloseOwnPosition(", 1)[1].split("bool OpenBoardPosition(", 1)[0]
        self.assertIn("DailyRiskAllowsNewEntry()", open_body)
        self.assertNotIn("DailyRiskAllowsNewEntry()", close_body)
        self.assertIn("MaxDailyLossPercent>10.0", self.source)
        self.assertIn("TimeTradeServer()", self.source)

    def test_single_ea_instance_lock_prevents_duplicate_chart_executors(self):
        self.assertIn("GlobalVariableSetOnCondition", self.source)
        self.assertIn("GlobalVariableDel", self.source)
        self.assertIn("InstanceLockName()", self.source)
        self.assertIn("another EA instance already owns this symbol/magic lock", self.source)

    def test_broker_results_are_matched_to_terminal_request_id(self):
        self.assertIn("pendingRequestId=result.request_id", self.source)
        self.assertIn("result.request_id==pendingRequestId", self.source)
        self.assertIn("pendingOrderTicket=result.order", self.source)

    def test_partial_fills_are_not_reported_as_full_execution(self):
        self.assertIn("OPEN_PARTIAL_FILL_CONFIRMED", self.source)
        self.assertIn("CLOSE_PARTIAL_FILL_CONFIRMED", self.source)
        self.assertIn("result.volume", self.source)
        self.assertIn("TRADE_TRANSACTION_REQUEST", self.source)
        self.assertIn("PollPendingOrderStatus()", self.source)
        self.assertIn("HistoryDealsTotal()", self.source)
        self.assertIn("ORDER_STATE_CANCELED", self.source)

    def test_ea_does_not_generate_independent_orders_on_tick(self):
        on_tick = self.source.split("void OnTick()", 1)[1]
        self.assertNotIn("OrderSend", on_tick)
        self.assertIn("centralized board is the only decision authority", on_tick)

    def test_deinitialization_requests_cancel_for_its_active_residual_order(self):
        self.assertIn("void OnDeinit(const int reason)", self.source)
        self.assertIn("cancelRequest.action=TRADE_ACTION_REMOVE", self.source)
        self.assertIn("cancelRequest.order=pendingOrderTicket", self.source)
        self.assertIn("ORDER_MAGIC)==MagicNumber", self.source)
        self.assertIn("CANCEL_REQUESTED", self.source)
        self.assertIn("CANCEL_NOT_CONFIRMED", self.source)

    def test_broker_fill_policy_is_not_guessed_when_market_execution_has_no_supported_mode(self):
        self.assertIn("bool PrepareTradeRequest(MqlTradeRequest &request)", self.source)
        self.assertIn("return false; // Market execution forbids RETURN", self.source)
        self.assertIn("if(!PrepareTradeRequest(request))", self.source)
        self.assertIn("request.type_filling=ORDER_FILLING_RETURN;", self.source)

    def test_status_record_ends_with_a_real_newline_and_no_account_mode_field(self):
        self.assertIn('|%s|%s|%I64d|%s|%.8f|%.8f|%d|%s|%.10f|%d|%s|%s|%.4f|%.4f|%.2f|%.10f|%.10f|%.8f|%.8f|%.8f\\n",', self.source)
        self.assertNotIn("ACCOUNT_TRADE_MODE", self.source)
        self.assertNotIn("accountMode", self.source)

    def test_broker_tick_value_and_lot_specs_are_exported_to_python(self):
        self.assertIn("SYMBOL_TRADE_TICK_SIZE", self.source)
        self.assertIn("SYMBOL_TRADE_TICK_VALUE_LOSS", self.source)
        self.assertIn("SYMBOL_VOLUME_MIN", self.source)
        self.assertIn("SYMBOL_VOLUME_STEP", self.source)
        self.assertIn("SYMBOL_VOLUME_MAX", self.source)
        self.assertIn("AccountInfoDouble(ACCOUNT_EQUITY)", self.source)
        self.assertIn("equity,tickSize,tickValueLoss,volumeMin,volumeStep,volumeMax", self.source)

    def test_supervisor_requires_headway_identity_but_not_demo_classification(self):
        supervisor_path = (
            Path(__file__).resolve().parents[1]
            / "scripts" / "BitcoinIntelligenceLabSupervisor.ps1"
        )
        supervisor = supervisor_path.read_text(encoding="utf-8")
        self.assertIn("trade-hw\\.online", supervisor)
        self.assertNotIn("not_headway_demo_server", supervisor)
        self.assertNotRegex(
            supervisor,
            r"\$gate\.server\s+-notmatch\s+['\"][^'\"]*demo",
        )

    def test_position_snapshot_is_staged_before_publication(self):
        writer = self.source.split("void WritePositions()", 1)[1].split("bool ValidVolume(", 1)[0]
        self.assertIn("positions.tsv.tmp", writer)
        self.assertIn("FileFlush(handle)", writer)
        self.assertIn("FileClose(handle)", writer)
        self.assertIn('FileMove(stagingPath,FILE_COMMON,BaseFolder()+"positions.tsv",FILE_COMMON|FILE_REWRITE)', writer)

    def test_trade_requests_bind_to_actual_headway_chart_symbol_and_magic(self):
        self.assertIn("request.symbol=_Symbol", self.source)
        self.assertIn("request.magic=MagicNumber", self.source)
        self.assertIn("request.position=ticket", self.source)
        self.assertIn("PositionGetString(POSITION_SYMBOL)!=_Symbol", self.source)


if __name__ == "__main__":
    unittest.main()
