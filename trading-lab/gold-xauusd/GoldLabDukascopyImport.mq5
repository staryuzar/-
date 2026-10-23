#property strict
#property script_show_inputs
#property version   "1.00"
#property description "Import and verify an external XAUUSD tick sample into an isolated MT5 custom symbol."

input string InpCsvFile       = "Dukascopy_XAUUSD_2026-03-26.csv";
input string InpOriginSymbol  = "XAUUSD";
input string InpCustomSymbol  = "XAUUSD_DK0326";
input string InpResultFile    = "GoldLabDukascopyImportResult.txt";

void ResultLine(const string line)
{
   Print("GoldLabImport|",line);
   int h=FileOpen(InpResultFile,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)
      h=FileOpen(InpResultFile,FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)
   {
      Print("GoldLabImport|RESULT_FILE_ERROR|",GetLastError());
      return;
   }
   FileSeek(h,0,SEEK_END);
   FileWriteString(h,line+"\r\n");
   FileFlush(h);
   FileClose(h);
}

void FailImport(const string reason)
{
   ResultLine("STATUS=FAIL;reason="+reason+";last_error="+IntegerToString(GetLastError()));
}

bool SetIntegerChecked(const string symbol,const ENUM_SYMBOL_INFO_INTEGER property,const long value)
{
   ResetLastError();
   if(!CustomSymbolSetInteger(symbol,property,value))
   {
      ResultLine("SET_INTEGER_FAILED;property="+EnumToString(property)+";value="+IntegerToString((int)value)+";error="+IntegerToString(GetLastError()));
      return(false);
   }
   return(true);
}

bool SetDoubleChecked(const string symbol,const ENUM_SYMBOL_INFO_DOUBLE property,const double value)
{
   ResetLastError();
   if(!CustomSymbolSetDouble(symbol,property,value))
   {
      ResultLine("SET_DOUBLE_FAILED;property="+EnumToString(property)+";value="+DoubleToString(value,8)+";error="+IntegerToString(GetLastError()));
      return(false);
   }
   return(true);
}

