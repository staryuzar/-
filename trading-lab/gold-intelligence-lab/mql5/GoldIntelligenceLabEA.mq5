//+------------------------------------------------------------------+
//| Gold Intelligence Lab EA                                         |
//| EMA trend + Donchian breakout + ATR risk control                 |
//| Trading is disabled by default.                                  |
//+------------------------------------------------------------------+
#property strict
#property version   "0.10"
#property description "Auditable research EA. Trading disabled by default."

#include <Trade/Trade.mqh>
CTrade trade;

input bool   EnableTrading=false;                // False: signals/panel only
input bool   AllowRealAccountTrading=false;      // Additional explicit guard
input double RiskPercent=0.50;                  // Equity risk per trade (%)
input double EstimatedRoundTurnCostPerLot=7.0;   // Estimated fees/slippage per lot in account currency
input int    FastEMAPeriod=20;
input int    SlowEMAPeriod=50;
input int    ATRPeriod=14;
input int    DonchianPeriod=20;
input double StopATRMultiple=2.0;
input double RewardRiskRatio=2.0;
input int    MaxSpreadPoints=80;
input double MaxDailyLossPercent=2.0;            // Start-of-day equity guard
input double MaxEquityDrawdownPercent=15.0;      // Since this EA instance started
input int    MaxTradesPerDay=3;
input ulong  MagicNumber=28102026;
input int    DeviationPoints=30;

int hFast=INVALID_HANDLE, hSlow=INVALID_HANDLE, hATR=INVALID_HANDLE;
datetime lastBarTime=0;
int tradesToday=0;
int currentDayKey=-1;
double dayStartEquity=0.0;
double initialEquity=0.0;
string lastStatus="Starting";

int DayKey(datetime t)
{
   MqlDateTime d;
   TimeToStruct(t,d);
   return d.year*10000+d.mon*100+d.day;
}

bool IsNewBar()
{
   datetime t=iTime(_Symbol,_Period,0);
   if(t<=0) return false;
   if(t!=lastBarTime)
   {
      lastBarTime=t;
      return true;
   }
   return false;
}

bool GetOne(int handle,int shift,double &value)
{
   double temp[1];
   if(handle==INVALID_HANDLE) return false;
   if(CopyBuffer(handle,0,shift,1,temp)!=1) return false;
   value=temp[0];
   return MathIsValidNumber(value);
}

bool HasOurPosition()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber)
         return true;
   }
   return false;
}

double RoundPriceToTick(double price)
{
   double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tick<=0) tick=_Point;
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   return NormalizeDouble(MathRound(price/tick)*tick,digits);
}

int VolumeDigits(double step)
{
   for(int d=0;d<=8;d++)
      if(MathAbs(step-NormalizeDouble(step,d))<1e-9) return d;
   return 2;
}

double LotsForRisk(ENUM_ORDER_TYPE orderType,double entry,double stop)
{
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double riskCash=equity*RiskPercent/100.0;
   double loss=0.0;

   if(riskCash<=0 || !OrderCalcProfit(orderType,_Symbol,1.0,entry,stop,loss))
   {
      lastStatus="OrderCalcProfit failed; no trade";
      return 0.0;
   }

   double lossPerLot=MathAbs(loss);
   if(lossPerLot<=0) return 0.0;

   double raw=riskCash/(lossPerLot+MathMax(0.0,EstimatedRoundTurnCostPerLot));
   double minLot=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxLot=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) return 0.0;

   raw=MathMin(raw,maxLot);
   double lots=MathFloor((raw+1e-12)/step)*step;
   lots=NormalizeDouble(lots,VolumeDigits(step));

   // Never round up to minimum if it exceeds the risk budget.
   if(lots+1e-10<minLot || lots<=0)
   {
      lastStatus="Calculated risk below broker minimum volume; no trade";
      return 0.0;
   }
   return lots;
}

int GetSignal(double &atrValue,double &upper,double &lower)
{
   double fast=0,slow=0;
   if(!GetOne(hFast,1,fast) || !GetOne(hSlow,1,slow) || !GetOne(hATR,1,atrValue))
   {
      lastStatus="Waiting for indicator buffers";
      return 0;
   }
   if(atrValue<=0)
   {
      lastStatus="ATR invalid";
      return 0;
   }

   upper=-DBL_MAX;
   lower=DBL_MAX;

   // Reference levels exclude the signal candle (shift 1) to avoid look-ahead.
   for(int shift=2;shift<2+DonchianPeriod;shift++)
   {
      double hi=iHigh(_Symbol,_Period,shift);
      double lo=iLow(_Symbol,_Period,shift);
      if(hi<=0 || lo<=0)
      {
         lastStatus="Waiting for history";
         return 0;
      }
      if(hi>upper) upper=hi;
      if(lo<lower) lower=lo;
   }

   double close1=iClose(_Symbol,_Period,1);
   if(close1>upper && fast>slow)
   {
      lastStatus="BUY setup";
      return 1;
   }
   if(close1<lower && fast<slow)
   {
      lastStatus="SELL setup";
      return -1;
   }
   lastStatus="No breakout confirmation";
   return 0;
}

