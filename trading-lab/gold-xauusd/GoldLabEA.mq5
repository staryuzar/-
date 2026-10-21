#property strict
#property version   "1.009"
#property description "GoldLab XAUUSD research candidate; demo/backtest only"



input ulong            InpMagic              = 2026102101;
input ENUM_TIMEFRAMES  InpEntryTF             = PERIOD_M5;
input ENUM_TIMEFRAMES  InpBiasTF              = PERIOD_H1;
input double           InpRiskPercent         = 0.50;
input int              InpFastEMA             = 20;
input int              InpSlowEMA             = 50;
input int              InpBiasFastEMA         = 50;
input int              InpBiasSlowEMA         = 200;
input int              InpRSIPeriod           = 14;
input double           InpRSIMidline          = 50.0;
input int              InpADXPeriod           = 14;
input double           InpMinADX              = 18.0;
input double           InpMaxADX              = 40.0;
input bool             InpAllowLong            = true;
input double           InpMaxSpreadPoints      = 100.0;
input int              InpATRPeriod           = 14;
input double           InpStopATR             = 1.8;
input double           InpTargetATR           = 2.4;
input double           InpTrailATR             = 1.4;
input bool             InpCloseOnOpposite     = true;
input bool             InpWriteTradeCSV       = true;
input bool             InpRequireSignalCandleDirection = false;
input bool             InpRequireFastEMARejection = false;

uint lastTradeRetcode=0;
string lastTradeMessage="";
int hFast=INVALID_HANDLE, hSlow=INVALID_HANDLE;
int hBiasFast=INVALID_HANDLE, hBiasSlow=INVALID_HANDLE;
int hRSI=INVALID_HANDLE, hADX=INVALID_HANDLE, hATR=INVALID_HANDLE;
datetime lastBar=0;
string tradeLogName="GoldLab_trade_audit.csv";


