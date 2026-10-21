#property strict
#property version   "1.00"
#property description "XAUUSD H1 trend + M15 pullback EA; risk-capped research candidate, not a profit guarantee."

#include <Trade/Trade.mqh>
CTrade trade;

input string InpTradeSymbol = "";              // Empty = chart symbol
input ENUM_TIMEFRAMES InpSignalTF = PERIOD_M15;
input ENUM_TIMEFRAMES InpBiasTF = PERIOD_H1;
input double InpRiskPercent = 0.50;             // Risk per trade (% equity)
input double InpDailyLossLimitPercent = 3.00;   // Pause new entries after daily equity loss
input int InpFastEMA = 50;
input int InpSlowEMA = 200;
input int InpPullbackEMA = 20;
input int InpRSIPeriod = 14;
input int InpATRPeriod = 14;
input double InpStopATR = 2.0;
input double InpTargetATR = 3.0;
input double InpBreakEvenATR = 1.0;
input int InpMaxSpreadPoints = 100;
input ulong InpMagic = 20261021;
input int InpDeviationPoints = 20;
input bool InpAllowBuy = true;
input bool InpAllowSell = true;

int hFast = INVALID_HANDLE, hSlow = INVALID_HANDLE;
int hPullback = INVALID_HANDLE, hRSI = INVALID_HANDLE, hATR = INVALID_HANDLE;
datetime g_lastBar = 0;
int g_dayOfYear = -1;
double g_dayStartEquity = 0.0;
bool g_dailyLock = false;

string TradeSymbol()
{
   return (InpTradeSymbol == "" ? _Symbol : InpTradeSymbol);
}

bool ReadValue(const int handle, const int buffer, const int shift, double &value)
{
   double values[];
   ArraySetAsSeries(values, true);
   if(CopyBuffer(handle, buffer, shift, 1, values) != 1)
      return false;
   value = values[0];
   return MathIsValidNumber(value);
}

void RefreshDailyGuard()
{
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);
   if(now.day_of_year != g_dayOfYear)
   {
      g_dayOfYear = now.day_of_year;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      g_dailyLock = false;
   }
   if(g_dayStartEquity > 0.0)
   {
      double dd = 100.0 * (g_dayStartEquity - AccountInfoDouble(ACCOUNT_EQUITY)) / g_dayStartEquity;
      if(dd >= InpDailyLossLimitPercent)
         g_dailyLock = true;
   }
}

bool IsNewBar(const string symbol, const ENUM_TIMEFRAMES tf)
{
   datetime t = iTime(symbol, tf, 0);
   if(t <= 0 || t == g_lastBar)
      return false;
   g_lastBar = t;
   return true;
}

bool HasOurPosition(const string symbol)
{
   for(int i = PositionsTotal() - 1; i >= 0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) == symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
   }
   return false;
}

double NormalizeVolume(const string symbol, double volume)
{
   double vmin = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0 || vmin <= 0.0 || vmax <= 0.0)
      return 0.0;
   volume = MathMin(vmax, volume);
   volume = MathFloor(volume / step + 1e-9) * step;
   int digits = 0;
   double probe = step;
   while(digits < 8 && MathAbs(probe - MathRound(probe)) > 1e-8)
   {
      probe *= 10.0;
      digits++;
   }
   volume = NormalizeDouble(volume, digits);
   if(volume + 1e-9 < vmin)
      return 0.0; // Never round up beyond the configured risk.
   return volume;
}

double LotsForRisk(const string symbol, const double stopDistance)
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = equity * InpRiskPercent / 100.0;
   double tickSize = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   if(equity <= 0.0 || riskMoney <= 0.0 || stopDistance <= 0.0 ||
      tickSize <= 0.0 || tickValue <= 0.0)
      return 0.0;
   double lossPerLot = (stopDistance / tickSize) * tickValue;
   if(lossPerLot <= 0.0)
      return 0.0;
   return NormalizeVolume(symbol, riskMoney / lossPerLot);
}

