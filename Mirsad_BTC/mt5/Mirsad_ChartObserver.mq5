//+------------------------------------------------------------------+
//| Mirsad Chart Observer — read-only MT5 chart capture agent        |
//| Captures one attached chart plus its native MqlRates snapshot.   |
//| No trade functions. Does not publish MIR1 commands.               |
//+------------------------------------------------------------------+
#property strict
#property version   "1.002"
#property description "Mirsad read-only MT5 chart screenshot and OHLC observer"

#define MIRSAD_OBSERVER_MIN_SOURCE_WIDTH 640
#define MIRSAD_OBSERVER_MIN_SOURCE_HEIGHT 360

input bool InpEnableImageCapture = true; // Disable image capture while keeping direct MT5 data feeds active
input int  InpCaptureIntervalSeconds = 60;   // Screenshot cadence (5..3600 seconds)
input int  InpMarketSnapshotIntervalSeconds = 2; // MT5 market-feed cadence (1..30 seconds)
input string InpMarketSymbol = "BTCUSDT"; // Stable Mirsad symbol mapped to this broker symbol
input int  InpHistoryBars             = 120;  // Requested bars including the forming bar; set as needed
input int  InpScreenshotWidth         = 1600; // PNG output width
input int  InpScreenshotHeight        = 900;  // PNG output height
input bool InpCaptureImmediately      = true; // Capture after the initial terminal window has stabilized
input int  InpInitialCaptureDelaySeconds = 10; // Allow Windows to maximize the chart before its first snapshot
input bool InpPublishNativeIndicators = true; // Publish native MT5 CopyBuffer values independently of chart images
input bool InpPublishMarketDepth = true; // Publish broker market book when supported

