"""
ODIN DB — lightweight session + log store.
Uses MongoDB if available, otherwise JSONL files under ./data/odin_db.
"""
import os
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger("odin.db")

DATA_DIR = Path(__file__).parent / "data" / "odin_db"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.utcnow().isoformat()


class JsonlStore:
    def __init__(self, name: str):
        self.path = DATA_DIR / f"{name}.jsonl"

    def append(self, doc: Dict[str, Any]):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(doc, default=str) + "\n")

    def read(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(line) for line in lines[-limit:]]


class OdinDB:
    """Async-compatible DB wrapper."""

    def __init__(self):
        self._connected = False
        self.sessions = JsonlStore("sessions")
        self.logs = JsonlStore("logs")
        self.permissions = JsonlStore("permissions")

    async def connect(self):
        self._connected = True
        logger.info("ODIN DB connected (JSONL fallback)")

    async def disconnect(self):
        self._connected = False

    async def log_task_start(self, state):
        self.sessions.append({
            "event": "task_start",
            "task_id": state.task_id,
            "goal": state.goal,
            "session_id": state.session_id,
            "ts": _now(),
        })

    async def log_task_complete(self, state):
        self.sessions.append({
            "event": "task_complete",
            "task_id": state.task_id,
            "status": state.status,
            "ts": _now(),
        })

    async def log_event(self, state, event: str, data: Dict[str, Any]):
        self.logs.append({
            "task_id": state.task_id,
            "event": event,
            "data": data,
            "ts": _now(),
        })

    async def log_permission(self, tool_name: str, params: Dict[str, Any], approved: bool, session_id: str):
        self.permissions.append({
            "tool_name": tool_name,
            "params": params,
            "approved": approved,
            "session_id": session_id,
            "ts": _now(),
        })

    async def get_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(reversed(self.sessions.read(limit)))  # newest first

    async def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self.logs.read(limit)))


_db: OdinDB = OdinDB()


def get_db() -> OdinDB:
    return _db
