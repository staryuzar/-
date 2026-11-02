//+------------------------------------------------------------------+
//| Mirsad Chart Observer — read-only MT5 chart capture agent        |
//| Captures one attached chart plus its native MqlRates snapshot.   |
//| No trade functions. Does not publish MIR1 commands.               |
//+------------------------------------------------------------------+
#property strict
#property version   "1.001"
#property description "Mirsad read-only MT5 chart screenshot and OHLC observer"

input int  InpCaptureIntervalSeconds = 60;   // Snapshot cadence (5..3600 seconds)
input int  InpHistoryBars             = 120;  // Requested bars including the forming bar; set as needed
input int  InpScreenshotWidth         = 1600; // PNG output width
input int  InpScreenshotHeight        = 900;  // PNG output height
input bool InpCaptureImmediately      = true; // Capture shortly after initialization

string g_observer_root = "MirsadBTC\\observer";
string g_image_root    = "MirsadBTC\\observer\\images";
long   g_chart_id      = 0;
ulong  g_next_capture_at_ms = 0;
uint   g_sequence = 0;
bool   g_pending = false;
ulong  g_pending_started_tick = 0;
string g_pending_id = "";
string g_pending_local_image = "";
string g_pending_common_image = "";
string g_pending_manifest_name = "";
string g_pending_payload = "";

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
      "\"updated_at_utc_ms\":%I64d,\"message\":\"%s\"}",
      JsonEscape(state), JsonEscape(capture_id),
      JsonEscape(ChartSymbol(g_chart_id)),
      JsonEscape(TimeframeLabel((ENUM_TIMEFRAMES)ChartPeriod(g_chart_id))),
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
                           const int server_utc_offset_seconds)
{
   string symbol = ChartSymbol(g_chart_id);
   ENUM_TIMEFRAMES timeframe = (ENUM_TIMEFRAMES)ChartPeriod(g_chart_id);
   bool source_dimensions_usable = (source_width >= 320 && source_main_height >= 160);
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
   payload += "\"plot_bounds_status\":\"NOT_CALIBRATED_FROM_PIXELS\"";
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

   bool source_dimensions_usable = (source_width >= 320 && source_main_height >= 160);
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
      server_time_seconds, server_utc_offset_seconds
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
   if(InpCaptureIntervalSeconds < 1 || InpHistoryBars < 1 ||
      InpScreenshotWidth < 320 || InpScreenshotHeight < 180)
      return INIT_PARAMETERS_INCORRECT;

   g_chart_id = ChartID();
   if(g_chart_id == 0)
      return INIT_FAILED;

   FolderCreate("MirsadBTC", 0);
   FolderCreate("MirsadBTC", FILE_COMMON);
   FolderCreate(g_observer_root, FILE_COMMON);
   FolderCreate(g_image_root, FILE_COMMON);

   MathSrand((int)GetTickCount());
   if(!EventSetTimer(1))
   {
      PrintFormat("Mirsad Observer: EventSetTimer failed. Error=%d", GetLastError());
      return INIT_FAILED;
   }

   g_next_capture_at_ms = InpCaptureImmediately
      ? GetTickCount64()
      : GetTickCount64() + (ulong)InpCaptureIntervalSeconds * 1000;

   PublishObserverStatus("STARTED", "",
                         "Read-only MT5 chart observer started on the attached chart.");
   PrintFormat("Mirsad Chart Observer started. Chart=%I64d Symbol=%s Timeframe=%s Interval=%d sec. No trading functions.",
               g_chart_id, ChartSymbol(g_chart_id),
               TimeframeLabel((ENUM_TIMEFRAMES)ChartPeriod(g_chart_id)),
               InpCaptureIntervalSeconds);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   PublishObserverStatus("STOPPED", g_pending_id,
                         StringFormat("Observer stopped. Reason=%d", reason));
}

void OnTimer()
{
   if(g_pending)
   {
      TryFinalizePendingCapture();
      return;
   }

   ulong now_tick = GetTickCount64();
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
