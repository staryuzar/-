#property strict
#property version   "1.005"
#property description "Bitcoin Intelligence Lab — Headway BTC demo command executor"

input ulong  MagicNumber = 28102027;
input bool   EnableTrading = true;
input bool   RequireHeadwayDemo = true;
input int    MaxSpreadPoints = 0; // 0 disables this optional filter
input int    CommandPollSeconds = 1;
input int    SlippagePoints = 100;
input double MaxRiskPercent = 0.0; // 0 disables the optional EA-side equity cap
input bool   ShowStatusOnChart = true;
input int    MaxOpenPositions = 0; // 0 allows multiple positions without an artificial count limit

string lastCommandId = "";
string pendingCommandId = "";
string pendingCommandAction = "";
string lastStatus = "Initializing";
datetime lastHeartbeat = 0;

string BaseFolder() { return "BitcoinIntelligenceLab\\"; }

bool IsBitcoinSymbol()
{
   string symbol=_Symbol;
   StringToUpper(symbol);
   return (StringFind(symbol,"BTC")>=0);
}

bool IsAllowedAccount()
{
   ENUM_ACCOUNT_TRADE_MODE mode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string server = AccountInfoString(ACCOUNT_SERVER);
   StringToLower(server);
   if(RequireHeadwayDemo)
      return (mode == ACCOUNT_TRADE_MODE_DEMO &&
              (StringFind(server, "headway-demo") >= 0 || StringFind(server, "demo.trade-hw.online") >= 0));
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
   double bid=0, ask=0, point=0;
   long stops=0;
   SymbolInfoDouble(_Symbol,SYMBOL_BID,bid);
   SymbolInfoDouble(_Symbol,SYMBOL_ASK,ask);
   SymbolInfoDouble(_Symbol,SYMBOL_POINT,point);
   SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL,stops);
   string accountServer=AccountInfoString(ACCOUNT_SERVER);
   StringReplace(accountServer,"|","/");
   int accountMode=(int)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   int ownPositions=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber) ownPositions++;
   }
   string line=StringFormat("BTCIL1|%s|%s|%I64d|%s|%.8f|%.8f|%d|%s|%.10f|%d|%s|%s|%d\n",
      _Symbol,EnumToString(_Period),(long)TimeGMT(),
      TerminalInfoInteger(TERMINAL_CONNECTED)?"CONNECTED":"DISCONNECTED",
      bid,ask,ownPositions,lastStatus,point,(int)stops,
      TerminalAllowsTrading()?"TRADE_READY":"TRADE_BLOCKED",
      accountServer,accountMode);
   WriteTextFile("ea_status.tsv",line);
}

void WritePositions()
{
   string content="ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n";
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol ||
         (ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber) continue;
      content+=StringFormat("%I64u|%s|%d|%.8f|%.8f|%.8f|%.8f|%.8f|%.2f\n",
         ticket,PositionGetString(POSITION_SYMBOL),
         (int)PositionGetInteger(POSITION_TYPE),
         PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_PRICE_CURRENT),
         PositionGetDouble(POSITION_SL),
         PositionGetDouble(POSITION_TP),
         PositionGetDouble(POSITION_PROFIT));
   }
   WriteTextFile("positions.tsv",content);
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

int CountOwnPositions()
{
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber) count++;
   }
   return count;
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