string g_observer_root = "MirsadBTC\\observer";
string g_image_root    = "MirsadBTC\\observer\\images";
long   g_chart_id      = 0;
ulong  g_next_capture_at_ms = 0;
ulong  g_next_market_snapshot_at_ms = 0;
ulong  g_next_calendar_refresh_at_ms = 0;
string g_economic_calendar_json = "\"economic_calendar\":{\"status\":\"NOT_REQUESTED\",\"source\":\"MT5_ECONOMIC_CALENDAR\",\"currency\":\"USD\",\"events\":[]}";
uint   g_sequence = 0;
bool   g_pending = false;
ulong  g_pending_started_tick = 0;
string g_pending_id = "";
string g_pending_local_image = "";
string g_pending_common_image = "";
string g_pending_manifest_name = "";
string g_pending_payload = "";

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
   for(int i = 0; i < MIRSAD_TIMEFRAME_COUNT; i++)
   {
      ENUM_TIMEFRAMES timeframe = g_indicator_timeframes[i];
      g_h_ema20[i] = iMA(symbol, timeframe, 20, 0, MODE_EMA, PRICE_CLOSE);
      g_h_ema50[i] = iMA(symbol, timeframe, 50, 0, MODE_EMA, PRICE_CLOSE);
      g_h_rsi14[i] = iRSI(symbol, timeframe, 14, PRICE_CLOSE);
      g_h_atr14[i] = iATR(symbol, timeframe, 14);
      g_h_macd[i] = iMACD(symbol, timeframe, 12, 26, 9, PRICE_CLOSE);
      g_h_bands[i] = iBands(symbol, timeframe, 20, 0, 2.0, PRICE_CLOSE);
      g_h_stochastic[i] = iStochastic(symbol, timeframe, 5, 3, 3, MODE_SMA, STO_LOWHIGH);
      g_h_adx[i] = iADX(symbol, timeframe, 14);
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
      return "{\"status\":\"UNAVAILABLE\",\"closed\":null,\"current\":null,\"error_code\":-1}";
   double values[2];
   ResetLastError();
   int copied = CopyBuffer(indicator_handle, buffer_index, 0, 2, values);
   int error_code = GetLastError();
   if(copied != 2)
      return StringFormat(
         "{\"status\":\"UNAVAILABLE\",\"closed\":null,\"current\":null,\"copied\":%d,\"error_code\":%d}",
         copied, error_code
      );
   // CopyBuffer stores the oldest requested element first: values[0] is
   // shift 1 (last closed bar), values[1] is shift 0 (forming bar).
   if(!MathIsValidNumber(values[0]) || !MathIsValidNumber(values[1]))
      return "{\"status\":\"INVALID\",\"closed\":null,\"current\":null,\"error_code\":0}";
   return StringFormat(
      "{\"status\":\"READY\",\"closed\":%s,\"current\":%s,\"error_code\":0}",
      DoubleToString(values[0], 10),
      DoubleToString(values[1], 10)
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

bool ReadBinaryFileSize(const string file_name, const int common_flag, ulong &size_out)
{
   size_out = 0;
   int handle = FileOpen(file_name, FILE_READ | FILE_BIN | common_flag);
   if(handle == INVALID_HANDLE)
      return false;
   size_out = FileSize(handle);
   FileClose(handle);
   return true;
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

void PublishObserverStatus(const string state,
                           const string capture_id,
                           const string message)
{
   string payload = StringFormat(
      "{\"schema\":\"MIR-CHART-OBSERVER-STATUS-1\","
      "\"state\":\"%s\",\"capture_id\":\"%s\","
      "\"symbol\":\"%s\",\"timeframe\":\"%s\","
      "\"chart_window_handle\":%I64d,\"chart_is_maximized\":%s,"
      "\"updated_at_utc_ms\":%I64d,\"message\":\"%s\"}",
      JsonEscape(state), JsonEscape(capture_id),
      JsonEscape(ChartSymbol(g_chart_id)),
      JsonEscape(TimeframeLabel((ENUM_TIMEFRAMES)ChartPeriod(g_chart_id))),
      ChartGetInteger(g_chart_id, CHART_WINDOW_HANDLE),
      JsonBool((bool)ChartGetInteger(g_chart_id, CHART_IS_MAXIMIZED)),
      UtcNowMs(), JsonEscape(message)
   );

   string temporary_name = g_observer_root + "\\observer_status.json.tmp";
   string final_name = g_observer_root + "\\observer_status.json";
   int handle = FileOpen(temporary_name,
                         FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON,
                         0, CP_UTF8);
   if(handle == INVALID_HANDLE)
      return;
   FileWriteString(handle, payload);
   FileFlush(handle);
   FileClose(handle);
   FileMove(temporary_name, FILE_COMMON, final_name,
            FILE_COMMON | FILE_REWRITE);
}

string AccountTradeModeLabel()
{
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_DEMO)
      return "DEMO";
   if(mode == ACCOUNT_TRADE_MODE_REAL)
      return "REAL";
   if(mode == ACCOUNT_TRADE_MODE_CONTEST)
      return "CONTEST";
   return "UNKNOWN";
}

string BuildRatesJson(const MqlRates &rates[],
                      const int copied,
                      const int digits)
{
   string output = "[";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         output += ",";

      // CopyRates stores the oldest copied element at physical index zero.
      // The last physical element is shift zero (the currently forming bar).
      bool is_closed = (i < copied - 1);
      output += StringFormat(
         "{\"time_server_ms\":%I64d,"
         "\"open\":%s,\"high\":%s,\"low\":%s,\"close\":%s,"
         "\"tick_volume\":%I64d,\"real_volume\":%I64d,"
         "\"spread_points\":%d,\"is_closed\":%s}",
         (long)rates[i].time * 1000,
         DoubleToString(rates[i].open, digits),
         DoubleToString(rates[i].high, digits),
         DoubleToString(rates[i].low, digits),
         DoubleToString(rates[i].close, digits),
         rates[i].tick_volume, rates[i].real_volume,
         rates[i].spread, JsonBool(is_closed)
      );
   }
   output += "]";
   return output;
}


string ChartPixelPointJson(const bool valid, const int x, const int y)
{
   if(!valid)
      return "null";
   return StringFormat("{\"x_px\":%d,\"y_px\":%d}", x, y);
}

string BuildChartPixelGeometryJson(const MqlRates &rates[],
                                   const int copied,
                                   const int source_width,
                                   const int source_height,
                                   const int image_width,
                                   const int image_height)
{
   string bars_json = "[";
   int valid_count = 0;
   int visible_count = 0;

   for(int i = 0; i < copied; i++)
   {
      int open_x = -1, open_y = -1;
      int high_x = -1, high_y = -1;
      int low_x = -1, low_y = -1;
      int close_x = -1, close_y = -1;

      bool open_ok = ChartTimePriceToXY(g_chart_id, 0, rates[i].time, rates[i].open, open_x, open_y);
      bool high_ok = ChartTimePriceToXY(g_chart_id, 0, rates[i].time, rates[i].high, high_x, high_y);
      bool low_ok = ChartTimePriceToXY(g_chart_id, 0, rates[i].time, rates[i].low, low_x, low_y);
      bool close_ok = ChartTimePriceToXY(g_chart_id, 0, rates[i].time, rates[i].close, close_x, close_y);

      bool all_points_ok = open_ok && high_ok && low_ok && close_ok;
      int min_x = open_x;
      int max_x = open_x;
      if(high_x < min_x) min_x = high_x;
      if(low_x < min_x) min_x = low_x;
      if(close_x < min_x) min_x = close_x;
      if(high_x > max_x) max_x = high_x;
      if(low_x > max_x) max_x = low_x;
      if(close_x > max_x) max_x = close_x;
      bool x_aligned = all_points_ok && (max_x - min_x <= 1);
      bool visible = (
         x_aligned
         && source_width > 0 && source_height > 0
         && open_x >= 0 && open_x < source_width
         && high_y >= 0 && high_y < source_height
         && low_y >= 0 && low_y < source_height
         && open_y >= 0 && open_y < source_height
         && close_y >= 0 && close_y < source_height
      );
      bool y_order_valid = (
         all_points_ok
         && high_y <= MathMin(open_y, close_y)
         && low_y >= MathMax(open_y, close_y)
      );
      bool point_set_valid = all_points_ok && x_aligned && y_order_valid;
      double x_center = point_set_valid
         ? ((double)open_x + (double)high_x + (double)low_x + (double)close_x) / 4.0
         : -1.0;

      if(i > 0)
         bars_json += ",";
      bars_json += StringFormat(
         "{\"time_server_ms\":%I64d,"
         "\"is_closed\":%s,"
         "\"valid\":%s,"
         "\"visible\":%s,"
         "\"x_px\":%s,"
         "\"x_alignment_error_px\":%d,"
         "\"open\":%s,"
         "\"high\":%s,"
         "\"low\":%s,"
         "\"close\":%s}",
         (long)rates[i].time * 1000,
         JsonBool(i < copied - 1),
         JsonBool(point_set_valid),
         JsonBool(visible),
         DoubleToString(x_center, 3),
         (x_aligned ? max_x - min_x : -1),
         ChartPixelPointJson(open_ok, open_x, open_y),
         ChartPixelPointJson(high_ok, high_x, high_y),
         ChartPixelPointJson(low_ok, low_x, low_y),
         ChartPixelPointJson(close_ok, close_x, close_y)
      );
      if(point_set_valid) valid_count++;
      if(visible && point_set_valid) visible_count++;
   }
   bars_json += "]";

   double scale_x = source_width > 0 ? (double)image_width / (double)source_width : 0.0;
   double scale_y = source_height > 0 ? (double)image_height / (double)source_height : 0.0;
   return StringFormat(
      "{\"schema\":\"MIR-MT5-CHART-GEOMETRY-1\","
      "\"coordinate_source\":\"MQL5_CHART_TIME_PRICE_TO_XY\","
      "\"coordinate_origin\":\"MAIN_CHART_WINDOW_TOP_LEFT\","
      "\"source_width_px\":%d,\"source_height_px\":%d,"
      "\"image_width_px\":%d,\"image_height_px\":%d,"
      "\"provisional_x_scale_to_image\":%s,"
      "\"provisional_y_scale_to_image\":%s,"
      "\"bars_total\":%d,\"bars_valid\":%d,\"bars_visible\":%d,"
      "\"bars\":%s}",
      source_width, source_height, image_width, image_height,
      DoubleToString(scale_x, 8), DoubleToString(scale_y, 8),
      copied, valid_count, visible_count, bars_json
   );
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
   if(now_tick >= g_next_calendar_refresh_at_ms)
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
      "Mirsad Observer direct feeds published. Market=MirsadBTC\\market.json; Candles=MirsadBTC\\observer\\candles.json; NativeIndicators=%s; ImageCapture=%s.",
      (InpPublishNativeIndicators ? "enabled" : "disabled"),
      (InpEnableImageCapture ? "enabled" : "disabled")
   );
   return true;
}


