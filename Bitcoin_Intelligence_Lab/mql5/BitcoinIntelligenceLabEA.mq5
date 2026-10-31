#property strict
#property version   "1.006"
#property description "Bitcoin Intelligence Lab — Headway BTC centralized command executor"

input ulong  MagicNumber = 28102027;
input bool   EnableTrading = true;
input int    MaxSpreadPoints = 0; // 0 disables this optional filter
input int    CommandPollSeconds = 1;
input int    SlippagePoints = 100;
input double MaxRiskPercent = 0.50; // maximum equity loss per entry, in percent
input double MaxDailyLossPercent = 2.00; // pause new entries after this server-day equity drawdown
input bool   ShowStatusOnChart = true;
input int    MaxOpenPositions = 1; // one BTCIL-managed position at a time

string lastCommandId = "";
string pendingCommandId = "";
string pendingCommandAction = "";
uint pendingRequestId = 0;
uint pendingRetcode = 0;
datetime pendingRequestTime = 0;
ulong pendingOrderTicket = 0;
ulong pendingPositionTicket = 0;
double pendingRequestedVolume = 0.0;
double pendingFilledVolume = 0.0;
string lastStatus = "Initializing";
datetime lastHeartbeat = 0;
bool hasInstanceLock = false;

string BaseFolder() { return "BitcoinIntelligenceLab\\"; }

string InstanceLockName()
{
   return StringFormat("BTCIL_%I64u_%s",MagicNumber,_Symbol);
}

bool IsBitcoinSymbol()
{
   string symbol=_Symbol;
   StringToUpper(symbol);
   return (StringFind(symbol,"BTC")>=0);
}

bool IsHeadwayBroker()
{
   // Account mode is deliberately not inspected. The broker identity is Headway.
   string server = AccountInfoString(ACCOUNT_SERVER);
   StringToLower(server);
   return (StringFind(server, "headway") >= 0 || StringFind(server, "trade-hw.online") >= 0);
}

bool TerminalAllowsTrading()
{
   return (EnableTrading && TerminalInfoInteger(TERMINAL_CONNECTED) &&
           TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED) &&
           IsHeadwayBroker());
}

string DailyRiskKeyName()
{
   return StringFormat("BTCIL_DAY_KEY_%I64d_%I64u",
      AccountInfoInteger(ACCOUNT_LOGIN),MagicNumber);
}

string DailyEquityName()
{
   return StringFormat("BTCIL_DAY_EQ_%I64d_%I64u",
      AccountInfoInteger(ACCOUNT_LOGIN),MagicNumber);
}

void RefreshDailyRiskBaseline()
{
   MqlDateTime serverTime;
   TimeToStruct(TimeTradeServer(),serverTime);
   double dayKey=(double)(serverTime.year*10000+serverTime.mon*100+serverTime.day);
   string keyName=DailyRiskKeyName();
   string equityName=DailyEquityName();
   if(!GlobalVariableCheck(keyName) || GlobalVariableGet(keyName)!=dayKey ||
      !GlobalVariableCheck(equityName))
   {
      GlobalVariableSet(equityName,AccountInfoDouble(ACCOUNT_EQUITY));
      GlobalVariableSet(keyName,dayKey);
   }
}

bool DailyRiskAllowsNewEntry()
{
   RefreshDailyRiskBaseline();
   double baseline=GlobalVariableGet(DailyEquityName());
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(baseline<=0.0 || equity<=0.0) return false;
   double drawdownPercent=MathMax(0.0,(baseline-equity)/baseline*100.0);
   return (drawdownPercent<MaxDailyLossPercent);
}

double CurrentDailyDrawdownPercent()
{
   RefreshDailyRiskBaseline();
   double baseline=GlobalVariableGet(DailyEquityName());
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(baseline<=0.0 || equity<=0.0) return -1.0;
   return MathMax(0.0,(baseline-equity)/baseline*100.0);
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
   int ownPositions=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber) ownPositions++;
   }
   string line=StringFormat("BTCIL1|%s|%s|%I64d|%s|%.8f|%.8f|%d|%s|%.10f|%d|%s|%s|%.4f|%.4f\n",
      _Symbol,EnumToString(_Period),(long)TimeGMT(),
      TerminalInfoInteger(TERMINAL_CONNECTED)?"CONNECTED":"DISCONNECTED",
      bid,ask,ownPositions,lastStatus,point,(int)stops,
      TerminalAllowsTrading()?"TRADE_READY":"TRADE_BLOCKED",
      accountServer,CurrentDailyDrawdownPercent(),MaxDailyLossPercent);
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