void TryTrade(int signal,double atrValue)
{
   if(!EnableTrading)
   {
      lastStatus="Signal only: EnableTrading=false";
      return;
   }

   ENUM_ACCOUNT_TRADE_MODE mode=(ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode==ACCOUNT_TRADE_MODE_REAL && !AllowRealAccountTrading)
   {
      lastStatus="Blocked: real-account trading disabled by safety guard";
      return;
   }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
   {
      lastStatus="Blocked: trading permissions disabled";
      return;
   }
   if(HasOurPosition())
   {
      lastStatus="Existing EA position; waiting";
      return;
   }
   if(tradesToday>=MaxTradesPerDay)
   {
      lastStatus="Daily trade limit reached";
      return;
   }

   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(dayStartEquity>0 && (dayStartEquity-equity)/dayStartEquity*100.0>=MaxDailyLossPercent)
   {
      lastStatus="Daily loss guard reached";
      return;
   }
   if(initialEquity>0 && (initialEquity-equity)/initialEquity*100.0>=MaxEquityDrawdownPercent)
   {
      lastStatus="Maximum drawdown guard reached; re-check EA state before restarting";
      return;
   }

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick))
   {
      lastStatus="No live tick";
      return;
   }

   double spreadPoints=(tick.ask-tick.bid)/_Point;
   if(spreadPoints>MaxSpreadPoints)
   {
      lastStatus="Blocked by spread guard";
      return;
   }

   double stopsLevel=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
   double tickSize=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double stopDistance=MathMax(atrValue*StopATRMultiple,stopsLevel+MathMax(tickSize,_Point));
   bool isBuy=(signal>0);
   double entry=isBuy?tick.ask:tick.bid;
   double sl=RoundPriceToTick(isBuy?entry-stopDistance:entry+stopDistance);
   double tp=RoundPriceToTick(isBuy?entry+stopDistance*RewardRiskRatio:entry-stopDistance*RewardRiskRatio);
   ENUM_ORDER_TYPE orderType=isBuy?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   double lots=LotsForRisk(orderType,entry,sl);
   if(lots<=0) return;

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(DeviationPoints);
   bool sent=false;
   if(isBuy) sent=trade.Buy(lots,_Symbol,0.0,sl,tp,"GoldLab EMA/Donchian");
   else      sent=trade.Sell(lots,_Symbol,0.0,sl,tp,"GoldLab EMA/Donchian");

   uint rc=trade.ResultRetcode();
   if(sent && (rc==TRADE_RETCODE_DONE || rc==TRADE_RETCODE_PLACED || rc==TRADE_RETCODE_DONE_PARTIAL))
   {
      tradesToday++;
      lastStatus=StringFormat("Order accepted: %s %.2f lots",isBuy?"BUY":"SELL",lots);
   }
   else
   {
      lastStatus=StringFormat("Order failed: retcode=%u %s",rc,trade.ResultRetcodeDescription());
   }
}

int OnInit()
{
   if(FastEMAPeriod<2 || SlowEMAPeriod<=FastEMAPeriod || ATRPeriod<2 || DonchianPeriod<2 ||
      RiskPercent<=0 || RiskPercent>5 || StopATRMultiple<=0 || RewardRiskRatio<=0 ||
      MaxTradesPerDay<1 || MaxSpreadPoints<0 || MaxDailyLossPercent<=0 || MaxEquityDrawdownPercent<=0)
      return INIT_PARAMETERS_INCORRECT;

   hFast=iMA(_Symbol,_Period,FastEMAPeriod,0,MODE_EMA,PRICE_CLOSE);
   hSlow=iMA(_Symbol,_Period,SlowEMAPeriod,0,MODE_EMA,PRICE_CLOSE);
   hATR=iATR(_Symbol,_Period,ATRPeriod);
   if(hFast==INVALID_HANDLE || hSlow==INVALID_HANDLE || hATR==INVALID_HANDLE)
      return INIT_FAILED;

   trade.SetExpertMagicNumber(MagicNumber);
   currentDayKey=DayKey(TimeTradeServer());
   dayStartEquity=AccountInfoDouble(ACCOUNT_EQUITY);
   initialEquity=dayStartEquity;
   lastStatus="Initialized; trading off by default";
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(hFast!=INVALID_HANDLE) IndicatorRelease(hFast);
   if(hSlow!=INVALID_HANDLE) IndicatorRelease(hSlow);
   if(hATR!=INVALID_HANDLE) IndicatorRelease(hATR);
   Comment("");
}

void OnTick()
{
   int today=DayKey(TimeTradeServer());
   if(today!=currentDayKey)
   {
      currentDayKey=today;
      tradesToday=0;
      dayStartEquity=AccountInfoDouble(ACCOUNT_EQUITY);
   }

   if(!IsNewBar()) return;

   double atrValue=0,upper=0,lower=0;
   int signal=GetSignal(atrValue,upper,lower);
   if(signal!=0) TryTrade(signal,atrValue);

   double fast=0,slow=0;
   GetOne(hFast,1,fast);
   GetOne(hSlow,1,slow);

   Comment("Gold Intelligence Lab EA\n",
           "Symbol: ",_Symbol," | TF: ",EnumToString(_Period),"\n",
           "Mode: ",(EnableTrading?"TRADING ENABLED":"SIGNAL ONLY"),"\n",
           "EMA fast/slow: ",DoubleToString(fast,_Digits)," / ",DoubleToString(slow,_Digits),"\n",
           "ATR: ",DoubleToString(atrValue,_Digits),"\n",
           "Donchian high/low: ",DoubleToString(upper,_Digits)," / ",DoubleToString(lower,_Digits),"\n",
           "Trades today: ",tradesToday," / ",MaxTradesPerDay,"\n",
           "Status: ",lastStatus);
}
//+------------------------------------------------------------------+
