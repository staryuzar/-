#property strict
#property version   "1.009"
#property description "TV26 Technical Ratings clone candidate - Arabic panel, five timeframes"

input bool   InpEnableTrading       = true;
input bool   InpDemoOnly            = true;
input ulong  InpMagic               = 26102326;
input double InpRiskPercent         = 0.50;
input int    InpATRPeriod           = 14;
input double InpStopATR             = 2.0;
input double InpTargetATR           = 3.0;
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
double g_rating[N_TF];
double g_maRating[N_TF], g_oscRating[N_TF];
int g_ready[N_TF], g_maReady[N_TF], g_oscReady[N_TF];
datetime g_lastM1Bar=0;
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
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b)) return false;
      score=(a<30 && a>b ? 1 : (a>70 && a<b ? -1 : 0));
      g_diagA[t][j]=a; g_diagB[t][j]=b;
      return true;
   }
   if(j==STOCH14)
   {
      // TradingView stochFull(14,3,3): raw %K, SMA(3) for K, then SMA(3) for D.
      if(!TVStochasticValues(g_tfs[t],a,b)) return false;
      score=(a<20 && b<20 && a>b ? 1 : (a>80 && b>80 && a<b ? -1 : 0));
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
      score=(downtrend && k0<20 && d0<20 && k0>d0 ? 1 :
             (uptrend && k0>80 && d0>80 && k0<d0 ? -1 : 0));
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
int AlignedSignal()
{
   bool allStrongBuy=true, allStrongSell=true;
   for(int t=0;t<N_TF;t++)
   {
      if(g_ready[t]!=N_RATINGS || g_maReady[t]!=15 || g_oscReady[t]!=11) return 0;
      if(g_rating[t]<=STRONG) allStrongBuy=false;
      if(g_rating[t]>=-STRONG) allStrongSell=false;
   }
   if(allStrongBuy) return 1;
   if(allStrongSell) return -1;
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
   req.deviation=InpDeviationPoints;req.type_filling=ORDER_FILLING_IOC;req.comment="TV26 close opposite";
   bool sent=OrderSend(req,res);
   if(!sent || (res.retcode!=TRADE_RETCODE_DONE && res.retcode!=TRADE_RETCODE_DONE_PARTIAL))
      return false;
   // A partial-close retcode is not a successful reversal if the old position remains.
   return !PositionSelectByTicket(ticket);
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
void TradeIfAligned()
{
   int sig=AlignedSignal();
   if(sig==0)
   {
      RememberSignal(0); // Re-arm after the five-timeframe consensus is no longer strong.
      g_lastAction="انتظار؛ لا يوجد توافق قوي مكتمل بين الأطر الخمسة";
      return;
   }
   if(!InpEnableTrading){g_lastAction=(sig>0?"إشارة شراء قوي متوافقة":"إشارة بيع قوي متوافقة")+"؛ التنفيذ معطّل";return;}

   ulong trackedTicket=0;
   ENUM_POSITION_TYPE trackedSide;
   bool hasTracked=FindOurPosition(trackedTicket,trackedSide);
   if(hasTracked && ((sig>0 && trackedSide==POSITION_TYPE_BUY) || (sig<0 && trackedSide==POSITION_TYPE_SELL)))
   {
      RememberSignal(sig);
      g_lastAction="الصفقة الحالية في اتجاه الإشارة؛ لا تكرار للدخول";
      g_lastBlock="";
      return;
   }
   if(!hasTracked && sig==g_lastExecutedSignal)
   {
      g_lastAction="انتظار؛ أُنفذت إشارة بهذا الاتجاه سابقاً، ولن تتكرر حتى تتغير حالة التوافق";
      return;
   }
   if(InpDemoOnly && AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
   {g_lastBlock="حماية الحساب: التداول مسموح على الحساب التجريبي فقط";g_lastAction="لم يُرسل أمر";return;}
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK),bid=SymbolInfoDouble(_Symbol,SYMBOL_BID),point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   if(ask<=0 || bid<=0 || point<=0){g_lastBlock="السعر غير متاح";return;}
   double spread=(ask-bid)/point;
   if(spread>InpMaxSpreadPoints){g_lastBlock="السبريد أعلى من الحد: "+DoubleToString(spread,1);g_lastAction="انتظار";return;}
   // Validate ATR, stops and volume before closing any opposite position.
   double atr=0;
   if(!ReadBuf(g_atr[0],0,1,atr) || atr<=0){g_lastBlock="قيمة ATR غير جاهزة؛ لم تُغلق أي صفقة";g_lastAction="انتظار";return;}
   ENUM_ORDER_TYPE type=(sig>0?ORDER_TYPE_BUY:ORDER_TYPE_SELL);
   double entry=(sig>0?ask:bid);
   double sl=(sig>0?entry-InpStopATR*atr:entry+InpStopATR*atr);
   double tp=(sig>0?entry+InpTargetATR*atr:entry-InpTargetATR*atr);
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   sl=NormalizeDouble(sl,digits);tp=NormalizeDouble(tp,digits);
   double lots=LotsByRisk(type,entry,sl);
   if(lots<=0){g_lastBlock="حجم العقد المحسوب أقل من الحد الأدنى أو تعذر حساب المخاطرة؛ لم تُغلق أي صفقة";g_lastAction="لم يُرسل أمر";return;}
   ulong ticket=0;ENUM_POSITION_TYPE side;
   if(FindOurPosition(ticket,side))
   {
      if((sig>0 && side==POSITION_TYPE_BUY)||(sig<0 && side==POSITION_TYPE_SELL))
      {g_lastAction="الصفقة الحالية في اتجاه الإشارة؛ لا تكرار للدخول";g_lastBlock="";return;}
      if(!CloseTicket(ticket)){g_lastBlock="تعذر إغلاق الصفقة المعاكسة؛ راجع سجل Experts";g_lastAction="إيقاف الانعكاس";return;}
   }
   MqlTradeRequest req;MqlTradeResult res;ZeroMemory(req);ZeroMemory(res);
   req.action=TRADE_ACTION_DEAL;req.symbol=_Symbol;req.magic=InpMagic;req.volume=lots;req.type=type;req.price=entry;
   req.sl=sl;req.tp=tp;req.deviation=InpDeviationPoints;req.type_filling=FillMode();req.comment="TV26 all-TF strong rating";
   bool sent=OrderSend(req,res);
   if(sent && (res.retcode==TRADE_RETCODE_DONE || res.retcode==TRADE_RETCODE_DONE_PARTIAL || res.retcode==TRADE_RETCODE_PLACED))
   {RememberSignal(sig);g_lastAction=(sig>0?"شراء":"بيع")+" نُفّذ/قُبل؛ حجم "+DoubleToString(lots,2);g_lastBlock="";Print("TV26 order accepted. retcode=",res.retcode," volume=",lots);}
   else
   {g_lastAction="رفض الأمر؛ لم يُعتبر التنفيذ ناجحاً";g_lastBlock="رمز الوسيط: "+IntegerToString((int)res.retcode)+" / "+res.comment;Print("TV26 order failed. sent=",sent," retcode=",res.retcode," comment=",res.comment);}
}
int OnInit()
{
   g_tfs[0]=InpTF1;g_tfs[1]=InpTF2;g_tfs[2]=InpTF3;g_tfs[3]=InpTF4;g_tfs[4]=InpTF5;
   for(int t=0;t<N_TF;t++)
      for(int k=0;k<t;k++) if(g_tfs[t]==g_tfs[k]){Print("TV26: يجب اختيار خمسة أطر زمنية مختلفة");return INIT_PARAMETERS_INCORRECT;}
   if(InpRiskPercent<=0 || InpStopATR<=0 || InpTargetATR<=0){Print("TV26: إعدادات المخاطرة غير صالحة");return INIT_PARAMETERS_INCORRECT;}
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
void OnTick()
{
   if(!IsNewM1Bar()) return;
   EvaluateAll();DrawPanel();ExportAuditIfNeeded();TradeIfAligned();DrawPanel();
}
