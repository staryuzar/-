//+------------------------------------------------------------------+
//| Mirsad BTC — Execution Bridge Expert Advisor                     |
//| Engine 5 transport endpoint: command in, telemetry/ACK out.       |
//| All signal/risk calculations remain in Mirsad Engine 4.           |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "Mirsad BTC command-driven MT5 execution and telemetry bridge"

input string InpBrokerSymbol       = "";          // Empty = chart symbol
input string InpMarketSymbol       = "BTCUSDT";   // Engine 5 broker-to-Mirsad symbol mapping
input int    InpTimerSeconds       = 1;
input ulong  InpMagicNumber        = 26110201;
input int    InpDeviationPoints    = 20;
input int    InpHistoryDays         = 90;          // Bounded broker deal history window
input int    InpHistoryDealLimit    = 1000;         // Maximum recent Mirsad deals retained after filtering
input int    InpDealHistoryRefreshSeconds = 60;     // Full history scan interval; heartbeat remains one second
input bool   InpAllowExecution     = true;         // User-requested default: command-driven trading enabled

string g_broker_symbol = "";
bool   g_processing = false;
ulong  g_next_deal_history_refresh_at_ms = 0;
string g_cached_deal_history_json = "";

string CommonPath(const string name)
{
   return "MirsadBTC\\" + name;
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "");
   StringReplace(value, "\n", " ");
   return value;
}

string JsonGet(const string json, const string key)
{
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";

   pos = StringFind(json, ":", pos + StringLen(search));
   if(pos < 0) return "";
   pos++;

   int length = StringLen(json);
   while(pos < length)
   {
      ushort ch = StringGetCharacter(json, pos);
      if(ch != 32 && ch != 9 && ch != 10 && ch != 13) break;
      pos++;
   }
   if(pos >= length) return "";

   ushort first = StringGetCharacter(json, pos);
   if(first == 34)
   {
      pos++;
      int start = pos;
      bool escaped = false;
      while(pos < length)
      {
         ushort ch = StringGetCharacter(json, pos);
         if(ch == 34 && !escaped) break;
         if(ch == 92 && !escaped) escaped = true;
         else escaped = false;
         pos++;
      }
      if(pos >= length) return "";
      string value = StringSubstr(json, start, pos - start);
      StringReplace(value, "\\\"", "\"");
      StringReplace(value, "\\\\", "\\");
      return value;
   }

   int start = pos;
   while(pos < length)
   {
      ushort ch = StringGetCharacter(json, pos);
      if(ch == 44 || ch == 125 || ch == 93 || ch == 32 || ch == 9 || ch == 10 || ch == 13) break;
      pos++;
   }
   if(pos <= start) return "";
   return StringSubstr(json, start, pos - start);
}

double JsonNumber(const string json, const string key)
{
   string value = JsonGet(json, key);
   if(value == "") return 0.0;
   return StringToDouble(value);
}

long JsonLong(const string json, const string key)
{
   string value = JsonGet(json, key);
   if(value == "") return 0;
   return (long)StringToInteger(value);
}

bool WriteCommonText(const string file_name, const string data)
{
   // Stage the complete snapshot at a sibling path. Readers continue to see
   // the previous valid JSON until FileMove publishes the flushed replacement.
   string temporary_name = file_name + ".tmp";
   int handle = FileOpen(CommonPath(temporary_name),
                         FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON,
                         0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("Mirsad: cannot open Common Files/%s for staged write. Error=%d",
                  temporary_name, GetLastError());
      return false;
   }

   uint written = FileWriteString(handle, data);
   FileFlush(handle);
   FileClose(handle);
   if(written == 0 && StringLen(data) > 0)
   {
      PrintFormat("Mirsad: staged write produced no bytes for %s.", file_name);
      return false;
   }

   // Never fall back to truncating the published file. If a reader briefly
   // holds the destination, retry the atomic replacement with bounded backoff.
   for(int attempt = 0; attempt < 6; attempt++)
   {
      ResetLastError();
      if(FileMove(CommonPath(temporary_name), FILE_COMMON,
                  CommonPath(file_name), FILE_COMMON | FILE_REWRITE))
         return true;

      int error_code = GetLastError();
      PrintFormat("Mirsad: atomic publish retry %d for %s failed. Error=%d",
                  attempt + 1, file_name, error_code);
      if(attempt < 5)
         Sleep(15 * (attempt + 1));
   }

   PrintFormat("Mirsad: atomic publish failed for %s; previous snapshot was preserved.",
               file_name);
   return false;
}

string ReadCommonText(const string file_name)
{
   int handle = FileOpen(CommonPath(file_name),
                         FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON,
                         0, CP_UTF8);
   if(handle == INVALID_HANDLE) return "";
   string data = FileReadString(handle);
   FileClose(handle);
   return data;
}

string ReadLastCommandId()
{
   return ReadCommonText("last_command_id.txt");
}

