"""
MCP Service — lightweight FastAPI gateway that exposes the MCP server tools
over HTTP on port 8082. Proxies tool calls to the local bridge (8099) or
MCP server (8080) depending on the tool.
"""
import os
import json
import httpx
import logging
from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/env/ENV"))
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mcp-service")

SERVICE_PORT = int(os.getenv("MCP_SERVICE_PORT", "8082"))
MCP_PORT     = int(os.getenv("MCP_PORT", "8080"))
BRIDGE_URL   = os.getenv("BRIDGE_URL", "http://127.0.0.1:8099")
BRIDGE_KEY   = os.getenv("MCP_API_KEY", os.getenv("BRIDGE_KEY", "BELLA_2026_BRIDGE_KEY"))
MCP_URL      = os.getenv("MCP_URL", f"http://127.0.0.1:{MCP_PORT}")

app = FastAPI(title="MCP Service Gateway", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ToolCall(BaseModel):
    tool: str
    params: Dict[str, Any] = {}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "mcp-service",
        "mcp_url": MCP_URL,
        "bridge_url": BRIDGE_URL,
        "port": SERVICE_PORT,
    }


@app.get("/tools")
async def list_tools():
    """List tools exposed by the upstream MCP server."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{MCP_URL}/tools")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning(f"MCP tools list failed: {e}")
        return {
            "tools": [
                {"name": "shell_run", "description": "Run shell via bridge"},
                {"name": "file_read", "description": "Read file via bridge"},
                {"name": "file_write", "description": "Write file via bridge"},
                {"name": "memory_save", "description": "Save memory"},
                {"name": "memory_search", "description": "Search memory"},
                {"name": "n8n_trigger", "description": "Trigger n8n webhook"},
                {"name": "health_check", "description": "Check service health"},
            ]
        }


@app.post("/execute")
async def execute(call: ToolCall):
    """Execute a tool. Bridges file/shell tools; forwards everything else to MCP."""
    bridge_tools = {"shell_run", "file_read", "file_write", "file_append_local",
                    "file_read_local", "file_write_local", "file_list", "file_delete"}
    headers = {"X-API-Key": BRIDGE_KEY, "Content-Type": "application/json"}

    try:
        if call.tool in bridge_tools:
            if call.tool == "shell_run":
                url = f"{BRIDGE_URL}/shell/run"
                body = call.params
            else:
                url = f"{BRIDGE_URL}/n8n/trigger"
                body = {"task": call.tool.replace("_local", ""), "payload": call.params, "api_key": BRIDGE_KEY}
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(url, headers=headers, json=body)
                r.raise_for_status()
                return {"tool": call.tool, "result": r.json()}
        else:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{MCP_URL}/execute", json=call.dict())
                r.raise_for_status()
                return r.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Tool {call.tool} failed: HTTP {e.response.status_code}")
        raise HTTPException(status_code=502, detail=f"Upstream error: {e.response.text}")
    except Exception as e:
        logger.error(f"Tool {call.tool} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    logger.info(f"MCP Service starting on 0.0.0.0:{SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