void OnStart()
{
   FileDelete(InpResultFile);
   ResultLine("STATUS=STARTED;script_version=1.00;source=Dukascopy;symbol="+InpCustomSymbol);

   if(!SymbolSelect(InpOriginSymbol,true))
   {
      FailImport("origin_symbol_not_selectable");
      return;
   }

   double contract=SymbolInfoDouble(InpOriginSymbol,SYMBOL_TRADE_CONTRACT_SIZE);
   double minLot=SymbolInfoDouble(InpOriginSymbol,SYMBOL_VOLUME_MIN);
   double maxLot=SymbolInfoDouble(InpOriginSymbol,SYMBOL_VOLUME_MAX);
   double lotStep=SymbolInfoDouble(InpOriginSymbol,SYMBOL_VOLUME_STEP);
   long execution=(long)SymbolInfoInteger(InpOriginSymbol,SYMBOL_TRADE_EXEMODE);
   long filling=(long)SymbolInfoInteger(InpOriginSymbol,SYMBOL_FILLING_MODE);
   long calcMode=(long)SymbolInfoInteger(InpOriginSymbol,SYMBOL_TRADE_CALC_MODE);
   long stops=(long)SymbolInfoInteger(InpOriginSymbol,SYMBOL_TRADE_STOPS_LEVEL);
   long freeze=(long)SymbolInfoInteger(InpOriginSymbol,SYMBOL_TRADE_FREEZE_LEVEL);

   if(contract<=0.0 || minLot<=0.0 || maxLot<minLot || lotStep<=0.0)
   {
      FailImport("origin_symbol_specifications_invalid");
      return;
   }

   bool wasCustom=false;
   if(SymbolExist(InpCustomSymbol,wasCustom))
   {
      if(!wasCustom)
      {
         FailImport("target_name_conflicts_with_broker_symbol");
         return;
      }
      SymbolSelect(InpCustomSymbol,false);
      ResetLastError();
      if(!CustomSymbolDelete(InpCustomSymbol))
      {
         FailImport("could_not_remove_previous_custom_symbol");
         return;
      }
   }

   ResetLastError();
   if(!CustomSymbolCreate(InpCustomSymbol,"GoldLab\\Dukascopy",InpOriginSymbol))
   {
      FailImport("custom_symbol_create_failed");
      return;
   }

   // Establish price precision and contract/risk metadata BEFORE importing ticks:
   // MT5 deletes custom history when digits, chart mode, point size, or tick size changes.
   bool specOk=true;
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_DIGITS,3);
   specOk &= SetDoubleChecked(InpCustomSymbol,SYMBOL_POINT,0.001);
   specOk &= SetDoubleChecked(InpCustomSymbol,SYMBOL_TRADE_TICK_SIZE,0.001);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_CHART_MODE,SYMBOL_CHART_MODE_BID);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_TRADE_MODE,SYMBOL_TRADE_MODE_FULL);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_TRADE_EXEMODE,execution);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_FILLING_MODE,filling);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_TRADE_CALC_MODE,calcMode);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_TRADE_STOPS_LEVEL,stops);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_TRADE_FREEZE_LEVEL,freeze);
   specOk &= SetIntegerChecked(InpCustomSymbol,SYMBOL_SPREAD_FLOAT,1);
   specOk &= SetDoubleChecked(InpCustomSymbol,SYMBOL_TRADE_CONTRACT_SIZE,contract);
   specOk &= SetDoubleChecked(InpCustomSymbol,SYMBOL_VOLUME_MIN,minLot);
   specOk &= SetDoubleChecked(InpCustomSymbol,SYMBOL_VOLUME_MAX,maxLot);
   specOk &= SetDoubleChecked(InpCustomSymbol,SYMBOL_VOLUME_STEP,lotStep);
   if(!specOk)
   {
      FailImport("custom_symbol_specification_setup_failed");
      return;
   }

   // Custom sessions are set to full-day windows. Actual availability remains defined by
   // the imported quote ticks; this avoids accidentally imposing Headway's session hours
   // on a historical sample from a different provider.
   for(int day=0;day<7;day++)
   {
      if(!CustomSymbolSetSessionQuote(InpCustomSymbol,(ENUM_DAY_OF_WEEK)day,0,(datetime)0,(datetime)86399))
      {
         FailImport("custom_quote_session_setup_failed_day_"+IntegerToString(day));
         return;
      }
      if(!CustomSymbolSetSessionTrade(InpCustomSymbol,(ENUM_DAY_OF_WEEK)day,0,(datetime)0,(datetime)86399))
      {
         FailImport("custom_trade_session_setup_failed_day_"+IntegerToString(day));
         return;
      }
   }

   if(!SymbolSelect(InpCustomSymbol,true))
   {
      FailImport("custom_symbol_select_failed");
      return;
   }

   // A $1 price move at 0.01 lot should imply a cash result near contract*0.01.
   // Verify the custom symbol's calculation mode before accepting the imported history.
   double riskProbe=0.0;
   ResetLastError();
   if(!OrderCalcProfit(ORDER_TYPE_BUY,InpCustomSymbol,0.01,4500.000,4499.000,riskProbe))
   {
      FailImport("custom_order_calc_profit_failed");
      return;
   }
   double expectedRisk=contract*0.01;
   if(expectedRisk<=0.0 || MathAbs(riskProbe)<expectedRisk*0.50 || MathAbs(riskProbe)>expectedRisk*2.00)
   {
      ResultLine("RISK_PROBE_OUT_OF_RANGE;contract="+DoubleToString(contract,4)+";expected_abs="+DoubleToString(expectedRisk,4)+";observed="+DoubleToString(riskProbe,4));
      FailImport("custom_symbol_profit_calculation_mismatch");
      return;
   }

   ResetLastError();
   int f=FileOpen(InpCsvFile,FILE_READ|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',');
   if(f==INVALID_HANDLE)
   {
      FailImport("input_csv_open_failed_"+IntegerToString(GetLastError()));
      return;
   }

   string h1=FileReadString(f);
   string h2=FileReadString(f);
   string h3=FileReadString(f);
   StringToLower(h1); StringToLower(h2); StringToLower(h3);
   if(h1!="timestamp" || h2!="askprice" || h3!="bidprice")
   {
      FileClose(f);
      ResultLine("CSV_HEADER_INVALID;field1="+h1+";field2="+h2+";field3="+h3);
      FailImport("unexpected_csv_header");
      return;
   }

   int capacity=100000;
   MqlTick ticks[];
   if(ArrayResize(ticks,capacity,capacity)<capacity)
   {
      FileClose(f);
      FailImport("initial_tick_array_allocation_failed");
      return;
   }

   int count=0;
   int invalidRows=0;
   long previousMs=0;
   double minBid=DBL_MAX, maxBid=0.0, minAsk=DBL_MAX, maxAsk=0.0;
   while(!FileIsEnding(f))
   {
      string tsText=FileReadString(f);
      if(tsText=="" && FileIsEnding(f))
         break;
      string askText=FileReadString(f);
      string bidText=FileReadString(f);
      if(tsText=="" && askText=="" && bidText=="")
      {
         if(FileIsEnding(f)) break;
         continue;
      }

      long stamp=StringToInteger(tsText);
      double ask=StringToDouble(askText);
      double bid=StringToDouble(bidText);
      if(stamp<=0 || !MathIsValidNumber(ask) || !MathIsValidNumber(bid) || bid<=0.0 || ask<bid)
      {
         invalidRows++;
         FileClose(f);
         ResultLine("INVALID_ROW;row="+IntegerToString(count+invalidRows)+";timestamp="+tsText+";ask="+askText+";bid="+bidText);
         FailImport("invalid_tick_row");
         return;
      }
      if(count>0 && stamp<previousMs)
      {
         FileClose(f);
         ResultLine("NONMONOTONIC_TIMESTAMP;previous="+(string)previousMs+";current="+(string)stamp);
         FailImport("tick_timestamps_not_ascending");
         return;
      }

      if(count>=capacity)
      {
         int nextCapacity=capacity*2;
         if(nextCapacity>3000000 || ArrayResize(ticks,nextCapacity,capacity)<nextCapacity)
         {
            FileClose(f);
            FailImport("tick_array_growth_failed_or_limit_exceeded");
            return;
         }
         capacity=nextCapacity;
      }

      ticks[count].time_msc=stamp;
      ticks[count].time=(datetime)(stamp/1000);
      ticks[count].bid=bid;
      ticks[count].ask=ask;
      ticks[count].last=0.0;
      ticks[count].volume=0;
      ticks[count].volume_real=0.0;
      ticks[count].flags=TICK_FLAG_BID|TICK_FLAG_ASK;

      if(bid<minBid) minBid=bid;
      if(bid>maxBid) maxBid=bid;
      if(ask<minAsk) minAsk=ask;
      if(ask>maxAsk) maxAsk=ask;
      previousMs=stamp;
      count++;
   }
   FileClose(f);

   if(count<1000)
   {
      FailImport("valid_tick_count_below_1000");
      return;
   }
   if(ArrayResize(ticks,count)<count)
   {
      FailImport("tick_array_shrink_failed");
      return;
   }

   long firstMs=ticks[0].time_msc;
   long lastMs=ticks[count-1].time_msc;
   ResultLine("CSV_PARSED;tick_count="+IntegerToString(count)+";invalid_rows="+IntegerToString(invalidRows)+
              ";first_epoch_ms="+(string)firstMs+";last_epoch_ms="+(string)lastMs+
              ";bid_min="+DoubleToString(minBid,3)+";bid_max="+DoubleToString(maxBid,3)+
              ";ask_min="+DoubleToString(minAsk,3)+";ask_max="+DoubleToString(maxAsk,3));

   ResetLastError();
   int imported=CustomTicksReplace(InpCustomSymbol,firstMs,lastMs,ticks,(uint)count);
   if(imported!=(int)count)
   {
      ResultLine("CUSTOM_TICKS_REPLACE_FAILED;expected="+IntegerToString(count)+";actual="+IntegerToString(imported)+";error="+IntegerToString(GetLastError()));
      FailImport("custom_ticks_replace_count_mismatch");
      return;
   }

   MqlTick verifyTicks[];
   if(ArrayResize(verifyTicks,count)<count)
   {
      FailImport("verification_tick_array_allocation_failed");
      return;
   }
   ResetLastError();
   int verified=CopyTicksRange(InpCustomSymbol,verifyTicks,COPY_TICKS_ALL,(ulong)firstMs,(ulong)lastMs);
   if(verified!=(int)count)
   {
      ResultLine("COPY_TICKS_RANGE_MISMATCH;expected="+IntegerToString(count)+";actual="+IntegerToString(verified)+";error="+IntegerToString(GetLastError()));
      FailImport("imported_tick_readback_count_mismatch");
      return;
   }
   if(verifyTicks[0].time_msc!=firstMs || verifyTicks[verified-1].time_msc!=lastMs)
   {
      FailImport("imported_tick_readback_boundary_mismatch");
      return;
   }

   MqlRates rates[];
   ResetLastError();
   int m1Bars=CopyRates(InpCustomSymbol,PERIOD_M1,ticks[0].time,ticks[count-1].time,rates);
   if(m1Bars<1000)
   {
      ResultLine("M1_HISTORY_TOO_SHORT;bars="+IntegerToString(m1Bars)+";error="+IntegerToString(GetLastError()));
      FailImport("minute_bars_not_formed_from_ticks");
      return;
   }

   ResultLine("STATUS=PASS;target_symbol="+InpCustomSymbol+
              ";origin_symbol="+InpOriginSymbol+
              ";source=Dukascopy;valid_ticks="+IntegerToString(count)+
              ";custom_ticks_replace="+IntegerToString(imported)+
              ";copyticksrange_readback="+IntegerToString(verified)+
              ";m1_bars="+IntegerToString(m1Bars)+
              ";first_epoch_ms="+(string)firstMs+";last_epoch_ms="+(string)lastMs+
              ";digits="+IntegerToString((int)SymbolInfoInteger(InpCustomSymbol,SYMBOL_DIGITS))+
              ";point="+DoubleToString(SymbolInfoDouble(InpCustomSymbol,SYMBOL_POINT),6)+
              ";tick_size="+DoubleToString(SymbolInfoDouble(InpCustomSymbol,SYMBOL_TRADE_TICK_SIZE),6)+
              ";contract_size="+DoubleToString(SymbolInfoDouble(InpCustomSymbol,SYMBOL_TRADE_CONTRACT_SIZE),4)+
              ";risk_probe_for_1usd_move_at_0.01_lot="+DoubleToString(riskProbe,4));
   Print("GoldLabImport|IMPORT COMPLETE; verified tick history is stored in the custom-symbol database.");
}