bool TradeRetcodeAccepted(const uint code)
{
   return (code==TRADE_RETCODE_DONE || code==TRADE_RETCODE_DONE_PARTIAL || code==TRADE_RETCODE_PLACED);
}
string TradeRetcodeLabel(const uint code)
{
   if(code==TRADE_RETCODE_DONE) return "FILLED";
   if(code==TRADE_RETCODE_DONE_PARTIAL) return "PARTIAL_FILL";
   if(code==TRADE_RETCODE_PLACED) return "ACCEPTED_PENDING";
   return "REJECTED_OR_UNKNOWN";
}
bool GetSupportedFillingMode(ENUM_ORDER_TYPE_FILLING &mode)
{
   long flags=SymbolInfoInteger(_Symbol,SYMBOL_FILLING_MODE);
   ENUM_SYMBOL_TRADE_EXECUTION execution=(ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_EXEMODE);
   // RETURN is not permitted by MT5 for Market Execution. Only select a mode the symbol advertises.
   if(execution==SYMBOL_TRADE_EXECUTION_MARKET)
   {
      if((flags & SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK) { mode=ORDER_FILLING_FOK; return true; }
      if((flags & SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC) { mode=ORDER_FILLING_IOC; return true; }
      lastTradeRetcode=0;
      lastTradeMessage="UNSUPPORTED_FILLING_MODE; execution=MARKET; flags="+IntegerToString((int)flags);
      return false;
   }
   mode=ORDER_FILLING_RETURN;
   return true;
}
bool SendCheckedRequest(MqlTradeRequest &request)
{
   MqlTradeCheckResult check;
   MqlTradeResult result;
   ZeroMemory(check); ZeroMemory(result);
   ResetLastError();
   if(!OrderCheck(request,check))
   {
      int err=GetLastError();
      lastTradeRetcode=check.retcode;
      lastTradeMessage="ORDERCHECK_API_FAILED; retcode="+IntegerToString((int)check.retcode)+
                       "; error="+IntegerToString(err)+"; "+check.comment;
      return false;
   }
   // Successful OrderCheck commonly reports retcode=0; tolerate DONE for terminal/build variants.
   if(check.retcode!=0 && check.retcode!=TRADE_RETCODE_DONE)
   {
      lastTradeRetcode=check.retcode;
      lastTradeMessage="ORDERCHECK_REJECTED; retcode="+IntegerToString((int)check.retcode)+
                       "; "+check.comment;
      return false;
   }

   ResetLastError();
   bool sent=OrderSend(request,result);
   lastTradeRetcode=result.retcode;
   lastTradeMessage="state="+TradeRetcodeLabel(result.retcode)+
                    "; retcode="+IntegerToString((int)result.retcode)+
                    "; comment="+result.comment;
   if(!sent)
      lastTradeMessage="ORDERSEND_API_FAILED; error="+IntegerToString(GetLastError())+
                       "; "+lastTradeMessage;
   return (sent && TradeRetcodeAccepted(result.retcode));
}
bool HasActiveOrderForSymbolMagic()
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong orderTicket=OrderGetTicket(i);
      if(orderTicket==0) continue;
      if(OrderGetString(ORDER_SYMBOL)==_Symbol &&
         (ulong)OrderGetInteger(ORDER_MAGIC)==InpMagic)
         return true;
   }
   return false;
}
bool SendMarketOrder(const ENUM_ORDER_TYPE type,const double lots,const double sl,const double tp,const string comment)
{
   MqlTradeRequest request;
   ZeroMemory(request);
   ENUM_ORDER_TYPE_FILLING filling;
   if(!GetSupportedFillingMode(filling)) return false;
   request.action=TRADE_ACTION_DEAL; request.symbol=_Symbol; request.magic=InpMagic;
   request.volume=lots; request.type=type;
   request.price=(type==ORDER_TYPE_BUY ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID));
   request.sl=sl; request.tp=tp; request.deviation=20; request.type_filling=filling;
   request.type_time=ORDER_TIME_GTC; request.comment=comment;
   return SendCheckedRequest(request);
}
bool ClosePositionByTicket(const ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) { lastTradeMessage="POSITION_NOT_FOUND"; return false; }
   if(HasActiveOrderForSymbolMagic())
   {
      lastTradeRetcode=TRADE_RETCODE_PLACED;
      lastTradeMessage="CLOSE_DEFERRED; active order already exists for this symbol/magic";
      return true;
   }
   ENUM_POSITION_TYPE side=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double volume=PositionGetDouble(POSITION_VOLUME);
   MqlTradeRequest request; ZeroMemory(request);
   request.action=TRADE_ACTION_DEAL; request.position=ticket;
   request.symbol=PositionGetString(POSITION_SYMBOL); request.magic=InpMagic; request.volume=volume;
   request.type=(side==POSITION_TYPE_BUY ? ORDER_TYPE_SELL : ORDER_TYPE_BUY);
   request.price=(side==POSITION_TYPE_BUY ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK));
   request.deviation=20;
   ENUM_ORDER_TYPE_FILLING filling;
   if(!GetSupportedFillingMode(filling)) return false;
   request.type_filling=filling; request.type_time=ORDER_TIME_GTC;
   request.comment="GoldLab opposite-signal close";
   return SendCheckedRequest(request);
}
bool ModifyPositionSLTP(const ulong ticket,const double sl,const double tp)
{
   if(!PositionSelectByTicket(ticket)) { lastTradeMessage="POSITION_NOT_FOUND"; return false; }
   MqlTradeRequest request; ZeroMemory(request);
   request.action=TRADE_ACTION_SLTP; request.position=ticket;
   request.symbol=PositionGetString(POSITION_SYMBOL); request.magic=InpMagic; request.sl=sl; request.tp=tp;
   return SendCheckedRequest(request) && lastTradeRetcode==TRADE_RETCODE_DONE;
}

bool ReadValue(const int handle,const int buffer,const int shift,double &value)
{
   double data[];
   ArraySetAsSeries(data,true);
   if(handle==INVALID_HANDLE || CopyBuffer(handle,buffer,shift,1,data)!=1)
      return false;
   value=data[0];
   return MathIsValidNumber(value);
}

double RoundToTick(const double price)
{
   double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   if(tick<=0.0) return NormalizeDouble(price,digits);
   return NormalizeDouble(MathRound(price/tick)*tick,digits);
}

