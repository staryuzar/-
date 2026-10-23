#property strict
#property version "1.00"
#property description "Imports independently validated Dukascopy XAUUSD M1 warm-up bars and ticks into an isolated MT5 custom symbol."

input string InpCustomSymbol = "XAUUSD_DUKA";
input string InpRatesFile = "dukascopy-m1.csv";
input string InpTicksFile = "dukascopy-tick.csv";
input string InpResultFile = "dukascopy-import-result.txt";

int g_result = INVALID_HANDLE;

void ResultLine(const string value)
{
   if(g_result != INVALID_HANDLE)
      FileWrite(g_result,value);
   Print("DUKASCOPY_IMPORT|",value);
}

void Fail(const string reason)
{
   ResultLine("status=FAIL");
   ResultLine("reason="+reason);
   if(g_result != INVALID_HANDLE)
   {
      FileFlush(g_result);
      FileClose(g_result);
      g_result=INVALID_HANDLE;
   }
}

bool LoadRates(MqlRates &rates[],long &first_time,long &last_time)
{
   int file=FileOpen(InpRatesFile,FILE_READ|FILE_CSV|FILE_ANSI,',');
   if(file==INVALID_HANDLE)
   {
      ResultLine("rates_file_open_error="+IntegerToString(GetLastError()));
      return false;
   }

   // Dukascopy CSV header: timestamp,open,high,low,close,volume
   for(int h=0;h<6 && !FileIsEnding(file);h++)
      FileReadString(file);

   ArrayResize(rates,0,20000);
   first_time=0;
   last_time=0;
   long previous=0;
   int bad=0;

   while(!FileIsEnding(file))
   {
      string ts_text=FileReadString(file);
      if(ts_text=="")
      {
         if(FileIsEnding(file)) break;
         continue;
      }
      string open_text=FileReadString(file);
      string high_text=FileReadString(file);
      string low_text=FileReadString(file);
      string close_text=FileReadString(file);
      string volume_text=FileReadString(file);

      long stamp=(long)StringToInteger(ts_text);
      if(stamp>1000000000000) stamp/=1000;
      double o=StringToDouble(open_text);
      double h=StringToDouble(high_text);
      double l=StringToDouble(low_text);
      double c=StringToDouble(close_text);
      long vol=(long)StringToInteger(volume_text);

      if(stamp<=0 || o<=0 || h<=0 || l<=0 || c<=0 || h<l ||
         (o<l || o>h || c<l || c>h) ||
         (previous>0 && stamp<=previous))
      {
         bad++;
         continue;
      }

      int n=ArraySize(rates);
      if(ArrayResize(rates,n+1,20000)!=n+1)
      {
         FileClose(file);
         ResultLine("rates_array_resize_failed_at="+IntegerToString(n));
         return false;
      }
      rates[n].time=(datetime)stamp;
      rates[n].open=o;
      rates[n].high=h;
      rates[n].low=l;
      rates[n].close=c;
      rates[n].tick_volume=(vol>0 ? vol : 0);
      rates[n].spread=0;
      rates[n].real_volume=(vol>0 ? vol : 0);
      if(first_time==0) first_time=stamp;
      last_time=stamp;
      previous=stamp;
   }
   FileClose(file);
   ResultLine("rates_rows="+IntegerToString(ArraySize(rates)));
   ResultLine("rates_bad_rows="+IntegerToString(bad));
   ResultLine("rates_first_epoch="+IntegerToString(first_time));
   ResultLine("rates_last_epoch="+IntegerToString(last_time));
   return (ArraySize(rates)>=15000 && bad==0 && first_time>0 && last_time>first_time);
}

bool LoadTicks(MqlTick &ticks[],long &first_msc,long &last_msc)
{
   int file=FileOpen(InpTicksFile,FILE_READ|FILE_CSV|FILE_ANSI,',');
   if(file==INVALID_HANDLE)
   {
      ResultLine("ticks_file_open_error="+IntegerToString(GetLastError()));
      return false;
   }

   // Dukascopy CSV header: timestamp,askPrice,bidPrice
   for(int h=0;h<3 && !FileIsEnding(file);h++)
      FileReadString(file);

   ArrayResize(ticks,0,20000);
   first_msc=0;
   last_msc=0;
   long previous=0;
   int bad=0;

   while(!FileIsEnding(file))
   {
      string ts_text=FileReadString(file);
      if(ts_text=="")
      {
         if(FileIsEnding(file)) break;
         continue;
      }
      string ask_text=FileReadString(file);
      string bid_text=FileReadString(file);
      long stamp=(long)StringToInteger(ts_text);
      double ask=StringToDouble(ask_text);
      double bid=StringToDouble(bid_text);

      if(stamp<=0 || bid<=0 || ask<bid || (previous>0 && stamp<previous))
      {
         bad++;
         continue;
      }

      int n=ArraySize(ticks);
      if(ArrayResize(ticks,n+1,20000)!=n+1)
      {
         FileClose(file);
         ResultLine("ticks_array_resize_failed_at="+IntegerToString(n));
         return false;
      }
      ticks[n].time_msc=stamp;
      ticks[n].time=(datetime)(stamp/1000);
      ticks[n].bid=bid;
      ticks[n].ask=ask;
      ticks[n].last=0.0;
      ticks[n].volume=0;
      ticks[n].volume_real=0.0;
      ticks[n].flags=(uint)(TICK_FLAG_BID|TICK_FLAG_ASK);
      if(first_msc==0) first_msc=stamp;
      last_msc=stamp;
      previous=stamp;
   }
   FileClose(file);
   ResultLine("ticks_rows="+IntegerToString(ArraySize(ticks)));
   ResultLine("ticks_bad_rows="+IntegerToString(bad));
   ResultLine("ticks_first_msc="+IntegerToString(first_msc));
   ResultLine("ticks_last_msc="+IntegerToString(last_msc));
   return (ArraySize(ticks)>=400000 && bad==0 && first_msc>0 && last_msc>first_msc);
}