string BuildCapturePayload(const string capture_id,
                           const string image_name,
                           const int image_width,
                           const int image_height,
                           const int source_width,
                           const int source_main_height,
                           const int windows_total,
                           const int first_visible_bar,
                           const int visible_bars,
                           const int chart_scale,
                           const int chart_mode,
                           const bool chart_shift,
                           const bool chart_autoscroll,
                           const double price_min,
                           const double price_max,
                           const long background_color,
                           const long foreground_color,
                           const long bull_color,
                           const long bear_color,
                           const MqlRates &rates[],
                           const int copied,
                           const int rates_error_code,
                           const int digits,
                           const long capture_at_utc_ms,
                           const long rates_snapshot_at_utc_ms,
                           const long server_time_seconds,
                           const int server_utc_offset_seconds,
                           const string pixel_geometry_json)
{
   string symbol = ChartSymbol(g_chart_id);
   ENUM_TIMEFRAMES timeframe = (ENUM_TIMEFRAMES)ChartPeriod(g_chart_id);
   bool source_dimensions_usable = (source_width >= MIRSAD_OBSERVER_MIN_SOURCE_WIDTH && source_main_height >= MIRSAD_OBSERVER_MIN_SOURCE_HEIGHT);
   string source_dimensions_status = source_dimensions_usable
      ? "USABLE"
      : "BELOW_VISUAL_CALIBRATION_THRESHOLD";

   string payload = "{";
   payload += "\"schema\":\"MIR-CHART-OBSERVATION-1\",";
   payload += "\"capture_id\":\"" + JsonEscape(capture_id) + "\",";
   payload += "\"capture_at_utc_ms\":" + (string)capture_at_utc_ms + ",";
   payload += "\"rates_snapshot_at_utc_ms\":" + (string)rates_snapshot_at_utc_ms + ",";
   payload += "\"server_time_seconds\":" + (string)server_time_seconds + ",";
   payload += "\"server_utc_offset_seconds_at_capture\":" + (string)server_utc_offset_seconds + ",";
   payload += "\"account\":{";
   payload += "\"terminal_connected\":" + JsonBool((bool)TerminalInfoInteger(TERMINAL_CONNECTED)) + ",";
   payload += "\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\",";
   payload += "\"trade_mode\":" + (string)AccountInfoInteger(ACCOUNT_TRADE_MODE) + ",";
   payload += "\"trade_mode_label\":\"" + AccountTradeModeLabel() + "\"";
   payload += "},";
   payload += "\"image_file\":\"" + JsonEscape(image_name) + "\",";
   payload += "\"image_width_px\":" + (string)image_width + ",";
   payload += "\"image_height_px\":" + (string)image_height + ",";
   payload += "\"chart\":{";
   payload += "\"chart_id\":\"" + (string)g_chart_id + "\",";
   payload += "\"chart_window_handle\":" + (string)ChartGetInteger(g_chart_id, CHART_WINDOW_HANDLE) + ",";
   payload += "\"chart_is_maximized\":" + JsonBool((bool)ChartGetInteger(g_chart_id, CHART_IS_MAXIMIZED)) + ",";
   payload += "\"symbol\":\"" + JsonEscape(symbol) + "\",";
   payload += "\"timeframe\":\"" + JsonEscape(TimeframeLabel(timeframe)) + "\",";
   payload += "\"digits\":" + (string)digits + ",";
   payload += "\"source_width_px\":" + (string)source_width + ",";
   payload += "\"source_main_window_height_px\":" + (string)source_main_height + ",";
   payload += "\"source_dimensions_usable\":" + JsonBool(source_dimensions_usable) + ",";
   payload += "\"source_dimensions_status\":\"" + source_dimensions_status + "\",";
   payload += "\"windows_total\":" + (string)windows_total + ",";
   payload += "\"first_visible_bar_shift\":" + (string)first_visible_bar + ",";
   payload += "\"visible_bars\":" + (string)visible_bars + ",";
   payload += "\"chart_scale\":" + (string)chart_scale + ",";
   payload += "\"chart_mode\":" + (string)chart_mode + ",";
   payload += "\"chart_shift\":" + JsonBool(chart_shift) + ",";
   payload += "\"chart_autoscroll\":" + JsonBool(chart_autoscroll) + ",";
   payload += "\"price_min\":" + DoubleToString(price_min, digits) + ",";
   payload += "\"price_max\":" + DoubleToString(price_max, digits) + ",";
   payload += "\"background_color\":" + (string)background_color + ",";
   payload += "\"foreground_color\":" + (string)foreground_color + ",";
   payload += "\"bull_color\":" + (string)bull_color + ",";
   payload += "\"bear_color\":" + (string)bear_color + ",";
   payload += "\"price_scale_type\":\"linear\",";
   payload += "\"plot_bounds_status\":\"NOT_CALIBRATED_FROM_PIXELS\",";
   payload += "\"pixel_geometry\":" + pixel_geometry_json;
   payload += "},";
   payload += "\"bars_time_basis\":\"MT5_SERVER_TIME\",";
   payload += "\"bars_requested\":" + (string)InpHistoryBars + ",";
   payload += "\"bars_copied\":" + (string)copied + ",";
   payload += "\"rates_status\":\"" + (copied > 0 ? "AVAILABLE" : "UNAVAILABLE") + "\",";
   payload += "\"rates_error_code\":" + (string)rates_error_code + ",";
   payload += "\"forming_bar_included\":" + JsonBool(copied > 0) + ",";
   payload += "\"bars\":" + BuildRatesJson(rates, copied, digits);
   payload += "}";
   return payload;
}