double NormalizeVolumeDown(double lots)
{
   double vmin=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0.0 || vmin<=0.0 || vmax<vmin) return 0.0;
   lots=MathMin(lots,vmax);
   lots=MathFloor((lots+1e-10)/step)*step;
   if(lots<vmin) return 0.0;
   int decimals=2;
   if(step<0.01) decimals=3;
   if(step<0.001) decimals=4;
   return NormalizeDouble(lots,decimals);
}

double LotsForRisk(const ENUM_ORDER_TYPE type,const double entry,const double stop)
{
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney=equity*InpRiskPercent/100.0;
   double lossOneLot=0.0;
   if(riskMoney<=0.0 || !OrderCalcProfit(type,_Symbol,1.0,entry,stop,lossOneLot))
      return 0.0;
   lossOneLot=MathAbs(lossOneLot);
   if(lossOneLot<=0.0) return 0.0;
   return NormalizeVolumeDown(riskMoney/lossOneLot);
}

string RiskRejectDetail(const ENUM_ORDER_TYPE type,const double entry,const double stop)
{
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney=equity*InpRiskPercent/100.0;
   double oneLotLoss=0.0, minLotLoss=0.0;
   double minLot=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   bool oneOk=OrderCalcProfit(type,_Symbol,1.0,entry,stop,oneLotLoss);
   bool minOk=(minLot>0.0 && OrderCalcProfit(type,_Symbol,minLot,entry,stop,minLotLoss));
   double rawLots=(oneOk && MathAbs(oneLotLoss)>0.0 ? riskMoney/MathAbs(oneLotLoss) : 0.0);
   return "risk_budget="+DoubleToString(riskMoney,2)+
          ";raw_lots="+DoubleToString(rawLots,4)+
          ";min_lot="+DoubleToString(minLot,2)+
          ";min_lot_risk="+(minOk ? DoubleToString(MathAbs(minLotLoss),2) : "calc_failed")+
          ";equity="+DoubleToString(equity,2)+
          ";risk_pct="+DoubleToString(InpRiskPercent,2);
}

bool IsNewBar()
{
   datetime t=iTime(_Symbol,InpEntryTF,0);
   if(t<=0 || t==lastBar) return false;
   return true;
}

void LogEvent(const string event,const string detail)
{
   Print("GoldLab|",event,"|",_Symbol,"|",detail);
}

void AppendDealRow(const ulong deal)
{
   if(!InpWriteTradeCSV || deal==0) return;
   if(!HistoryDealSelect(deal)) return;
   int file=FileOpen(tradeLogName,FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',');
   if(file==INVALID_HANDLE) {
      // Do not fall back to FILE_WRITE: that mode truncates an existing audit CSV.
      Print("GoldLab: cannot open audit CSV safely; error=",GetLastError());
      return;
   }
   // FILE_READ|FILE_WRITE creates a missing file; therefore FileOpen may succeed
   // on a new empty file and the header must be selected by size, not by open failure.
   if(FileSize(file)==0) {
      FileWrite(file,"deal","time","symbol","entry","type","volume","price","profit","commission","swap","reason","position_id");
   } else {
      FileSeek(file,0,SEEK_END);
   }
   FileWrite(file,
      (string)deal,
      TimeToString((datetime)HistoryDealGetInteger(deal,DEAL_TIME),TIME_DATE|TIME_SECONDS),
      HistoryDealGetString(deal,DEAL_SYMBOL),
      (string)HistoryDealGetInteger(deal,DEAL_ENTRY),
      (string)HistoryDealGetInteger(deal,DEAL_TYPE),
      DoubleToString(HistoryDealGetDouble(deal,DEAL_VOLUME),2),
      DoubleToString(HistoryDealGetDouble(deal,DEAL_PRICE),_Digits),
      DoubleToString(HistoryDealGetDouble(deal,DEAL_PROFIT),2),
      DoubleToString(HistoryDealGetDouble(deal,DEAL_COMMISSION),2),
      DoubleToString(HistoryDealGetDouble(deal,DEAL_SWAP),2),
      (string)HistoryDealGetInteger(deal,DEAL_REASON),
      (string)HistoryDealGetInteger(deal,DEAL_POSITION_ID));
   FileClose(file);
}

