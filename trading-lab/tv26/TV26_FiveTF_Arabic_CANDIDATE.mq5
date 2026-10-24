#property strict
#property version   "1.010"
#property description "TV26 Technical Ratings clone candidate - Arabic panel, five timeframes"

input bool   InpEnableTrading       = true;
input bool   InpDemoOnly            = true;
input bool   InpTesterOnly          = false; // When true, refuse execution outside MT5 Strategy Tester.
input bool   InpUseRuleBasedEarlyExit = true;  // Master diagnostic switch for rule-based exits.
input bool   InpUseM1PriceReversalExit = false; // Isolated follow-up: test summary exits without the premature M1 path.
input ulong  InpMagic               = 26102326;
input double InpRiskPercent         = 1.00;
input int    InpATRPeriod           = 14;
input double InpStopATR             = 2.0;
input double InpTargetATR           = 4.0;
input int    InpCooldownBarsAfterExit = 0; // Optional cooldown on the M1 chart after a closed trade; 0 disables it.
input bool   InpRequireM1CloseBreakout = false; // Optional entry gate: last closed M1 candle must close beyond the prior candle high/low.
input double InpMaxSpreadPoints     = 100.0;
input int    InpDeviationPoints     = 20;
input ENUM_TIMEFRAMES InpTF1        = PERIOD_M1;
input ENUM_TIMEFRAMES InpTF2        = PERIOD_M5;
input ENUM_TIMEFRAMES InpTF3        = PERIOD_M15;
input ENUM_TIMEFRAMES InpTF4        = PERIOD_M30;
input ENUM_TIMEFRAMES InpTF5        = PERIOD_H1;

#define N_TF 5
#define N_RATINGS 26
#define STRONG 0.50

enum RatingIndex
{
   SMA10=0, EMA10, SMA20, EMA20, SMA30, EMA30, SMA50, EMA50,
   SMA100, EMA100, SMA200, EMA200, ICHIMOKU_BASE, VWMA20, HULL9,
   RSI14, STOCH14, CCI20, ADX14, AO, MOMENTUM10, MACD, STOCH_RSI,
   WILLIAMS_R, BULL_BEAR_POWER, ULTIMATE_OSC
};

ENUM_TIMEFRAMES g_tfs[N_TF];
int g_handles[N_TF][N_RATINGS];
int g_bulls[N_TF], g_bears[N_TF], g_atr[N_TF], g_trendEMA[N_TF];
int g_macdFast[N_TF], g_macdSlow[N_TF];
int g_scores[N_TF][N_RATINGS];
bool g_working[N_TF][N_RATINGS];
double g_diagA[N_TF][N_RATINGS],g_diagB[N_TF][N_RATINGS],g_diagC[N_TF][N_RATINGS];
double g_diagD[N_TF][N_RATINGS],g_diagE[N_TF][N_RATINGS];
datetime g_lastAuditBar[N_TF];
datetime g_auditAttemptBar[N_TF];
int g_auditAttempts[N_TF];
string g_auditFile="";
bool g_historyExported=false;
// Reproduce TradingView ta.rsi() RMA arithmetic instead of relying on platform iRSI rounding.
double g_tvRsiAvgGain[N_TF],g_tvRsiAvgLoss[N_TF],g_tvRsiLastClose[N_TF];
double g_tvRsiCurrent[N_TF],g_tvRsiPrevious[N_TF];
datetime g_tvRsiLastClosedBar[N_TF];
bool g_tvRsiInitialized[N_TF];
double g_rating[N_TF];
double g_maRating[N_TF], g_oscRating[N_TF];
int g_ready[N_TF], g_maReady[N_TF], g_oscReady[N_TF];
datetime g_lastM1Bar=0;
datetime g_lastExitTime=0;
datetime g_lastPanelUpdate=0;
string g_lastAction="لم يُرسل أي أمر";
string g_lastBlock="";
int g_lastExecutedSignal=0;
string g_signalGV="";

string g_names[N_RATINGS]={
 "متوسط بسيط 10","متوسط أسي 10","متوسط بسيط 20","متوسط أسي 20",
 "متوسط بسيط 30","متوسط أسي 30","متوسط بسيط 50","متوسط أسي 50",
 "متوسط بسيط 100","متوسط أسي 100","متوسط بسيط 200","متوسط أسي 200",
 "إيشيموكو - خط الأساس","متوسط مرجّح بالحجم","متوسط هال 9",
 "القوة النسبية RSI","ستوكاستك","قناة السلع CCI","مؤشر الاتجاه ADX",
 "المذبذب الرائع AO","الزخم Momentum","تقارب/تباعد المتوسطات MACD",
 "ستوكاستك RSI","ويليامز %R","قوة الثيران والدببة","المذبذب النهائي"
};