void OnStart()
{
   g_result=FileOpen(InpResultFile,FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(g_result==INVALID_HANDLE)
   {
      Print("DUKASCOPY_IMPORT|Cannot create result file; error=",GetLastError());
      return;
   }

   ResultLine("status=STARTED");
   ResultLine("symbol="+InpCustomSymbol);
   if(!SymbolSelect("XAUUSD",true))
   {
      Fail("broker_origin_symbol_unavailable");
      return;
   }

   if(SymbolInfoDouble("XAUUSD",SYMBOL_POINT)<=0.0)
   {
      Fail("origin_symbol_has_invalid_point");
      return;
   }

   if(SymbolInfoInteger(InpCustomSymbol,SYMBOL_EXIST))
   {
      if(!CustomSymbolDelete(InpCustomSymbol))
      {
         Fail("cannot_delete_previous_custom_symbol_"+IntegerToString(GetLastError()));
         return;
      }
   }

   ResetLastError();
   if(!CustomSymbolCreate(InpCustomSymbol,"GoldLab","XAUUSD"))
   {
      Fail("custom_symbol_create_error_"+IntegerToString(GetLastError()));
      return;
   }

   if(!CustomSymbolSetInteger(InpCustomSymbol,SYMBOL_DIGITS,3) ||
      !CustomSymbolSetDouble(InpCustomSymbol,SYMBOL_POINT,0.001) ||
      !CustomSymbolSetDouble(InpCustomSymbol,SYMBOL_TRADE_TICK_SIZE,0.001) ||
      !CustomSymbolSetInteger(InpCustomSymbol,SYMBOL_SPREAD_FLOAT,true) ||
      !CustomSymbolSetInteger(InpCustomSymbol,SYMBOL_TRADE_MODE,SYMBOL_TRADE_MODE_FULL))
   {
      Fail("custom_symbol_property_setup_error_"+IntegerToString(GetLastError()));
      return;
   }
   if(!SymbolSelect(InpCustomSymbol,true))
   {
      Fail("custom_symbol_select_error_"+IntegerToString(GetLastError()));
      return;
   }
   if(MathAbs(SymbolInfoDouble(InpCustomSymbol,SYMBOL_POINT)-0.001)>0.0000001 ||
      MathAbs(SymbolInfoDouble(InpCustomSymbol,SYMBOL_TRADE_TICK_SIZE)-0.001)>0.0000001 ||
      SymbolInfoInteger(InpCustomSymbol,SYMBOL_DIGITS)!=3)
   {
      Fail("custom_symbol_point_or_tick_size_mismatch");
      return;
   }

   MqlRates rates[];
   long first_rate=0,last_rate=0;
   if(!LoadRates(rates,first_rate,last_rate))
   {
      Fail("warmup_rates_validation_failed");
      return;
   }

   ResetLastError();
   int rates_added=CustomRatesUpdate(InpCustomSymbol,rates,(uint)ArraySize(rates));
   ResultLine("rates_imported="+IntegerToString(rates_added));
   if(rates_added<15000)
   {
      Fail("custom_rates_update_incomplete_"+IntegerToString(GetLastError()));
      return;
   }

   MqlTick ticks[];
   long first_tick=0,last_tick=0;
   if(!LoadTicks(ticks,first_tick,last_tick))
   {
      Fail("tick_validation_failed");
      return;
   }

   ResetLastError();
   int ticks_added=CustomTicksReplace(InpCustomSymbol,first_tick,last_tick+1,ticks,(uint)ArraySize(ticks));
   ResultLine("ticks_imported="+IntegerToString(ticks_added));
   if(ticks_added!=ArraySize(ticks))
   {
      Fail("custom_ticks_replace_count_mismatch_"+IntegerToString(GetLastError()));
      return;
   }

   if(!SymbolSelect(InpCustomSymbol,true))
   {
      Fail("custom_symbol_select_failed_"+IntegerToString(GetLastError()));
      return;
   }

   ResultLine("symbol_digits="+IntegerToString((int)SymbolInfoInteger(InpCustomSymbol,SYMBOL_DIGITS)));
   ResultLine("symbol_point="+DoubleToString(SymbolInfoDouble(InpCustomSymbol,SYMBOL_POINT),6));
   ResultLine("symbol_tick_size="+DoubleToString(SymbolInfoDouble(InpCustomSymbol,SYMBOL_TRADE_TICK_SIZE),6));
   ResultLine("symbol_volume_min="+DoubleToString(SymbolInfoDouble(InpCustomSymbol,SYMBOL_VOLUME_MIN),2));
   ResultLine("symbol_volume_step="+DoubleToString(SymbolInfoDouble(InpCustomSymbol,SYMBOL_VOLUME_STEP),2));
   ResultLine("status=PASS");

   FileFlush(g_result);
   FileClose(g_result);
   g_result=INVALID_HANDLE;
}
