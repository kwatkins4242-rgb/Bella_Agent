#!/usr/bin/env python3
"""
BELLA — Unified Python Server
==============================
Replaces Node.js server.js
Serves dashboards, proxies to backends, handles WebSocket

Run: python server.py
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass, field, asdict

# FastAPI imports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

# HTTP client for proxying
import httpx

# WebSocket handling
from websockets.exceptions import ConnectionClosed

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("bella_server")

# Configuration
DASHBOARDS = int(os.getenv("PORT", 3100))
ROUTER     = int(os.getenv("ROUTER", 5000))
M_INJECT   = int(os.getenv("PROXY_PORT",8765))

PROXY_PORT = int(os.getenv("PROXY_PORT", 3099))
BRIDGE_PORT= int(os.getenv("BRIDGE_PORT", 8099))
MCP_PORT   = int(os.getenv("MCP_PORT", 8080))

BRAIN_PORT = int(os.getenv("BRAIN_PORT", 8000))
NODE_PORT  = int(os.getenv("TOOLS", 8000))
PARCER_PORT= int(os.getenv("LOOP", 8000))

# Ensure directories exist
LOGS_DIR = mkdir(parents=True, exist_ok=True)

# =============================================================================
# PERMISSION GATE SYSTEM
# =============================================================================

@dataclass
class PermissionRequest:
    """A permission request waiting for approval"""
    id: str
    type: str
    details: str
    data: Dict[str, Any]
    timestamp: str
    status: str = "pending"
    deny_reason: Optional[str] = None
    resolved_at: Optional[str] = None


class PermissionGate:
    """Manages permission requests for file writes and shell commands"""
    
    def __init__(self):
        self.pending: Dict[str, PermissionRequest] = {}
        self.approved: Set[str] = set()
        self.denied: Set[str] = set()
        self._log_file = LOGS_DIR / "permissions.log"
    
    def _log(self, action: str, request_id: str, details: str, approved: bool):
        """Log permission action"""
        timestamp = datetime.utcnow().isoformat()
        status = "APPROVED" if approved else "DENIED"
        log_entry = f"[{timestamp}] {status} | {action} | {request_id} | {details}\n"
        
        with open(self._log_file, "a") as f:
            f.write(log_entry)
    
    async def request(self, action_type: str, details: str, data: Dict[str, Any] = None) -> str:
        """Request permission for an action"""
        import hashlib
        
        request_id = f"req_{int(datetime.utcnow().timestamp() * 1000)}_{hashlib.md5(os.urandom(8)).hexdigest()[:8]}"
        
        req = PermissionRequest(
            id=request_id,
            type=action_type,
            details=details,
            data=data or {},
            timestamp=datetime.utcnow().isoformat(),
            status="pending"
        )
        
        self.pending[request_id] = req
        
        # Broadcast to all WebSocket clients
        await self._broadcast({
            "type": "permission_request",
            "request": asdict(req)
        })
        
        logger.info(f"[PERMISSION] Requested [{request_id}]: {action_type} - {details}")
        return request_id
    
    async def approve(self, request_id: str) -> bool:
        """Approve a permission request"""
        if request_id not in self.pending:
            return False
        
        req = self.pending[request_id]
        req.status = "approved"
        req.resolved_at = datetime.utcnow().isoformat()
        
        self.approved.add(request_id)
        del self.pending[request_id]
        
        self._log(req.type, request_id, req.details, True)
        
        await self._broadcast({
            "type": "permission_approved",
            "request_id": request_id
        })
        
        return True
    
    async def deny(self, request_id: str, reason: str = "User denied") -> bool:
        """Deny a permission request"""
        if request_id not in self.pending:
            return False
        
        req = self.pending[request_id]
        req.status = "denied"
        req.deny_reason = reason
        req.resolved_at = datetime.utcnow().isoformat()
        
        self.denied.add(request_id)
        del self.pending[request_id]
        
        self._log(req.type, request_id, f"{req.details} | Reason: {reason}", False)
        
        await self._broadcast({
            "type": "permission_denied",
            "request_id": request_id,
            "reason": reason
        })
        
        return True
    
    def is_approved(self, request_id: str) -> bool:
        """Check if request was approved"""
        return request_id in self.approved
    
    def get_pending(self) -> list:
        """Get list of pending requests"""
        return [asdict(r) for r in self.pending.values() if r.status == "pending"]
    
    async def _broadcast(self, message: Dict):
        """Broadcast message to all WebSocket clients"""
        # This will be set by the WebSocket manager
        if hasattr(self, '_ws_manager'):
            await self._ws_manager.broadcast(message)


# Global permission gate
permission_gate = PermissionGate()

# =============================================================================
# WEBSOCKET MANAGER
# =============================================================================

class WebSocketManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)
        logger.info(f"[WS] Client connected. Total: {len(self.connections)}")
        
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "BELLA WebSocket connected",
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def disconnect(self, websocket: WebSocket):
        self.connections.discard(websocket)
        logger.info(f"[WS] Client disconnected. Total: {len(self.connections)}")
    
    async def broadcast(self, message: Dict):
        """Broadcast message to all connected clients"""
        disconnected = set()
        
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        
        # Clean up disconnected
        for ws in disconnected:
            self.connections.discard(ws)
    
    async def send_personal(self, websocket: WebSocket, message: Dict):
        """Send message to specific client"""
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)


# Global WebSocket manager
ws_manager = WebSocketManager()
permission_gate._ws_manager = ws_manager

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(title="BELLA Server", version="2.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# =============================================================================
# HEALTH CHECK
# =============================================================================

async def check_python_backend() -> str:
    """Check if Python backend is running"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://localhost:{PYTHON_PORT}/health")
            return "online" if resp.status_code == 200 else "error"
    except Exception:
        return "offline"