bool WasCommandSeen(const string command_id)
{
   int handle = FileOpen(CommonPath("command_ledger.txt"),
                         FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON,
                         0, CP_UTF8);
   if(handle != INVALID_HANDLE)
   {
      while(!FileIsEnding(handle))
      {
         string stored_id = FileReadString(handle);
         if(stored_id == command_id)
         {
            FileClose(handle);
            return true;
         }
      }
      FileClose(handle);
   }

   // Backward compatibility with an ID persisted by earlier EA versions.
   return (ReadLastCommandId() == command_id);
}

bool SaveLastCommandId(const string command_id)
{
   int handle = FileOpen(CommonPath("command_ledger.txt"),
                         FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON,
                         0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("Mirsad: cannot open command ledger. Error=%d", GetLastError());
      return false;
   }
   if(!FileSeek(handle, 0, SEEK_END))
   {
      FileClose(handle);
      PrintFormat("Mirsad: cannot seek command ledger. Error=%d", GetLastError());
      return false;
   }
   uint written = FileWriteString(handle, command_id + "\r\n");
   FileFlush(handle);
   FileClose(handle);
   if(written == 0)
   {
      PrintFormat("Mirsad: command ledger write failed for %s.", command_id);
      return false;
   }

   // Verify the durable ledger entry before allowing OrderSend. A restart
   // or uncertain disk write must fail closed rather than risk a duplicate.
   if(!WasCommandSeen(command_id))
   {
      PrintFormat("Mirsad: command ledger read-back failed for %s.", command_id);
      return false;
   }

   // Keep the compatibility marker too; a failed marker write blocks send.
   if(!WriteCommonText("last_command_id.txt", command_id))
   {
      PrintFormat("Mirsad: last command marker write failed for %s.", command_id);
      return false;
   }
   return true;
}

long NowUtcMs()
{
   return (long)TimeGMT() * 1000;
}

bool AreTradePermissionsAvailable()
{
   return (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
          && (bool)MQLInfoInteger(MQL_TRADE_ALLOWED)
          && (bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
          && (bool)AccountInfoInteger(ACCOUNT_TRADE_EXPERT);
}

bool IsExecutionEnabled()
{
   return InpAllowExecution && AreTradePermissionsAvailable();
}

bool IsSupportedAccountMarginMode(const long margin_mode)
{
   return margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_NETTING
          || margin_mode == ACCOUNT_MARGIN_MODE_EXCHANGE
          || margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING;
}

bool HasOpenNettingSymbolExposure(const string symbol)
{
   long margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      return false;
   if(margin_mode != ACCOUNT_MARGIN_MODE_RETAIL_NETTING
      && margin_mode != ACCOUNT_MARGIN_MODE_EXCHANGE)
      return true; // Unknown accounting mode: fail closed.

   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) return true;
      if(PositionGetString(POSITION_SYMBOL) == symbol)
         return true;
   }

   for(int i = 0; i < OrdersTotal(); i++)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) return true;
      if(OrderGetString(ORDER_SYMBOL) == symbol)
         return true;
   }
   return false;
}

bool PositionHistoryIsMirsadOwned(const ulong ticket)
{
   if(!PositionSelectByTicket(ticket))
      return false;
   if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
      return false;

   long margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      return true;
   if(margin_mode != ACCOUNT_MARGIN_MODE_RETAIL_NETTING
      && margin_mode != ACCOUNT_MARGIN_MODE_EXCHANGE)
      return false;

   long position_identifier = PositionGetInteger(POSITION_IDENTIFIER);
   if(position_identifier <= 0
      || !HistorySelectByPosition((ulong)position_identifier))
      return false;

   int deals_total = HistoryDealsTotal();
   if(deals_total <= 0)
      return false;
   for(int i = 0; i < deals_total; i++)
   {
      ulong deal_ticket = HistoryDealGetTicket(i);
      if(deal_ticket == 0)
         return false;
      long deal_magic = HistoryDealGetInteger(deal_ticket, DEAL_MAGIC);
      string deal_symbol = HistoryDealGetString(deal_ticket, DEAL_SYMBOL);
      if((ulong)deal_magic != InpMagicNumber || deal_symbol != g_broker_symbol)
         return false;
   }
   return true;
}

string NumberJson(const double value, const int digits = 10)
{
   return DoubleToString(value, digits);
}

string BuildPositionsJson()
{
   string output = "[";
   bool first = true;

   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      long type = PositionGetInteger(POSITION_TYPE);
      double volume = PositionGetDouble(POSITION_VOLUME);
      double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      double profit = PositionGetDouble(POSITION_PROFIT);
      long position_magic = PositionGetInteger(POSITION_MAGIC);
      long position_id = PositionGetInteger(POSITION_IDENTIFIER);
      string currency = AccountInfoString(ACCOUNT_CURRENCY);

      if(!first) output += ",";
      first = false;
      output += StringFormat(
         "{\"ticket\":%I64u,\"position_id\":%I64d,\"symbol\":\"%s\",\"type\":%d,\"magic\":%I64d,\"volume\":%s,"
         "\"price_open\":%s,\"stop_loss\":%s,\"take_profit\":%s,"
         "\"profit\":%s,\"profit_currency\":\"%s\"}",
         ticket, position_id, JsonEscape(symbol), (int)type, position_magic,
         NumberJson(volume, 8), NumberJson(open_price, 10),
         NumberJson(sl, 10), NumberJson(tp, 10),
         NumberJson(profit, 2), JsonEscape(currency)
      );
   }

   output += "]";
   return output;
}

