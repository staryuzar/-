from __future__ import annotations
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from ..config import ENABLE_ORDER_PUBLISH,MT5_COMMON_FILES,MT5_HEARTBEAT_MAX_AGE_SECONDS

def _read_object(path:Path)->dict[str,Any]:
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {}
    except (OSError,UnicodeError,json.JSONDecodeError):
        return {}

class MT5BridgeEngine:
    """Engine 3: bidirectional program/EA bridge. It never classifies account type or computes risk."""
    def __init__(self,common_files:str|None=None):
        configured=common_files if common_files is not None else MT5_COMMON_FILES
        self.root=Path(configured).expanduser()/"MirsadBTC" if configured else None

    def inspect(self)->dict[str,Any]:
        base={"engine":"engine_3_mt5_bridge","direction":"bidirectional_program_to_expert"}
        if self.root is None:
            return {**base,"status":"NOT_CONFIGURED",
                    "message":"Set MIRSAD_MT5_COMMON_FILES to the terminal Common\\\\Files directory."}
        payload=_read_object(self.root/"status.json")
        if not payload:
            return {**base,"status":"WAITING_FOR_EXPERT","message":"No EA heartbeat file received yet."}
        heartbeat=int(payload.get("heartbeat_at_ms",0) or 0)
        age=(int(time.time()*1000)-heartbeat)/1000 if heartbeat else None
        schema_ok=payload.get("schema")=="MIR1"
        alive=bool(payload.get("terminal_connected")) and schema_ok and age is not None and 0<=age<=MT5_HEARTBEAT_MAX_AGE_SECONDS
        return {
            **base,"status":"CONNECTED" if alive else "STALE",
            "heartbeat_age_seconds":round(age,2) if age is not None else None,
            "account":payload.get("account",{}),
            "symbol":payload.get("symbol"),
            "symbol_spec":payload.get("symbol_spec",{}),
            "positions":payload.get("positions",[]),
            "last_order_ack":_read_object(self.root/"ack.json"),
            "message":"Fresh EA telemetry received." if alive else "EA heartbeat missing, stale or protocol schema mismatch.",
            "account_type_classification":"NOT_PERFORMED",
            "risk_calculation":"OWNED_BY_ENGINE_4",
        }

    @staticmethod
    def _validate_decision(decision:dict[str,Any])->dict[str,Any]:
        action=str(decision.get("action","WAIT")).upper()
        if action not in {"BUY","SELL"}:
            raise ValueError("Only a BUY or SELL decision can be published as an OPEN command.")
        if decision.get("status")!="READY":
            raise ValueError("Decision engine status is not READY.")
        risk=decision.get("risk_plan",{})
        if risk.get("status")!="READY":
            raise ValueError("Engine 4 has not completed risk-based position sizing.")
        symbol=str(decision.get("symbol",""))
        command_id=str(uuid.uuid4())
        volume=float(risk.get("volume",0))
        entry=float(decision.get("entry_reference",0))
        sl=float(decision.get("stop_loss",0))
        tp=float(decision.get("take_profit",0))
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}",symbol):
            raise ValueError("Invalid symbol in decision.")
        if not all(map(lambda n:n>0 and n<float("inf"),(volume,entry,sl,tp))):
            raise ValueError("Order prices and volume must be finite positive values.")
        if action=="BUY" and not (sl<entry<tp):
            raise ValueError("BUY stop-loss/entry/take-profit levels are inconsistent.")
        if action=="SELL" and not (tp<entry<sl):
            raise ValueError("SELL stop-loss/entry/take-profit levels are inconsistent.")
        return {
            "schema":"MIR1","command_id":command_id,"action":action,
            "symbol":symbol,"volume":volume,"entry_reference":entry,
            "stop_loss":sl,"take_profit":tp,
        }

    def publish_decision(self,decision:dict[str,Any],bridge_state:dict[str,Any])->dict[str,Any]:
        """Writes an explicit Engine 4 command envelope only when an operator enables publishing."""
        try:
            envelope=self._validate_decision(decision)
        except (TypeError,ValueError,OverflowError) as exc:
            return {"status":"REJECTED","reason":str(exc)}
        if not ENABLE_ORDER_PUBLISH:
            return {"status":"PUBLISH_DISABLED","command_id":None,
                    "message":"Command publication is disabled; no file or order was sent."}
        if self.root is None or bridge_state.get("status")!="CONNECTED":
            return {"status":"BLOCKED","message":"A fresh Engine 3 bridge heartbeat is required."}
        now=int(time.time()*1000)
        envelope.update({"created_at_ms":now,"expires_at_ms":now+60000})
        self.root.mkdir(parents=True,exist_ok=True)
        target=self.root/"command.json"
        temp=self.root/("command."+envelope["command_id"]+".tmp")
        temp.write_text(json.dumps(envelope,separators=(",",":")),encoding="utf-8")
        os.replace(temp,target)
        return {"status":"PUBLISHED","command_id":envelope["command_id"],
                "message":"Command envelope published to Common Files; EA acknowledgement is still required."}
