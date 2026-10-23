#property strict
#property version   "1.000"
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
int g_scores[N_TF][N_RATINGS];
bool g_working[N_TF][N_RATINGS];
double g_rating[N_TF];
double g_maRating[N_TF], g_oscRating[N_TF];
int g_ready[N_TF], g_maReady[N_TF], g_oscReady[N_TF];
datetime g_lastM1Bar=0;
datetime g_lastPanelUpdate=0;
string g_lastAction="لم يُرسل أي أمر";
string g_lastBlock="";

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
string SummaryName(double r,int ready)
{
   if(ready<N_RATINGS) return "غير مكتمل";
   if(r>STRONG) return "شراء قوي";
   if(r>0.10) return "شراء";
   if(r< -STRONG) return "بيع قوي";
   if(r< -0.10) return "بيع";
   return "حياد";
}
bool ReadBuf(int handle,int buffer,int shift,double &v)
{
   if(handle==INVALID_HANDLE) return false;
   double a[]; ArraySetAsSeries(a,true);
   if(CopyBuffer(handle,buffer,shift,1,a)!=1) return false;
   v=a[0]; return MathIsValidNumber(v) && v!=EMPTY_VALUE;
}
bool ReadRates(ENUM_TIMEFRAMES tf,int count,int shift,MqlRates &rates[])
{
   ArraySetAsSeries(rates,true);
   return CopyRates(_Symbol,tf,shift,count,rates)==count;
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
      g_bulls[t]=iBullsPower(_Symbol,g_tfs[t],13);
      g_bears[t]=iBearsPower(_Symbol,g_tfs[t],13);
      g_atr[t]=iATR(_Symbol,g_tfs[t],InpATRPeriod);
      g_trendEMA[t]=iMA(_Symbol,g_tfs[t],13,0,MODE_EMA,PRICE_CLOSE);
      int periods[12]={10,10,20,20,30,30,50,50,100,100,200,200};
      for(int j=0;j<12;j++)
      {
         ENUM_MA_METHOD method=(j%2==0 ? MODE_SMA : MODE_EMA);
         g_handles[t][j]=iMA(_Symbol,g_tfs[t],periods[j],0,method,PRICE_CLOSE);
      }
      g_handles[t][ICHIMOKU_BASE]=iIchimoku(_Symbol,g_tfs[t],9,26,52);
      g_handles[t][RSI14]=iRSI(_Symbol,g_tfs[t],14,PRICE_CLOSE);
      g_handles[t][STOCH14]=iStochastic(_Symbol,g_tfs[t],14,3,3,MODE_SMA,STO_LOWHIGH);
      g_handles[t][CCI20]=iCCI(_Symbol,g_tfs[t],20,PRICE_TYPICAL);
      g_handles[t][ADX14]=iADX(_Symbol,g_tfs[t],14);
      g_handles[t][AO]=iAO(_Symbol,g_tfs[t]);
      g_handles[t][MOMENTUM10]=iMomentum(_Symbol,g_tfs[t],10,PRICE_CLOSE);
      g_handles[t][MACD]=iMACD(_Symbol,g_tfs[t],12,26,9,PRICE_CLOSE);
      g_handles[t][WILLIAMS_R]=iWPR(_Symbol,g_tfs[t],14);
      if(g_bulls[t]==INVALID_HANDLE || g_bears[t]==INVALID_HANDLE || g_atr[t]==INVALID_HANDLE)
         Print("TV26 init: handle auxiliary failed for ",TFName(g_tfs[t]));
      for(int j=0;j<N_RATINGS;j++)
      {
         if(j==VWMA20 || j==HULL9 || j==STOCH_RSI || j==BULL_BEAR_POWER || j==ULTIMATE_OSC) continue;
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
      score=(cc[0]>a ? 1 : (cc[0]<a ? -1 : 0)); return true;
   }
   if(j==ICHIMOKU_BASE)
   {
      double conversion=0, base=0, spanA=0, spanB=0;
      if(!ReadBuf(g_handles[t][j],0,1,conversion) || !ReadBuf(g_handles[t][j],1,1,base) ||
         !ReadBuf(g_handles[t][j],2,1,spanA) || !ReadBuf(g_handles[t][j],3,1,spanB)) return false;
      double cc[]; ArraySetAsSeries(cc,true);
      if(CopyClose(_Symbol,g_tfs[t],1,1,cc)!=1) return false;
      if(spanA>spanB && base>spanA && conversion>base && cc[0]>conversion) score=1;
      else if(spanA<spanB && base<spanA && conversion<base && cc[0]<conversion) score=-1;
      else score=0;
      return true;
   }
   if(j==VWMA20 || j==HULL9)
   {
      a=(j==VWMA20 ? VWMAValue(g_tfs[t]) : HullValue(g_tfs[t]));
      if(a==EMPTY_VALUE || !MathIsValidNumber(a)) return false;
      double cc[]; ArraySetAsSeries(cc,true);
      if(CopyClose(_Symbol,g_tfs[t],1,1,cc)!=1) return false;
      score=(cc[0]>a ? 1 : (cc[0]<a ? -1 : 0)); return true;
   }
   if(j==RSI14)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b)) return false;
      score=(a<30 && a>b ? 1 : (a>70 && a<b ? -1 : 0)); return true;
   }
   if(j==STOCH14)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],1,1,b)) return false;
      score=(a<20 && b<20 && a>b ? 1 : (a>80 && b>80 && a<b ? -1 : 0)); return true;
   }
   if(j==CCI20)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b)) return false;
      score=(a<-100 && a>b ? 1 : (a>100 && a<b ? -1 : 0)); return true;
   }
   if(j==ADX14)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],1,1,b) || !ReadBuf(g_handles[t][j],2,1,c)) return false;
      double prevADX=0;
      if(!ReadBuf(g_handles[t][j],0,2,prevADX)) return false;
      score=(a>20 && b>c && a>prevADX ? 1 : (a>20 && b<c && a<prevADX ? -1 : 0)); return true;
   }
   if(j==AO)
   {
      double prev2=0;
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b) || !ReadBuf(g_handles[t][j],0,3,prev2)) return false;
      bool buyCross=(a>0 && b<=0), sellCross=(a<0 && b>=0);
      bool buySaucer=(a>0 && b>0 && a>b && b<prev2);
      bool sellSaucer=(a<0 && b<0 && a<b && b>prev2);
      score=(buyCross || buySaucer ? 1 : (sellCross || sellSaucer ? -1 : 0)); return true;
   }
   if(j==MOMENTUM10)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b)) return false;
      score=(a>b ? 1 : (a<b ? -1 : 0)); return true;
   }
   if(j==MACD)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],1,1,b)) return false;
      score=(a>b ? 1 : (a<b ? -1 : 0)); return true;
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
      bool downtrend=(rsi[0]<rsi[1]), uptrend=(rsi[0]>rsi[1]);
      score=(downtrend && k0<20 && d0<20 && k0>d0 ? 1 :
             (uptrend && k0>80 && d0>80 && k0<d0 ? -1 : 0));
      return true;
   }
   if(j==WILLIAMS_R)
   {
      if(!ReadBuf(g_handles[t][j],0,1,a) || !ReadBuf(g_handles[t][j],0,2,b)) return false;
      score=(a<-80 && a>b ? 1 : (a>-20 && a<b ? -1 : 0)); return true;
   }
   if(j==BULL_BEAR_POWER)
   {
      double bullPrev=0,bearNow=0,bearPrev=0,emaNow=0,emaPrev=0;
      if(!ReadBuf(g_bulls[t],0,1,a) || !ReadBuf(g_bulls[t],0,2,bullPrev) ||
         !ReadBuf(g_bears[t],0,1,bearNow) || !ReadBuf(g_bears[t],0,2,bearPrev) ||
         !ReadBuf(g_trendEMA[t],0,1,emaNow) || !ReadBuf(g_trendEMA[t],0,2,emaPrev)) return false;
      double cc[]; ArraySetAsSeries(cc,true);
      if(CopyClose(_Symbol,g_tfs[t],1,1,cc)!=1) return false;
      bool uptrend=(cc[0]>emaNow && emaNow>emaPrev), downtrend=(cc[0]<emaNow && emaNow<emaPrev);
      score=(uptrend && bearNow<0 && bearNow>bearPrev ? 1 :
             (downtrend && a>0 && a<bullPrev ? -1 : 0)); return true;
   }
   if(j==ULTIMATE_OSC)
   {
      a=UltimateValue(g_tfs[t]); if(a==EMPTY_VALUE || !MathIsValidNumber(a)) return false;
      score=(a>70 ? 1 : (a<30 ? -1 : 0)); return true;
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
   if(g_ready[0]!=N_RATINGS || g_ready[1]!=N_RATINGS || g_ready[2]!=N_RATINGS ||
      g_ready[3]!=N_RATINGS || g_ready[4]!=N_RATINGS) return 0;
   for(int t=0;t<N_TF;t++) if(g_rating[t]<STRONG) { bool allSell=true; for(int k=0;k<N_TF;k++) if(g_rating[k]>-STRONG) allSell=false; return (allSell?-1:0); }
   return 1;
}
string DetailSignal(int t,int j)
{
   if(!g_working[t][j]) return "عطل";
   return SignalName(g_scores[t][j]);
}
void DrawPanel()
{
   string p="مستشار تقييم TV26 | الذهب: "+_Symbol+"\n";
   p+="المكونات: 26 (15 متوسطاً + 11 مذبذباً) | الإطار مبني على شموع مغلقة\n";
   p+="الإطار | الملخص العام | المتوسطات | المذبذبات | الجاهز\n";
   for(int t=0;t<N_TF;t++)
      p+=TFName(g_tfs[t])+" | "+SummaryName(g_rating[t],g_ready[t])+" ("+DoubleToString(g_rating[t],3)+") | "+
         SummaryName(g_maRating[t],g_maReady[t])+" | "+SummaryName(g_oscRating[t],g_oscReady[t])+" | "+
         IntegerToString(g_ready[t])+"/26\n";
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
   return sent && (res.retcode==TRADE_RETCODE_DONE || res.retcode==TRADE_RETCODE_DONE_PARTIAL);
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
void TradeIfAligned()
{
   int sig=AlignedSignal();
   if(sig==0){g_lastAction="انتظار؛ لا يوجد توافق قوي مكتمل بين الأطر الخمسة";return;}
   if(!InpEnableTrading){g_lastAction=(sig>0?"إشارة شراء قوي متوافقة":"إشارة بيع قوي متوافقة")+"؛ التنفيذ معطّل";return;}
   if(InpDemoOnly && AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
   {g_lastBlock="حماية الحساب: التداول مسموح على الحساب التجريبي فقط";g_lastAction="لم يُرسل أمر";return;}
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK),bid=SymbolInfoDouble(_Symbol,SYMBOL_BID),point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   if(ask<=0 || bid<=0 || point<=0){g_lastBlock="السعر غير متاح";return;}
   double spread=(ask-bid)/point;
   if(spread>InpMaxSpreadPoints){g_lastBlock="السبريد أعلى من الحد: "+DoubleToString(spread,1);g_lastAction="انتظار";return;}
   ulong ticket=0;ENUM_POSITION_TYPE side;
   if(FindOurPosition(ticket,side))
   {
      if((sig>0 && side==POSITION_TYPE_BUY)||(sig<0 && side==POSITION_TYPE_SELL))
      {g_lastAction="الصفقة الحالية في اتجاه الإشارة؛ لا تكرار للدخول";return;}
      if(!CloseTicket(ticket)){g_lastBlock="تعذر إغلاق الصفقة المعاكسة؛ راجع سجل Experts";g_lastAction="إيقاف الانعكاس";return;}
   }
   double atr=0;
   if(!ReadBuf(g_atr[0],0,1,atr) || atr<=0){g_lastBlock="قيمة ATR غير جاهزة";return;}
   ENUM_ORDER_TYPE type=(sig>0?ORDER_TYPE_BUY:ORDER_TYPE_SELL);
   double entry=(sig>0?ask:bid);
   double sl=(sig>0?entry-InpStopATR*atr:entry+InpStopATR*atr);
   double tp=(sig>0?entry+InpTargetATR*atr:entry-InpTargetATR*atr);
   int digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   sl=NormalizeDouble(sl,digits);tp=NormalizeDouble(tp,digits);
   double lots=LotsByRisk(type,entry,sl);
   if(lots<=0){g_lastBlock="حجم العقد المحسوب أقل من الحد الأدنى أو تعذر حساب المخاطرة";g_lastAction="لم يُرسل أمر";return;}
   MqlTradeRequest req;MqlTradeResult res;ZeroMemory(req);ZeroMemory(res);
   req.action=TRADE_ACTION_DEAL;req.symbol=_Symbol;req.magic=InpMagic;req.volume=lots;req.type=type;req.price=entry;
   req.sl=sl;req.tp=tp;req.deviation=InpDeviationPoints;req.type_filling=FillMode();req.comment="TV26 all-TF strong rating";
   bool sent=OrderSend(req,res);
   if(sent && (res.retcode==TRADE_RETCODE_DONE || res.retcode==TRADE_RETCODE_DONE_PARTIAL || res.retcode==TRADE_RETCODE_PLACED))
   {g_lastAction=(sig>0?"شراء":"بيع")+" نُفّذ/قُبل؛ حجم "+DoubleToString(lots,2);g_lastBlock="";Print("TV26 order accepted. retcode=",res.retcode," volume=",lots);}
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
   EvaluateAll();DrawPanel();
}
void OnTick()
{
   if(!IsNewM1Bar()) return;
   EvaluateAll();DrawPanel();TradeIfAligned();DrawPanel();
}