string BuildDealHistoryJson()
{
   datetime to_server = TimeTradeServer();
   if(to_server <= 0)
      to_server = TimeCurrent();
   datetime from_server = to_server - (datetime)(InpHistoryDays * 86400);
   long server_utc_offset_seconds = (long)to_server - (long)TimeGMT();
   long queried_at_utc_ms = NowUtcMs();

   ResetLastError();
   if(!HistorySelect(from_server, to_server))
   {
      int history_error = GetLastError();
      return StringFormat(
         "{\"schema\":\"MIR1-DEALS-1\",\"status\":\"UNAVAILABLE\","
         "\"queried_at_utc_ms\":%I64d,\"history_error\":%d,\"deals\":[]}",
         queried_at_utc_ms, history_error
      );
   }

   int total_selected = HistoryDealsTotal();
   int max_retained = InpHistoryDealLimit;
   if(max_retained < 1)
      max_retained = 1000;

   // Filter by Mirsad magic and broker symbol before applying the output cap.
   // A busy account must not hide older Mirsad deals behind unrelated manual
   // trades or other Expert Advisors.
   string retained_deals[];
   int retained_source_indices[];
   if(ArrayResize(retained_deals, max_retained) != max_retained ||
      ArrayResize(retained_source_indices, max_retained) != max_retained)
   {
      return StringFormat(
         "{\"schema\":\"MIR1-DEALS-1\",\"status\":\"UNAVAILABLE\","
         "\"queried_at_utc_ms\":%I64d,\"history_error\":%d,\"deals\":[]}",
         queried_at_utc_ms, GetLastError()
      );
   }

   int retained_count = 0;
   int matching_total = 0;
   int next_write = 0;

   for(int index = 0; index < total_selected; index++)
   {
      ulong deal_ticket = HistoryDealGetTicket(index);
      if(deal_ticket == 0)
         continue;

      long deal_magic = HistoryDealGetInteger(deal_ticket, DEAL_MAGIC);
      string deal_symbol = HistoryDealGetString(deal_ticket, DEAL_SYMBOL);
      if((ulong)deal_magic != InpMagicNumber || deal_symbol != g_broker_symbol)
         continue;

      long deal_time_server_ms = HistoryDealGetInteger(deal_ticket, DEAL_TIME_MSC);
      long deal_order = HistoryDealGetInteger(deal_ticket, DEAL_ORDER);
      long position_id = HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID);
      long deal_type = HistoryDealGetInteger(deal_ticket, DEAL_TYPE);
      long deal_entry = HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);
      long deal_reason = HistoryDealGetInteger(deal_ticket, DEAL_REASON);
      double deal_volume = HistoryDealGetDouble(deal_ticket, DEAL_VOLUME);
      double deal_price = HistoryDealGetDouble(deal_ticket, DEAL_PRICE);
      double deal_profit = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT);
      double deal_commission = HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION);
      double deal_swap = HistoryDealGetDouble(deal_ticket, DEAL_SWAP);
      double deal_fee = HistoryDealGetDouble(deal_ticket, DEAL_FEE);
      double net_cashflow = deal_profit + deal_commission + deal_swap + deal_fee;
      string deal_comment = HistoryDealGetString(deal_ticket, DEAL_COMMENT);

      if(deal_time_server_ms <= 0 ||
         !MathIsValidNumber(deal_volume) || deal_volume < 0.0 ||
         !MathIsValidNumber(deal_price) || deal_price < 0.0 ||
         !MathIsValidNumber(net_cashflow))
         continue;

      string deal_json = StringFormat(
         "{\"deal_ticket\":%I64u,\"order_ticket\":%I64d,\"position_id\":%I64d,"
         "\"magic\":%I64d,\"symbol\":\"%s\",\"type\":%I64d,\"entry\":%I64d,"
         "\"reason\":%I64d,\"time_server_ms\":%I64d,\"volume\":%s,\"price\":%s,"
         "\"profit\":%s,\"commission\":%s,\"swap\":%s,\"fee\":%s,"
         "\"net_cashflow\":%s,\"currency\":\"%s\",\"comment\":\"%s\"}",
         deal_ticket, deal_order, position_id, deal_magic, JsonEscape(deal_symbol),
         deal_type, deal_entry, deal_reason, deal_time_server_ms,
         NumberJson(deal_volume, 8), NumberJson(deal_price, 10),
         NumberJson(deal_profit, 2), NumberJson(deal_commission, 2),
         NumberJson(deal_swap, 2), NumberJson(deal_fee, 2),
         NumberJson(net_cashflow, 2), JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)),
         JsonEscape(deal_comment)
      );

      int slot = 0;
      if(retained_count < max_retained)
      {
         slot = retained_count;
         retained_count++;
      }
      else
      {
         slot = next_write;
         next_write = (next_write + 1) % max_retained;
      }
      retained_deals[slot] = deal_json;
      retained_source_indices[slot] = index;
      matching_total++;
   }

   // The circular buffer holds the newest Mirsad-owned deals in chronological
   // order. truncated now describes Mirsad's own matching history, not all
   // trading activity on the broker account.
   int oldest_slot = (matching_total > retained_count ? next_write : 0);
   int history_start_index = (retained_count > 0 ? retained_source_indices[oldest_slot] : 0);
   string deals = "[";
   bool first = true;
   for(int offset = 0; offset < retained_count; offset++)
   {
      int slot = (oldest_slot + offset) % retained_count;
      if(!first)
         deals += ",";
      deals += retained_deals[slot];
      first = false;
   }
   deals += "]";

   return StringFormat(
      "{\"schema\":\"MIR1-DEALS-1\",\"status\":\"READY\","
      "\"queried_at_utc_ms\":%I64d,\"window_start_server_ms\":%I64d,"
      "\"window_end_server_ms\":%I64d,\"server_utc_offset_seconds_at_query\":%I64d,"
      "\"history_total_selected\":%d,\"history_matching_total\":%d,"
      "\"history_start_index\":%d,\"returned_count\":%d,"
      "\"truncated\":%s,\"symbol\":\"%s\",\"magic\":%I64u,"
      "\"currency\":\"%s\",\"time_basis\":\"MT5_SERVER_TIME\","
      "\"deals\":%s}",
      queried_at_utc_ms,
      (long)from_server * 1000,
      (long)to_server * 1000,
      server_utc_offset_seconds,
      total_selected, matching_total, history_start_index, retained_count,
      (matching_total > retained_count ? "true" : "false"),
      JsonEscape(g_broker_symbol), InpMagicNumber,
      JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)), deals
   );
}