bool BeginCapture()
{
   string symbol = ChartSymbol(g_chart_id);
   ENUM_TIMEFRAMES timeframe = (ENUM_TIMEFRAMES)ChartPeriod(g_chart_id);
   if(symbol == "" || timeframe == PERIOD_CURRENT)
   {
      PublishObserverStatus("ERROR", "", "Chart symbol or timeframe is unavailable.");
      return false;
   }

   int source_width = (int)ChartGetInteger(g_chart_id, CHART_WIDTH_IN_PIXELS);
   int source_main_height = (int)ChartGetInteger(g_chart_id, CHART_HEIGHT_IN_PIXELS, 0);
   int windows_total = (int)ChartGetInteger(g_chart_id, CHART_WINDOWS_TOTAL);
   int first_visible_bar = (int)ChartGetInteger(g_chart_id, CHART_FIRST_VISIBLE_BAR);
   int visible_bars = (int)ChartGetInteger(g_chart_id, CHART_VISIBLE_BARS);
   int chart_scale = (int)ChartGetInteger(g_chart_id, CHART_SCALE);
   int chart_mode = (int)ChartGetInteger(g_chart_id, CHART_MODE);
   bool chart_shift = (bool)ChartGetInteger(g_chart_id, CHART_SHIFT);
   bool chart_autoscroll = (bool)ChartGetInteger(g_chart_id, CHART_AUTOSCROLL);

   double price_min = ChartGetDouble(g_chart_id, CHART_PRICE_MIN, 0);
   double price_max = ChartGetDouble(g_chart_id, CHART_PRICE_MAX, 0);
   long background_color = ChartGetInteger(g_chart_id, CHART_COLOR_BACKGROUND);
   long foreground_color = ChartGetInteger(g_chart_id, CHART_COLOR_FOREGROUND);
   long bull_color = ChartGetInteger(g_chart_id, CHART_COLOR_CANDLE_BULL);
   long bear_color = ChartGetInteger(g_chart_id, CHART_COLOR_CANDLE_BEAR);

   bool source_dimensions_usable = (source_width >= MIRSAD_OBSERVER_MIN_SOURCE_WIDTH && source_main_height >= MIRSAD_OBSERVER_MIN_SOURCE_HEIGHT);
   if(!source_dimensions_usable)
   {
      PrintFormat("Mirsad Observer: source chart viewport is %d x %d px; capture will still be requested at %d x %d px. Visual calibration must treat source dimensions as unavailable.",
                  source_width, source_main_height,
                  InpScreenshotWidth, InpScreenshotHeight);
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   ResetLastError();
   int copied = CopyRates(symbol, timeframe, 0, InpHistoryBars, rates);
   int rates_error_code = 0;
   if(copied < 0)
   {
      rates_error_code = GetLastError();
      ArrayResize(rates, 0);
      copied = 0;
      PublishObserverStatus(
         "RATES_READ_PARTIAL", "",
         StringFormat("Chart image capture will continue without OHLC bars. CopyRates error=%d.",
                      rates_error_code)
      );
   }

   ChartRedraw(g_chart_id);
   string pixel_geometry_json = BuildChartPixelGeometryJson(
      rates, copied, source_width, source_main_height,
      InpScreenshotWidth, InpScreenshotHeight
   );
   long rates_snapshot_at_utc_ms = UtcNowMs();
   long server_time_seconds = (long)TimeTradeServer();
   int server_utc_offset_seconds = (int)(TimeTradeServer() - TimeGMT());
   long capture_at_utc_ms = UtcNowMs();

   g_sequence++;
   string capture_id = StringFormat("%I64d_%I64d_%u",
                                    capture_at_utc_ms,
                                    (long)GetTickCount64(),
                                    g_sequence);
   string image_name = "o_" + capture_id + ".png";
   string local_image = "MirsadBTC\\" + image_name;
   string common_image = g_image_root + "\\" + image_name;

   ChartRedraw(g_chart_id);
   ResetLastError();
   bool screenshot_requested = ChartScreenShot(
      g_chart_id, local_image,
      InpScreenshotWidth, InpScreenshotHeight, ALIGN_RIGHT
   );
   if(!screenshot_requested)
   {
      PublishObserverStatus(
         "SCREENSHOT_REQUEST_FAILED", capture_id,
         StringFormat("ChartScreenShot returned false. Error=%d", GetLastError())
      );
      return false;
   }

   g_pending_id = capture_id;
   g_pending_local_image = local_image;
   g_pending_common_image = common_image;
   g_pending_manifest_name = g_observer_root + "\\capture_" + capture_id + ".json";
   g_pending_payload = BuildCapturePayload(
      capture_id, image_name, InpScreenshotWidth, InpScreenshotHeight,
      source_width, source_main_height, windows_total,
      first_visible_bar, visible_bars, chart_scale, chart_mode,
      chart_shift, chart_autoscroll, price_min, price_max,
      background_color, foreground_color, bull_color, bear_color,
      rates, copied, rates_error_code, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS),
      capture_at_utc_ms, rates_snapshot_at_utc_ms,
      server_time_seconds, server_utc_offset_seconds,
      pixel_geometry_json
   );
   g_pending = true;
   g_pending_started_tick = GetTickCount64();
   PublishObserverStatus("SCREENSHOT_PENDING", capture_id,
                         "Screenshot requested; waiting for the local PNG before publishing its manifest.");
   return true;
}