void ManageBreakEven(const string symbol)
{
   double atr = 0.0;
   if(!ReadValue(hATR, 0, 1, atr) || atr <= 0.0)
      return;
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return;
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   for(int i = PositionsTotal() - 1; i >= 0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol ||
         (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(type == POSITION_TYPE_BUY && tick.bid - open >= InpBreakEvenATR * atr)
      {
         if(sl == 0.0 || sl < open)
            trade.PositionModify(ticket, NormalizeDouble(open, digits), tp);
      }
      else if(type == POSITION_TYPE_SELL && open - tick.ask >= InpBreakEvenATR * atr)
      {
         if(sl == 0.0 || sl > open)
            trade.PositionModify(ticket, NormalizeDouble(open, digits), tp);
      }
   }
}

int OnInit()
{
   string symbol = TradeSymbol();
   if(!SymbolSelect(symbol, true))
      return INIT_FAILED;
   if(InpRiskPercent <= 0.0 || InpRiskPercent > 2.0 ||
      InpDailyLossLimitPercent <= 0.0 || InpStopATR <= 0.0 ||
      InpTargetATR <= 0.0 || InpMaxSpreadPoints < 0)
      return INIT_PARAMETERS_INCORRECT;

   hFast = iMA(symbol, InpBiasTF, InpFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   hSlow = iMA(symbol, InpBiasTF, InpSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   hPullback = iMA(symbol, InpSignalTF, InpPullbackEMA, 0, MODE_EMA, PRICE_CLOSE);
   hRSI = iRSI(symbol, InpSignalTF, InpRSIPeriod, PRICE_CLOSE);
   hATR = iATR(symbol, InpSignalTF, InpATRPeriod);
   if(hFast == INVALID_HANDLE || hSlow == INVALID_HANDLE ||
      hPullback == INVALID_HANDLE || hRSI == INVALID_HANDLE || hATR == INVALID_HANDLE)
      return INIT_FAILED;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   trade.SetTypeFillingBySymbol(symbol);
   RefreshDailyGuard();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(hFast != INVALID_HANDLE) IndicatorRelease(hFast);
   if(hSlow != INVALID_HANDLE) IndicatorRelease(hSlow);
   if(hPullback != INVALID_HANDLE) IndicatorRelease(hPullback);
   if(hRSI != INVALID_HANDLE) IndicatorRelease(hRSI);
   if(hATR != INVALID_HANDLE) IndicatorRelease(hATR);
}

void OnTick()
{
   string symbol = TradeSymbol();
   RefreshDailyGuard();
   ManageBreakEven(symbol);
   if(g_dailyLock || !IsNewBar(symbol, InpSignalTF))
      return;
   if(BarsCalculated(hFast) < InpSlowEMA + 5 ||
      BarsCalculated(hSlow) < InpSlowEMA + 5 ||
      BarsCalculated(hPullback) < InpPullbackEMA + 5 ||
      BarsCalculated(hRSI) < InpRSIPeriod + 5 ||
      BarsCalculated(hATR) < InpATRPeriod + 5)
      return;
   if(HasOurPosition(symbol))
      return;

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return;
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0.0 || (tick.ask - tick.bid) / point > InpMaxSpreadPoints)
      return;

   double fast = 0.0, slow = 0.0, ema = 0.0, rsi1 = 0.0, rsi2 = 0.0, atr = 0.0;
   if(!ReadValue(hFast, 0, 1, fast) || !ReadValue(hSlow, 0, 1, slow) ||
      !ReadValue(hPullback, 0, 1, ema) || !ReadValue(hRSI, 0, 1, rsi1) ||
      !ReadValue(hRSI, 0, 2, rsi2) || !ReadValue(hATR, 0, 1, atr) || atr <= 0.0)
      return;

   double close1 = iClose(symbol, InpSignalTF, 1);
   double close2 = iClose(symbol, InpSignalTF, 2);
   if(close1 <= 0.0 || close2 <= 0.0)
      return;

   bool bullish = fast > slow;
   bool bearish = fast < slow;
   bool buySignal = InpAllowBuy && bullish && close2 <= ema && close1 > ema &&
                    rsi2 < 50.0 && rsi1 >= 50.0;
   bool sellSignal = InpAllowSell && bearish && close2 >= ema && close1 < ema &&
                     rsi2 > 50.0 && rsi1 <= 50.0;
   if(!buySignal && !sellSignal)
      return;

   double stopDistance = InpStopATR * atr;
   double targetDistance = InpTargetATR * atr;
   double lots = LotsForRisk(symbol, stopDistance);
   if(lots <= 0.0)
   {
      Print("ENTRY_BLOCKED: volume below broker minimum or invalid tick-value data; symbol=", symbol);
      return;
   }

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   bool sent = false;
   if(buySignal)
   {
      double sl = NormalizeDouble(tick.ask - stopDistance, digits);
      double tp = NormalizeDouble(tick.ask + targetDistance, digits);
      sent = trade.Buy(lots, symbol, 0.0, sl, tp, "H1 trend / M15 pullback");
   }
   else if(sellSignal)
   {
      double sl = NormalizeDouble(tick.bid + stopDistance, digits);
      double tp = NormalizeDouble(tick.bid - targetDistance, digits);
      sent = trade.Sell(lots, symbol, 0.0, sl, tp, "H1 trend / M15 pullback");
   }

   if(!sent)
      Print("ORDER_FAILED: retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   else
      Print("ORDER_SENT: side=", (buySignal ? "BUY" : "SELL"),
            " lots=", DoubleToString(lots, 2),
            " risk_pct=", DoubleToString(InpRiskPercent, 2),
            " sl_atr=", DoubleToString(InpStopATR, 2),
            " tp_atr=", DoubleToString(InpTargetATR, 2));
}