bool HasForeignPositionsOnSymbol()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber)
         return true;
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
   request.comment="BTCIL close";
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
   if(result.request_id==0 || (code==TRADE_RETCODE_PLACED && result.order==0))
   {
      lastStatus="CLOSE_REJECTED: broker returned no request/order identifier for acknowledgment tracking";
      return false;
   }
   pendingRequestId=result.request_id;
   pendingRetcode=code;
   pendingRequestTime=TimeCurrent();
   pendingOrderTicket=result.order;
   pendingPositionTicket=ticket;
   pendingRequestedVolume=volume;
   pendingFilledVolume=result.volume;
   lastStatus=StringFormat("CLOSE_SUBMITTED_PENDING: request=%u order=%I64u position=%I64u retcode=%u",
      result.request_id,result.order,ticket,code);
   return true;
}

bool OpenBoardPosition(const string side,const double volume,const double sl,const double tp)
{
   if(!TerminalAllowsTrading()) { lastStatus="BLOCKED: Headway server/terminal permission gate"; return false; }
   if(!DailyRiskAllowsNewEntry())
   {
      lastStatus="BLOCKED: daily equity loss limit reached; new entries paused";
      return false;
   }
   if(!IsBitcoinSymbol()) { lastStatus="BLOCKED: chart symbol is not a Bitcoin instrument"; return false; }
   if(HasForeignPositionsOnSymbol())
   {
      lastStatus="BLOCKED: another position exists on this symbol outside BTCIL MagicNumber";
      return false;
   }
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
      { lastStatus="BLOCKED: EA equity risk cap exceeded"; return false; }
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
   if(result.request_id==0 || (code==TRADE_RETCODE_PLACED && result.order==0))
   {
      lastStatus="ORDER_REJECTED: broker returned no request/order identifier for acknowledgment tracking";
      return false;
   }
   pendingRequestId=result.request_id;
   pendingRetcode=code;
   pendingRequestTime=TimeCurrent();
   pendingOrderTicket=result.order;
   pendingPositionTicket=0;
   pendingRequestedVolume=volume;
   pendingFilledVolume=result.volume;
   lastStatus=StringFormat("ORDER_SUBMITTED_PENDING: request=%u order=%I64u retcode=%u",
      result.request_id,result.order,code);
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
      if(!TerminalAllowsTrading()) { lastStatus="BLOCKED: Headway server/terminal permission gate"; ok=false; }
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
      pendingRequestId=0;
      pendingRetcode=0;
      pendingRequestTime=0;
      pendingOrderTicket=0;
      pendingPositionTicket=0;
      pendingRequestedVolume=0.0;
      pendingFilledVolume=0.0;
   }
   else
   {
      ackStatus=(action=="OPEN")?"SUBMITTED_PENDING":"CLOSE_SUBMITTED_PENDING";
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
      MaxRiskPercent<=0.0 || MaxRiskPercent>2.0 ||
      MaxDailyLossPercent<=0.0 || MaxDailyLossPercent>10.0 || MaxOpenPositions<1)
      return INIT_PARAMETERS_INCORRECT;
   string lockName=InstanceLockName();
   if(!GlobalVariableCheck(lockName)) GlobalVariableTemp(lockName);
   if(!GlobalVariableSetOnCondition(lockName,(double)ChartID(),0.0))
   {
      Print("BTCIL|INIT_BLOCKED|another EA instance already owns this symbol/magic lock");
      return INIT_FAILED;
   }
   hasInstanceLock=true;
   RefreshDailyRiskBaseline();
   FolderCreate("BitcoinIntelligenceLab",FILE_COMMON);
   int store=FileOpen(BaseFolder()+"last_command_id.txt",FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(store!=INVALID_HANDLE) { lastCommandId=FileReadString(store); FileClose(store); }
   if(!EventSetTimer(CommandPollSeconds))
   {
      if(hasInstanceLock && GlobalVariableCheck(lockName) &&
         GlobalVariableGet(lockName)==(double)ChartID())
         GlobalVariableDel(lockName);
      hasInstanceLock=false;
      return INIT_FAILED;
   }
   lastStatus=TerminalAllowsTrading()?"READY: Headway board-execution mode":"WAITING: Headway / connection / Algo Trading permission";
   WriteStatus();
   WritePositions();
   Print("BTCIL|INIT|symbol=",_Symbol,"|period=",EnumToString(_Period),
         "|server=",AccountInfoString(ACCOUNT_SERVER),"|headway_server=",IsHeadwayBroker()?"true":"false",
         "|trade_enabled=",EnableTrading?"true":"false","|magic=",MagicNumber);
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   PollProgramCommand();
   PollPendingOrderStatus();
   datetime now=TimeGMT();
   if(now-lastHeartbeat>=10)
   {
      WriteStatus();
      WritePositions();
      lastHeartbeat=now;
   }
   if(ShowStatusOnChart) Comment("Bitcoin Intelligence Lab\n",lastStatus);
}