void PublishTelemetry()
{
   MqlTick tick;
   bool has_tick = SymbolInfoTick(g_broker_symbol, tick);
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);

   double bid = has_tick ? tick.bid : 0.0;
   double ask = has_tick ? tick.ask : 0.0;
   long broker_time_msc = has_tick ? (long)tick.time_msc : 0;
   long tick_age_seconds = 2147483647;
   if(has_tick)
   {
      tick_age_seconds = (long)TimeTradeServer() - (long)tick.time;
      if(tick_age_seconds < 0) tick_age_seconds = 0;
   }

   double tick_size = SymbolInfoDouble(g_broker_symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value_loss = SymbolInfoDouble(g_broker_symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   double volume_min = SymbolInfoDouble(g_broker_symbol, SYMBOL_VOLUME_MIN);
   double volume_step = SymbolInfoDouble(g_broker_symbol, SYMBOL_VOLUME_STEP);
   double volume_max = SymbolInfoDouble(g_broker_symbol, SYMBOL_VOLUME_MAX);
   double point = SymbolInfoDouble(g_broker_symbol, SYMBOL_POINT);
   double contract_size = SymbolInfoDouble(g_broker_symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   long digits = SymbolInfoInteger(g_broker_symbol, SYMBOL_DIGITS);
   long trade_mode = SymbolInfoInteger(g_broker_symbol, SYMBOL_TRADE_MODE);

   long account_margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   string account = StringFormat(
      "\"account\":{\"login\":%I64d,\"server\":\"%s\",\"currency\":\"%s\","
      "\"margin_mode\":%I64d,\"hedging_mode\":%s,"
      "\"balance\":%s,\"equity\":%s,\"free_margin\":%s}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      JsonEscape(AccountInfoString(ACCOUNT_SERVER)),
      JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)),
      account_margin_mode,
      account_margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ? "true" : "false",
      NumberJson(AccountInfoDouble(ACCOUNT_BALANCE), 2),
      NumberJson(AccountInfoDouble(ACCOUNT_EQUITY), 2),
      NumberJson(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2)
   );

   string quote = StringFormat(
      "\"quote\":{\"bid\":%s,\"ask\":%s,\"time_ms\":%I64d,"
      "\"broker_time_msc\":%I64d,\"tick_age_seconds\":%I64d}",
      NumberJson(bid, 10), NumberJson(ask, 10), NowUtcMs(),
      broker_time_msc, tick_age_seconds
   );

   string spec = StringFormat(
      "\"symbol_spec\":{\"tick_size\":%s,\"tick_value_loss\":%s,"
      "\"volume_min\":%s,\"volume_step\":%s,\"volume_max\":%s,"
      "\"digits\":%I64d,\"point\":%s,\"contract_size\":%s,\"trade_mode\":%I64d,"
      "\"stops_level_points\":%I64d,\"freeze_level_points\":%I64d,"
      "\"filling_mode\":%I64d,\"execution_mode\":%I64d}",
      NumberJson(tick_size, 10), NumberJson(tick_value_loss, 10),
      NumberJson(volume_min, 8), NumberJson(volume_step, 8),
      NumberJson(volume_max, 8), digits, NumberJson(point, 10),
      NumberJson(contract_size, 4), trade_mode,
      SymbolInfoInteger(g_broker_symbol, SYMBOL_TRADE_STOPS_LEVEL),
      SymbolInfoInteger(g_broker_symbol, SYMBOL_TRADE_FREEZE_LEVEL),
      SymbolInfoInteger(g_broker_symbol, SYMBOL_FILLING_MODE),
      SymbolInfoInteger(g_broker_symbol, SYMBOL_TRADE_EXEMODE)
   );

   string payload = StringFormat(
      "{\"schema\":\"MIR1\",\"terminal_connected\":%s,\"execution_enabled\":%s,\"execution_input_enabled\":%s,\"trade_permissions_available\":%s,\"heartbeat_at_ms\":%I64d,"
      "\"symbol\":\"%s\",\"market_symbol\":\"%s\",\"magic_number\":%I64u,%s,%s,%s,\"positions\":%s}",
      connected ? "true" : "false", IsExecutionEnabled() ? "true" : "false",
      InpAllowExecution ? "true" : "false", AreTradePermissionsAvailable() ? "true" : "false", NowUtcMs(),
      JsonEscape(g_broker_symbol), JsonEscape(InpMarketSymbol), InpMagicNumber,
      account, quote, spec, BuildPositionsJson()
   );

   WriteCommonText("status.json", payload);
   WriteCommonText("positions.json", BuildPositionsJson());

   // The 1-second MIR1 heartbeat must stay light. HistorySelect scans the
   // broker's requested window, so refresh the filtered ledger separately.
   ulong deal_now_ms = GetTickCount64();
   if(g_cached_deal_history_json == "" ||
      deal_now_ms >= g_next_deal_history_refresh_at_ms)
   {
      g_cached_deal_history_json = BuildDealHistoryJson();
      int refresh_seconds = InpDealHistoryRefreshSeconds;
      if(StringFind(g_cached_deal_history_json, "\"status\":\"READY\"") < 0)
         refresh_seconds = 10;
      g_next_deal_history_refresh_at_ms = deal_now_ms + (ulong)refresh_seconds * 1000;
   }
   WriteCommonText("deals.json", g_cached_deal_history_json);
}

