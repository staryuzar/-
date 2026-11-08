//+------------------------------------------------------------------+
//| Mirsad MT5 Native Feed — read-only OHLC and market publisher     |
//| Publishes market quotes, native MqlRates and CopyBuffer values.   |
//| No image processing or trading functions.                        |
//+------------------------------------------------------------------+
#property strict
#property version   "1.005"
#property description "Mirsad read-only MT5 native OHLC and market data publisher"

input int  InpMarketSnapshotIntervalSeconds = 2; // MT5 market-feed cadence (1..30 seconds)
input string InpMarketSymbol = "BTCUSDT"; // Stable Mirsad symbol mapped to this broker symbol
input int  InpHistoryBars = 1000; // Deep native history for Engine 2 and Engine 3
input bool InpPublishNativeIndicators = true; // Publish native MT5 CopyBuffer values for Engine 3 validation
input bool InpPublishMarketDepth = true; // Publish broker market book when supported
input bool InpPublishEconomicCalendar = false; // Keep slow MT5 calendar calls off the time-critical quote/candle publisher; Engine 1 uses independent sources

string g_observer_root = "MirsadBTC\\observer";
long   g_chart_id = 0;
ulong  g_next_market_snapshot_at_ms = 0;
ulong  g_next_calendar_refresh_at_ms = 0;
string g_economic_calendar_json = "\"economic_calendar\":{\"status\":\"NOT_REQUESTED\",\"source\":\"MT5_ECONOMIC_CALENDAR\",\"currency\":\"USD\",\"events\":[]}";

#define MIRSAD_TIMEFRAME_COUNT 6
ENUM_TIMEFRAMES g_indicator_timeframes[MIRSAD_TIMEFRAME_COUNT] =
   {PERIOD_M1, PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4, PERIOD_D1};
string g_indicator_timeframe_names[MIRSAD_TIMEFRAME_COUNT] =
   {"1m", "5m", "15m", "1h", "4h", "1d"};

int g_h_ema20[MIRSAD_TIMEFRAME_COUNT];
int g_h_ema50[MIRSAD_TIMEFRAME_COUNT];
int g_h_rsi14[MIRSAD_TIMEFRAME_COUNT];
int g_h_atr14[MIRSAD_TIMEFRAME_COUNT];
int g_h_macd[MIRSAD_TIMEFRAME_COUNT];
int g_h_bands[MIRSAD_TIMEFRAME_COUNT];
int g_h_stochastic[MIRSAD_TIMEFRAME_COUNT];
int g_h_adx[MIRSAD_TIMEFRAME_COUNT];
int g_h_cci20[MIRSAD_TIMEFRAME_COUNT];
int g_h_mfi14[MIRSAD_TIMEFRAME_COUNT];
int g_h_momentum14[MIRSAD_TIMEFRAME_COUNT];
int g_h_wpr14[MIRSAD_TIMEFRAME_COUNT];
int g_h_obv[MIRSAD_TIMEFRAME_COUNT];
int g_h_osma[MIRSAD_TIMEFRAME_COUNT];
bool g_book_subscribed = false;

void ResetIndicatorHandles()
{
   ArrayInitialize(g_h_ema20, INVALID_HANDLE);
   ArrayInitialize(g_h_ema50, INVALID_HANDLE);
   ArrayInitialize(g_h_rsi14, INVALID_HANDLE);
   ArrayInitialize(g_h_atr14, INVALID_HANDLE);
   ArrayInitialize(g_h_macd, INVALID_HANDLE);
   ArrayInitialize(g_h_bands, INVALID_HANDLE);
   ArrayInitialize(g_h_stochastic, INVALID_HANDLE);
   ArrayInitialize(g_h_adx, INVALID_HANDLE);
   ArrayInitialize(g_h_cci20, INVALID_HANDLE);
   ArrayInitialize(g_h_mfi14, INVALID_HANDLE);
   ArrayInitialize(g_h_momentum14, INVALID_HANDLE);
   ArrayInitialize(g_h_wpr14, INVALID_HANDLE);
   ArrayInitialize(g_h_obv, INVALID_HANDLE);
   ArrayInitialize(g_h_osma, INVALID_HANDLE);
}