string TFName(ENUM_TIMEFRAMES tf)
{
   if(tf==PERIOD_M1) return "د1";
   if(tf==PERIOD_M5) return "د5";
   if(tf==PERIOD_M15) return "د15";
   if(tf==PERIOD_M30) return "د30";
   if(tf==PERIOD_H1) return "س1";
   return EnumToString(tf);
}
string SignalName(int s)
{
   if(s>0) return "شراء";
   if(s<0) return "بيع";
   return "حياد";
}
string SummaryName(double r,int ready,int expected)
{
   if(expected<=0 || ready<expected) return "غير مكتمل";
   if(r>STRONG) return "شراء قوي";
   if(r>0.10) return "شراء";
   if(r< -STRONG) return "بيع قوي";
   if(r< -0.10) return "بيع";
   return "حياد";
}
string RatingText(double r,int ready,int expected)
{
   if(expected<=0 || ready<expected) return "—";
   return DoubleToString(r,3);
}
bool ReadBuf(int handle,int buffer,int shift,double &v)
{
   if(handle==INVALID_HANDLE) return false;
   double a[]; ArraySetAsSeries(a,true);
   if(CopyBuffer(handle,buffer,shift,1,a)!=1) return false;
   v=a[0]; return MathIsValidNumber(v) && v!=EMPTY_VALUE;
}
// Ignore binary floating-point noise when a close equals a moving-average value.
int TVComparePriceLevel(double source,double level)
{
   double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double epsilon=MathMax(MathAbs(tick)*1.0e-7,1.0e-12);
   double difference=source-level;
   if(MathAbs(difference)<=epsilon) return 0;
   return difference>0.0 ? 1 : -1;
}
bool ReadRates(ENUM_TIMEFRAMES tf,int count,int shift,MqlRates &rates[])
{
   ArraySetAsSeries(rates,true);
   return CopyRates(_Symbol,tf,shift,count,rates)==count;
}
// Reproduce TradingView ta.stoch() -> SMA(3) -> SMA(3) explicitly.
// This avoids relying on platform-specific iStochastic smoothing/buffer conventions.
bool TVStochasticValues(ENUM_TIMEFRAMES tf,double &kOut,double &dOut)
{
   MqlRates rates[];
   const int rangePeriod=14;
   const int smoothK=3;
   const int smoothD=3;
   const int rawCount=smoothK+smoothD-1; // 5 raw %K values feed the two-stage smoothing.
   const int need=rawCount+rangePeriod-1; // shifts 1..18, including the closed candle.
   if(!ReadRates(tf,need,1,rates)) return false;
   double raw[];
   ArrayResize(raw,rawCount);
   for(int i=0;i<rawCount;i++)
   {
      double highest=rates[i].high;
      double lowest=rates[i].low;
      for(int j=i+1;j<i+rangePeriod;j++)
      {
         if(rates[j].high>highest) highest=rates[j].high;
         if(rates[j].low<lowest) lowest=rates[j].low;
      }
      double width=highest-lowest;
      if(width<=0.0) return false;
      raw[i]=100.0*(rates[i].close-lowest)/width;
   }
   double kSum=0.0;
   for(int i=0;i<smoothK;i++) kSum+=raw[i];
   kOut=kSum/smoothK;
   double dSum=0.0;
   for(int i=0;i<smoothD;i++)
   {
      double oneK=0.0;
      for(int j=0;j<smoothK;j++) oneK+=raw[i+j];
      dSum+=oneK/smoothK;
   }
   dOut=dSum/smoothD;
   return MathIsValidNumber(kOut) && MathIsValidNumber(dOut);
}
double WMA_Close(ENUM_TIMEFRAMES tf,int period,int shift)
{
   if(period<1) return EMPTY_VALUE;
   double c[]; ArraySetAsSeries(c,true);
   if(CopyClose(_Symbol,tf,shift,period,c)!=period) return EMPTY_VALUE;
   double sum=0,weights=0;
   for(int i=0;i<period;i++){ double w=period-i; sum+=c[i]*w; weights+=w; }
   if(weights<=0) return EMPTY_VALUE;
   return sum/weights;
}
double HullValue(ENUM_TIMEFRAMES tf)
{
   const int n=9, half=4, root=3;
   double raw[]; ArrayResize(raw,root); ArraySetAsSeries(raw,true);
   for(int i=0;i<root;i++)
   {
      double a=WMA_Close(tf,half,1+i);
      double b=WMA_Close(tf,n,1+i);
      if(a==EMPTY_VALUE || b==EMPTY_VALUE) return EMPTY_VALUE;
      raw[i]=2.0*a-b;
   }
   double sum=0,weights=0;
   for(int i=0;i<root;i++){double w=root-i;sum+=raw[i]*w;weights+=w;}
   if(weights<=0) return EMPTY_VALUE;
   return sum/weights;
}
double VWMAValue(ENUM_TIMEFRAMES tf)
{
   MqlRates rr[]; if(!ReadRates(tf,20,1,rr)) return EMPTY_VALUE;
   double pv=0,vol=0;
   for(int i=0;i<20;i++){double v=(double)rr[i].tick_volume;pv+=rr[i].close*v;vol+=v;}
   if(vol<=0) return EMPTY_VALUE;
   return pv/vol;
}
double UltimateValue(ENUM_TIMEFRAMES tf)
{
   MqlRates rr[]; if(!ReadRates(tf,29,1,rr)) return EMPTY_VALUE;
   double bp[28],tr[28];
   for(int i=0;i<28;i++)
   {
      double prev=rr[i+1].close;
      double low=MathMin(rr[i].low,prev), high=MathMax(rr[i].high,prev);
      bp[i]=rr[i].close-low; tr[i]=high-low;
   }
   double sumsBP[3]={0,0,0},sumsTR[3]={0,0,0};
   int periods[3]={7,14,28};
   for(int k=0;k<3;k++)
   {
      for(int i=0;i<periods[k];i++){sumsBP[k]+=bp[i];sumsTR[k]+=tr[i];}
      if(sumsTR[k]<=0) return EMPTY_VALUE;
   }
   double a=sumsBP[0]/sumsTR[0],b=sumsBP[1]/sumsTR[1],c=sumsBP[2]/sumsTR[2];
   return 100.0*(4.0*a+2.0*b+c)/7.0;
}
bool InitHandles()
{
   for(int t=0;t<N_TF;t++)
   {
      for(int j=0;j<N_RATINGS;j++) g_handles[t][j]=INVALID_HANDLE;
      // TechnicalRating v3 source computes Bulls/Bears Power with EMA(13).
      g_bulls[t]=iBullsPower(_Symbol,g_tfs[t],13);
      g_bears[t]=iBearsPower(_Symbol,g_tfs[t],13);
      g_atr[t]=iATR(_Symbol,g_tfs[t],InpATRPeriod);
      g_trendEMA[t]=iMA(_Symbol,g_tfs[t],50,0,MODE_EMA,PRICE_CLOSE);
      g_macdFast[t]=iMA(_Symbol,g_tfs[t],12,0,MODE_EMA,PRICE_CLOSE);
      g_macdSlow[t]=iMA(_Symbol,g_tfs[t],26,0,MODE_EMA,PRICE_CLOSE);
      int periods[12]={10,10,20,20,30,30,50,50,100,100,200,200};
      for(int j=0;j<12;j++)
      {
         ENUM_MA_METHOD method=(j%2==0 ? MODE_SMA : MODE_EMA);
         g_handles[t][j]=iMA(_Symbol,g_tfs[t],periods[j],0,method,PRICE_CLOSE);
      }
      g_handles[t][ICHIMOKU_BASE]=iIchimoku(_Symbol,g_tfs[t],9,26,52);
      g_handles[t][RSI14]=iRSI(_Symbol,g_tfs[t],14,PRICE_CLOSE);
      g_handles[t][STOCH14]=iStochastic(_Symbol,g_tfs[t],14,3,3,MODE_SMA,STO_LOWHIGH);
      g_handles[t][CCI20]=iCCI(_Symbol,g_tfs[t],20,PRICE_CLOSE);
      // Use Wilder smoothing to match TradingView ta.dmi(14,14); iADX() uses a different smoothing algorithm.
      g_handles[t][ADX14]=iADXWilder(_Symbol,g_tfs[t],14);
      g_handles[t][AO]=iAO(_Symbol,g_tfs[t]);
      // TradingView Momentum is close minus close[10]; compute it manually below.
      // MACD is calculated from EMA(12), EMA(26), then EMA(9) below to match Pine.
      g_handles[t][WILLIAMS_R]=iWPR(_Symbol,g_tfs[t],14);
      if(g_bulls[t]==INVALID_HANDLE || g_bears[t]==INVALID_HANDLE || g_atr[t]==INVALID_HANDLE ||
         g_trendEMA[t]==INVALID_HANDLE || g_macdFast[t]==INVALID_HANDLE || g_macdSlow[t]==INVALID_HANDLE)
         Print("TV26 init: handle auxiliary failed for ",TFName(g_tfs[t]));
      for(int j=0;j<N_RATINGS;j++)
      {
         if(j==VWMA20 || j==HULL9 || j==MOMENTUM10 || j==MACD || j==STOCH_RSI || j==BULL_BEAR_POWER || j==ULTIMATE_OSC) continue;
         if(g_handles[t][j]==INVALID_HANDLE)
            Print("TV26 init: handle failed: ",g_names[j]," / ",TFName(g_tfs[t]));
      }
   }
   return true;
}
void ReleaseHandles()
{
   for(int t=0;t<N_TF;t++)
   {
      for(int j=0;j<N_RATINGS;j++)
         if(g_handles[t][j]!=INVALID_HANDLE) IndicatorRelease(g_handles[t][j]);
      if(g_bulls[t]!=INVALID_HANDLE) IndicatorRelease(g_bulls[t]);
      if(g_trendEMA[t]!=INVALID_HANDLE) IndicatorRelease(g_trendEMA[t]);
      if(g_bears[t]!=INVALID_HANDLE) IndicatorRelease(g_bears[t]);
      if(g_atr[t]!=INVALID_HANDLE) IndicatorRelease(g_atr[t]);
      if(g_macdFast[t]!=INVALID_HANDLE) IndicatorRelease(g_macdFast[t]);
      if(g_macdSlow[t]!=INVALID_HANDLE) IndicatorRelease(g_macdSlow[t]);
   }
}
double TVRSIFromAverages(double avgGain,double avgLoss)
{
   if(avgLoss==0.0 && avgGain>0.0) return 100.0;
   if(avgGain==0.0 && avgLoss>0.0) return 0.0;
   if(avgGain==0.0 && avgLoss==0.0) return 50.0;
   double rs=avgGain/avgLoss;
   return 100.0-(100.0/(1.0+rs));
}

