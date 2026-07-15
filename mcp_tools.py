"""
MCP Tool Executor - Real connection to FastMCP server
Replaces the fake ToolExecutor in engine.py
"""

import os
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("odin.mcp_tools")

class MCPToolExecutor:
    """Connects Backend engine to MCP server for real tool execution"""

    def __init__(self, mcp_url: str = None, api_key: str = None):
        self.mcp_url = mcp_url or os.getenv("MCP_URL", "http://127.0.0.1:8080")
        self.api_key = api_key or os.getenv("MCP_API_KEY", "BELLA_2026_BRIDGE_KEY")
        self.timeout = 60.0
        logger.info(f"MCP Tool Executor initialized → {self.mcp_url}")

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generic MCP tool call"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.mcp_url}/mcp/call_tool",
                    headers=self._headers(),
                    json={"tool": tool_name, "arguments": params}
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✓ MCP tool {tool_name} → success")
                return {"success": True, "result": result}
        except httpx.HTTPStatusError as e:
            logger.error(f"✗ MCP tool {tool_name} → HTTP {e.response.status_code}")
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            logger.error(f"✗ MCP tool {tool_name} → {e}")
            return {"success": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════
    # SHELL TOOLS
    # ═══════════════════════════════════════════════════════════════════════

    async def shell_run(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Run shell command on bridge server"""
        return await self.call_tool("shell_run", {"command": command, "timeout": timeout})

    async def shell_run_local(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Run shell command locally"""
        return await self.call_tool("shell_run_local", {"command": command, "timeout": timeout})

    async def shell_background(self, command: str) -> Dict[str, Any]:
        """Start background process"""
        return await self.call_tool("shell_background", {"command": command})

    # ═══════════════════════════════════════════════════════════════════════
    # FILE TOOLS
    # ═══════════════════════════════════════════════════════════════════════

    async def file_read(self, path: str) -> Dict[str, Any]:
        """Read file from bridge"""
        return await self.call_tool("file_read", {"path": path})

    async def file_read_local(self, path: str) -> Dict[str, Any]:
        """Read file locally"""
        return await self.call_tool("file_read_local", {"path": path})

    async def file_write(self, path: str, content: str, mode: str = "w") -> Dict[str, Any]:
        """Write file on bridge"""
        return await self.call_tool("file_write", {"path": path, "content": content, "mode": mode})

    async def file_write_local(self, path: str, content: str, mode: str = "w") -> Dict[str, Any]:
        """Write file locally"""
        return await self.call_tool("file_write_local", {"path": path, "content": content, "mode": mode})

    async def file_list(self, directory: str, pattern: str = "*") -> Dict[str, Any]:
        """List files in directory"""
        return await self.call_tool("file_list", {"directory": directory, "pattern": pattern})

    async def file_search(self, root: str, pattern: str, max_depth: int = 5) -> Dict[str, Any]:
        """Search for files"""
        return await self.call_tool("file_search", {"root": root, "pattern": pattern, "max_depth": max_depth})

    # ═══════════════════════════════════════════════════════════════════════
    # MEMORY TOOLS
    # ═══════════════════════════════════════════════════════════════════════

    async def memory_search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Search Bella's memory"""
        return await self.call_tool("memory_search", {"query": query, "limit": limit})

    async def memory_save(self, content: str, role: str = "assistant", session_id: str = "default", importance: int = 5) -> Dict[str, Any]:
        """Save to Bella's memory"""
        return await self.call_tool("memory_save", {
            "content": content,
            "role": role,
            "session_id": session_id,
            "importance": importance
        })

    async def memory_recall(self, message: str, limit: int = 5) -> Dict[str, Any]:
        """Recall relevant memories"""
        return await self.call_tool("memory_recall", {"message": message, "limit": limit})

    async def memory_graph_query(self, query: str) -> Dict[str, Any]:
        """Query knowledge graph"""
        return await self.call_tool("memory_graph_query", {"query": query})

    # ═══════════════════════════════════════════════════════════════════════
    # N8N TOOLS
    # ═══════════════════════════════════════════════════════════════════════

    async def n8n_trigger(self, workflow_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger n8n workflow"""
        return await self.call_tool("n8n_trigger", {"workflow_name": workflow_name, "payload": payload})

    async def n8n_handoff(self, summary: str, context: str, next_step: str) -> Dict[str, Any]:
        """Handoff task to n8n"""
        return await self.call_tool("n8n_handoff", {
            "summary": summary,
            "context": context,
            "next_step": next_step
        })

    # ═══════════════════════════════════════════════════════════════════════
    # ODIN TOOLS
    # ═══════════════════════════════════════════════════════════════════════

    async def odin_chat(self, message: str, session_id: str = "default") -> Dict[str, Any]:
        """Chat with ODIN core"""
        return await self.call_tool("odin_chat", {"message": message, "session_id": session_id})

    async def odin_auto(self, goal: str, session_id: str = "default") -> Dict[str, Any]:
        """Run ODIN autonomous mode"""
        return await self.call_tool("odin_auto", {"goal": goal, "session_id": session_id})

    async def odin_code(self, task: str, language: str = "python") -> Dict[str, Any]:
        """Generate code via ODIN"""
        return await self.call_tool("odin_code", {"task": task, "language": language})

    # ═══════════════════════════════════════════════════════════════════════
    # HEALTH / STATUS
    # ═══════════════════════════════════════════════════════════════════════

    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health"""
        return await self.call_tool("health_check", {})

    async def list_tools(self) -> Dict[str, Any]:
        """List all available MCP tools"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.mcp_url}/mcp/tools/list",
                    headers=self._headers()
                )
                response.raise_for_status()
                return {"success": True, "tools": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════
    # RAW HTTP (for any tool)
    # ═══════════════════════════════════════════════════════════════════════

    async def http_post(self, url: str, headers: Optional[Dict] = None, body: Optional[Dict] = None) -> Dict[str, Any]:
        """Raw HTTP POST"""
        return await self.call_tool("http_post", {"url": url, "headers": headers or {}, "body": body or {}})

    async def http_get(self, url: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Raw HTTP GET"""
        return await self.call_tool("http_get", {"url": url, "headers": headers or {}, "params": params or {}})