void InitializeIndicatorHandles(const string symbol)
{
   if(!InpPublishNativeIndicators)
      return;
   ResetIndicatorHandles();
   int warmup_bars = (InpHistoryBars > 100 ? InpHistoryBars : 100);
   for(int i = 0; i < MIRSAD_TIMEFRAME_COUNT; i++)
   {
      ENUM_TIMEFRAMES timeframe = g_indicator_timeframes[i];

      // Request each timeframe's history before creating indicator handles.
      // MT5 may load higher-timeframe history asynchronously; the publisher
      // reports WARMING_UP until BarsCalculated/CopyBuffer are actually ready.
      MqlRates warmup_rates[];
      ArraySetAsSeries(warmup_rates, false);
      ResetLastError();
      int warmup_copied = CopyRates(symbol, timeframe, 0, warmup_bars, warmup_rates);
      if(warmup_copied < 0)
         PrintFormat("Mirsad Observer: history warm-up pending for %s. Error=%d",
                     g_indicator_timeframe_names[i], GetLastError());

      g_h_ema20[i] = iMA(symbol, timeframe, 20, 0, MODE_EMA, PRICE_CLOSE);
      g_h_ema50[i] = iMA(symbol, timeframe, 50, 0, MODE_EMA, PRICE_CLOSE);
      g_h_rsi14[i] = iRSI(symbol, timeframe, 14, PRICE_CLOSE);
      g_h_atr14[i] = iATR(symbol, timeframe, 14);
      g_h_macd[i] = iMACD(symbol, timeframe, 12, 26, 9, PRICE_CLOSE);
      g_h_bands[i] = iBands(symbol, timeframe, 20, 0, 2.0, PRICE_CLOSE);
      g_h_stochastic[i] = iStochastic(symbol, timeframe, 5, 3, 3, MODE_SMA, STO_LOWHIGH);
      g_h_adx[i] = iADXWilder(symbol, timeframe, 14);
      g_h_cci20[i] = iCCI(symbol, timeframe, 20, PRICE_TYPICAL);
      g_h_mfi14[i] = iMFI(symbol, timeframe, 14, VOLUME_TICK);
      g_h_momentum14[i] = iMomentum(symbol, timeframe, 14, PRICE_CLOSE);
      g_h_wpr14[i] = iWPR(symbol, timeframe, 14);
      g_h_obv[i] = iOBV(symbol, timeframe, VOLUME_TICK);
      g_h_osma[i] = iOsMA(symbol, timeframe, 12, 26, 9, PRICE_CLOSE);
   }
}

void ReleaseIndicatorHandles()
{
   for(int i = 0; i < MIRSAD_TIMEFRAME_COUNT; i++)
   {
      if(g_h_ema20[i] != INVALID_HANDLE) IndicatorRelease(g_h_ema20[i]);
      if(g_h_ema50[i] != INVALID_HANDLE) IndicatorRelease(g_h_ema50[i]);
      if(g_h_rsi14[i] != INVALID_HANDLE) IndicatorRelease(g_h_rsi14[i]);
      if(g_h_atr14[i] != INVALID_HANDLE) IndicatorRelease(g_h_atr14[i]);
      if(g_h_macd[i] != INVALID_HANDLE) IndicatorRelease(g_h_macd[i]);
      if(g_h_bands[i] != INVALID_HANDLE) IndicatorRelease(g_h_bands[i]);
      if(g_h_stochastic[i] != INVALID_HANDLE) IndicatorRelease(g_h_stochastic[i]);
      if(g_h_adx[i] != INVALID_HANDLE) IndicatorRelease(g_h_adx[i]);
      if(g_h_cci20[i] != INVALID_HANDLE) IndicatorRelease(g_h_cci20[i]);
      if(g_h_mfi14[i] != INVALID_HANDLE) IndicatorRelease(g_h_mfi14[i]);
      if(g_h_momentum14[i] != INVALID_HANDLE) IndicatorRelease(g_h_momentum14[i]);
      if(g_h_wpr14[i] != INVALID_HANDLE) IndicatorRelease(g_h_wpr14[i]);
      if(g_h_obv[i] != INVALID_HANDLE) IndicatorRelease(g_h_obv[i]);
      if(g_h_osma[i] != INVALID_HANDLE) IndicatorRelease(g_h_osma[i]);
   }
}