// Seed Wilder RMA from the same oldest-to-newest 1,600 closed candles exported
// by ExportReferenceHistory(). Use TradingView's recurrence alpha*x+(1-alpha)*prev.
bool InitializeTVRSIState(int t)
{
   const int period=14;
   const int historyBars=1600;
   MqlRates rates[];
   if(!ReadRates(g_tfs[t],historyBars,1,rates)) return false;

   double gainSum=0.0,lossSum=0.0;
   for(int s=historyBars-2;s>=historyBars-1-period;s--)
   {
      double delta=rates[s].close-rates[s+1].close;
      if(delta>0.0) gainSum+=delta;
      else if(delta<0.0) lossSum-=delta;
   }

   double alpha=1.0/(double)period;
   g_tvRsiAvgGain[t]=gainSum/(double)period;
   g_tvRsiAvgLoss[t]=lossSum/(double)period;
   double previousValue=EMPTY_VALUE,currentValue=EMPTY_VALUE;

   // The seed ends at series index historyBars-1-period. Continue toward shift 1.
   for(int s=historyBars-2-period;s>=0;s--)
   {
      double delta=rates[s].close-rates[s+1].close;
      double gain=(delta>0.0 ? delta : 0.0);
      double loss=(delta<0.0 ? -delta : 0.0);
      g_tvRsiAvgGain[t]=alpha*gain+(1.0-alpha)*g_tvRsiAvgGain[t];
      g_tvRsiAvgLoss[t]=alpha*loss+(1.0-alpha)*g_tvRsiAvgLoss[t];
      double value=TVRSIFromAverages(g_tvRsiAvgGain[t],g_tvRsiAvgLoss[t]);
      if(s==1) previousValue=value;
      if(s==0) currentValue=value;
   }
   if(!MathIsValidNumber(previousValue) || !MathIsValidNumber(currentValue) ||
      previousValue==EMPTY_VALUE || currentValue==EMPTY_VALUE) return false;

   g_tvRsiPrevious[t]=previousValue;
   g_tvRsiCurrent[t]=currentValue;
   g_tvRsiLastClose[t]=rates[0].close;
   g_tvRsiLastClosedBar[t]=rates[0].time;
   g_tvRsiInitialized[t]=true;
   return true;
}

// Advance RSI once per newly closed candle; catch up every missed candle chronologically.
bool UpdateTVRSIState(int t,double &current,double &previous)
{
   if(!g_tvRsiInitialized[t] && !InitializeTVRSIState(t)) return false;
   datetime closedTime=iTime(_Symbol,g_tfs[t],1);
   if(closedTime<=0) return false;

   if(closedTime!=g_tvRsiLastClosedBar[t])
   {
      int oldShift=iBarShift(_Symbol,g_tfs[t],g_tvRsiLastClosedBar[t],true);
      if(oldShift<2)
      {
         g_tvRsiInitialized[t]=false;
         if(!InitializeTVRSIState(t)) return false;
      }
      else
      {
         double alpha=1.0/14.0;
         for(int sh=oldShift-1;sh>=1;sh--)
         {
            datetime stamp=iTime(_Symbol,g_tfs[t],sh);
            double close=iClose(_Symbol,g_tfs[t],sh);
            if(stamp<=0 || close<=0.0) return false;
            double delta=close-g_tvRsiLastClose[t];
            double gain=(delta>0.0 ? delta : 0.0);
            double loss=(delta<0.0 ? -delta : 0.0);
            g_tvRsiAvgGain[t]=alpha*gain+(1.0-alpha)*g_tvRsiAvgGain[t];
            g_tvRsiAvgLoss[t]=alpha*loss+(1.0-alpha)*g_tvRsiAvgLoss[t];
            g_tvRsiPrevious[t]=g_tvRsiCurrent[t];
            g_tvRsiCurrent[t]=TVRSIFromAverages(g_tvRsiAvgGain[t],g_tvRsiAvgLoss[t]);
            g_tvRsiLastClose[t]=close;
            g_tvRsiLastClosedBar[t]=stamp;
         }
      }
   }

   current=g_tvRsiCurrent[t];
   previous=g_tvRsiPrevious[t];
   return MathIsValidNumber(current) && MathIsValidNumber(previous) &&
          current!=EMPTY_VALUE && previous!=EMPTY_VALUE;
}