void ClearPendingCommand()
{
   pendingCommandId="";
   pendingCommandAction="";
   pendingRequestId=0;
   pendingRetcode=0;
   pendingRequestTime=0;
   pendingOrderTicket=0;
   pendingPositionTicket=0;
   pendingRequestedVolume=0.0;
   pendingFilledVolume=0.0;
}

void FinalizePendingOrder()
{
   string finalStatus="";
   if(pendingFilledVolume<=0.0)
      finalStatus="ORDER_REJECTED_OR_CANCELLED";
   else if(pendingCommandAction=="OPEN")
      finalStatus=(pendingFilledVolume+1e-8>=pendingRequestedVolume)
         ?"OPEN_FILL_CONFIRMED":"OPEN_PARTIAL_FILL_CONFIRMED";
   else if(pendingCommandAction=="CLOSE")
      finalStatus=(pendingFilledVolume+1e-8>=pendingRequestedVolume)
         ?"CLOSE_FILL_CONFIRMED":"CLOSE_PARTIAL_FILL_CONFIRMED";
   else finalStatus="ORDER_STATUS_UNKNOWN";

   double remainingVolume=0.0;
   if(pendingPositionTicket>0 && PositionSelectByTicket(pendingPositionTicket))
      remainingVolume=PositionGetDouble(POSITION_VOLUME);
   string detail=StringFormat(
      "request=%u order=%I64u filled=%.8f requested=%.8f remaining_position=%.8f retcode=%u",
      pendingRequestId,pendingOrderTicket,pendingFilledVolume,pendingRequestedVolume,
      remainingVolume,pendingRetcode);
   string commandId=pendingCommandId;
   string action=pendingCommandAction;
   lastStatus=finalStatus+": "+detail;
   WriteAck(commandId,finalStatus,action,detail);
   WriteStatus();
   WritePositions();
   ClearPendingCommand();
}