string IndicatorPairJson(const int indicator_handle, const int buffer_index)
{
   if(indicator_handle == INVALID_HANDLE)
      return "{\"status\":\"UNAVAILABLE\",\"previous_closed\":null,\"closed\":null,\"current\":null,\"error_code\":-1,\"bars_calculated\":-1}";
   ResetLastError();
   int calculated = BarsCalculated(indicator_handle);
   int calculated_error = GetLastError();
   if(calculated < 3)
      return StringFormat(
         "{\"status\":\"WARMING_UP\",\"previous_closed\":null,\"closed\":null,\"current\":null,\"bars_calculated\":%d,\"error_code\":%d}",
         calculated, calculated_error
      );
   double values[3];
   ResetLastError();
   int copied = CopyBuffer(indicator_handle, buffer_index, 0, 3, values);
   int error_code = GetLastError();
   if(copied != 3)
      return StringFormat(
         "{\"status\":\"WARMING_UP\",\"previous_closed\":null,\"closed\":null,\"current\":null,\"copied\":%d,\"bars_calculated\":%d,\"error_code\":%d}",
         copied, calculated, error_code
      );
   // CopyBuffer stores the oldest requested element first: values[0] is
   // shift 2 (previous closed), values[1] is shift 1 (last closed), and
   // values[2] is shift 0 (forming bar).
   if(!MathIsValidNumber(values[0]) || !MathIsValidNumber(values[1]) || !MathIsValidNumber(values[2]))
      return "{\"status\":\"INVALID\",\"previous_closed\":null,\"closed\":null,\"current\":null,\"error_code\":0}";
   return StringFormat(
      "{\"status\":\"READY\",\"previous_closed\":%s,\"closed\":%s,\"current\":%s,\"error_code\":0}",
      DoubleToString(values[0], 10),
      DoubleToString(values[1], 10),
      DoubleToString(values[2], 10)
   );
}

string BuildIndicatorFrameJson(const string symbol,
                               const int frame_index,
                               const int server_utc_offset_seconds)
{
   ENUM_TIMEFRAMES timeframe = g_indicator_timeframes[frame_index];
   long closed_time_utc_ms = ((long)iTime(symbol, timeframe, 1) - server_utc_offset_seconds) * 1000;
   long current_time_utc_ms = ((long)iTime(symbol, timeframe, 0) - server_utc_offset_seconds) * 1000;
   string values = "";
   values += "\"ema20\":" + IndicatorPairJson(g_h_ema20[frame_index], 0) + ",";
   values += "\"ema50\":" + IndicatorPairJson(g_h_ema50[frame_index], 0) + ",";
   values += "\"rsi14\":" + IndicatorPairJson(g_h_rsi14[frame_index], 0) + ",";
   values += "\"atr14\":" + IndicatorPairJson(g_h_atr14[frame_index], 0) + ",";
   values += "\"macd_main\":" + IndicatorPairJson(g_h_macd[frame_index], 0) + ",";
   values += "\"macd_signal\":" + IndicatorPairJson(g_h_macd[frame_index], 1) + ",";
   values += "\"bollinger_middle\":" + IndicatorPairJson(g_h_bands[frame_index], 0) + ",";
   values += "\"bollinger_upper\":" + IndicatorPairJson(g_h_bands[frame_index], 1) + ",";
   values += "\"bollinger_lower\":" + IndicatorPairJson(g_h_bands[frame_index], 2) + ",";
   values += "\"stochastic_k\":" + IndicatorPairJson(g_h_stochastic[frame_index], 0) + ",";
   values += "\"stochastic_d\":" + IndicatorPairJson(g_h_stochastic[frame_index], 1) + ",";
   values += "\"adx14\":" + IndicatorPairJson(g_h_adx[frame_index], 0) + ",";
   values += "\"plus_di14\":" + IndicatorPairJson(g_h_adx[frame_index], 1) + ",";
   values += "\"minus_di14\":" + IndicatorPairJson(g_h_adx[frame_index], 2) + ",";
   values += "\"cci20\":" + IndicatorPairJson(g_h_cci20[frame_index], 0) + ",";
   values += "\"mfi14\":" + IndicatorPairJson(g_h_mfi14[frame_index], 0) + ",";
   values += "\"momentum14\":" + IndicatorPairJson(g_h_momentum14[frame_index], 0) + ",";
   values += "\"wpr14\":" + IndicatorPairJson(g_h_wpr14[frame_index], 0) + ",";
   values += "\"obv\":" + IndicatorPairJson(g_h_obv[frame_index], 0) + ",";
   values += "\"osma\":" + IndicatorPairJson(g_h_osma[frame_index], 0);
   return StringFormat(
      "\"%s\":{\"closed_bar_time_utc_ms\":%I64d,\"forming_bar_time_utc_ms\":%I64d,\"values\":{%s}}",
      g_indicator_timeframe_names[frame_index],
      closed_time_utc_ms, current_time_utc_ms, values
   );
}

