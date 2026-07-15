#!/usr/bin/env python3
"""
MCP Post — webhook receiver on port 8083.
Accepts events from n8n, external tools, or dashboards and forwards them
to Bella memory and/or the MCP tool server.
"""
import os
import json
import logging
import httpx
from typing import Any, Dict
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/env/ENV"))
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mcp-post")

POST_PORT      = int(os.getenv("MCP_POST_PORT", "8083"))
MCP_URL        = os.getenv("MCP_URL", "http://127.0.0.1:8080")
BRIDGE_URL     = os.getenv("BRIDGE_URL", "http://127.0.0.1:8099")
BRIDGE_KEY     = os.getenv("MCP_API_KEY", os.getenv("BRIDGE_KEY", "BELLA_2026_BRIDGE_KEY"))
MEMORY_API_URL = os.getenv("MEMORY_API_URL", "http://127.0.0.1:8010")
BELLA_API_KEY  = os.getenv("BELLA_API_KEY", "bella-keith-private-2026")

app = FastAPI(title="MCP Post", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Event(BaseModel):
    source: str = "n8n"
    type: str
    payload: Dict[str, Any] = {}


async def _memory_save(content: str, session_id: str = "default", tags=None):
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                f"{MEMORY_API_URL}/memory/save",
                headers={"X-API-Key": BELLA_API_KEY, "Content-Type": "application/json"},
                json={"content": content, "session_id": session_id, "tags": tags or []},
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning(f"memory save failed: {e}")
        return {"error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok", "port": POST_PORT, "mcp_url": MCP_URL, "memory_api": MEMORY_API_URL}


@app.post("/event")
async def receive_event(event: Event):
    logger.info(f"Received {event.type} from {event.source}")
    if event.type == "feed_memory":
        body = event.payload
        result = await _memory_save(
            body.get("content", ""),
            body.get("session_id", "default"),
            body.get("tags", []),
        )
        return {"status": "stored", "memory": result}

    if event.type == "session_start":
        session_id = event.payload.get("session_id", "default")
        return {"status": "ack", "session_id": session_id}

    if event.type == "tool_call":
        tool = event.payload.get("tool")
        params = event.payload.get("params", {})
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{MCP_URL}/execute", json={"tool": tool, "params": params})
            r.raise_for_status()
            return r.json()

    return {"status": "ignored", "type": event.type}


@app.post("/n8n/{workflow}")
async def n8n_webhook(workflow: str, request: Request):
    """n8n webhook compatibility endpoint."""
    body = await request.json()
    logger.info(f"n8n webhook: {workflow} | body: {body}")
    if workflow in {"bella-feed-memory", "feed-memory"}:
        return await receive_event(Event(type="feed_memory", payload=body))
    if workflow in {"bella-session-start", "session-start"}:
        return await receive_event(Event(type="session_start", payload=body))
    return {"status": "ok", "workflow": workflow}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"MCP Post starting on 0.0.0.0:{POST_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=POST_PORT)