void PublishAck(const string command_id, const string state,
                const uint retcode, const ulong order_ticket,
                const ulong deal_ticket, const double filled_volume,
                const double filled_price, const string message)
{
   string payload = StringFormat(
      "{\"schema\":\"MIR1\",\"command_id\":\"%s\",\"state\":\"%s\","
      "\"retcode\":%u,\"order_ticket\":%I64u,\"deal_ticket\":%I64u,"
      "\"filled_volume\":%s,\"filled_price\":%s,\"message\":\"%s\","
      "\"ack_at_ms\":%I64d}",
      JsonEscape(command_id), state, retcode, order_ticket, deal_ticket,
      NumberJson(filled_volume, 8), NumberJson(filled_price, 10),
      JsonEscape(message), NowUtcMs()
   );
   WriteCommonText("ack.json", payload);
   PrintFormat("Mirsad ACK: id=%s state=%s retcode=%u order=%I64u deal=%I64u",
               command_id, state, retcode, order_ticket, deal_ticket);
}

bool IsVolumeOnBrokerStep(const string symbol, const double volume)
{
   double vmin = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(vmin <= 0.0 || vmax < vmin || step <= 0.0) return false;
   if(volume < vmin - 1e-9 || volume > vmax + 1e-9) return false;
   double steps = (volume - vmin) / step;
   return (MathAbs(steps - MathRound(steps)) <= 1e-6);
}