string BuildNativeIndicatorSnapshotPayload(const string symbol)
{
   long server_time_seconds = (long)TimeTradeServer();
   int server_utc_offset_seconds = (int)(server_time_seconds - (long)TimeGMT());
   string payload = "{";
   payload += "\"schema\":\"MIR-MT5-INDICATORS-1\",";
   payload += "\"captured_at_utc_ms\":" + (string)UtcNowMs() + ",";
   payload += "\"server_time_seconds\":" + (string)server_time_seconds + ",";
   payload += "\"terminal_connected\":" + JsonBool((bool)TerminalInfoInteger(TERMINAL_CONNECTED)) + ",";
   payload += "\"broker_symbol\":\"" + JsonEscape(symbol) + "\",";
   payload += "\"market_symbol\":\"" + JsonEscape(InpMarketSymbol) + "\",";
   payload += "\"account\":{\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\"},";
   payload += "\"time_basis\":\"UTC_NORMALIZED_FROM_MT5_SERVER_TIME\",";
   payload += "\"calculation_source\":\"MT5_NATIVE_INDICATOR_BUFFERS\",";
   payload += "\"closed_values_are_shift\":1,";
   payload += "\"current_values_are_shift\":0,";
   payload += "\"timeframes\":{";
   for(int i = 0; i < MIRSAD_TIMEFRAME_COUNT; i++)
   {
      if(i > 0) payload += ",";
      payload += BuildIndicatorFrameJson(symbol, i, server_utc_offset_seconds);
   }
   payload += "}}";
   return payload;
}

string MarketBookTypeLabel(const ENUM_BOOK_TYPE book_type)
{
   if(book_type == BOOK_TYPE_BUY) return "BUY";
   if(book_type == BOOK_TYPE_SELL) return "SELL";
   if(book_type == BOOK_TYPE_BUY_MARKET) return "BUY_MARKET";
   if(book_type == BOOK_TYPE_SELL_MARKET) return "SELL_MARKET";
   return "UNKNOWN";
}

string BuildMarketDepthJson(const string symbol, const int digits)
{
   if(!InpPublishMarketDepth)
      return "\"depth_of_market\":{\"status\":\"DISABLED\",\"source\":\"MT5_MARKET_BOOK\",\"levels\":[]}";
   if(!g_book_subscribed)
   {
      ResetLastError();
      g_book_subscribed = MarketBookAdd(symbol);
   }
   MqlBookInfo book[];
   ResetLastError();
   bool available = MarketBookGet(symbol, book);
   int error_code = GetLastError();
   if(!available)
      return StringFormat(
         "\"depth_of_market\":{\"status\":\"UNAVAILABLE\",\"source\":\"MT5_MARKET_BOOK\",\"subscribed\":%s,\"error_code\":%d,\"levels\":[]}",
         JsonBool(g_book_subscribed), error_code
      );
   int count = MathMin(ArraySize(book), 40);
   string levels = "[";
   int emitted = 0;
   for(int i = 0; i < count; i++)
   {
      if(book[i].price <= 0 || book[i].volume < 0 || !MathIsValidNumber(book[i].price))
         continue;
      if(emitted > 0) levels += ",";
      levels += StringFormat(
         "{\"side\":\"%s\",\"price\":%s,\"volume\":%I64d,\"volume_real\":%s}",
         MarketBookTypeLabel(book[i].type),
         DoubleToString(book[i].price, digits),
         book[i].volume,
         DoubleToString(book[i].volume_real, 8)
      );
      emitted++;
   }
   levels += "]";
   return StringFormat(
      "\"depth_of_market\":{\"status\":\"AVAILABLE\",\"source\":\"MT5_MARKET_BOOK\",\"subscribed\":%s,\"captured_at_utc_ms\":%I64d,\"level_count\":%d,\"levels\":%s}",
      JsonBool(g_book_subscribed), UtcNowMs(), emitted, levels
   );
}

