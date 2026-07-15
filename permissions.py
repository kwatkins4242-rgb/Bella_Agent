"""
ODIN Permission Gate — deny-first approval system for tool calls.
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("odin.permissions")


class PermissionGate:
    def __init__(self, auto_approve: bool = False, timeout: float = 120.0):
        self.auto_approve = auto_approve
        self.timeout = timeout
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.responses: Dict[str, bool] = {}
        self._lock = asyncio.Lock()

    async def request(self, tool_name: str, params: Dict[str, Any], context: str = "") -> bool:
        if self.auto_approve:
            return True
        request_id = f"perm_{datetime.utcnow().timestamp()}_{tool_name}"
        async with self._lock:
            self.pending[request_id] = {
                "id": request_id,
                "tool_name": tool_name,
                "params": params,
                "context": context,
                "timestamp": datetime.utcnow().isoformat(),
            }
        logger.info(f"Permission requested: {request_id} | {tool_name}")
        try:
            await asyncio.wait_for(self._wait_for_response(request_id), timeout=self.timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                self.pending.pop(request_id, None)
                self.responses.pop(request_id, None)
            return False
        return self.responses.get(request_id, False)

    async def _wait_for_response(self, request_id: str):
        while True:
            if request_id in self.responses:
                return
            await asyncio.sleep(0.5)

    def respond(self, request_id: str, approved: bool) -> bool:
        if request_id not in self.pending:
            return False
        self.responses[request_id] = approved
        self.pending.pop(request_id, None)
        return True

    def get_pending(self) -> List[Dict[str, Any]]:
        return list(self.pending.values())

    def deny_all(self):
        for rid in list(self.pending.keys()):
            self.respond(rid, False)