bool PrepareTradeRequest(MqlTradeRequest &request)
{
   request.magic=MagicNumber;
   request.deviation=(ulong)SlippagePoints;
   request.type_time=ORDER_TIME_GTC;
   long fillingModes=0;
   long executionMode=0;
   if(!SymbolInfoInteger(_Symbol,SYMBOL_FILLING_MODE,fillingModes) ||
      !SymbolInfoInteger(_Symbol,SYMBOL_TRADE_EXEMODE,executionMode))
      return false;

   if((ENUM_SYMBOL_TRADE_EXECUTION)executionMode==SYMBOL_TRADE_EXECUTION_MARKET)
   {
      if((fillingModes & SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK)
         request.type_filling=ORDER_FILLING_FOK;
      else if((fillingModes & SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC)
         request.type_filling=ORDER_FILLING_IOC;
      else
         return false; // Market execution forbids RETURN; never guess unsupported FOK/IOC.
   }
   else
   {
      request.type_filling=ORDER_FILLING_RETURN;
   }
   return true;
}

string TradeResultText(const MqlTradeResult &result)
{
   return StringFormat("retcode=%u comment=%s",result.retcode,result.comment);
}

bool CloseOwnPosition(const ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return false;
   if(PositionGetString(POSITION_SYMBOL)!=_Symbol ||
      (ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber) return false;

   long positionType=PositionGetInteger(POSITION_TYPE);
   double volume=PositionGetDouble(POSITION_VOLUME);
   double bid=0,ask=0;
   if(!SymbolInfoDouble(_Symbol,SYMBOL_BID,bid) ||
      !SymbolInfoDouble(_Symbol,SYMBOL_ASK,ask) || bid<=0 || ask<=0 || ask<bid ||
      volume<=0)
   {
      lastStatus="CLOSE_REJECTED: current broker quote or position volume unavailable";
      return false;
   }

   MqlTradeRequest request={};
   MqlTradeResult result={};
   request.action=TRADE_ACTION_DEAL;
   request.position=ticket;
   request.symbol=_Symbol;
   request.volume=volume;
   request.type=(positionType==POSITION_TYPE_BUY)?ORDER_TYPE_SELL:ORDER_TYPE_BUY;
   request.price=(positionType==POSITION_TYPE_BUY)?bid:ask;
   request.comment="Bitcoin Intelligence Lab close";
   if(!PrepareTradeRequest(request))
   {
      lastStatus="CLOSE_REJECTED: broker exposes no supported filling policy";
      return false;
   }

   bool sent=OrderSend(request,result);
   uint code=result.retcode;
   if(!sent || (code!=TRADE_RETCODE_DONE && code!=TRADE_RETCODE_DONE_PARTIAL &&
                code!=TRADE_RETCODE_PLACED))
   {
      lastStatus="CLOSE_REJECTED: "+TradeResultText(result);
      return false;
   }
   ulong deal=result.deal;
   if(deal>0 && HistoryDealSelect(deal) &&
      HistoryDealGetString(deal,DEAL_SYMBOL)==_Symbol &&
      (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)==MagicNumber)
      lastStatus=StringFormat("CLOSE_FILL_CONFIRMED: deal=%I64u position=%I64u",deal,ticket);
   else
      lastStatus=StringFormat("CLOSE_SUBMITTED_PENDING: retcode=%u position=%I64u",code,ticket);
   return true;
}

bool OpenBoardPosition(const string side,const double volume,const double sl,const double tp)
{
   if(!TerminalAllowsTrading()) { lastStatus="BLOCKED: Headway DEMO/terminal permission gate"; return false; }
   if(!IsBitcoinSymbol()) { lastStatus="BLOCKED: chart symbol is not a Bitcoin instrument"; return false; }
   if(MaxOpenPositions>0 && CountOwnPositions()>=MaxOpenPositions)
   { lastStatus="BLOCKED: configured maximum open positions reached"; return false; }
   if(!ValidVolume(volume)) { lastStatus="BLOCKED: volume violates broker min/max/step"; return false; }

   double bid=0, ask=0, point=0;
   if(!SymbolInfoDouble(_Symbol,SYMBOL_BID,bid) || !SymbolInfoDouble(_Symbol,SYMBOL_ASK,ask) ||
      !SymbolInfoDouble(_Symbol,SYMBOL_POINT,point) || point<=0 || ask<bid)
   { lastStatus="BLOCKED: broker quote unavailable"; return false; }
   if(MaxSpreadPoints>0 && (ask-bid)/point>MaxSpreadPoints)
   { lastStatus="BLOCKED: optional spread filter exceeded"; return false; }
   if(!ValidProtection(side,sl,tp)) { lastStatus="BLOCKED: stop/target violates price or broker stops"; return false; }

   if(MaxRiskPercent>0.0)
   {
      double projectedLoss=0.0;
      ENUM_ORDER_TYPE orderType=(side=="BUY")?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
      double entry=(side=="BUY")?ask:bid;
      if(!OrderCalcProfit(orderType,_Symbol,volume,entry,sl,projectedLoss) || projectedLoss>=0.0 ||
         MathAbs(projectedLoss)>AccountInfoDouble(ACCOUNT_EQUITY)*MaxRiskPercent/100.0)
      { lastStatus="BLOCKED: optional EA-side equity risk cap exceeded"; return false; }
   }

   MqlTradeRequest request={};
   MqlTradeResult result={};
   request.action=TRADE_ACTION_DEAL;
   request.symbol=_Symbol;
   request.volume=volume;
   request.type=(side=="BUY")?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   request.price=(side=="BUY")?ask:bid;
   request.sl=sl;
   request.tp=tp;
   request.comment="Bitcoin Intelligence Lab";
   if(!PrepareTradeRequest(request))
   {
      lastStatus="ORDER_REJECTED: broker exposes no supported filling policy";
      return false;
   }

   bool sent=OrderSend(request,result);
   uint code=result.retcode;
   if(!sent || (code!=TRADE_RETCODE_DONE && code!=TRADE_RETCODE_PLACED &&
                code!=TRADE_RETCODE_DONE_PARTIAL))
   {
      lastStatus="ORDER_REJECTED: "+TradeResultText(result);
      return false;
   }
   ulong deal=result.deal;
   if(deal>0 && HistoryDealSelect(deal))
   {
      if(HistoryDealGetString(deal,DEAL_SYMBOL)==_Symbol &&
         (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)==MagicNumber)
         lastStatus=StringFormat("ORDER_FILL_CONFIRMED: deal=%I64u order=%I64u",deal,result.order);
      else lastStatus="ORDER_SUBMITTED: deal identity mismatch; inspect terminal history";
   }
   else lastStatus=StringFormat("ORDER_SUBMITTED_PENDING: retcode=%u order=%I64u",code,result.order);
   return true;
}

void PollProgramCommand()
{
   // Serialize broker commands until the outstanding request receives its
   // OnTradeTransaction confirmation; never overwrite a pending command ID.
   if(pendingCommandId!="") return;
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
   pendingCommandId=commandId;
   pendingCommandAction=action;
   if(action=="OPEN")
   {
      ok=OpenBoardPosition(side,volume,sl,tp);
      detail=lastStatus;
   }
   else if(action=="CLOSE")
   {
      if(!TerminalAllowsTrading()) { lastStatus="BLOCKED: Headway DEMO/terminal permission gate"; ok=false; }
      else { ok=CloseOwnPosition(ticket); }
      detail=lastStatus;
   }
   else { lastStatus="BLOCKED: unsupported action"; detail=lastStatus; }

   lastCommandId=commandId;
   int store=FileOpen(BaseFolder()+"last_command_id.txt",FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(store!=INVALID_HANDLE) { FileWriteString(store,lastCommandId); FileClose(store); }
   string ackStatus="REJECTED";
   if(!ok)
   {
      pendingCommandId="";
      pendingCommandAction="";
   }
   if(ok)
   {
      if(StringFind(lastStatus,"ORDER_FILL_CONFIRMED")==0) ackStatus="FILLED";
      else if(StringFind(lastStatus,"ORDER_SUBMITTED_PENDING")==0) ackStatus="SUBMITTED_PENDING";
      else if(StringFind(lastStatus,"CLOSE_FILL_CONFIRMED")==0) ackStatus="CLOSED";
      else if(StringFind(lastStatus,"CLOSE_SUBMITTED_PENDING")==0) ackStatus="CLOSE_SUBMITTED_PENDING";
      else ackStatus="ACCEPTED";
   }
   WriteAck(commandId,ackStatus,action,detail);
}

int OnInit()
{
   if(!IsBitcoinSymbol())
   {
      Print("BTCIL|INIT_BLOCKED|select a Bitcoin instrument; current=",_Symbol);
      return INIT_PARAMETERS_INCORRECT;
   }
   if(MagicNumber==0 || CommandPollSeconds<1 || MaxSpreadPoints<0 || SlippagePoints<0 ||
      MaxRiskPercent<0 || MaxOpenPositions<0) return INIT_PARAMETERS_INCORRECT;
   FolderCreate("BitcoinIntelligenceLab",FILE_COMMON);
   int store=FileOpen(BaseFolder()+"last_command_id.txt",FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(store!=INVALID_HANDLE) { lastCommandId=FileReadString(store); FileClose(store); }
   if(!EventSetTimer(CommandPollSeconds)) return INIT_FAILED;
   lastStatus=TerminalAllowsTrading()?"READY: Headway demo board-execution mode":"WAITING: Headway demo / connection / Algo Trading permission";
   WriteStatus();
   WritePositions();
   Print("BTCIL|INIT|symbol=",_Symbol,"|period=",EnumToString(_Period),
         "|server=",AccountInfoString(ACCOUNT_SERVER),"|demo=",IsAllowedAccount()?"true":"false",
         "|trade_enabled=",EnableTrading?"true":"false","|magic=",MagicNumber);
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   PollProgramCommand();
   datetime now=TimeGMT();
   if(now-lastHeartbeat>=10)
   {
      WriteStatus();
      WritePositions();
      lastHeartbeat=now;
   }
   if(ShowStatusOnChart) Comment("Bitcoin Intelligence Lab\n",lastStatus);
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0 || pendingCommandId=="")
      return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetString(trans.deal,DEAL_SYMBOL)!=_Symbol ||
      (ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)!=MagicNumber)
      return;

   long entry=HistoryDealGetInteger(trans.deal,DEAL_ENTRY);
   long type=HistoryDealGetInteger(trans.deal,DEAL_TYPE);
   string status="FILL_CONFIRMED";
   if(entry==DEAL_ENTRY_IN) status="OPEN_FILL_CONFIRMED";
   else if(entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY) status="CLOSE_FILL_CONFIRMED";
   else return;

   string detail=StringFormat("deal=%I64u order=%I64u volume=%.8f price=%.8f type=%d",
      trans.deal,(ulong)HistoryDealGetInteger(trans.deal,DEAL_ORDER),
      HistoryDealGetDouble(trans.deal,DEAL_VOLUME),
      HistoryDealGetDouble(trans.deal,DEAL_PRICE),(int)type);
   lastStatus=status+": "+detail;
   WriteAck(pendingCommandId,status,pendingCommandAction,detail);
   WriteStatus();
   WritePositions();
   pendingCommandId="";
   pendingCommandAction="";
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