long UtcNowMs()
{
   return (long)TimeGMT() * 1000;
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "");
   StringReplace(value, "\n", " ");
   return value;
}

string JsonBool(const bool value)
{
   return value ? "true" : "false";
}

string TimeframeLabel(const ENUM_TIMEFRAMES timeframe)
{
   string value = EnumToString(timeframe);
   StringReplace(value, "PERIOD_", "");
   return value;
}

bool WriteCommonManifest(const string final_name, const string payload)
{
   string temporary_name = final_name + ".tmp";
   int handle = FileOpen(temporary_name,
                         FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON,
                         0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("Mirsad Observer: cannot open manifest temp file. Error=%d",
                  GetLastError());
      return false;
   }

   FileWriteString(handle, payload);
   FileFlush(handle);
   FileClose(handle);

   ResetLastError();
   if(!FileMove(temporary_name, FILE_COMMON, final_name,
                FILE_COMMON | FILE_REWRITE))
   {
      PrintFormat("Mirsad Observer: cannot publish manifest. Error=%d",
                  GetLastError());
      FileDelete(temporary_name, FILE_COMMON);
      return false;
   }
   return true;
}

string BuildMarketRatesJson(const MqlRates &rates[],
                            const int copied,
                            const int digits,
                            const int server_utc_offset_seconds)
{
   string output = "[";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         output += ",";
      bool is_closed = (i < copied - 1);
      long utc_open_time_ms = ((long)rates[i].time - server_utc_offset_seconds) * 1000;
      double volume = (double)rates[i].tick_volume;
      output += StringFormat(
         "{\"open_time_ms\":%I64d,\"open\":%s,\"high\":%s,\"low\":%s,\"close\":%s,\"volume\":%s,\"closed\":%s}",
         utc_open_time_ms,
         DoubleToString(rates[i].open, digits),
         DoubleToString(rates[i].high, digits),
         DoubleToString(rates[i].low, digits),
         DoubleToString(rates[i].close, digits),
         DoubleToString(volume, 2),
         JsonBool(is_closed)
      );
   }
   output += "]";
   return output;
}

string BuildMarketFrameJson(const string symbol,
                            const string timeframe_key,
                            const ENUM_TIMEFRAMES timeframe,
                            const int digits,
                            const int server_utc_offset_seconds)
{
   MqlRates frame_rates[];
   ArraySetAsSeries(frame_rates, false);
   ResetLastError();
   int copied = CopyRates(symbol, timeframe, 0, InpHistoryBars, frame_rates);
   int error_code = 0;
   if(copied < 0)
   {
      error_code = GetLastError();
      ArrayResize(frame_rates, 0);
      copied = 0;
   }
   return StringFormat(
      "\"%s\":{\"copied\":%d,\"error_code\":%d,\"bars\":%s}",
      timeframe_key, copied, error_code,
      BuildMarketRatesJson(frame_rates, copied, digits, server_utc_offset_seconds)
   );
}

string CalendarImportanceLabel(const ENUM_CALENDAR_EVENT_IMPORTANCE importance)
{
   if(importance == CALENDAR_IMPORTANCE_HIGH)
      return "HIGH";
   if(importance == CALENDAR_IMPORTANCE_MODERATE)
      return "MODERATE";
   if(importance == CALENDAR_IMPORTANCE_LOW)
      return "LOW";
   return "NONE";
}

