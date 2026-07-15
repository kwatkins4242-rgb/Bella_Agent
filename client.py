"""
MCP HTTP Client — binds to port 8081 and exposes a simple REST wrapper around
the local MCP server (port 8080) and bridge (port 8099).
"""
import os
import json
import logging
import httpx
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/env/ENV"))
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mcp-http-client")

CLIENT_PORT = int(os.getenv("MCP_CLIENT_PORT", "8081"))
MCP_PORT    = int(os.getenv("MCP_PORT", "8080"))
MCP_URL     = os.getenv("MCP_URL", f"http://127.0.0.1:{MCP_PORT}")
BRIDGE_URL  = os.getenv("BRIDGE_URL", "http://127.0.0.1:8099")
BRIDGE_KEY  = os.getenv("MCP_API_KEY", os.getenv("BRIDGE_KEY", "BELLA_2026_BRIDGE_KEY"))

app = FastAPI(title="MCP HTTP Client", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ToolRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}


@app.get("/health")
async def health():
    return {"status": "ok", "mcp_url": MCP_URL, "bridge_url": BRIDGE_URL, "port": CLIENT_PORT}


@app.get("/tools")
async def tools():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{MCP_URL}/tools")
        r.raise_for_status()
        return r.json()


@app.post("/tools/{tool_name}")
async def call_tool(tool_name: str, req: Request):
    body = await req.json()
    params = body.get("arguments", body)
    headers = {"X-API-Key": BRIDGE_KEY, "Content-Type": "application/json"}

    try:
        # File/shell tools go to bridge for local execution
        if tool_name in {"shell_run", "file_read", "file_write", "file_list", "file_delete", "file_move"}:
            if tool_name == "shell_run":
                url = f"{BRIDGE_URL}/shell/run"
                payload = params
            else:
                url = f"{BRIDGE_URL}/n8n/trigger"
                payload = {"task": tool_name, "payload": params, "api_key": BRIDGE_KEY}
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(url, headers=headers, json=payload)
                r.raise_for_status()
                return r.json()

        # Everything else goes to the MCP server
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{MCP_URL}/execute", json={"tool": tool_name, "params": params})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    logger.info(f"MCP HTTP Client starting on 0.0.0.0:{CLIENT_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=CLIENT_PORT)