bool TryFinalizePendingCapture()
{
   if(!g_pending)
      return false;

   if(!FileIsExist(g_pending_local_image, 0))
   {
      if(GetTickCount64() - g_pending_started_tick > 10000)
      {
         PublishObserverStatus("SCREENSHOT_TIMEOUT", g_pending_id,
                               "Screenshot file did not appear within 10 seconds.");
         g_pending = false;
         g_pending_payload = "";
      }
      return false;
   }

   ulong local_size = 0;
   if(!ReadBinaryFileSize(g_pending_local_image, 0, local_size) || local_size < 128)
      return false;

   ResetLastError();
   if(!FileCopy(g_pending_local_image, 0, g_pending_common_image, FILE_COMMON | FILE_REWRITE))
   {
      PublishObserverStatus(
         "IMAGE_COPY_FAILED", g_pending_id,
         StringFormat("Could not copy screenshot to Common Files. Error=%d", GetLastError())
      );
      return false;
   }

   ulong common_size = 0;
   if(!ReadBinaryFileSize(g_pending_common_image, FILE_COMMON, common_size) ||
      common_size != local_size)
   {
      PublishObserverStatus("IMAGE_COPY_INCOMPLETE", g_pending_id,
                            "The common-folder image size does not match the local screenshot.");
      return false;
   }

   string payload = g_pending_payload;
   StringReplace(payload, "\"forming_bar_included\":true,",
                 "\"forming_bar_included\":true,\"image_size_bytes\":" +
                 (string)common_size + ",\"published_at_utc_ms\":" +
                 (string)UtcNowMs() + ",");

   if(!WriteCommonManifest(g_pending_manifest_name, payload))
   {
      PublishObserverStatus("MANIFEST_PUBLISH_FAILED", g_pending_id,
                            "Image copied, but its manifest could not be published.");
      return false;
   }

   FileDelete(g_pending_local_image, 0);
   PublishObserverStatus("READY", g_pending_id,
                         "Image and matching OHLC snapshot were published to the observer inbox.");

   g_pending = false;
   g_pending_id = "";
   g_pending_local_image = "";
   g_pending_common_image = "";
   g_pending_manifest_name = "";
   g_pending_payload = "";
   return true;
}