bool ResolveBrokerFillingMode(const string symbol, ENUM_ORDER_TYPE_FILLING &mode)
{
   long modes = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   long execution = SymbolInfoInteger(symbol, SYMBOL_TRADE_EXEMODE);
   if((modes & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
   {
      mode = ORDER_FILLING_IOC;
      return true;
   }
   if((modes & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
   {
      mode = ORDER_FILLING_FOK;
      return true;
   }
   if(execution != SYMBOL_TRADE_EXECUTION_MARKET)
   {
      mode = ORDER_FILLING_RETURN;
      return true;
   }
   return false;
}

void RejectAndRemember(const string command_id, const string reason,
                       const uint retcode = 0)
{
   SaveLastCommandId(command_id);
   PublishAck(command_id, "REJECTED", retcode, 0, 0, 0.0, 0.0, reason);
}

void ProcessCommand()
{
   if(g_processing) return;
   g_processing = true;

   string json = ReadCommonText("command.json");
   if(json == "")
   {
      g_processing = false;
      return;
   }

   string schema = JsonGet(json, "schema");
   string command_id = JsonGet(json, "command_id");
   if(schema != "MIR1" || command_id == "" ||
      StringLen(command_id) > 64)
   {
      g_processing = false;
      return;
   }

   string existing_ack = ReadCommonText("ack.json");
   string ack_id = JsonGet(existing_ack, "command_id");
   string ack_state = JsonGet(existing_ack, "state");
   if(ack_id == command_id &&
      (ack_state == "RECEIVED" || ack_state == "REJECTED" ||
       ack_state == "SUBMITTED" || ack_state == "PARTIAL" ||
       ack_state == "FILLED" || ack_state == "CANCELLED" ||
       ack_state == "EXPIRED" || ack_state == "UNKNOWN"))
   {
      g_processing = false;
      return;
   }

   if(WasCommandSeen(command_id))
   {
      PublishAck(command_id, "UNKNOWN", 0, 0, 0, 0.0, 0.0,
                 "This command ID exists in the persistent ledger. It will not be resent to avoid a duplicate trade.");
      g_processing = false;
      return;
   }

   if(!IsExecutionEnabled())
   {
      RejectAndRemember(command_id,
                        "Execution is disabled by the EA input or MT5 trading permissions; no broker request was sent.");
      g_processing = false;
      return;
   }

   long expires_at = JsonLong(json, "expires_at_ms");
   if(expires_at <= NowUtcMs())
   {
      SaveLastCommandId(command_id);
      PublishAck(command_id, "EXPIRED", 0, 0, 0, 0.0, 0.0,
                 "Command expiry time has passed. No order was sent.");
      g_processing = false;
      return;
   }

   string action = JsonGet(json, "action");
   string command_symbol = JsonGet(json, "symbol");
   string market_symbol = JsonGet(json, "market_symbol");
   double entry_reference = JsonNumber(json, "entry_reference");
   double volume = JsonNumber(json, "volume");
   double stop_loss = JsonNumber(json, "stop_loss");
   double take_profit = JsonNumber(json, "take_profit");

   if(action != "BUY" && action != "SELL" && action != "CLOSE" && action != "MODIFY")
   {
      RejectAndRemember(command_id, "Unsupported MIR1 action. Expected BUY, SELL, CLOSE or MODIFY.");
      g_processing = false;
      return;
   }

   long account_margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(!IsSupportedAccountMarginMode(account_margin_mode))
   {
      RejectAndRemember(command_id, "Unsupported/unknown MT5 account margin mode; no position may be opened or managed.");
      g_processing = false;
      return;
   }
   if((action == "BUY" || action == "SELL")
      && account_margin_mode != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
      && HasOpenNettingSymbolExposure(command_symbol))
   {
      RejectAndRemember(command_id, "Netting account already has an open position or pending order on this symbol; refusing to merge Mirsad exposure with another position.");
      g_processing = false;
      return;
   }

   if(command_symbol == "" || command_symbol != g_broker_symbol)
   {
      RejectAndRemember(command_id, "Command symbol does not match the configured broker symbol.");
      g_processing = false;
      return;
   }

   if(market_symbol == "" || market_symbol != InpMarketSymbol)
   {
      RejectAndRemember(command_id, "Market-symbol mapping does not match the EA input mapping.");
      g_processing = false;
      return;
   }

   if(!SymbolSelect(command_symbol, true))
   {
      RejectAndRemember(command_id, "Broker symbol could not be selected.");
      g_processing = false;
      return;
   }

   MqlTick tick;
   if(!SymbolInfoTick(command_symbol, tick) || tick.bid <= 0.0 || tick.ask < tick.bid)
   {
      RejectAndRemember(command_id, "No valid current broker quote is available.");
      g_processing = false;
      return;
   }

   ulong position_ticket = 0;
   ENUM_POSITION_TYPE existing_position_type = POSITION_TYPE_BUY;
   if(action == "CLOSE" || action == "MODIFY")
   {
      long ticket_value = JsonLong(json, "position_ticket");
      if(ticket_value <= 0)
      {
         RejectAndRemember(command_id, "CLOSE/MODIFY requires a positive position_ticket.");
         g_processing = false;
         return;
      }
      position_ticket = (ulong)ticket_value;
      if(!PositionSelectByTicket(position_ticket))
      {
         RejectAndRemember(command_id, "Position ticket is no longer open; no request was sent.");
         g_processing = false;
         return;
      }
      if(PositionGetString(POSITION_SYMBOL) != command_symbol)
      {
         RejectAndRemember(command_id, "Position symbol does not match the requested command symbol.");
         g_processing = false;
         return;
      }
      long position_magic = PositionGetInteger(POSITION_MAGIC);
      if((ulong)position_magic != InpMagicNumber)
      {
         RejectAndRemember(command_id, "CLOSE/MODIFY is restricted to positions owned by this Mirsad EA magic number.");
         g_processing = false;
         return;
      }
      if(!PositionHistoryIsMirsadOwned(position_ticket))
      {
         RejectAndRemember(command_id, "CLOSE/MODIFY is blocked because the account's position history is mixed, unavailable or not exclusively owned by Mirsad.");
         g_processing = false;
         return;
      }
      existing_position_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double current_volume = PositionGetDouble(POSITION_VOLUME);
      if(action == "CLOSE")
      {
         if(!MathIsValidNumber(volume) || volume <= 0.0 ||
            volume > current_volume + 1e-8 ||
            !IsVolumeOnBrokerStep(command_symbol, volume))
         {
            RejectAndRemember(command_id, "Close volume is invalid or exceeds the current position volume.");
            g_processing = false;
            return;
         }
      }
      else
      {
         double current_sl = PositionGetDouble(POSITION_SL);
         double current_tp = PositionGetDouble(POSITION_TP);
         double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
         double tick_size = SymbolInfoDouble(command_symbol, SYMBOL_TRADE_TICK_SIZE);
         double point_size = SymbolInfoDouble(command_symbol, SYMBOL_POINT);
         long stops_points = SymbolInfoInteger(command_symbol, SYMBOL_TRADE_STOPS_LEVEL);
         long freeze_points = SymbolInfoInteger(command_symbol, SYMBOL_TRADE_FREEZE_LEVEL);
         double minimum_distance = MathMax(stops_points, freeze_points) * point_size + tick_size;
         double price_tolerance = MathMax(tick_size * 0.5, point_size * 0.5);

         if(!MathIsValidNumber(stop_loss) || stop_loss <= 0.0 ||
            !MathIsValidNumber(take_profit) || take_profit < 0.0 ||
            tick_size <= 0.0 || point_size <= 0.0 ||
            !MathIsValidNumber(current_sl) || !MathIsValidNumber(current_tp) ||
            !MathIsValidNumber(open_price) || open_price <= 0.0)
         {
            RejectAndRemember(command_id, "MODIFY contains invalid protective prices or broker symbol specifications.");
            g_processing = false;
            return;
         }
         if(MathAbs(take_profit - current_tp) > price_tolerance)
         {
            RejectAndRemember(command_id, "MODIFY may not change the position's existing take-profit.");
            g_processing = false;
            return;
         }
         if(MathAbs(stop_loss / tick_size - MathRound(stop_loss / tick_size)) > 1e-6)
         {
            RejectAndRemember(command_id, "MODIFY stop-loss is not aligned to the broker tick size.");
            g_processing = false;
            return;
         }
         if(existing_position_type == POSITION_TYPE_BUY)
         {
            if(stop_loss < open_price - price_tolerance ||
               (current_sl > 0.0 && stop_loss <= current_sl + price_tolerance) ||
               stop_loss >= tick.bid || (tick.bid - stop_loss) < minimum_distance ||
               (take_profit > 0.0 && stop_loss >= take_profit))
            {
               RejectAndRemember(command_id, "BUY MODIFY must tighten at/above entry and remain outside broker stop/freeze distances.");
               g_processing = false;
               return;
            }
         }
         else
         {
            if(stop_loss > open_price + price_tolerance ||
               (current_sl > 0.0 && stop_loss >= current_sl - price_tolerance) ||
               stop_loss <= tick.ask || (stop_loss - tick.ask) < minimum_distance ||
               (take_profit > 0.0 && stop_loss <= take_profit))
            {
               RejectAndRemember(command_id, "SELL MODIFY must tighten at/below entry and remain outside broker stop/freeze distances.");
               g_processing = false;
               return;
            }
         }
      }
   }
   else
   {
      if(!MathIsValidNumber(entry_reference) || entry_reference <= 0.0 ||
         !MathIsValidNumber(volume) || volume <= 0.0 ||
         !MathIsValidNumber(stop_loss) || stop_loss <= 0.0 ||
         !MathIsValidNumber(take_profit) || take_profit <= 0.0)
      {
         RejectAndRemember(command_id, "OPEN command contains non-positive or non-finite execution fields.");
         g_processing = false;
         return;
      }
      if(!IsVolumeOnBrokerStep(command_symbol, volume))
      {
         RejectAndRemember(command_id, "Program volume does not meet the broker's declared min/max/step.");
         g_processing = false;
         return;
      }
      double minimum_stop_distance = SymbolInfoInteger(command_symbol, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(command_symbol, SYMBOL_POINT);
      if(action == "BUY" && (!(stop_loss < tick.ask && take_profit > tick.ask) ||
         (tick.ask-stop_loss) < minimum_stop_distance || (take_profit-tick.ask) < minimum_stop_distance))
      {
         RejectAndRemember(command_id, "BUY stop-loss/take-profit levels are inconsistent with current broker Ask.");
         g_processing = false;
         return;
      }
      if(action == "SELL" && (!(take_profit < tick.bid && stop_loss > tick.bid) ||
         (stop_loss-tick.bid) < minimum_stop_distance || (tick.bid-take_profit) < minimum_stop_distance))
      {
         RejectAndRemember(command_id, "SELL stop-loss/take-profit levels are inconsistent with current broker Bid.");
         g_processing = false;
         return;
      }
   }

   // Persist the ID before a request. If execution outcome is uncertain,
   // the EA will report UNKNOWN instead of resubmitting the same command.
   if(!SaveLastCommandId(command_id))
   {
      PublishAck(command_id, "REJECTED", 0, 0, 0, 0.0, 0.0,
                 "Could not persist the command ID; no broker request was sent.");
      g_processing = false;
      return;
   }
   PublishAck(command_id, "RECEIVED", 0, 0, 0, 0.0, 0.0,
              "Command accepted by MIR1 protocol. Preparing one broker request.");

   MqlTradeRequest request = {};
   MqlTradeCheckResult check = {};
   MqlTradeResult result = {};

   request.magic = InpMagicNumber;
   request.symbol = command_symbol;
   request.comment = command_id;
   if(action == "MODIFY")
   {
      request.action = TRADE_ACTION_SLTP;
      request.position = position_ticket;
      request.sl = stop_loss;
      request.tp = take_profit;
   }
   else
   {
      request.action = TRADE_ACTION_DEAL;
      request.volume = volume;
      request.deviation = (ulong)MathMax(0, InpDeviationPoints);
      if(!ResolveBrokerFillingMode(command_symbol, request.type_filling))
      {
         PublishAck(command_id, "REJECTED", 0, 0, 0, 0.0, 0.0,
                    "No broker-supported filling policy is available for this execution mode.");
         g_processing = false;
         return;
      }
      request.type_time = ORDER_TIME_GTC;
      if(action == "CLOSE")
      {
         request.position = position_ticket;
         request.type = (existing_position_type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         request.price = (existing_position_type == POSITION_TYPE_BUY) ? tick.bid : tick.ask;
         request.sl = 0.0;
         request.tp = 0.0;
      }
      else
      {
         request.type = (action == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
         request.price = entry_reference;
         request.sl = stop_loss;
         request.tp = take_profit;
      }
   }

   ResetLastError();
   bool checked = OrderCheck(request, check);
   if(!checked || check.retcode != 0)
   {
      int error_code = GetLastError();
      PublishAck(command_id, "REJECTED", check.retcode, 0, 0, 0.0, 0.0,
                 StringFormat("MT5 OrderCheck failed. error=%d comment=%s",
                              error_code, check.comment));
      g_processing = false;
      return;
   }

   ResetLastError();
   bool sent = OrderSend(request, result);
   int send_error = GetLastError();

   string state = "UNKNOWN";
   if(result.retcode == TRADE_RETCODE_DONE)
      state = "FILLED";
   else if(result.retcode == TRADE_RETCODE_DONE_PARTIAL)
      state = "PARTIAL";
   else if(result.retcode == TRADE_RETCODE_PLACED)
      state = "SUBMITTED";
   // A lost trade-server connection makes the broker outcome ambiguous.
   // Keep the command UNKNOWN so a late OnTradeTransaction can confirm it;
   // never tell the bridge that the order definitely failed.
   else if(result.retcode == TRADE_RETCODE_CONNECTION)
      state = "UNKNOWN";
   else if(!sent || result.retcode != 0)
      state = "REJECTED";

   string message = StringFormat(
      "OrderSend bool=%s, retcode=%u, external=%d, error=%d, comment=%s",
      sent ? "true" : "false", result.retcode,
      result.retcode_external, send_error, result.comment
   );

   PublishAck(command_id, state, result.retcode, result.order, result.deal,
              result.volume, result.price, message);
   g_processing = false;
}

int OnInit()
{
   if(InpTimerSeconds < 1 || InpTimerSeconds > 60)
      return INIT_PARAMETERS_INCORRECT;
   if(InpHistoryDays < 1 || InpHistoryDays > 365 ||
      InpHistoryDealLimit < 100 || InpHistoryDealLimit > 5000 ||
      InpDealHistoryRefreshSeconds < 10 || InpDealHistoryRefreshSeconds > 3600)
      return INIT_PARAMETERS_INCORRECT;
   if(InpMarketSymbol == "")
      return INIT_PARAMETERS_INCORRECT;

   g_broker_symbol = (InpBrokerSymbol == "") ? _Symbol : InpBrokerSymbol;
   if(g_broker_symbol == "")
      return INIT_FAILED;

   FolderCreate("MirsadBTC", FILE_COMMON);

   if(!SymbolSelect(g_broker_symbol, true))
      PrintFormat("Mirsad: broker symbol %s was not selected yet. Waiting for terminal quote feed.",
                  g_broker_symbol);

   EventSetTimer(InpTimerSeconds);
   PrintFormat("Mirsad BTC Execution Bridge started. Broker symbol=%s, market symbol=%s, execution_enabled=%s. "
               "Commands are accepted only from MIR1; no autonomous signals.",
               g_broker_symbol, InpMarketSymbol, IsExecutionEnabled() ? "true" : "false");

   PublishTelemetry();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   PrintFormat("Mirsad BTC Execution Bridge stopped. reason=%d", reason);
}

void OnTimer()
{
   PublishTelemetry();
   ProcessCommand();
}

void OnTick()
{
   // Execution is command-driven from Engine 4; ticks never create a trade signal.
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_REQUEST) return;
   if(request.magic != InpMagicNumber) return;

   string ack = ReadCommonText("ack.json");
   string ack_id = JsonGet(ack, "command_id");
   if(ack_id == "" || StringFind(request.comment, ack_id) < 0) return;

   string current_state = JsonGet(ack, "state");
   if(current_state == "FILLED" || current_state == "PARTIAL" ||
      current_state == "REJECTED")
      return;

   string state = "UNKNOWN";
   if(result.retcode == TRADE_RETCODE_DONE) state = "FILLED";
   else if(result.retcode == TRADE_RETCODE_DONE_PARTIAL) state = "PARTIAL";
   else if(result.retcode == TRADE_RETCODE_PLACED) state = "SUBMITTED";
   else if(result.retcode == TRADE_RETCODE_CONNECTION) state = "UNKNOWN";
   else if(result.retcode != 0) state = "REJECTED";

   PublishAck(ack_id, state, result.retcode, result.order, result.deal,
              result.volume, result.price, result.comment);
}