bool ComputeOne(int t,int j,int &score)
{
   score=0;
   double a=0,b=0,c=0;
   if(j<=EMA200)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a)) return false;
      double cc[]; ArraySetAsSeries(cc,true);
      if(CopyClose(_Symbol,g_tfs[t],1,1,cc)!=1) return false;
      score=TVComparePriceLevel(cc[0],a);
      g_diagA[t][j]=a; g_diagB[t][j]=cc[0];
      return true;
   }
   if(j==ICHIMOKU_BASE)
   {
      double conversion=0, base=0, spanA=0, spanB=0;
      // TechnicalRating v3 compares lead spans at [26], but current Tenkan/Kijun.
      // MT5 iIchimoku applies a forward plot shift to Senkou buffers 2/3, which is
      // already reflected by CopyBuffer indexing. Requesting shift 27 double-shifts
      // the series (verified against exported OHLC: it selected the TV span from 52 bars back).
      // Shift 1 gives the Pine span value [26] for the last closed bar.
      if(!ReadBuf(g_handles[t][j],0,1,conversion) || !ReadBuf(g_handles[t][j],1,1,base) ||
         !ReadBuf(g_handles[t][j],2,1,spanA) || !ReadBuf(g_handles[t][j],3,1,spanB)) return false;
      double cc[]; ArraySetAsSeries(cc,true);
      if(CopyClose(_Symbol,g_tfs[t],1,1,cc)!=1) return false;
      if(spanA>spanB && base>spanA && conversion>base && cc[0]>conversion) score=1;
      else if(spanA<spanB && base<spanA && conversion<base && cc[0]<conversion) score=-1;
      else score=0;
      g_diagA[t][j]=conversion; g_diagB[t][j]=base; g_diagC[t][j]=spanA;
      g_diagD[t][j]=spanB; g_diagE[t][j]=cc[0];
      return true;
   }
   if(j==VWMA20 || j==HULL9)
   {
      a=(j==VWMA20 ? VWMAValue(g_tfs[t]) : HullValue(g_tfs[t]));
      if(a==EMPTY_VALUE || !MathIsValidNumber(a)) return false;
      double cc[]; ArraySetAsSeries(cc,true);
      if(CopyClose(_Symbol,g_tfs[t],1,1,cc)!=1) return false;
      score=TVComparePriceLevel(cc[0],a);
      g_diagA[t][j]=a; g_diagB[t][j]=cc[0];
      return true;
   }
   if(j==RSI14)
   {
      if(!UpdateTVRSIState(t,a,b)) return false;
      score=(a<30 && a>b ? 1 : (a>70 && a<b ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b;
      return true;
   }
   if(j==STOCH14)
   {
      // TradingView stochFull(14,3,3): raw %K, SMA(3) for K, then SMA(3) for D.
      if(!TVStochasticValues(g_tfs[t],a,b)) return false;
      const double kdEpsilon=1.0e-10; // Avoid spurious votes from floating-point noise at K==D.
      score=(a<20 && b<20 && a>b+kdEpsilon ? 1 : (a>80 && b>80 && a<b-kdEpsilon ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b;
      return true;
   }
   if(j==CCI20)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b)) return false;
      score=(a<-100 && a>b ? 1 : (a>100 && a<b ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b;
      return true;
   }
   if(j==ADX14)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],1,1,b) || !ReadBuf(g_handles[t][j],2,1,c)) return false;
      double prevADX=0;
      if(!ReadBuf(g_handles[t][j],0,2,prevADX)) return false;
      // Exact TechnicalRating v3 source uses rising ADX for both directions.
      score=(a>20 && b>c && a>prevADX ? 1 : (a>20 && b<c && a>prevADX ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b; g_diagC[t][j]=c; g_diagD[t][j]=prevADX;
      return true;
   }
   if(j==AO)
   {
      double prev2=0;
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b) || !ReadBuf(g_handles[t][j],0,3,prev2)) return false;
      bool buyCross=(a>0 && b<=0), sellCross=(a<0 && b>=0);
      bool buySaucer=(a>0 && b>0 && a>b && b<prev2);
      bool sellSaucer=(a<0 && b<0 && a<b && b>prev2);
      score=(buyCross || buySaucer ? 1 : (sellCross || sellSaucer ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b; g_diagC[t][j]=prev2;
      return true;
   }
   if(j==MOMENTUM10)
   {
      // Match Pine ta.mom(close, 10): current close minus close 10 bars earlier.
      double closes[]; ArraySetAsSeries(closes,true);
      if(CopyClose(_Symbol,g_tfs[t],1,12,closes)!=12) return false;
      double momNow=closes[0]-closes[10];
      double momPrev=closes[1]-closes[11];
      score=(momNow>momPrev ? 1 : (momNow<momPrev ? -1 : 0));
      g_diagA[t][j]=momNow; g_diagB[t][j]=momPrev; g_diagC[t][j]=closes[0]; g_diagD[t][j]=closes[10];
      return true;
   }
   if(j==MACD)
   {
      // TradingView ta.macd(): EMA(12)-EMA(26), with EMA(9) of that MACD as signal.
      const int count=300;
      double fastValues[],slowValues[];
      ArraySetAsSeries(fastValues,true);
      ArraySetAsSeries(slowValues,true);
      if(CopyBuffer(g_macdFast[t],0,1,count,fastValues)!=count ||
         CopyBuffer(g_macdSlow[t],0,1,count,slowValues)!=count) return false;
      double macdValues[];
      ArrayResize(macdValues,count);
      ArraySetAsSeries(macdValues,true);
      for(int i=0;i<count;i++) macdValues[i]=fastValues[i]-slowValues[i];
      double signal=macdValues[count-1];
      const double alpha=2.0/(9.0+1.0);
      for(int i=count-2;i>=0;i--) signal=alpha*macdValues[i]+(1.0-alpha)*signal;
      a=macdValues[0]; b=signal;
      score=(a>b ? 1 : (a<b ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b; g_diagC[t][j]=fastValues[0]; g_diagD[t][j]=slowValues[0];
      return true;
   }
   if(j==STOCH_RSI)
   {
      double rsi[]; ArraySetAsSeries(rsi,true);
      if(CopyBuffer(g_handles[t][RSI14],0,1,20,rsi)!=20) return false;
      double raw[7];
      for(int sh=0;sh<7;sh++)
      {
         double lo=rsi[sh],hi=rsi[sh];
         for(int k=sh;k<sh+14;k++){lo=MathMin(lo,rsi[k]);hi=MathMax(hi,rsi[k]);}
         if(hi-lo<1e-8) return false;
         raw[sh]=100.0*(rsi[sh]-lo)/(hi-lo);
      }
      double k0=(raw[0]+raw[1]+raw[2])/3.0, k1=(raw[1]+raw[2]+raw[3])/3.0;
      double k2=(raw[2]+raw[3]+raw[4])/3.0;
      double d0=(k0+k1+k2)/3.0;
      // Technical Ratings trend filter: close relative to EMA(50), not the one-bar RSI slope.
      double trendClose[]; ArraySetAsSeries(trendClose,true);
      double emaTrend=0;
      if(CopyClose(_Symbol,g_tfs[t],1,1,trendClose)!=1 ||
         !ReadBuf(g_trendEMA[t],0,1,emaTrend)) return false;
      bool downtrend=(trendClose[0]<emaTrend), uptrend=(trendClose[0]>emaTrend);
      const double kdEpsilon=1.0e-10; // Treat mathematically equal K/D as neutral.
      score=(downtrend && k0<20 && d0<20 && k0>d0+kdEpsilon ? 1 :
             (uptrend && k0>80 && d0>80 && k0<d0-kdEpsilon ? -1 : 0));
      g_diagA[t][j]=k0; g_diagB[t][j]=d0; g_diagC[t][j]=trendClose[0]; g_diagD[t][j]=emaTrend;
      return true;
   }
   if(j==WILLIAMS_R)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b)) return false;
      score=(a<-80 && a>b ? 1 : (a>-20 && a<b ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b;
      return true;
   }
   if(j==BULL_BEAR_POWER)
   {
      double bullPrev=0,bearNow=0,bearPrev=0,emaNow=0;
      if(!ReadBuf(g_bulls[t],0,1,a) || !ReadBuf(g_bulls[t],0,2,bullPrev) ||
         !ReadBuf(g_bears[t],0,1,bearNow) || !ReadBuf(g_bears[t],0,2,bearPrev) ||
         !ReadBuf(g_trendEMA[t],0,1,emaNow)) return false;
      double cc[]; ArraySetAsSeries(cc,true);
      if(CopyClose(_Symbol,g_tfs[t],1,1,cc)!=1) return false;
      // TechnicalRating v3: BBP(13), while trend gating uses close versus EMA(50).
      bool uptrend=(cc[0]>emaNow), downtrend=(cc[0]<emaNow);
      score=(uptrend && bearNow<0 && bearNow>bearPrev ? 1 :
             (downtrend && a>0 && a<bullPrev ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=bullPrev; g_diagC[t][j]=bearNow;
      g_diagD[t][j]=bearPrev; g_diagE[t][j]=emaNow; // Trend threshold; candle_close is exported separately.
      return true;
   }
   if(j==ULTIMATE_OSC)
   {
      a=UltimateValue(g_tfs[t]); if(a==EMPTY_VALUE || !MathIsValidNumber(a)) return false;
      score=(a>70 ? 1 : (a<30 ? -1 : 0));
      g_diagA[t][j]=a;
      return true;
   }
   return false;
}
void EvaluateAll()
{
   for(int t=0;t<N_TF;t++)
   {
      int maSum=0,oscSum=0; g_ready[t]=0; g_maReady[t]=0; g_oscReady[t]=0;
      for(int j=0;j<N_RATINGS;j++)
      {
         g_diagA[t][j]=EMPTY_VALUE; g_diagB[t][j]=EMPTY_VALUE;
         g_diagC[t][j]=EMPTY_VALUE; g_diagD[t][j]=EMPTY_VALUE; g_diagE[t][j]=EMPTY_VALUE;
         int s=0; bool ok=ComputeOne(t,j,s);
         g_working[t][j]=ok; g_scores[t][j]=(ok?s:0);
         if(ok){g_ready[t]++; if(j<15){maSum+=s;g_maReady[t]++;}else{oscSum+=s;g_oscReady[t]++;}}
      }
      g_maRating[t]=(g_maReady[t]>0 ? (double)maSum/(double)g_maReady[t] : 0.0);
      g_oscRating[t]=(g_oscReady[t]>0 ? (double)oscSum/(double)g_oscReady[t] : 0.0);
      g_rating[t]=(g_maReady[t]==15 && g_oscReady[t]==11 ? (g_maRating[t]+g_oscRating[t])/2.0 : 0.0);
   }
}
// Multi-timeframe trend + confirmation + M1 execution.
// H1 and M30 set the directional bias; M15 confirms it; M5 may be neutral
// but cannot materially oppose it. M1 breakout is the execution trigger by default.
// The entry decision uses exactly three TradingView-style summaries: M5, M15 and M30.
// Entry is allowed only when all three are Strong Buy or all three are Strong Sell.
int AlignedSignal()
{
   const int frames[3]={1,2,3}; // M5, M15, M30; M1 is execution/price-action monitoring only.
   for(int i=0;i<3;i++)
   {
      int t=frames[i];
      if(g_ready[t]!=N_RATINGS || g_maReady[t]!=15 || g_oscReady[t]!=11)
         return 0;
   }
   bool strongBuy=(g_rating[1]>STRONG && g_rating[2]>STRONG && g_rating[3]>STRONG);
   bool strongSell=(g_rating[1]<-STRONG && g_rating[2]<-STRONG && g_rating[3]<-STRONG);
   if(strongBuy) return 1;
   if(strongSell) return -1;
   return 0;
}
string DetailSignal(int t,int j)
{
   if(!g_working[t][j]) return "عطل";
   return SignalName(g_scores[t][j]);
}
void DrawPanel()
{
   string p="مستشار تقييم TV26 | الذهب: "+_Symbol+"\n";
   p+="المكونات: 26 (15 متوسطاً + 11 مذبذباً) | الإطار مبني على شموع مغلقة\n";   p+="ملف التدقيق: Common\\Files\\"+g_auditFile+" (CSV)\n";
   p+="قاعدة القرار: ملخصات د5 + د15 + د30 فقط؛ دخول عند اتفاق شراء قوي/بيع قوي، وخروج عند انقلاب أي ملخص عكس الصفقة أو كسر سعري مؤكد على د1\\n";
   p+="افتتاح الشمعة المغلقة (خادم MT5) | الإطار | الملخص العام | المتوسطات | المذبذبات | الجاهز\n";
   for(int t=0;t<N_TF;t++)
   {
      datetime closedBar=iTime(_Symbol,g_tfs[t],1);
      string barTime=(closedBar>0 ? TimeToString(closedBar,TIME_DATE|TIME_MINUTES) : "غير متاح");
      p+=barTime+" | "+TFName(g_tfs[t])+" | "+SummaryName(g_rating[t],g_ready[t],N_RATINGS)+" ("+RatingText(g_rating[t],g_ready[t],N_RATINGS)+") | "+
         SummaryName(g_maRating[t],g_maReady[t],15)+" ("+RatingText(g_maRating[t],g_maReady[t],15)+") | "+
         SummaryName(g_oscRating[t],g_oscReady[t],11)+" ("+RatingText(g_oscRating[t],g_oscReady[t],11)+") | "+
         IntegerToString(g_ready[t])+"/26 (م "+IntegerToString(g_maReady[t])+"/15، ذ "+IntegerToString(g_oscReady[t])+"/11)\n";
   }
   p+="\nحالة كل مؤشر في الأطر الخمسة: د1 / د5 / د15 / د30 / س1\n";
   for(int j=0;j<N_RATINGS;j++)
   {
      p+=g_names[j]+": ";
      for(int t=0;t<N_TF;t++)
      {
         p+=DetailSignal(t,j);
         if(t<N_TF-1) p+=" / ";
      }
      p+="\n";
   }
   p+="\nقرار التنفيذ: "+g_lastAction;
   if(g_lastBlock!="") p+="\nسبب المنع/التنبيه: "+g_lastBlock;
   p+="\nالتداول الآلي: "+(InpEnableTrading?"مفعّل":"معطّل")+" | حماية الحساب التجريبي: "+(InpDemoOnly?"مفعّلة":"غير مفعّلة");
   Comment(p);
}
string AuditValue(double v)
{
   if(v==EMPTY_VALUE || !MathIsValidNumber(v)) return "";
   return DoubleToString(v,8);
}
void ExportAuditForTF(int t)
{
   datetime closedBar=iTime(_Symbol,g_tfs[t],1);
   if(closedBar<=0 || closedBar==g_lastAuditBar[t]) return;

   // Indicator history may arrive asynchronously at startup. Retry this exact candle
   // until every component is ready, up to 10 timer attempts (about 20 seconds).
   if(g_auditAttemptBar[t]!=closedBar)
   {
      g_auditAttemptBar[t]=closedBar;
      g_auditAttempts[t]=0;
   }
   bool allReady=(g_ready[t]==N_RATINGS && g_maReady[t]==15 && g_oscReady[t]==11);
   if(!allReady)
   {
      g_auditAttempts[t]++;
      if(g_auditAttempts[t]<10) return;
   }

   int fh=FileOpen(g_auditFile,FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_ANSI,',',CP_UTF8);
   if(fh==INVALID_HANDLE)
   {
      Print("TV26 audit export: FileOpen failed, error=",GetLastError()," file=",g_auditFile);
      return;
   }
   if(FileSize(fh)==0)
      FileWrite(fh,"bar_open_time_server","symbol","broker_company","broker_server","timeframe","component","readiness","vote",
                "value_a","value_b","value_c","value_d","value_e","candle_open","candle_high","candle_low","candle_close","tick_volume");
   FileSeek(fh,0,SEEK_END);
   string ts=TimeToString(closedBar,TIME_DATE|TIME_MINUTES);
   string company=AccountInfoString(ACCOUNT_COMPANY);
   string server=AccountInfoString(ACCOUNT_SERVER);
   string summaryReady=(g_ready[t]==N_RATINGS && g_maReady[t]==15 && g_oscReady[t]==11 ? "OK" : "INCOMPLETE");
   string allValue=(summaryReady=="OK" ? AuditValue(g_rating[t]) : "");
   string maValue=(g_maReady[t]==15 ? AuditValue(g_maRating[t]) : "");
   string oscValue=(g_oscReady[t]==11 ? AuditValue(g_oscRating[t]) : "");
   MqlRates closedRates[];
   bool haveRates=ReadRates(g_tfs[t],1,1,closedRates);
   string candleOpen=(haveRates ? AuditValue(closedRates[0].open) : "");
   string candleHigh=(haveRates ? AuditValue(closedRates[0].high) : "");
   string candleLow=(haveRates ? AuditValue(closedRates[0].low) : "");
   string candleClose=(haveRates ? AuditValue(closedRates[0].close) : "");
   string tickVolume=(haveRates ? IntegerToString(closedRates[0].tick_volume) : "");
   FileWrite(fh,ts,_Symbol,company,server,TFName(g_tfs[t]),"SUMMARY",summaryReady,"",
             allValue,maValue,oscValue,IntegerToString(g_ready[t]),
             IntegerToString(g_maReady[t])+"/15;"+IntegerToString(g_oscReady[t])+"/11",
             candleOpen,candleHigh,candleLow,candleClose,tickVolume);
   for(int j=0;j<N_RATINGS;j++)
   {
      string ready=(g_working[t][j] ? "OK" : "NOT_READY");
      string vote=(g_working[t][j] ? IntegerToString(g_scores[t][j]) : "");
      FileWrite(fh,ts,_Symbol,company,server,TFName(g_tfs[t]),g_names[j],ready,vote,
                AuditValue(g_diagA[t][j]),AuditValue(g_diagB[t][j]),AuditValue(g_diagC[t][j]),
                AuditValue(g_diagD[t][j]),AuditValue(g_diagE[t][j]),"","","","","");
   }
   FileFlush(fh);
   FileClose(fh);
   g_lastAuditBar[t]=closedBar;
}
void ExportAuditIfNeeded()
{
   for(int t=0;t<N_TF;t++) ExportAuditForTF(t);
}
// Export pre-test OHLCV history for formula-level audits on every timeframe.
// This is market data only; it contains no account credentials or order data.
bool ExportReferenceHistory()
{
   if(g_historyExported) return true;
   const int historyBars=1600;
   for(int t=0;t<N_TF;t++)
   {
      MqlRates check[];
      ArraySetAsSeries(check,true);
      int copied=CopyRates(_Symbol,g_tfs[t],1,historyBars,check);
      if(copied<historyBars)
      {
         Print("TV26 reference history not ready for ",TFName(g_tfs[t]),
               "; copied ",copied," of ",historyBars," bars. Will retry.");
         return false;
      }
   }
   string fileName="TV26_OHLC_History_"+_Symbol+".csv";
   int fh=FileOpen(fileName,FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI,',',CP_UTF8);
   if(fh==INVALID_HANDLE)
   {
      Print("TV26 reference history FileOpen failed: ",GetLastError());
      return false;
   }
   FileWrite(fh,"timeframe","bar_open_time_server","symbol","broker_company","broker_server",
             "candle_open","candle_high","candle_low","candle_close","tick_volume");
   string company=AccountInfoString(ACCOUNT_COMPANY);
   string server=AccountInfoString(ACCOUNT_SERVER);
   for(int t=0;t<N_TF;t++)
   {
      MqlRates rates[];
      ArraySetAsSeries(rates,true);
      int copied=CopyRates(_Symbol,g_tfs[t],1,historyBars,rates);
      if(copied<historyBars)
      {
         FileClose(fh);
         FileDelete(fileName,FILE_COMMON);
         Print("TV26 reference history copy changed during export for ",TFName(g_tfs[t]),
               "; copied ",copied," of ",historyBars," bars. Will retry.");
         return false;
      }
      // Array is marked as series (index 0 = most recent), write oldest to newest.
      for(int i=copied-1;i>=0;i--)
      {
         string ts=TimeToString(rates[i].time,TIME_DATE|TIME_MINUTES);
         FileWrite(fh,TFName(g_tfs[t]),ts,_Symbol,company,server,
                   AuditValue(rates[i].open),AuditValue(rates[i].high),
                   AuditValue(rates[i].low),AuditValue(rates[i].close),
                   IntegerToString((long)rates[i].tick_volume));
      }
   }
   FileFlush(fh);
   FileClose(fh);
   g_historyExported=true;
   for(int t=0;t<N_TF;t++)
   {
      if(!InitializeTVRSIState(t))
         Print("TV26 RSI warmup not ready for ",TFName(g_tfs[t]),"; will retry on next evaluation.");
   }
   Print("TV26 reference history export OK: ",fileName,
         "; frames=",N_TF,"; bars per frame=",historyBars);
   return true;
}
bool IsNewM1Bar()
{
   datetime now=iTime(_Symbol,PERIOD_M1,0);
   if(now==0) return false;
   if(now!=g_lastM1Bar){g_lastM1Bar=now;return true;}
   return false;
}
bool FindOurPosition(ulong &ticket,ENUM_POSITION_TYPE &side)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol || (ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      ticket=tk;side=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);return true;
   }
   return false;
}
bool CloseTicket(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return false;
   ENUM_POSITION_TYPE side=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double vol=PositionGetDouble(POSITION_VOLUME);
   MqlTradeRequest req;MqlTradeResult res;ZeroMemory(req);ZeroMemory(res);
   req.action=TRADE_ACTION_DEAL;req.position=ticket;req.symbol=_Symbol;req.magic=InpMagic;req.volume=vol;
   req.type=(side==POSITION_TYPE_BUY?ORDER_TYPE_SELL:ORDER_TYPE_BUY);
   req.price=(req.type==ORDER_TYPE_BUY?SymbolInfoDouble(_Symbol,SYMBOL_ASK):SymbolInfoDouble(_Symbol,SYMBOL_BID));
   req.deviation=InpDeviationPoints;req.type_filling=FillMode();req.comment="TV26 close opposite";
   bool sent=OrderSend(req,res);
   if(!sent || (res.retcode!=TRADE_RETCODE_DONE && res.retcode!=TRADE_RETCODE_DONE_PARTIAL))
      return false;
   // A partial-close retcode is not a successful reversal if the old position remains.
   return !PositionSelectByTicket(ticket);
}
// In netting/exchange accounts only one position can exist per symbol.
// Refuse to touch a symbol position owned by a manual trade or another EA.
bool HasForeignNettingPosition()
{
   ENUM_ACCOUNT_MARGIN_MODE mode=(ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(mode==ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) return false;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0 || !PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic) return true;
   }
   return false;
}
double NormalizeLots(double lots)
{
   double minv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),maxv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX),step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0 || minv<=0) return 0;
   lots=MathMin(lots,maxv);lots=MathFloor(lots/step)*step;
   if(lots<minv) return 0;
   return NormalizeDouble(lots,2);
}
double LotsByRisk(ENUM_ORDER_TYPE type,double entry,double stop)
{
   double money=AccountInfoDouble(ACCOUNT_EQUITY)*InpRiskPercent/100.0,loss=0;
   if(money<=0 || !OrderCalcProfit(type,_Symbol,1.0,entry,stop,loss)) return 0;
   if(MathAbs(loss)<=0) return 0;
   return NormalizeLots(money/MathAbs(loss));
}
ENUM_ORDER_TYPE_FILLING FillMode()
{
   long f=SymbolInfoInteger(_Symbol,SYMBOL_FILLING_MODE);
   if((f & SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK) return ORDER_FILLING_FOK;
   return ORDER_FILLING_IOC;
}
void RememberSignal(int sig)
{
   g_lastExecutedSignal=sig;
   if(g_signalGV!="") GlobalVariableSet(g_signalGV,(double)sig);
}
int OppositeSummaryTimeframe(ENUM_POSITION_TYPE side)
{
   const int frames[3]={1,2,3}; // M5, M15, M30
   for(int i=0;i<3;i++)
   {
      int t=frames[i];
      if(g_ready[t]!=N_RATINGS || g_maReady[t]!=15 || g_oscReady[t]!=11) continue;
      // Any opposite-direction rating (Sell/Strong Sell against a buy, vice versa) triggers exit.
      if(side==POSITION_TYPE_BUY && g_rating[t]<-0.10) return t;
      if(side==POSITION_TYPE_SELL && g_rating[t]>0.10) return t;
   }
   return -1;
}

// Objective M1 reversal: a closed candle in the opposite direction breaks the
// extreme of the three candles immediately before it; a candle color alone is insufficient.
bool ConfirmedM1PriceReversal(ENUM_POSITION_TYPE side,string &detail)
{
   double o=iOpen(_Symbol,PERIOD_M1,1);
   double cl=iClose(_Symbol,PERIOD_M1,1);
   if(o<=0.0 || cl<=0.0) return false;
   double priorLow=DBL_MAX, priorHigh=-DBL_MAX;
   for(int sh=2;sh<=4;sh++)
   {
      double lo=iLow(_Symbol,PERIOD_M1,sh);
      double hi=iHigh(_Symbol,PERIOD_M1,sh);
      if(lo<=0.0 || hi<=0.0) return false;
      if(lo<priorLow) priorLow=lo;
      if(hi>priorHigh) priorHigh=hi;
   }
   if(side==POSITION_TYPE_BUY && cl<o && cl<priorLow)
   {
      detail="إغلاق هابط كسر قيعان الشموع الثلاث السابقة";
      return true;
   }
   if(side==POSITION_TYPE_SELL && cl>o && cl>priorHigh)
   {
      detail="إغلاق صاعد كسر قمم الشموع الثلاث السابقة";
      return true;
   }
   return false;
}

// Returns true whenever this EA has a position to manage, preventing a second
// entry on the same M1 bar as an exit.
bool ManageOpenPositionExit()
{
   ulong ticket=0;
   ENUM_POSITION_TYPE side=POSITION_TYPE_BUY;
   if(!FindOurPosition(ticket,side)) return false;

   // Test-only A/B toggle. Even when disabled, return true so entries remain blocked
   // while this position is open; broker SL/TP protections remain active.
   if(!InpUseRuleBasedEarlyExit)
   {
      g_lastAction="اختبار مقارنة: الخروج المبكر متوقف؛ حماية وقف الخسارة وجني الربح ما زالت فعّالة";
      g_lastBlock="";
      return true;
   }

   int oppositeFrame=OppositeSummaryTimeframe(side);
   string reason="";
   if(oppositeFrame>=0)
      reason="OPPOSITE_SUMMARY";
   else if(InpUseM1PriceReversalExit && ConfirmedM1PriceReversal(side,reason))
      reason="REAL_M1_REVERSAL";
   else
   {
      g_lastAction="الإبقاء على الصفقة؛ لا انقلاب ملخص ولا كسر سعري مؤكد";
      g_lastBlock="";
      return true;
   }

   Print("TV26_EXIT_TRIGGER;reason=",reason,
         ";bar=",TimeToString(iTime(_Symbol,PERIOD_M1,1),TIME_DATE|TIME_MINUTES),
         ";side=",EnumToString(side),
         ";ticket=",ticket,
         ";M5=",DoubleToString(g_rating[1],3),
         ";M15=",DoubleToString(g_rating[2],3),
         ";M30=",DoubleToString(g_rating[3],3),
         ";M1_close=",DoubleToString(iClose(_Symbol,PERIOD_M1,1),_Digits),
         ";opposite_frame=",(oppositeFrame>=0?TFName(g_tfs[oppositeFrame]):"none"));
   if(CloseTicket(ticket))
   {
      g_lastAction=(reason=="OPPOSITE_SUMMARY" ?
                    "أُغلقت الصفقة: أحد ملخصات د5/د15/د30 انعكس ضدها" :
                    "أُغلقت الصفقة: ارتداد سعري مؤكد على د1");
      g_lastBlock="";
      Print("TV26_EXIT_COMPLETED;reason=",reason,
            ";bar=",TimeToString(iTime(_Symbol,PERIOD_M1,1),TIME_DATE|TIME_MINUTES),
            ";ticket=",ticket);
   }
   else
   {
      g_lastAction="فشل إغلاق الصفقة؛ راجع سجل التنفيذ";
      g_lastBlock="رفض أمر الإغلاق أو بقي جزء من المركز مفتوحاً";
      Print("TV26_EXIT_FAILED;reason=",reason,
            ";bar=",TimeToString(iTime(_Symbol,PERIOD_M1,1),TIME_DATE|TIME_MINUTES),
            ";ticket=",ticket);
   }
   return true;
}
void TradeIfAligned()
{
   if(InpTesterOnly && !MQLInfoInteger(MQL_TESTER))
   {
      g_lastBlock="وضع الاختبار فقط مفعّل؛ التشغيل خارج Strategy Tester ممنوع";
      g_lastAction="لم يُرسل أمر خارج الاختبار";
      Print("TV26_ENTRY_BLOCK;reason=TESTER_ONLY_GUARD");
      return;
   }
   // Keep the demo-account boundary in force for both entries and rule-based exits.
   if(InpDemoOnly && AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
   {
      g_lastBlock="حماية الحساب: التداول والإغلاق الآلي مسموحان على الحساب التجريبي فقط";
      g_lastAction="لم يتم تعديل أي مركز";
      return;
   }
   if(ManageOpenPositionExit()) return;

   int sig=AlignedSignal();
   datetime decisionBar=iTime(_Symbol,PERIOD_M1,1);
   if(sig==0)
   {
      // A neutral consensus while a position is still open must not erase the
      // last executed direction; otherwise the same side may re-enter immediately
      // after that position closes if consensus briefly returns.
      ulong neutralTicket=0;
      ENUM_POSITION_TYPE neutralSide=POSITION_TYPE_BUY;
      bool neutralPositionOpen=FindOurPosition(neutralTicket,neutralSide);
      if(neutralPositionOpen)
      {
         if(g_lastExecutedSignal!=0)
            Print("TV26_SIGNAL_LATCH_HELD;reason=NEUTRAL_WHILE_POSITION_OPEN;side=",
                  EnumToString(neutralSide),";ticket=",neutralTicket,
                  ";signal_memory=",SignalName(g_lastExecutedSignal),
                  ";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
         g_lastBlock="توافق غير مكتمل؛ تتم متابعة المركز بقواعد الخروج المستقلة";
         g_lastAction="انتظار؛ لا يوجد توافق قوي، مع الاحتفاظ بذاكرة اتجاه الصفقة القائمة";
      }
      else
      {
         if(g_lastExecutedSignal!=0)
         {
            RememberSignal(0);
            Print("TV26_SIGNAL_LATCH_RESET;reason=NEUTRAL_WHILE_FLAT;bar=",
                  TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
         }
         g_lastBlock="";
         g_lastAction="انتظار؛ ملخصات د5/د15/د30 ليست كلها شراءً قوياً أو بيعاً قوياً";
      }
      return;
   }
   Print("TV26_CONSENSUS;signal=",SignalName(sig),
         ";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
         ";M5=",DoubleToString(g_rating[1],3),
         ";M15=",DoubleToString(g_rating[2],3),
         ";M30=",DoubleToString(g_rating[3],3));

   if(!InpEnableTrading)
   {
      g_lastAction=(sig>0?"إشارة شراء قوي متوافقة":"إشارة بيع قوي متوافقة")+"؛ التنفيذ معطّل";
      Print("TV26_ENTRY_BLOCK;reason=TRADING_DISABLED;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
      return;
   }

   if(HasForeignNettingPosition())
   {
      g_lastBlock="حساب Netting يحتوي على مركز ذهب لا يخص هذا المستشار؛ لم يتم تعديل المركز";
      g_lastAction="منع التنفيذ لحماية المركز الخارجي";
      Print("TV26_ENTRY_BLOCK;reason=FOREIGN_NETTING_POSITION;signal=",SignalName(sig),
            ";symbol=",_Symbol,";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
      return;
   }

   // Optional M1 close-breakout confirmation. The EA is evaluated once per new M1 bar:
   // sell only after the latest closed candle closes below the previous candle's low;
   // buy only after it closes above the previous candle's high.
   if(InpRequireM1CloseBreakout)
   {
      double decisionClose=iClose(_Symbol,PERIOD_M1,1);
      double priorHigh=iHigh(_Symbol,PERIOD_M1,2);
      double priorLow=iLow(_Symbol,PERIOD_M1,2);
      bool referenceReady=(decisionClose>0.0 && priorHigh>0.0 && priorLow>0.0);
      bool breakoutConfirmed=referenceReady && (sig>0 ? decisionClose>priorHigh : decisionClose<priorLow);
      if(!breakoutConfirmed)
      {
         g_lastBlock="تأكيد كسر إغلاق شمعة M1 غير مكتمل";
         g_lastAction="انتظار إغلاق يتجاوز قمة/قاع الشمعة السابقة";
         Print("TV26_ENTRY_BLOCK;reason=M1_CLOSE_BREAKOUT_NOT_CONFIRMED;signal=",SignalName(sig),
               ";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
               ";close=",DoubleToString(decisionClose,_Digits),
               ";prior_high=",DoubleToString(priorHigh,_Digits),
               ";prior_low=",DoubleToString(priorLow,_Digits),
               ";data_ready=",(referenceReady?"true":"false"));
         return;
      }
   }

   ulong trackedTicket=0;
   ENUM_POSITION_TYPE trackedSide;
   bool hasTracked=FindOurPosition(trackedTicket,trackedSide);
   if(hasTracked && ((sig>0 && trackedSide==POSITION_TYPE_BUY) || (sig<0 && trackedSide==POSITION_TYPE_SELL)))
   {
      RememberSignal(sig);
      g_lastAction="الصفقة الحالية في اتجاه الإشارة؛ لا تكرار للدخول";
      g_lastBlock="";
      Print("TV26_ENTRY_BLOCK;reason=POSITION_ALREADY_SAME_SIDE;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
      return;
   }
   if(!hasTracked && sig==g_lastExecutedSignal)
   {
      g_lastAction="انتظار؛ أُنفذت إشارة بهذا الاتجاه سابقاً، ولن تتكرر حتى تتغير حالة التوافق";
      Print("TV26_ENTRY_BLOCK;reason=SAME_SIGNAL_LATCH;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
      return;
   }
   if(!hasTracked && InpCooldownBarsAfterExit>0 && g_lastExitTime>0)
   {
      datetime allowedFrom=g_lastExitTime+(datetime)(InpCooldownBarsAfterExit*PeriodSeconds(PERIOD_M1));
      datetime currentBar=iTime(_Symbol,PERIOD_M1,0);
      if(currentBar>0 && currentBar<allowedFrom)
      {
         g_lastBlock="فترة تهدئة بعد إغلاق الصفقة";
         g_lastAction="انتظار؛ منع إعادة الدخول خلال فترة التهدئة";
         Print("TV26_ENTRY_BLOCK;reason=POST_EXIT_COOLDOWN;signal=",SignalName(sig),
               ";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
               ";last_exit=",TimeToString(g_lastExitTime,TIME_DATE|TIME_SECONDS),
               ";allowed_from=",TimeToString(allowedFrom,TIME_DATE|TIME_SECONDS),
               ";cooldown_bars=",InpCooldownBarsAfterExit);
         return;
      }
   }
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   if(ask<=0 || bid<=0 || point<=0)
   {
      g_lastBlock="السعر غير متاح";
      g_lastAction="لم يُرسل أمر";
      Print("TV26_ENTRY_BLOCK;reason=INVALID_PRICE;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
            ";ask=",DoubleToString(ask,_Digits),";bid=",DoubleToString(bid,_Digits),";point=",DoubleToString(point,8));
      return;
   }
   double spread=(ask-bid)/point;
   if(spread>InpMaxSpreadPoints)
   {
      g_lastBlock="السبريد أعلى من الحد: "+DoubleToString(spread,1);
      g_lastAction="انتظار";
      Print("TV26_ENTRY_BLOCK;reason=SPREAD;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
            ";spread_points=",DoubleToString(spread,1),";limit=",DoubleToString(InpMaxSpreadPoints,1));
      return;
   }

   // Validate ATR, stops and volume before closing any opposite position.
   double atr=0;
   if(!ReadBuf(g_atr[0],0,1,atr) || atr<=0)
   {
      g_lastBlock="قيمة ATR غير جاهزة؛ لم تُغلق أي صفقة";
      g_lastAction="انتظار";
      Print("TV26_ENTRY_BLOCK;reason=ATR_NOT_READY;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
            ";atr=",DoubleToString(atr,5));
      return;
   }
   ENUM_ORDER_TYPE type=(sig>0?ORDER_TYPE_BUY:ORDER_TYPE_SELL);
   double entry=(sig>0?ask:bid);
   double sl=(sig>0?entry-InpStopATR*atr:entry+InpStopATR*atr);
   double tp=(sig>0?entry+InpTargetATR*atr:entry-InpTargetATR*atr);
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   sl=NormalizeDouble(sl,digits);
   tp=NormalizeDouble(tp,digits);
   double lots=LotsByRisk(type,entry,sl);
   if(lots<=0)
   {
      g_lastBlock="حجم العقد المحسوب أقل من الحد الأدنى أو تعذر حساب المخاطرة؛ لم تُغلق أي صفقة";
      g_lastAction="لم يُرسل أمر";
      double riskBudget=AccountInfoDouble(ACCOUNT_EQUITY)*InpRiskPercent/100.0;
      double minVolume=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      double minLotLoss=0.0;
      bool minLotCalculated=OrderCalcProfit(type,_Symbol,minVolume,entry,sl,minLotLoss);
      Print("TV26_ENTRY_BLOCK;reason=MIN_VOLUME_RISK_CAP;signal=",SignalName(sig),
            ";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
            ";equity=",DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2),
            ";risk_budget=",DoubleToString(riskBudget,2),
            ";atr=",DoubleToString(atr,5),
            ";stop_distance=",DoubleToString(MathAbs(entry-sl),5),
            ";minimum_volume=",DoubleToString(minVolume,2),
            ";minimum_volume_loss=",DoubleToString(MathAbs(minLotLoss),2),
            ";min_lot_calc=",(minLotCalculated?"true":"false"),
            ";detail=calculated risk-size below broker minimum or risk calculation failed");
      return;
   }
   ulong ticket=0;
   ENUM_POSITION_TYPE side;
   if(FindOurPosition(ticket,side))
   {
      if((sig>0 && side==POSITION_TYPE_BUY)||(sig<0 && side==POSITION_TYPE_SELL))
      {
         g_lastAction="الصفقة الحالية في اتجاه الإشارة؛ لا تكرار للدخول";
         g_lastBlock="";
         Print("TV26_ENTRY_BLOCK;reason=POSITION_ALREADY_SAME_SIDE;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
         return;
      }
      if(!CloseTicket(ticket))
      {
         g_lastBlock="تعذر إغلاق الصفقة المعاكسة؛ راجع سجل Experts";
         g_lastAction="إيقاف الانعكاس";
         Print("TV26_ENTRY_BLOCK;reason=OPPOSITE_POSITION_CLOSE_FAILED;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES));
         return;
      }
   }
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action=TRADE_ACTION_DEAL;
   req.symbol=_Symbol;
   req.magic=InpMagic;
   req.volume=lots;
   req.type=type;
   req.price=entry;
   req.sl=sl;
   req.tp=tp;
   req.deviation=InpDeviationPoints;
   req.type_filling=FillMode();
   req.comment="TV26 all-TF strong rating";
   bool sent=OrderSend(req,res);
   if(sent && (res.retcode==TRADE_RETCODE_DONE || res.retcode==TRADE_RETCODE_DONE_PARTIAL || res.retcode==TRADE_RETCODE_PLACED))
   {
      RememberSignal(sig);
      g_lastAction=(sig>0?"شراء":"بيع")+" نُفّذ/قُبل؛ حجم "+DoubleToString(lots,2);
      g_lastBlock="";
      Print("TV26_ORDER_ACCEPTED;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
            ";retcode=",res.retcode,";volume=",DoubleToString(lots,2),";entry=",DoubleToString(entry,digits),
            ";sl=",DoubleToString(sl,digits),";tp=",DoubleToString(tp,digits));
   }
   else
   {
      g_lastAction="رفض الأمر؛ لم يُعتبر التنفيذ ناجحاً";
      g_lastBlock="رمز الوسيط: "+IntegerToString((int)res.retcode)+" / "+res.comment;
      Print("TV26_ORDER_REJECTED;signal=",SignalName(sig),";bar=",TimeToString(decisionBar,TIME_DATE|TIME_MINUTES),
            ";sent=",(sent?"true":"false"),";retcode=",res.retcode,";comment=",res.comment,
            ";volume=",DoubleToString(lots,2),";entry=",DoubleToString(entry,digits),
            ";sl=",DoubleToString(sl,digits),";tp=",DoubleToString(tp,digits));
   }
}
int OnInit()
{
   g_tfs[0]=InpTF1;g_tfs[1]=InpTF2;g_tfs[2]=InpTF3;g_tfs[3]=InpTF4;g_tfs[4]=InpTF5;
   // Signal and exit functions use fixed timeframe indices; reject any altered order to avoid silently rating the wrong periods.
   if(g_tfs[0]!=PERIOD_M1 || g_tfs[1]!=PERIOD_M5 ||
      g_tfs[2]!=PERIOD_M15 || g_tfs[3]!=PERIOD_M30 ||
      g_tfs[4]!=PERIOD_H1)
   {
      Print("TV26: ترتيب الأطر يجب أن يكون M1/M5/M15/M30/H1؛ إجماع الدخول والخروج يعتمد على هذه الفهارس");
      return INIT_PARAMETERS_INCORRECT;
   }
   // Hard safety limit: reject accidental risk settings above the lab's 2% ceiling.
   if(InpRiskPercent<=0 || InpRiskPercent>2.0)
   {
      Print("TV26: نسبة المخاطرة يجب أن تكون أكبر من صفر ولا تتجاوز 2.0%");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpATRPeriod<1 || InpStopATR<=0 || InpTargetATR<=0 ||
      InpMaxSpreadPoints<0 || InpDeviationPoints<0 || InpCooldownBarsAfterExit<0)
   {
      Print("TV26: إعدادات ATR أو السبريد أو الانزلاق أو التهدئة غير صالحة");
      return INIT_PARAMETERS_INCORRECT;
   }
   InitHandles();
   g_auditFile="TV26_Audit_"+_Symbol+"_"+IntegerToString((int)InpMagic)+".csv";
   ExportReferenceHistory();
   g_signalGV="TV26_LastSignal_"+_Symbol+"_"+IntegerToString((int)InpMagic);
   if(GlobalVariableCheck(g_signalGV)) g_lastExecutedSignal=(int)GlobalVariableGet(g_signalGV);
   EventSetTimer(2);
   Print("TV26 Arabic candidate initialized. This is a research candidate; validate in MetaEditor and Strategy Tester before use.");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason)
{
   EventKillTimer();ReleaseHandles();Comment("");
}
void OnTimer()
{
   if(!g_historyExported) ExportReferenceHistory();
   EvaluateAll();DrawPanel();ExportAuditIfNeeded();
}
// Detect actual position-closing deals, including broker SL/TP exits, for the optional cooldown.
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetString(trans.deal,DEAL_SYMBOL)!=_Symbol) return;
   if((ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)!=InpMagic) return;
   long entryKind=HistoryDealGetInteger(trans.deal,DEAL_ENTRY);
   if(entryKind!=DEAL_ENTRY_OUT && entryKind!=DEAL_ENTRY_OUT_BY && entryKind!=DEAL_ENTRY_INOUT) return;
   datetime closeTime=(datetime)HistoryDealGetInteger(trans.deal,DEAL_TIME);
   if(closeTime>g_lastExitTime) g_lastExitTime=closeTime;
   Print("TV26_POSITION_CLOSED;deal=",trans.deal,
         ";time=",TimeToString(closeTime,TIME_DATE|TIME_SECONDS),
         ";reason=",EnumToString((ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal,DEAL_REASON)),
         ";cooldown_bars=",InpCooldownBarsAfterExit);
}
void OnTick()
{
   if(!IsNewM1Bar()) return;
   EvaluateAll();DrawPanel();ExportAuditIfNeeded();TradeIfAligned();DrawPanel();
}
