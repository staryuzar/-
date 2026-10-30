#property strict
#property version   "1.001"
#property description "Bitcoin Intelligence Lab — Headway BTC demo command executor"

#include <Trade/Trade.mqh>

input ulong  MagicNumber = 28102027;
input bool   EnableTrading = true;
input bool   RequireHeadwayDemo = true;
input int    MaxSpreadPoints = 6000;
input int    CommandPollSeconds = 1;
input int    SlippagePoints = 100;
input double MaxRiskPercent = 0.50;
input bool   ShowStatusOnChart = true;

CTrade trade;
string lastCommandId = "";
string lastStatus = "Initializing";
datetime lastHeartbeat = 0;

string BaseFolder() { return "BitcoinIntelligenceLab\\"; }

bool IsAllowedAccount()
{
   ENUM_ACCOUNT_TRADE_MODE mode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string server = AccountInfoString(ACCOUNT_SERVER);
   if(RequireHeadwayDemo)
      return (mode == ACCOUNT_TRADE_MODE_DEMO && StringFind(server, "Headway-Demo") >= 0);
   return (mode == ACCOUNT_TRADE_MODE_DEMO);
}

bool TerminalAllowsTrading()
{
   return (EnableTrading && TerminalInfoInteger(TERMINAL_CONNECTED) &&
           TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED) &&
           IsAllowedAccount());
}

bool WriteTextFile(const string relativePath, const string content)
{
   int handle = FileOpen(BaseFolder()+relativePath, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle == INVALID_HANDLE) return false;
   FileWriteString(handle, content);
   FileClose(handle);
   return true;
}

void WriteAck(const string commandId, const string status, const string action, const string detail)
{
   string safeDetail = detail;
   StringReplace(safeDetail, "|", "/");
   StringReplace(safeDetail, "\r", " ");
   StringReplace(safeDetail, "\n", " ");
   StringReplace(safeDetail, "\"", "'");
   string json = StringFormat(
      "{\"schema\":\"BTCIL1\",\"id\":\"%s\",\"status\":\"%s\",\"action\":\"%s\",\"time_utc\":%I64d,\"detail\":\"%s\"}",
      commandId,status,action,(long)TimeGMT(),safeDetail
   );
   WriteTextFile("trade_command_ack.txt", json);
}

void WriteStatus()
{
   double bid=0, ask=0;
   SymbolInfoDouble(_Symbol,SYMBOL_BID,bid);
   SymbolInfoDouble(_Symbol,SYMBOL_ASK,ask);
   string line=StringFormat("BTCIL1|%s|%s|%I64d|%s|%.8f|%.8f|%d|%s\n",
      _Symbol,EnumToString(_Period),(long)TimeGMT(),
      TerminalInfoInteger(TERMINAL_CONNECTED)?"CONNECTED":"DISCONNECTED",
      bid,ask,(int)PositionsTotal(),lastStatus);
   WriteTextFile("ea_status.tsv",line);
}

bool ValidVolume(const double volume)
{
   double minLot=0, maxLot=0, step=0;
   if(!SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN,minLot) ||
      !SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX,maxLot) ||
      !SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP,step) ||
      minLot<=0 || maxLot<minLot || step<=0 || volume<minLot || volume>maxLot)
      return false;
   return (MathAbs((volume-minLot)/step-MathRound((volume-minLot)/step))<1e-6);
}

bool HasOwnPosition()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber) return true;
   }
   return false;
}

bool ValidProtection(const string side,const double sl,const double tp)
{
   double bid=0, ask=0, point=0;
   long stops=0, freeze=0;
   if(!SymbolInfoDouble(_Symbol,SYMBOL_BID,bid) || !SymbolInfoDouble(_Symbol,SYMBOL_ASK,ask) ||
      !SymbolInfoDouble(_Symbol,SYMBOL_POINT,point) || !SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL,stops) ||
      !SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL,freeze) || point<=0 || bid<=0 || ask<=0)
      return false;
   double minDistance=(double)MathMax(stops,freeze)*point;
   if(side=="BUY") return sl<bid && tp>ask && (bid-sl)>=minDistance && (tp-ask)>=minDistance;
   if(side=="SELL") return sl>ask && tp<bid && (sl-ask)>=minDistance && (bid-tp)>=minDistance;
   return false;
}