int OnInit()
{
   // Research builds are demo/live-safe: reject real accounts in live terminal execution,
   // but do not block historical Strategy Tester runs on the selected account context.
   ENUM_ACCOUNT_TRADE_MODE accountMode=(ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   bool testerMode=(bool)MQLInfoInteger(MQL_TESTER) || (bool)MQLInfoInteger(MQL_OPTIMIZATION);
   if(accountMode==ACCOUNT_TRADE_MODE_REAL && !testerMode)
   {
      Print("GoldLab: live execution on a real account is disabled in this research build; initialization refused.");
      return INIT_FAILED;
   }

   if(InpRiskPercent<=0.0 || InpRiskPercent>2.0 || InpFastEMA<2 || InpSlowEMA<=InpFastEMA ||
      InpBiasFastEMA<2 || InpBiasSlowEMA<=InpBiasFastEMA || InpStopATR<=0.0 ||
      InpTargetATR<=0.0 || InpATRPeriod<2 || InpRSIPeriod<2 || InpADXPeriod<2 ||
      InpMinADX<=0.0 || InpMaxADX<InpMinADX || InpMaxSpreadPoints<=0.0)
   {
      Print("GoldLab: invalid input parameters.");
      return INIT_PARAMETERS_INCORRECT;
   }

   hFast=iMA(_Symbol,InpEntryTF,InpFastEMA,0,MODE_EMA,PRICE_CLOSE);
   hSlow=iMA(_Symbol,InpEntryTF,InpSlowEMA,0,MODE_EMA,PRICE_CLOSE);
   hBiasFast=iMA(_Symbol,InpBiasTF,InpBiasFastEMA,0,MODE_EMA,PRICE_CLOSE);
   hBiasSlow=iMA(_Symbol,InpBiasTF,InpBiasSlowEMA,0,MODE_EMA,PRICE_CLOSE);
   hRSI=iRSI(_Symbol,InpEntryTF,InpRSIPeriod,PRICE_CLOSE);
   hADX=iADX(_Symbol,InpEntryTF,InpADXPeriod);
   hATR=iATR(_Symbol,InpEntryTF,InpATRPeriod);

   if(hFast==INVALID_HANDLE || hSlow==INVALID_HANDLE || hBiasFast==INVALID_HANDLE ||
      hBiasSlow==INVALID_HANDLE || hRSI==INVALID_HANDLE || hADX==INVALID_HANDLE || hATR==INVALID_HANDLE)
   {
      Print("GoldLab: indicator initialization failed; error=",GetLastError());
      return INIT_FAILED;
   }

   LogEvent("INIT","Execution-safety candidate v1.010; real-account live execution disabled; OrderCheck enabled; fill-mode validation enabled; filled/partial/pending retcodes separated; opposite exits are not blocked by spread.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(hFast!=INVALID_HANDLE) IndicatorRelease(hFast);
   if(hSlow!=INVALID_HANDLE) IndicatorRelease(hSlow);
   if(hBiasFast!=INVALID_HANDLE) IndicatorRelease(hBiasFast);
   if(hBiasSlow!=INVALID_HANDLE) IndicatorRelease(hBiasSlow);
   if(hRSI!=INVALID_HANDLE) IndicatorRelease(hRSI);
   if(hADX!=INVALID_HANDLE) IndicatorRelease(hADX);
   if(hATR!=INVALID_HANDLE) IndicatorRelease(hATR);
}

void ManagePositions(const double atr,const bool longSignal,const bool shortSignal)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol ||
         (ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;

      ENUM_POSITION_TYPE side=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double open=PositionGetDouble(POSITION_PRICE_OPEN);
      double oldSL=PositionGetDouble(POSITION_SL);
      double tp=PositionGetDouble(POSITION_TP);
      double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double stopLevel=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;

      if(InpCloseOnOpposite && ((side==POSITION_TYPE_BUY && shortSignal) ||
                                (side==POSITION_TYPE_SELL && longSignal)))
      {
         if(!ClosePositionByTicket(ticket))
            LogEvent("CLOSE_FAIL",("retcode="+IntegerToString((int)lastTradeRetcode)+"; "+lastTradeMessage));
         else if(lastTradeRetcode==TRADE_RETCODE_PLACED)
            LogEvent("CLOSE_PENDING",lastTradeMessage);
         else if(lastTradeRetcode==TRADE_RETCODE_DONE_PARTIAL)
            LogEvent("CLOSE_PARTIAL",lastTradeMessage);
         else
            LogEvent("CLOSE_FILLED",lastTradeMessage);
         continue;
      }

      if(atr<=0.0 || InpTrailATR<=0.0) continue;
      if(side==POSITION_TYPE_BUY)
      {
         double gain=bid-open;
         if(gain<atr) continue;
         double newSL=RoundToTick(bid-InpTrailATR*atr);
         if(newSL>oldSL && newSL<bid-stopLevel)
            if(!ModifyPositionSLTP(ticket,newSL,tp))
               LogEvent("TRAIL_FAIL",("retcode="+IntegerToString((int)lastTradeRetcode)+"; "+lastTradeMessage));
      }
      else if(side==POSITION_TYPE_SELL)
      {
         double gain=open-ask;
         if(gain<atr) continue;
         double newSL=RoundToTick(ask+InpTrailATR*atr);
         if((oldSL==0.0 || newSL<oldSL) && newSL>ask+stopLevel)
            if(!ModifyPositionSLTP(ticket,newSL,tp))
               LogEvent("TRAIL_FAIL",("retcode="+IntegerToString((int)lastTradeRetcode)));
      }
   }
}

void OnTick()
{
   // Manage an existing position on every incoming tick; signal evaluation remains once per completed M5 bar.
   // This avoids updating the ATR trail only once every five minutes.
   double managementATR=0.0;
   if(hATR!=INVALID_HANDLE && ReadValue(hATR,0,1,managementATR) && managementATR>0.0)
      ManagePositions(managementATR,false,false);

   if(!IsNewBar()) return;
   if(Bars(_Symbol,InpEntryTF)<MathMax(InpSlowEMA,InpATRPeriod)+5 ||
      Bars(_Symbol,InpBiasTF)<InpBiasSlowEMA+5) return;

   double fast1,slow1,biasFast,biasSlow,rsi1,rsi2,adx,atr;
   double candleOpen1=iOpen(_Symbol,InpEntryTF,1);
   double candleClose1=iClose(_Symbol,InpEntryTF,1);
   double candleHigh1=iHigh(_Symbol,InpEntryTF,1);
   double candleLow1=iLow(_Symbol,InpEntryTF,1);
   if(!ReadValue(hFast,0,1,fast1) ||
      !ReadValue(hSlow,0,1,slow1) || !ReadValue(hBiasFast,0,1,biasFast) ||
      !ReadValue(hBiasSlow,0,1,biasSlow) || !ReadValue(hRSI,0,1,rsi1) ||
      !ReadValue(hRSI,0,2,rsi2) || !ReadValue(hADX,0,1,adx) || !ReadValue(hATR,0,1,atr) ||
      !MathIsValidNumber(candleOpen1) || !MathIsValidNumber(candleClose1) ||
      !MathIsValidNumber(candleHigh1) || !MathIsValidNumber(candleLow1) ||
      candleOpen1<=0.0 || candleClose1<=0.0 || candleHigh1<=0.0 || candleLow1<=0.0 || candleHigh1<candleLow1)
   {
      LogEvent("DATA_WAIT","indicator values unavailable");
      return;
   }

   // Commit the bar timestamp only after all indicator data is readable; retry the same bar if history is late.
   lastBar=iTime(_Symbol,InpEntryTF,0);
   // Momentum-confirmed trend continuation: unlike a one-bar RSI midline cross,
   // this allows valid entries while RSI remains on the trend side of 50 and continues moving.
   // Signals still use only completed bars (shift 1 and shift 2).
   bool bullishSignalCandle=(candleClose1>candleOpen1);
   bool bearishSignalCandle=(candleClose1<candleOpen1);
   bool candleLongAllowed=(!InpRequireSignalCandleDirection || bullishSignalCandle);
   bool candleShortAllowed=(!InpRequireSignalCandleDirection || bearishSignalCandle);
   bool longFastEMARejection=(candleLow1<=fast1 && candleClose1>fast1);
   bool shortFastEMARejection=(candleHigh1>=fast1 && candleClose1<fast1);
   bool longFastEMAAllowed=(!InpRequireFastEMARejection || longFastEMARejection);
   bool shortFastEMAAllowed=(!InpRequireFastEMARejection || shortFastEMARejection);
   // Compute the bullish setup independently of whether new BUY entries are allowed.
   // Opposite-signal management must still see bullish setups when InpAllowLong=false.
   bool longSetup=(candleLongAllowed && longFastEMAAllowed && biasFast>biasSlow && fast1>slow1 && rsi1>InpRSIMidline &&
                   rsi1>rsi2 && adx>=InpMinADX && adx<=InpMaxADX);
   bool longSignal=(InpAllowLong && longSetup);
   bool shortSetup=(candleShortAllowed && shortFastEMAAllowed && biasFast<biasSlow && fast1<slow1 && rsi1<InpRSIMidline &&
                    rsi1<rsi2 && adx>=InpMinADX && adx<=InpMaxADX);
   bool shortSignal=shortSetup;

   double spreadPoints=(SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID))/_Point;
   LogEvent("SIGNAL_AUDIT",
      "bar="+TimeToString(iTime(_Symbol,InpEntryTF,1),TIME_DATE|TIME_MINUTES)+
      ";H1EMA"+IntegerToString(InpBiasFastEMA)+"="+DoubleToString(biasFast,_Digits)+
      ";H1EMA"+IntegerToString(InpBiasSlowEMA)+"="+DoubleToString(biasSlow,_Digits)+
      ";M5EMA"+IntegerToString(InpFastEMA)+"="+DoubleToString(fast1,_Digits)+
      ";M5EMA"+IntegerToString(InpSlowEMA)+"="+DoubleToString(slow1,_Digits)+
      ";RSIprev="+DoubleToString(rsi2,2)+";RSI="+DoubleToString(rsi1,2)+
      ";ADX="+DoubleToString(adx,2)+";ATR="+DoubleToString(atr,_Digits)+
      ";candle_open="+DoubleToString(candleOpen1,_Digits)+
      ";candle_close="+DoubleToString(candleClose1,_Digits)+
      ";candle_high="+DoubleToString(candleHigh1,_Digits)+
      ";candle_low="+DoubleToString(candleLow1,_Digits)+
      ";candle_bull="+(bullishSignalCandle ? "1":"0")+ ";candle_bear="+(bearishSignalCandle ? "1":"0")+
      ";ema_reject_long="+(longFastEMARejection ? "1":"0")+ ";ema_reject_short="+(shortFastEMARejection ? "1":"0")+
      ";require_signal_candle="+(InpRequireSignalCandleDirection ? "1":"0")+ ";require_fast_ema_rejection="+(InpRequireFastEMARejection ? "1":"0")+
      ";spread_points="+DoubleToString(spreadPoints,1)+
      ";adx_min="+DoubleToString(InpMinADX,1)+";adx_max="+DoubleToString(InpMaxADX,1)+
      ";allow_long="+(InpAllowLong ? "1":"0")+
      ";long_setup="+(longSetup ? "1":"0")+
      ";max_spread_points="+DoubleToString(InpMaxSpreadPoints,1)+
      ";spread_allowed="+(spreadPoints<=InpMaxSpreadPoints ? "1":"0")+
      ";long_entry="+(longSignal ? "1":"0")+";short_entry="+(shortSignal ? "1":"0"));

   bool spreadAllowed=(spreadPoints<=InpMaxSpreadPoints);
   // Spread blocks new entries/reversals, but must not suppress a valid opposite-signal exit.
   // The spread guard below still prevents opening a fresh position at an excessive spread.
   ManagePositions(atr,longSetup,shortSetup);
   if(!longSignal && !shortSignal) return;
   if(!spreadAllowed)
   {
      LogEvent("ENTRY_SKIP_SPREAD","spread_points="+DoubleToString(spreadPoints,1)+
               ";max_spread_points="+DoubleToString(InpMaxSpreadPoints,1));
      return;
   }

   // Prevent stacking duplicate exposure on the same symbol/magic; this is not a daily trade cap.
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0 && PositionSelectByTicket(ticket) &&
         PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==InpMagic)
      {
         LogEvent("ENTRY_SKIP","position already open for this symbol/magic");
         return;
      }
   }

   // A market request may briefly be accepted as PLACED before a position appears.
   // Do not issue a duplicate while an order for this symbol/magic is still active.
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong orderTicket=OrderGetTicket(i);
      if(orderTicket==0) continue; // OrderGetTicket selects the order for property reads.
      if(OrderGetString(ORDER_SYMBOL)==_Symbol &&
         (ulong)OrderGetInteger(ORDER_MAGIC)==InpMagic)
      {
         LogEvent("ENTRY_SKIP","active order already exists for this symbol/magic; order="+(string)orderTicket);
         return;
      }
   }

   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(ask<=0.0 || bid<=0.0 || atr<=0.0) return;
   double minStop=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
   double stopDistance=MathMax(InpStopATR*atr,minStop+2.0*_Point);
   double targetDistance=MathMax(InpTargetATR*atr,minStop+2.0*_Point);

   if(longSignal)
   {
      // For a buy, stop-level distance is checked from Bid; include the current spread in entry-to-stop risk.
      double sl=RoundToTick(bid-stopDistance);
      double tp=RoundToTick(ask+targetDistance);
      double lots=LotsForRisk(ORDER_TYPE_BUY,ask,sl);
      if(lots<=0.0) { LogEvent("ENTRY_REJECT",RiskRejectDetail(ORDER_TYPE_BUY,ask,sl)); return; }
      if(!SendMarketOrder(ORDER_TYPE_BUY,lots,sl,tp,"GoldLab long"))
         LogEvent("BUY_FAIL",("retcode="+IntegerToString((int)lastTradeRetcode)+"; "+lastTradeMessage));
      else if(lastTradeRetcode==TRADE_RETCODE_PLACED)
         LogEvent("BUY_PENDING","lots="+DoubleToString(lots,2)+"; "+lastTradeMessage);
      else if(lastTradeRetcode==TRADE_RETCODE_DONE_PARTIAL)
         LogEvent("BUY_PARTIAL","lots="+DoubleToString(lots,2)+"; "+lastTradeMessage);
      else
         LogEvent("BUY_FILLED","lots="+DoubleToString(lots,2)+"; ADX="+DoubleToString(adx,1)+"; "+lastTradeMessage);
   }
   else if(shortSignal)
   {
      // For a sell, stop-level distance is checked from Ask; include the current spread in entry-to-stop risk.
      double sl=RoundToTick(ask+stopDistance);
      double tp=RoundToTick(bid-targetDistance);
      double lots=LotsForRisk(ORDER_TYPE_SELL,bid,sl);
      if(lots<=0.0) { LogEvent("ENTRY_REJECT",RiskRejectDetail(ORDER_TYPE_SELL,bid,sl)); return; }
      if(!SendMarketOrder(ORDER_TYPE_SELL,lots,sl,tp,"GoldLab short"))
         LogEvent("SELL_FAIL",("retcode="+IntegerToString((int)lastTradeRetcode)+"; "+lastTradeMessage));
      else if(lastTradeRetcode==TRADE_RETCODE_PLACED)
         LogEvent("SELL_PENDING","lots="+DoubleToString(lots,2)+"; "+lastTradeMessage);
      else if(lastTradeRetcode==TRADE_RETCODE_DONE_PARTIAL)
         LogEvent("SELL_PARTIAL","lots="+DoubleToString(lots,2)+"; "+lastTradeMessage);
      else
         LogEvent("SELL_FILLED","lots="+DoubleToString(lots,2)+"; ADX="+DoubleToString(adx,1)+"; "+lastTradeMessage);
   }
}

void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(HistoryDealSelect(trans.deal) && HistoryDealGetString(trans.deal,DEAL_SYMBOL)==_Symbol &&
      (ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)==InpMagic)
      AppendDealRow(trans.deal);
}
