#property strict
#property version   "0.10"
#property description "GoldLab XAUUSD research candidate; demo/backtest only"

#include <Trade/Trade.mqh>

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
input int              InpATRPeriod           = 14;
input double           InpStopATR             = 1.8;
input double           InpTargetATR           = 2.4;
input double           InpTrailATR             = 1.4;
input bool             InpCloseOnOpposite     = true;
input bool             InpWriteTradeCSV       = true;

CTrade trade;
int hFast=INVALID_HANDLE, hSlow=INVALID_HANDLE;
int hBiasFast=INVALID_HANDLE, hBiasSlow=INVALID_HANDLE;
int hRSI=INVALID_HANDLE, hADX=INVALID_HANDLE, hATR=INVALID_HANDLE;
datetime lastBar=0;
string tradeLogName="GoldLab_trade_audit.csv";

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
      file=FileOpen(tradeLogName,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',');
      if(file==INVALID_HANDLE) { Print("GoldLab: cannot open audit CSV; error=",GetLastError()); return; }
      FileWrite(file,"deal","time","symbol","entry","type","volume","price","profit","commission","swap","reason","position_id");
   } else FileSeek(file,0,SEEK_END);
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
   if(InpRiskPercent<=0.0 || InpRiskPercent>2.0 || InpFastEMA<2 || InpSlowEMA<=InpFastEMA ||
      InpBiasFastEMA<2 || InpBiasSlowEMA<=InpBiasFastEMA || InpStopATR<=0.0 ||
      InpTargetATR<=0.0 || InpATRPeriod<2 || InpRSIPeriod<2 || InpADXPeriod<2)
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

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(20);
   LogEvent("INIT","Research candidate v0.10; no daily trade/loss lock.");
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
         if(!trade.PositionClose(ticket))
            LogEvent("CLOSE_FAIL",trade.ResultRetcodeDescription());
         continue;
      }

      if(atr<=0.0 || InpTrailATR<=0.0) continue;
      if(side==POSITION_TYPE_BUY)
      {
         double gain=bid-open;
         if(gain<atr) continue;
         double newSL=RoundToTick(bid-InpTrailATR*atr);
         if(newSL>oldSL && newSL<bid-stopLevel)
            if(!trade.PositionModify(ticket,newSL,tp))
               LogEvent("TRAIL_FAIL",trade.ResultRetcodeDescription());
      }
      else if(side==POSITION_TYPE_SELL)
      {
         double gain=open-ask;
         if(gain<atr) continue;
         double newSL=RoundToTick(ask+InpTrailATR*atr);
         if((oldSL==0.0 || newSL<oldSL) && newSL>ask+stopLevel)
            if(!trade.PositionModify(ticket,newSL,tp))
               LogEvent("TRAIL_FAIL",trade.ResultRetcodeDescription());
      }
   }
}

void OnTick()
{
   if(!IsNewBar()) return;
   if(Bars(_Symbol,InpEntryTF)<MathMax(InpSlowEMA,InpATRPeriod)+5 ||
      Bars(_Symbol,InpBiasTF)<InpBiasSlowEMA+5) return;

   double fast1,slow1,biasFast,biasSlow,rsi1,rsi2,adx,atr;
   if(!ReadValue(hFast,0,1,fast1) ||
      !ReadValue(hSlow,0,1,slow1) || !ReadValue(hBiasFast,0,1,biasFast) ||
      !ReadValue(hBiasSlow,0,1,biasSlow) || !ReadValue(hRSI,0,1,rsi1) ||
      !ReadValue(hRSI,0,2,rsi2) || !ReadValue(hADX,0,1,adx) || !ReadValue(hATR,0,1,atr))
   {
      LogEvent("DATA_WAIT","indicator values unavailable");
      return;
   }

   // Commit the bar timestamp only after all indicator data is readable; retry the same bar if history is late.
   lastBar=iTime(_Symbol,InpEntryTF,0);
   bool longSignal=(biasFast>biasSlow && fast1>slow1 && rsi2<=InpRSIMidline &&
                    rsi1>InpRSIMidline && adx>=InpMinADX);
   bool shortSignal=(biasFast<biasSlow && fast1<slow1 && rsi2>=InpRSIMidline &&
                     rsi1<InpRSIMidline && adx>=InpMinADX);

   double spreadPoints=(SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID))/_Point;
   LogEvent("SIGNAL_AUDIT",
      "bar="+TimeToString(iTime(_Symbol,InpEntryTF,1),TIME_DATE|TIME_MINUTES)+
      ";H1EMA"+IntegerToString(InpBiasFastEMA)+"="+DoubleToString(biasFast,_Digits)+
      ";H1EMA"+IntegerToString(InpBiasSlowEMA)+"="+DoubleToString(biasSlow,_Digits)+
      ";M5EMA"+IntegerToString(InpFastEMA)+"="+DoubleToString(fast1,_Digits)+
      ";M5EMA"+IntegerToString(InpSlowEMA)+"="+DoubleToString(slow1,_Digits)+
      ";RSIprev="+DoubleToString(rsi2,2)+";RSI="+DoubleToString(rsi1,2)+
      ";ADX="+DoubleToString(adx,2)+";ATR="+DoubleToString(atr,_Digits)+
      ";spread_points="+DoubleToString(spreadPoints,1)+
      ";long="+(longSignal ? "1":"0")+";short="+(shortSignal ? "1":"0"));

   ManagePositions(atr,longSignal,shortSignal);
   if(!longSignal && !shortSignal) return;

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

   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(ask<=0.0 || bid<=0.0 || atr<=0.0) return;
   double minStop=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
   double stopDistance=MathMax(InpStopATR*atr,minStop+2.0*_Point);
   double targetDistance=MathMax(InpTargetATR*atr,minStop+2.0*_Point);

   if(longSignal)
   {
      double sl=RoundToTick(ask-stopDistance);
      double tp=RoundToTick(ask+targetDistance);
      double lots=LotsForRisk(ORDER_TYPE_BUY,ask,sl);
      if(lots<=0.0) { LogEvent("ENTRY_REJECT","risk sizing below broker minimum or invalid tick-value"); return; }
      if(!trade.Buy(lots,_Symbol,0.0,sl,tp,"GoldLab v0.10 long"))
         LogEvent("BUY_FAIL",trade.ResultRetcodeDescription());
      else LogEvent("BUY_SENT","lots="+DoubleToString(lots,2)+"; ADX="+DoubleToString(adx,1));
   }
   else if(shortSignal)
   {
      double sl=RoundToTick(bid+stopDistance);
      double tp=RoundToTick(bid-targetDistance);
      double lots=LotsForRisk(ORDER_TYPE_SELL,bid,sl);
      if(lots<=0.0) { LogEvent("ENTRY_REJECT","risk sizing below broker minimum or invalid tick-value"); return; }
      if(!trade.Sell(lots,_Symbol,0.0,sl,tp,"GoldLab v0.10 short"))
         LogEvent("SELL_FAIL",trade.ResultRetcodeDescription());
      else LogEvent("SELL_SENT","lots="+DoubleToString(lots,2)+"; ADX="+DoubleToString(adx,1));
   }
}

void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(HistoryDealSelect(trans.deal) && HistoryDealGetString(trans.deal,DEAL_SYMBOL)==_Symbol &&
      (ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)==InpMagic)
      AppendDealRow(trans.deal);
}