string BuildEconomicCalendarJson(const int server_utc_offset_seconds)
{
   datetime server_now = TimeTradeServer();
   datetime from_time = server_now - 86400;
   datetime to_time = server_now + 7 * 86400;
   MqlCalendarValue values[];
   ResetLastError();
   int copied = CalendarValueHistory(values, from_time, to_time, "", "USD");
   if(copied < 0)
   {
      int error_code = GetLastError();
      return StringFormat(
         "\"economic_calendar\":{\"status\":\"UNAVAILABLE\",\"source\":\"MT5_ECONOMIC_CALENDAR\",\"currency\":\"USD\",\"error_code\":%d,\"events\":[]}",
         error_code
      );
   }

   int limit = MathMin(copied, 64);
   string events = "[";
   int emitted = 0;
   for(int i = 0; i < limit; i++)
   {
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id, event))
         continue;
      if(emitted > 0)
         events += ",";
      long event_utc_ms = ((long)values[i].time - server_utc_offset_seconds) * 1000;
      events += StringFormat(
         "{\"event_id\":%I64u,\"event_time_utc_ms\":%I64d,\"name\":\"%s\",\"importance\":\"%s\",\"currency\":\"USD\"}",
         values[i].event_id,
         event_utc_ms,
         JsonEscape(event.name),
         CalendarImportanceLabel(event.importance)
      );
      emitted++;
   }
   events += "]";
   return StringFormat(
      "\"economic_calendar\":{\"status\":\"AVAILABLE\",\"source\":\"MT5_ECONOMIC_CALENDAR\",\"currency\":\"USD\",\"events\":%s}",
      events
   );
}

string BuildTickHistoryJson(const string symbol,
                            const int digits,
                            const int server_utc_offset_seconds)
{
   long server_now_ms = (long)TimeTradeServer() * 1000;
   ulong to_msc = (ulong)server_now_ms;
   ulong from_msc = (ulong)MathMax(0, server_now_ms - 120000);
   MqlTick ticks[];
   ResetLastError();
   int copied = CopyTicksRange(symbol, ticks, COPY_TICKS_ALL, from_msc, to_msc);
   int error_code = 0;
   if(copied < 0)
   {
      error_code = GetLastError();
      copied = 0;
      ArrayResize(ticks, 0);
   }

   int start_index = MathMax(0, copied - 256);
   string output = "\"tick_window_seconds\":120,";
   output += StringFormat("\"tick_copy_count\":%d,\"tick_error_code\":%d,\"ticks\":[", copied, error_code);
   int emitted = 0;
   for(int i = start_index; i < copied; i++)
   {
      bool quote_update_valid = (ticks[i].bid > 0 && ticks[i].ask >= ticks[i].bid);
      bool last_update_valid = ((ticks[i].flags & TICK_FLAG_LAST) == TICK_FLAG_LAST && ticks[i].last > 0);
      bool volume_update_valid = ((ticks[i].flags & TICK_FLAG_VOLUME) == TICK_FLAG_VOLUME &&
                                  (ticks[i].volume > 0 || ticks[i].volume_real > 0));
      if(ticks[i].time_msc <= 0 || (!quote_update_valid && !last_update_valid && !volume_update_valid))
         continue;
      if(emitted > 0)
         output += ",";
      long tick_utc_ms = ticks[i].time_msc - (long)server_utc_offset_seconds * 1000;
      output += StringFormat(
         "{\"time_utc_ms\":%I64d,\"bid\":%s,\"ask\":%s,"
         "\"last\":%s,\"volume\":%I64u,\"volume_real\":%s,\"flags\":%u}",
         tick_utc_ms,
         DoubleToString(ticks[i].bid, digits),
         DoubleToString(ticks[i].ask, digits),
         DoubleToString(ticks[i].last, digits),
         ticks[i].volume,
         DoubleToString(ticks[i].volume_real, 8),
         ticks[i].flags
      );
      emitted++;
   }
   output += "]";
   return output;
}