int OnInit()
{
   if(InpCaptureIntervalSeconds < 1 || InpMarketSnapshotIntervalSeconds < 1 || InpMarketSnapshotIntervalSeconds > 30 || InpMarketSymbol == "" || InpHistoryBars < 1 ||
      (InpEnableImageCapture && (InpScreenshotWidth < 320 || InpScreenshotHeight < 180 ||
       InpInitialCaptureDelaySeconds < 0 || InpInitialCaptureDelaySeconds > 60)))
      return INIT_PARAMETERS_INCORRECT;

   g_chart_id = ChartID();
   if(g_chart_id == 0)
      return INIT_FAILED;

   // Bring the exact chart carrying this Observer to the foreground.
   ResetLastError();
   if(!ChartSetInteger(g_chart_id, CHART_BRING_TO_TOP, true))
      PrintFormat("Mirsad Observer: CHART_BRING_TO_TOP failed. Error=%d", GetLastError());
   ChartRedraw(g_chart_id);

   FolderCreate("MirsadBTC", 0);
   FolderCreate("MirsadBTC", FILE_COMMON);
   FolderCreate(g_observer_root, FILE_COMMON);
   FolderCreate(g_image_root, FILE_COMMON);

   ResetIndicatorHandles();
   if(InpPublishNativeIndicators)
      InitializeIndicatorHandles(ChartSymbol(g_chart_id));
   if(InpPublishMarketDepth)
   {
      ResetLastError();
      g_book_subscribed = MarketBookAdd(ChartSymbol(g_chart_id));
      if(!g_book_subscribed)
         PrintFormat("Mirsad Observer: broker market book unavailable or subscription failed. Error=%d", GetLastError());
   }

   MathSrand((int)GetTickCount());
   if(!EventSetTimer(1))
   {
      PrintFormat("Mirsad Observer: EventSetTimer failed. Error=%d", GetLastError());
      return INIT_FAILED;
   }

   g_next_market_snapshot_at_ms = GetTickCount64();
   g_next_capture_at_ms = InpEnableImageCapture
      ? (InpCaptureImmediately
         ? GetTickCount64() + (ulong)InpInitialCaptureDelaySeconds * 1000
         : GetTickCount64() + (ulong)InpCaptureIntervalSeconds * 1000)
      : 0;

   PublishObserverStatus("STARTED", "",
                         "Read-only MT5 chart observer started on the attached chart.");
   PrintFormat(
      "Mirsad Chart Observer mode. Direct MT5 data enabled; native indicators=%s; market depth=%s; chart images=%s.",
      (InpPublishNativeIndicators ? "enabled" : "disabled"),
      (InpPublishMarketDepth ? "enabled" : "disabled"),
      (InpEnableImageCapture ? "enabled" : "disabled")
   );
   PrintFormat("Mirsad Chart Observer started. Chart=%I64d Symbol=%s Timeframe=%s Interval=%d sec. No trading functions.",
               g_chart_id, ChartSymbol(g_chart_id),
               TimeframeLabel((ENUM_TIMEFRAMES)ChartPeriod(g_chart_id)),
               InpCaptureIntervalSeconds);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ReleaseIndicatorHandles();
   if(g_book_subscribed)
      MarketBookRelease(ChartSymbol(g_chart_id));
   PublishObserverStatus("STOPPED", g_pending_id,
                         StringFormat("Observer stopped. Reason=%d", reason));
}

void OnTimer()
{
   ulong now_tick = GetTickCount64();
   if(now_tick >= g_next_market_snapshot_at_ms)
   {
      PublishMarketSnapshot();
      g_next_market_snapshot_at_ms = now_tick + (ulong)InpMarketSnapshotIntervalSeconds * 1000;
   }

   // Direct market, candles and native indicator feeds run independently
   // from the optional chart-image capture path.
   if(!InpEnableImageCapture)
      return;

   if(g_pending)
   {
      TryFinalizePendingCapture();
      return;
   }

   if(now_tick < g_next_capture_at_ms)
      return;

   BeginCapture();
   g_next_capture_at_ms = now_tick + (ulong)InpCaptureIntervalSeconds * 1000;
}

void OnTick()
{
   // Intentionally empty: this observer never creates trading instructions.
}

void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   // Chart changes are intentionally not captured immediately; the timer
   // throttles snapshots and avoids an image storm while a user is resizing.
}