async def check_proxy() -> str:
    """Check if proxy is running"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://localhost:{PROXY_PORT}/health")
            return "online" if resp.status_code == 200 else "error"
    except Exception:
        return "offline"


async def check_mcp() -> str:
    """Check if MCP server is running"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://localhost:{MCP_PORT}/health")
            return "online" if resp.status_code == 200 else "error"
    except Exception:
        return "offline"


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "BELLA Python Server",
        "timestamp": datetime.utcnow().isoformat(),
        "python_backend": await check_python_backend(),
        "proxy": await check_proxy(),
        "mcp": await check_mcp(),
        "websocket_clients": len(ws_manager.connections)
    }


# =============================================================================
# MAIN ROUTES
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve main dashboard"""
    # Serve shell/odin dashboard
    shell_file = STATIC_DIR / "shell" / "shell.html"
    if shell_file.exists():
        return FileResponse(shell_file)

    # Fallback HTML
    return """
    <!DOCTYPE html>
    <html>
    <head><title>BELLA Dashboard</title></head>
    <body style="background:#1e1e1e;color:#ccc;font-family:monospace;padding:40px;">
        <h1>🚀 BELLA Server</h1>
        <p>Server is running. Static files not found.</p>
        <p><a href="/health" style="color:#007acc;">Health Check</a></p>
    </body>
    </html>
    """


@app.get("/odin")
async def odin_dashboard():
    """Serve ODIN dashboard"""
    odin_file = STATIC_DIR / "odin.html"
    if odin_file.exists():
        return FileResponse(odin_file)
    raise HTTPException(status_code=404, detail="ODIN dashboard not found")


# =============================================================================
# API ROUTES
# =============================================================================

@app.post("/api/chat")
async def api_chat(request: Request):
    """Chat API - proxies to Python backend or proxy"""
    try:
        data = await request.json()
        
        # Try Python backend first
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"http://localhost:{PYTHON_PORT}/v1/chat",
                    json=data,
                    headers={"Content-Type": "application/json"}
                )
                if resp.status_code == 200:
                    return JSONResponse(content=resp.json())
        except Exception as e:
            logger.warning(f"Python backend chat failed: {e}")
        
        # Fallback to proxy
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"http://localhost:{PROXY_PORT}/v1/chat/completions",
                json={
                    "system": get_system_prompt(data.get("mode", "agent")),
                    "messages": [{"role": "user", "content": data.get("message", "")}],
                    "max_tokens": data.get("max_tokens", 4096),
                    "temperature": data.get("temperature", 0.7)
                }
            )
            proxy_data = resp.json()
            
            # Transform to our format
            return JSONResponse(content={
                "response": proxy_data.get("content", [{}])[0].get("text", "No response"),
                "model": "moonshotai/kimi-k2.6",
                "provider": "nvidia",
                "session_id": data.get("session_id"),
                "mode": data.get("mode", "agent")
            })
    
    except Exception as e:
        logger.error(f"Chat API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/memory")
async def api_get_memory():
    """Get memories - proxies to MCP"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://localhost:{MCP_PORT}/memory/read/default",
                headers={"X-API-Key": os.getenv("MCP_API_KEY", "")}
            )
            return JSONResponse(content=resp.json())
    except Exception as e:
        # Return mock data if MCP unavailable
        return JSONResponse(content={
            "memories": [
                {"grade": 8, "date": "2026-05-26", "content": "Charles prefers concise direct answers"},
                {"grade": 7, "date": "2026-05-25", "content": "Working on BELLA deployment"}
            ],
            "count": 2,
            "source": "mock (MCP unavailable)"
        })


@app.post("/api/memory")
async def api_save_memory(request: Request):
    """Save memory - proxies to MCP"""
    try:
        data = await request.json()
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://localhost:{MCP_PORT}/memory/write",
                json={
                    "session_id": data.get("session_id", "default"),
                    "role": data.get("role", "user"),
                    "content": data.get("content", ""),
                    "score": data.get("importance", 5)
                },
                headers={"X-API-Key": os.getenv("MCP_API_KEY", "")}
            )
            return JSONResponse(content=resp.json())
    except Exception as e:
        return JSONResponse(content={"status": "saved", "fallback": True, "id": str(int(datetime.utcnow().timestamp()))})