string BuildMarketSnapshotPayload(const string broker_symbol,
                                  const string economic_calendar_json)
{
   long server_time_seconds = (long)TimeTradeServer();
   int server_utc_offset_seconds = (int)(server_time_seconds - (long)TimeGMT());
   long captured_at_utc_ms = UtcNowMs();
   int digits = (int)SymbolInfoInteger(broker_symbol, SYMBOL_DIGITS);

   MqlTick tick;
   bool has_tick = SymbolInfoTick(broker_symbol, tick);
   double bid = has_tick ? tick.bid : 0.0;
   double ask = has_tick ? tick.ask : 0.0;
   long tick_time_server_ms = has_tick ? (long)tick.time_msc : 0;
   double tick_age_seconds = has_tick
      ? MathMax(0.0, (double)server_time_seconds - (double)tick.time)
      : 2147483647.0;

   string payload = "{";
   payload += "\"schema\":\"MIR-MT5-MARKET-2\",";
   payload += "\"captured_at_utc_ms\":" + (string)captured_at_utc_ms + ",";
   payload += "\"server_time_seconds\":" + (string)server_time_seconds + ",";
   payload += "\"server_utc_offset_seconds_at_capture\":" + (string)server_utc_offset_seconds + ",";
   payload += "\"terminal_connected\":" + JsonBool((bool)TerminalInfoInteger(TERMINAL_CONNECTED)) + ",";
   payload += "\"broker_symbol\":\"" + JsonEscape(broker_symbol) + "\",";
   payload += "\"market_symbol\":\"" + JsonEscape(InpMarketSymbol) + "\",";
   payload += "\"account\":{\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\"},";
   payload += "\"quote\":{";
   payload += "\"bid\":" + DoubleToString(bid, digits) + ",";
   payload += "\"ask\":" + DoubleToString(ask, digits) + ",";
   payload += "\"time_ms\":" + (string)captured_at_utc_ms + ",";
   payload += "\"tick_time_server_ms\":" + (string)tick_time_server_ms + ",";
   payload += "\"tick_age_seconds\":" + DoubleToString(tick_age_seconds, 3);
   payload += "},";
   payload += "\"time_basis\":\"UTC_NORMALIZED_FROM_MT5_SERVER_TIME\",";
   payload += BuildTickHistoryJson(broker_symbol, digits, server_utc_offset_seconds) + ",";
   payload += BuildMarketDepthJson(broker_symbol, digits) + ",";
   payload += economic_calendar_json;
   payload += "}";
   return payload;
}

string BuildEngine2CandleSnapshotPayload(const string broker_symbol)
{
   long server_time_seconds = (long)TimeTradeServer();
   int server_utc_offset_seconds = (int)(server_time_seconds - (long)TimeGMT());
   long captured_at_utc_ms = UtcNowMs();
   int digits = (int)SymbolInfoInteger(broker_symbol, SYMBOL_DIGITS);

   string payload = "{";
   payload += "\"schema\":\"MIR-ENGINE2-CANDLES-1\",";
   payload += "\"captured_at_utc_ms\":" + (string)captured_at_utc_ms + ",";
   payload += "\"server_time_seconds\":" + (string)server_time_seconds + ",";
   payload += "\"terminal_connected\":" + JsonBool((bool)TerminalInfoInteger(TERMINAL_CONNECTED)) + ",";
   payload += "\"broker_symbol\":\"" + JsonEscape(broker_symbol) + "\",";
   payload += "\"market_symbol\":\"" + JsonEscape(InpMarketSymbol) + "\",";
   payload += "\"account\":{\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\"},";
   payload += "\"time_basis\":\"UTC_NORMALIZED_FROM_MT5_SERVER_TIME\",";
   payload += "\"timeframes\":{";
   payload += BuildMarketFrameJson(broker_symbol, "1m", PERIOD_M1, digits, server_utc_offset_seconds) + ",";
   payload += BuildMarketFrameJson(broker_symbol, "5m", PERIOD_M5, digits, server_utc_offset_seconds) + ",";
   payload += BuildMarketFrameJson(broker_symbol, "15m", PERIOD_M15, digits, server_utc_offset_seconds) + ",";
   payload += BuildMarketFrameJson(broker_symbol, "1h", PERIOD_H1, digits, server_utc_offset_seconds) + ",";
   payload += BuildMarketFrameJson(broker_symbol, "4h", PERIOD_H4, digits, server_utc_offset_seconds) + ",";
   payload += BuildMarketFrameJson(broker_symbol, "1d", PERIOD_D1, digits, server_utc_offset_seconds);
   payload += "}}";
   return payload;
}

