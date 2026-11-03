// Mirsad BTC - read-only telemetry bridge.
// It NEVER opens, modifies, or closes trades. Desktop/bridge integration is a later stage.
#property strict
#property version   "0.2.0"

input string InpBridgeUrl = "http://127.0.0.1:8000/api/v1/mt5/snapshot";
input int    InpTimerSeconds = 5;
input int    InpTimeoutMs = 2500;

string JsonEscape(const string value)
{
   string out=value;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   return out;
}

int OnInit()
{
   if(InpTimerSeconds < 1) return INIT_PARAMETERS_INCORRECT;
   EventSetTimer(InpTimerSeconds);
   Print("Mirsad BTC read-only bridge started. No trading functions are enabled.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
{
   string symbol=_Symbol;
   MqlTick tick;
   if(!SymbolInfoTick(symbol,tick)) return;
   string currency=AccountInfoString(ACCOUNT_CURRENCY);
   string server=AccountInfoString(ACCOUNT_SERVER);
   string iso_time=TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS);
   StringReplace(iso_time,".","-");
   StringReplace(iso_time," ","T");
   iso_time += "+00:00";
   string json=StringFormat(
      "{\"terminal_connected\":true,\"account_login\":\"%I64d\",\"server\":\"%s\",\"currency\":\"%s\",\"balance\":%.2f,\"equity\":%.2f,\"free_margin\":%.2f,\"symbol\":\"%s\",\"bid\":%.10f,\"ask\":%.10f,\"positions_count\":%d,\"terminal_time\":\"%s\"}",
      AccountInfoInteger(ACCOUNT_LOGIN), JsonEscape(server), JsonEscape(currency),
      AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE), JsonEscape(symbol), tick.bid, tick.ask,
      PositionsTotal(), iso_time);
   char data[]; char result[]; string result_headers;
   StringToCharArray(json,data,0,WHOLE_ARRAY,CP_UTF8);
   if(ArraySize(data)>0) ArrayResize(data,ArraySize(data)-1);
   string headers="Content-Type: application/json\r\n";
   ResetLastError();
   int code=WebRequest("POST",InpBridgeUrl,headers,InpTimeoutMs,data,result,result_headers);
   if(code<0) PrintFormat("Bridge telemetry failed; WebRequest error=%d. Allow localhost URL in terminal options.",GetLastError());
   else if(code!=200 && code!=201) PrintFormat("Bridge returned HTTP %d",code);
}