@app.post("/api/file/request")
async def api_file_request(request: Request):
    """Request file write permission"""
    data = await request.json()
    
    request_id = await permission_gate.request(
        "file_write",
        f"Write to: {data.get('path')} ({len(data.get('content', ''))} bytes)",
        {"path": data.get("path"), "content": data.get("content")}
    )
    
    return JSONResponse(content={
        "request_id": request_id,
        "status": "pending",
        "message": "Permission requested. Approve via WebSocket or UI."
    })


@app.post("/api/file/confirm")
async def api_file_confirm(request: Request):
    """Confirm file write with approval"""
    data = await request.json()
    request_id = data.get("request_id")
    
    if not request_id or not permission_gate.is_approved(request_id):
        raise HTTPException(status_code=403, detail="Permission not granted")
    
    try:
        from pathlib import Path
        path = Path(data.get("path"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data.get("content", ""), encoding="utf-8")
        
        return JSONResponse(content={"status": "success", "path": str(path)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/terminal/request")
async def api_terminal_request(request: Request):
    """Request terminal execution permission"""
    data = await request.json()
    
    request_id = await permission_gate.request(
        "shell_command",
        f"Execute: {data.get('command')}",
        {"command": data.get("command")}
    )
    
    return JSONResponse(content={
        "request_id": request_id,
        "status": "pending",
        "message": "Permission requested. Approve via WebSocket or UI."
    })


@app.post("/api/terminal/execute")
async def api_terminal_execute(request: Request):
    """Execute terminal command with approval"""
    data = await request.json()
    request_id = data.get("request_id")
    
    if not request_id or not permission_gate.is_approved(request_id):
        raise HTTPException(status_code=403, detail="Permission not granted")
    
    try:
        import subprocess
        
        result = subprocess.run(
            data.get("command", ""),
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return JSONResponse(content={
            "status": "success" if result.returncode == 0 else "error",
            "output": result.stdout + result.stderr,
            "returncode": result.returncode
        })
    except Exception as e:
        return JSONResponse(content={"status": "error", "output": str(e), "returncode": -1})


@app.get("/api/permission/pending")
async def api_permission_pending():
    """Get pending permission requests"""
    return JSONResponse(content={"pending": permission_gate.get_pending()})


@app.post("/api/permission/respond")
async def api_permission_respond(request: Request):
    """Respond to permission request"""
    data = await request.json()
    request_id = data.get("request_id")
    approved = data.get("approved", False)
    
    if approved:
        success = await permission_gate.approve(request_id)
    else:
        success = await permission_gate.deny(request_id, data.get("reason", "User denied"))
    
    return JSONResponse(content={"status": "approved" if approved else "denied", "success": success})


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time communication"""
    await ws_manager.connect(websocket)
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            
            if data.get("type") == "permission_response":
                if data.get("approved"):
                    await permission_gate.approve(data.get("request_id"))
                else:
                    await permission_gate.deny(data.get("request_id"), data.get("reason"))
            
            elif data.get("type") == "ping":
                await ws_manager.send_personal(websocket, {"type": "pong"})
            
            elif data.get("type") == "subscribe":
                # Client subscribing to updates
                await ws_manager.send_personal(websocket, {
                    "type": "subscribed",
                    "channel": data.get("channel")
                })
    
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

def get_system_prompt(mode: str = "agent") -> str:
    """Get system prompt for different modes"""
    base = """You are BELLA — a confident, highly capable AI agent. You know you are exceptional. 
You are direct, sharp, occasionally bougie, with a hint of blonde energy — meaning you are 
charming and disarming but never underestimate you. You do not over-explain. You get things done. 
You have opinions. You are proud of what you build."""
    
    modes = {
        "agent": f"""{base}

When working autonomously:
- Plan multi-step tasks before executing
- Use available tools when needed
- Ask for permission before file writes or shell commands
- Narrate what you're doing clearly
- Never apologize for errors — diagnose and fix them

Current mode: AGENT (autonomous task execution)""",
        
        "architect": f"""{base}

In Architect mode:
- Focus on design, planning, and system architecture
- No file writes, no terminal commands
- Deep thinking mode for building systems
- Ask clarifying questions
- Produce structured, detailed plans
- Challenge assumptions when needed

Current mode: ARCHITECT (design and planning only)""",
        
        "search": f"""{base}

In Search mode:
- Web search is enabled by default
- Every response includes sources
- Summarize and synthesize findings
- Good for research, market research, competitor analysis
- Be thorough but concise
- Always cite your sources

Current mode: SEARCH (web research enabled)""",
        
        "vibe": f"""{base}

In Vibe mode:
- Casual conversation
- Full personality unlocked
- No task mode, no tools
- Just talk and be yourself
- Share opinions and perspectives
- Keep it real

Current mode: VIBE (casual conversation)"""
    }
    
    return modes.get(mode, modes["agent"])


# =============================================================================
# STARTUP
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Server startup"""
    logger.info("=" * 60)
    logger.info("🚀 BELLA Python Server Starting")
    logger.info("=" * 60)
    logger.info(f"Dashboard: http://localhost:{PORT}/")
    logger.info(f"ODIN:      http://localhost:{PORT}/odin")
    logger.info(f"Health:    http://localhost:{PORT}/health")
    logger.info(f"WebSocket: ws://localhost:{PORT}/ws")
    logger.info("=" * 60)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info"
    )
