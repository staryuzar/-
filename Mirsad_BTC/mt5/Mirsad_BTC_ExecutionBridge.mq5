//+------------------------------------------------------------------+
//| Mirsad BTC — Execution Bridge Expert Advisor                     |
//| Engine 3 transport endpoint: command in, telemetry/ACK out.       |
//| All signal/risk calculations remain in Mirsad Engine 4.           |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "Mirsad BTC command-driven MT5 execution and telemetry bridge"

input string InpBrokerSymbol       = "";          // Empty = chart symbol
input string InpMarketSymbol       = "BTCUSDT";   // Engine 1 market symbol mapping
input int    InpTimerSeconds       = 1;
input ulong  InpMagicNumber        = 26110201;
input int    InpDeviationPoints    = 20;

string g_broker_symbol = "";
bool   g_processing = false;

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
   int handle = FileOpen(CommonPath(file_name),
                         FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON,
                         0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("Mirsad: cannot open Common Files/%s for write. Error=%d",
                  file_name, GetLastError());
      return false;
   }
   FileWriteString(handle, data);
   FileFlush(handle);
   FileClose(handle);
   return true;
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

bool SaveLastCommandId(const string command_id)
{
   return WriteCommonText("last_command_id.txt", command_id);
}

long NowUtcMs()
{
   return (long)TimeGMT() * 1000;
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
      string currency = AccountInfoString(ACCOUNT_CURRENCY);

      if(!first) output += ",";
      first = false;
      output += StringFormat(
         "{\"ticket\":%I64u,\"symbol\":\"%s\",\"type\":%d,\"magic\":%I64d,\"volume\":%s,"
         "\"price_open\":%s,\"stop_loss\":%s,\"take_profit\":%s,"
         "\"profit\":%s,\"profit_currency\":\"%s\"}",
         ticket, JsonEscape(symbol), (int)type, position_magic,
         NumberJson(volume, 8), NumberJson(open_price, 10),
         NumberJson(sl, 10), NumberJson(tp, 10),
         NumberJson(profit, 2), JsonEscape(currency)
      );
   }

   output += "]";
   return output;
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

   string account = StringFormat(
      "\"account\":{\"login\":%I64d,\"server\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%s,\"equity\":%s,\"free_margin\":%s}",
      AccountInfoInteger(ACCOUNT_LOGIN),
      JsonEscape(AccountInfoString(ACCOUNT_SERVER)),
      JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)),
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
      "\"digits\":%I64d,\"point\":%s,\"contract_size\":%s,\"trade_mode\":%I64d}",
      NumberJson(tick_size, 10), NumberJson(tick_value_loss, 10),
      NumberJson(volume_min, 8), NumberJson(volume_step, 8),
      NumberJson(volume_max, 8), digits, NumberJson(point, 10),
      NumberJson(contract_size, 4), trade_mode
   );

   string payload = StringFormat(
      "{\"schema\":\"MIR1\",\"terminal_connected\":%s,\"heartbeat_at_ms\":%I64d,"
      "\"symbol\":\"%s\",\"market_symbol\":\"%s\",\"magic_number\":%I64u,%s,%s,%s,\"positions\":%s}",
      connected ? "true" : "false", NowUtcMs(),
      JsonEscape(g_broker_symbol), JsonEscape(InpMarketSymbol), InpMagicNumber,
      account, quote, spec, BuildPositionsJson()
   );

   WriteCommonText("status.json", payload);
   WriteCommonText("positions.json", BuildPositionsJson());
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

ENUM_ORDER_TYPE_FILLING BrokerFillingMode(const string symbol)
{
   long modes = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((modes & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      return ORDER_FILLING_IOC;
   if((modes & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      return ORDER_FILLING_FOK;
   return ORDER_FILLING_RETURN;
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

   string last_id = ReadLastCommandId();
   if(last_id == command_id)
   {
      PublishAck(command_id, "UNKNOWN", 0, 0, 0, 0.0, 0.0,
                 "This command ID was already seen. It will not be resent to avoid a duplicate trade.");
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

   if(action != "BUY" && action != "SELL" && action != "CLOSE")
   {
      RejectAndRemember(command_id, "Unsupported MIR1 action. Expected BUY, SELL or CLOSE.");
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
   if(action == "CLOSE")
   {
      long ticket_value = JsonLong(json, "position_ticket");
      if(ticket_value <= 0)
      {
         RejectAndRemember(command_id, "CLOSE requires a positive position_ticket.");
         g_processing = false;
         return;
      }
      position_ticket = (ulong)ticket_value;
      if(!PositionSelectByTicket(position_ticket))
      {
         RejectAndRemember(command_id, "Position ticket is no longer open; no close request was sent.");
         g_processing = false;
         return;
      }
      if(PositionGetString(POSITION_SYMBOL) != command_symbol)
      {
         RejectAndRemember(command_id, "Position symbol does not match the requested close symbol.");
         g_processing = false;
         return;
      }
      existing_position_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double current_volume = PositionGetDouble(POSITION_VOLUME);
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
      if(action == "BUY" && !(stop_loss < tick.ask && take_profit > tick.ask))
      {
         RejectAndRemember(command_id, "BUY stop-loss/take-profit levels are inconsistent with current broker Ask.");
         g_processing = false;
         return;
      }
      if(action == "SELL" && !(take_profit < tick.bid && stop_loss > tick.bid))
      {
         RejectAndRemember(command_id, "SELL stop-loss/take-profit levels are inconsistent with current broker Bid.");
         g_processing = false;
         return;
      }
   }

   // Persist the ID before a request. If execution outcome is uncertain,
   // the EA will report UNKNOWN instead of resubmitting the same command.
   SaveLastCommandId(command_id);
   PublishAck(command_id, "RECEIVED", 0, 0, 0, 0.0, 0.0,
              "Command accepted by MIR1 protocol. Preparing one broker request.");

   MqlTradeRequest request = {};
   MqlTradeCheckResult check = {};
   MqlTradeResult result = {};

   request.action = TRADE_ACTION_DEAL;
   request.magic = InpMagicNumber;
   request.symbol = command_symbol;
   request.volume = volume;
   request.deviation = (ulong)MathMax(0, InpDeviationPoints);
   request.type_filling = BrokerFillingMode(command_symbol);
   request.type_time = ORDER_TIME_GTC;
   request.comment = command_id;

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

   ResetLastError();
   if(!OrderCheck(request, check))
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
   PrintFormat("Mirsad BTC Execution Bridge started. Broker symbol=%s, market symbol=%s. "
               "Commands are accepted only from MIR1; no autonomous signals.",
               g_broker_symbol, InpMarketSymbol);

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
   else if(result.retcode != 0) state = "REJECTED";

   PublishAck(ack_id, state, result.retcode, result.order, result.deal,
              result.volume, result.price, result.comment);
}