bool CloseOwnPosition(const ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return false;
   if(PositionGetString(POSITION_SYMBOL)!=_Symbol ||
      (ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber) return false;
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(SlippagePoints);
   bool sent=trade.PositionClose(ticket);
   uint code=trade.ResultRetcode();
   return sent && (code==TRADE_RETCODE_DONE || code==TRADE_RETCODE_DONE_PARTIAL);
}

bool OpenBoardPosition(const string side,const double volume,const double sl,const double tp)
{
   if(!TerminalAllowsTrading()) { lastStatus="BLOCKED: Headway DEMO/terminal permission gate"; return false; }
   if(_Symbol!="BTC" || _Period!=PERIOD_M1) { lastStatus="BLOCKED: attach to BTC M1 chart"; return false; }
   if(HasOwnPosition()) { lastStatus="BLOCKED: EA-managed BTC position already exists"; return false; }
   if(!ValidVolume(volume)) { lastStatus="BLOCKED: volume violates broker min/max/step"; return false; }

   double bid=0, ask=0, point=0;
   if(!SymbolInfoDouble(_Symbol,SYMBOL_BID,bid) || !SymbolInfoDouble(_Symbol,SYMBOL_ASK,ask) ||
      !SymbolInfoDouble(_Symbol,SYMBOL_POINT,point) || point<=0 || ask<bid)
   { lastStatus="BLOCKED: broker quote unavailable"; return false; }
   if((ask-bid)/point>MaxSpreadPoints) { lastStatus="BLOCKED: spread exceeds EA limit"; return false; }
   if(!ValidProtection(side,sl,tp)) { lastStatus="BLOCKED: stop/target violates price or broker stops"; return false; }

   double projectedLoss=0.0;
   ENUM_ORDER_TYPE orderType=(side=="BUY")?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   double entry=(side=="BUY")?ask:bid;
   if(!OrderCalcProfit(orderType,_Symbol,volume,entry,sl,projectedLoss) || projectedLoss>=0.0 ||
      MathAbs(projectedLoss)>AccountInfoDouble(ACCOUNT_EQUITY)*MaxRiskPercent/100.0)
   { lastStatus="BLOCKED: broker-calculated stop loss exceeds risk budget"; return false; }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(SlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   bool sent=false;
   if(side=="BUY") sent=trade.Buy(volume,_Symbol,0.0,sl,tp,"Bitcoin Intelligence Lab");
   if(side=="SELL") sent=trade.Sell(volume,_Symbol,0.0,sl,tp,"Bitcoin Intelligence Lab");
   uint code=trade.ResultRetcode();
   if(!sent || (code!=TRADE_RETCODE_DONE && code!=TRADE_RETCODE_PLACED && code!=TRADE_RETCODE_DONE_PARTIAL))
   {
      lastStatus=StringFormat("ORDER_REJECTED: retcode=%u %s",code,trade.ResultRetcodeDescription());
      return false;
   }
   ulong deal=trade.ResultDeal();
   if(deal>0 && HistoryDealSelect(deal))
   {
      if(HistoryDealGetString(deal,DEAL_SYMBOL)==_Symbol &&
         (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)==MagicNumber)
         lastStatus=StringFormat("ORDER_FILL_CONFIRMED: deal=%I64u order=%I64u",deal,trade.ResultOrder());
      else lastStatus="ORDER_SUBMITTED: deal identity mismatch; inspect terminal history";
   }
   else lastStatus=StringFormat("ORDER_SUBMITTED_PENDING: retcode=%u order=%I64u",code,trade.ResultOrder());
   return true;
}

void PollProgramCommand()
{
   int handle=FileOpen(BaseFolder()+"trade_command.txt",FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE) return;
   string line=FileReadString(handle);
   FileClose(handle);
   if(StringLen(line)<10) return;

   string fields[];
   ushort separator=StringGetCharacter("|",0);
   int count=StringSplit(line,separator,fields);
   if(count!=11 || fields[0]!="BTCIL1") { lastStatus="BLOCKED: malformed command envelope"; return; }

   string commandId=fields[1];
   if(commandId==lastCommandId) return;
   long issued=(long)StringToInteger(fields[2]);
   long expires=(long)StringToInteger(fields[3]);
   string symbol=fields[4], action=fields[5], side=fields[6];
   double volume=StringToDouble(fields[7]), sl=StringToDouble(fields[8]), tp=StringToDouble(fields[9]);
   ulong ticket=(ulong)StringToInteger(fields[10]);
   long now=(long)TimeGMT();
   if(symbol!="BTC" || issued<=0 || expires<=now || issued>now+5 || expires-issued>300)
   { lastCommandId=commandId; WriteAck(commandId,"REJECTED","NONE","Expired or invalid timestamp/symbol"); return; }

   bool ok=false;
   string detail="";
   if(action=="OPEN")
   {
      ok=OpenBoardPosition(side,volume,sl,tp);
      detail=lastStatus;
   }
   else if(action=="CLOSE")
   {
      if(!TerminalAllowsTrading()) { lastStatus="BLOCKED: Headway DEMO/terminal permission gate"; ok=false; }
      else { ok=CloseOwnPosition(ticket); lastStatus=ok?"CLOSE_ACCEPTED":"CLOSE_REJECTED"; }
      detail=lastStatus;
   }
   else { lastStatus="BLOCKED: unsupported action"; detail=lastStatus; }

   lastCommandId=commandId;
   WriteAck(commandId,ok?"ACCEPTED":"REJECTED",action,detail);
}

int OnInit()
{
   if(_Symbol!="BTC" || _Period!=PERIOD_M1)
   {
      Print("BTCIL|INIT_BLOCKED|attach to exact BTC M1 chart; current=",_Symbol,"/",EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   if(MagicNumber==0 || CommandPollSeconds<1 || MaxSpreadPoints<0 || SlippagePoints<0 ||
      MaxRiskPercent<=0 || MaxRiskPercent>1.0) return INIT_PARAMETERS_INCORRECT;
   FolderCreate("BitcoinIntelligenceLab",FILE_COMMON);
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(SlippagePoints);
   if(!EventSetTimer(CommandPollSeconds)) return INIT_FAILED;
   lastStatus=TerminalAllowsTrading()?"READY: Headway demo board-execution mode":"WAITING: Headway demo / connection / Algo Trading permission";
   WriteStatus();
   Print("BTCIL|INIT|symbol=",_Symbol,"|period=",EnumToString(_Period),
         "|server=",AccountInfoString(ACCOUNT_SERVER),"|demo=",IsAllowedAccount()?"true":"false",
         "|trade_enabled=",EnableTrading?"true":"false","|magic=",MagicNumber);
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   PollProgramCommand();
   datetime now=TimeGMT();
   if(now-lastHeartbeat>=10) { WriteStatus(); lastHeartbeat=now; }
   if(ShowStatusOnChart) Comment("Bitcoin Intelligence Lab\n",lastStatus);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   WriteTextFile("ea_status.tsv",StringFormat("BTCIL1|DEINIT|%I64d|%s\n",(long)TimeGMT(),lastStatus));
   Comment("");
}

void OnTick()
{
   // No self-generated entries. The centralized board is the only decision authority.
}