void PollPendingOrderStatus()
{
   if(pendingCommandId=="" || pendingOrderTicket==0 ||
      (pendingRetcode!=TRADE_RETCODE_PLACED &&
       pendingRetcode!=TRADE_RETCODE_DONE_PARTIAL))
      return;

   // Do not finalize a partial fill while the residual order remains active.
   if(OrderSelect(pendingOrderTicket)) return;

   datetime fromTime=(datetime)MathMax(0,(long)pendingRequestTime-120);
   datetime toTime=TimeCurrent()+60;
   if(!HistorySelect(fromTime,toTime)) return;

   double historyFilled=0.0;
   int totalDeals=HistoryDealsTotal();
   for(int i=0;i<totalDeals;i++)
   {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0) continue;
      if((ulong)HistoryDealGetInteger(deal,DEAL_ORDER)!=pendingOrderTicket) continue;
      if(HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol ||
         (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=MagicNumber) continue;
      long entry=HistoryDealGetInteger(deal,DEAL_ENTRY);
      bool expectedEntry=(pendingCommandAction=="OPEN" && entry==DEAL_ENTRY_IN) ||
         (pendingCommandAction=="CLOSE" &&
          (entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY));
      if(expectedEntry)
         historyFilled+=HistoryDealGetDouble(deal,DEAL_VOLUME);
   }

   if(historyFilled>0.0)
   {
      pendingFilledVolume=historyFilled;
      FinalizePendingOrder();
      return;
   }

   if(HistoryOrderSelect(pendingOrderTicket))
   {
      ENUM_ORDER_STATE state=(ENUM_ORDER_STATE)HistoryOrderGetInteger(
         pendingOrderTicket,ORDER_STATE);
      if(state==ORDER_STATE_FILLED || state==ORDER_STATE_CANCELED ||
         state==ORDER_STATE_REJECTED || state==ORDER_STATE_EXPIRED)
      {
         // Preserve the broker-confirmed result.volume when the history-deal
         // collection is momentarily behind the order-history update.
         FinalizePendingOrder();
      }
   }
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   // This transaction type carries the authoritative result for the matching
   // request_id, including the broker-confirmed deal volume and retcode.
   if(trans.type==TRADE_TRANSACTION_REQUEST &&
      pendingCommandId!="" && pendingRequestId>0 &&
      result.request_id==pendingRequestId)
   {
      pendingRetcode=result.retcode;
      if(result.order>0) pendingOrderTicket=result.order;
      if(result.retcode==TRADE_RETCODE_DONE)
      {
         pendingFilledVolume=result.volume;
         FinalizePendingOrder();
      }
      else if(result.retcode==TRADE_RETCODE_DONE_PARTIAL ||
              result.retcode==TRADE_RETCODE_PLACED)
      {
         pendingFilledVolume=result.volume;
         string status=(result.retcode==TRADE_RETCODE_PLACED)
            ?"SUBMITTED_PENDING":"PARTIAL_FILL_PENDING";
         string detail=StringFormat(
            "request=%u order=%I64u broker_confirmed_volume=%.8f requested_volume=%.8f retcode=%u",
            result.request_id,result.order,result.volume,pendingRequestedVolume,result.retcode);
         lastStatus=status+": "+detail;
         WriteAck(pendingCommandId,status,pendingCommandAction,detail);
         if(pendingOrderTicket==0)
            FinalizePendingOrder();
         else
            PollPendingOrderStatus();
      }
      else
      {
         pendingFilledVolume=0.0;
         FinalizePendingOrder();
      }
      return;
   }

   // Deal transaction order is not guaranteed. Use it only to refresh the
   // displayed position snapshot; the request result above owns the ACK.
   if(trans.type==TRADE_TRANSACTION_DEAL_ADD && trans.deal>0 &&
      HistoryDealSelect(trans.deal) &&
      HistoryDealGetString(trans.deal,DEAL_SYMBOL)==_Symbol &&
      (ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)==MagicNumber)
   {
      WriteStatus();
      WritePositions();
   }
}

void OnDeinit(const int reason)
{
   EventKillTimer();

   // If a residual broker order is still active (e.g. partial exchange fill),
   // request cancellation before unloading this executor instance.
   if(pendingOrderTicket>0 && OrderSelect(pendingOrderTicket) &&
      OrderGetString(ORDER_SYMBOL)==_Symbol &&
      (ulong)OrderGetInteger(ORDER_MAGIC)==MagicNumber)
   {
      MqlTradeRequest cancelRequest={};
      MqlTradeResult cancelResult={};
      cancelRequest.action=TRADE_ACTION_REMOVE;
      cancelRequest.order=pendingOrderTicket;
      bool cancelSent=OrderSend(cancelRequest,cancelResult);
      string cancelDetail=StringFormat(
         "order=%I64u sent=%s retcode=%u comment=%s",
         pendingOrderTicket,cancelSent?"true":"false",
         cancelResult.retcode,cancelResult.comment);
      if(pendingCommandId!="")
         WriteAck(pendingCommandId,
            (cancelSent && cancelResult.retcode==TRADE_RETCODE_DONE)
               ?"CANCEL_REQUESTED":"CANCEL_NOT_CONFIRMED",
            pendingCommandAction,cancelDetail);
      Print("BTCIL|PENDING_ORDER_CANCEL_ON_DEINIT|",cancelDetail);
   }
   if(hasInstanceLock)
   {
      string lockName=InstanceLockName();
      if(GlobalVariableCheck(lockName) &&
         GlobalVariableGet(lockName)==(double)ChartID())
         GlobalVariableDel(lockName);
      hasInstanceLock=false;
   }
   WriteTextFile("ea_status.tsv",StringFormat("BTCIL1|DEINIT|%I64d|%s\n",(long)TimeGMT(),lastStatus));
   Comment("");
}

void OnTick()
{
   // No self-generated entries. The centralized board is the only decision authority.
}