bool PublishMarketSnapshot()
{
   string symbol = ChartSymbol(g_chart_id);
   if(symbol == "" || InpMarketSymbol == "")
      return false;

   ulong now_tick = GetTickCount64();
   // CalendarValueHistory can block for minutes on terminals with unavailable/corrupt calendar data.
   // Keep it out of the two-second market/candle/indicator publication path by default.
   if(InpPublishEconomicCalendar && now_tick >= g_next_calendar_refresh_at_ms)
   {
      int server_offset = (int)((long)TimeTradeServer() - (long)TimeGMT());
      g_economic_calendar_json = BuildEconomicCalendarJson(server_offset);
      g_next_calendar_refresh_at_ms = now_tick + 60000;
   }

   string market_payload = BuildMarketSnapshotPayload(symbol, g_economic_calendar_json);
   if(!WriteCommonManifest("MirsadBTC\\market.json", market_payload))
   {
      PrintFormat("Mirsad Observer: could not publish Engine 1 MT5 market snapshot. Error=%d", GetLastError());
      return false;
   }

   string candle_payload = BuildEngine2CandleSnapshotPayload(symbol);
   if(!WriteCommonManifest("MirsadBTC\\observer\\candles.json", candle_payload))
   {
      PrintFormat("Mirsad Observer: could not publish Engine 2 candle history. Error=%d", GetLastError());
      return false;
   }

   if(InpPublishNativeIndicators)
   {
      string indicator_payload = BuildNativeIndicatorSnapshotPayload(symbol);
      if(!WriteCommonManifest("MirsadBTC\\observer\\indicators.json", indicator_payload))
      {
         PrintFormat("Mirsad Observer: could not publish native MT5 indicators. Error=%d", GetLastError());
         return false;
      }
   }
   PrintFormat(
      "Mirsad native feeds published. Market=MirsadBTC\\market.json; Candles=MirsadBTC\\observer\\candles.json; NativeIndicators=%s.",
      (InpPublishNativeIndicators ? "enabled" : "disabled")
   );
   return true;
}


int OnInit()
{
   if(InpMarketSnapshotIntervalSeconds < 1 || InpMarketSnapshotIntervalSeconds > 30 ||
      InpMarketSymbol == "" || InpHistoryBars < 1)
      return INIT_PARAMETERS_INCORRECT;

   g_chart_id = ChartID();
   if(g_chart_id == 0 || ChartSymbol(g_chart_id) == "")
      return INIT_FAILED;

   // This EA only publishes data and does not alter the chart viewport.
   FolderCreate("MirsadBTC", FILE_COMMON);
   FolderCreate(g_observer_root, FILE_COMMON);

   ResetIndicatorHandles();
   if(InpPublishNativeIndicators)
      InitializeIndicatorHandles(ChartSymbol(g_chart_id));
   if(InpPublishMarketDepth)
   {
      ResetLastError();
      g_book_subscribed = MarketBookAdd(ChartSymbol(g_chart_id));
      if(!g_book_subscribed)
         PrintFormat("Mirsad native feed: broker market book unavailable. Error=%d", GetLastError());
   }

   if(!EventSetTimer(1))
   {
      PrintFormat("Mirsad native feed: EventSetTimer failed. Error=%d", GetLastError());
      return INIT_FAILED;
   }

   g_next_market_snapshot_at_ms = GetTickCount64();
   PrintFormat(
      "Mirsad native feed publisher started. Symbol=%s; market interval=%d sec; native indicators=%s; market depth=%s; MT5 calendar=%s. Data-only EA.",
      ChartSymbol(g_chart_id),
      InpMarketSnapshotIntervalSeconds,
      (InpPublishNativeIndicators ? "enabled" : "disabled"),
      (InpPublishMarketDepth ? "enabled" : "disabled"),
      (InpPublishEconomicCalendar ? "enabled" : "disabled")
   );
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ReleaseIndicatorHandles();
   if(g_book_subscribed)
      MarketBookRelease(ChartSymbol(g_chart_id));
   PrintFormat("Mirsad native feed publisher stopped. Reason=%d", reason);
}

void OnTimer()
{
   ulong now_tick = GetTickCount64();
   if(now_tick >= g_next_market_snapshot_at_ms)
   {
      PublishMarketSnapshot();
      g_next_market_snapshot_at_ms = now_tick + (ulong)InpMarketSnapshotIntervalSeconds * 1000;
   }
}

void OnTick()
{
   // Intentionally empty: this EA publishes data and never trades.
}

