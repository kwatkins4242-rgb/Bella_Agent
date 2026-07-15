"""
ODIN Unified Backend — port 8000
=================================
Single FastAPI app that mounts:
  - /api/chat          → quick chat via router (no loop)
  - /api/run           → full engine loop (plan→reason→execute→verify)
  - /api/stream        → SSE stream of engine events
  - /api/status        → engine + service health
  - /api/permissions/* → approve/deny tool calls
  - /api/memory/*      → proxied to bella_memory_api
  - /api/sessions      → MongoDB session log
  - /api/providers     → list configured providers
  - /health            → simple ping

Run:
    cd /home/kwatk/AGENT
    python -m uvicorn odin-core.main:app --host 0.0.0.0 --port 8000 --reload

Or via start.sh.
"""

import sys
import os
import json
import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncGenerator

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE   = Path(__file__).parent          # /AGENT/odin-core
_ROOT   = _HERE.parent                   # /AGENT

# Allow imports: odin-core/, mongo/, memory/
for _p in [str(_HERE), str(_ROOT / "mongo"), str(_ROOT / "memory")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Env loading ───────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(_ROOT / "env", override=False)        # /AGENT/env (no extension)
load_dotenv(Path.home() / "Env/ENV", override=False)

# ── FastAPI ───────────────────────────────────────────────────────────────────
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# ── ODIN internals ────────────────────────────────────────────────────────────
from engine import OdinEngine
from permissions import PermissionGate
from db import get_db
import router as odin_router
from task_queue import get_task_queue, Task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("odin.main")

# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
if not _CONFIG_PATH.exists():
    logger.error(f"Backend config not found at {_CONFIG_PATH}")
    raise FileNotFoundError(f"Backend config not found at {_CONFIG_PATH}")
with open(_CONFIG_PATH) as f:
    CONFIG = json.load(f)

BELLA_URL     = os.getenv("MEMORY_API_URL", "http://127.0.0.1:8005")
BELLA_API_KEY = os.getenv("BELLA_API_KEY",  "bella-keith-private-2026")
N8N_BASE      = os.getenv("N8N_WEBHOOK_URL","http://127.0.0.1:5678/webhook/")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ODIN Core",
    version="3.0.0",
    description="ODIN AI Agent — unified backend"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Singletons ────────────────────────────────────────────────────────────────
_permission_gate: PermissionGate = PermissionGate(auto_approve=False, timeout=120.0)
_engine: Optional[OdinEngine] = None
_stream_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


def _get_engine() -> OdinEngine:
    global _engine
    if _engine is None:
        _engine = OdinEngine(
            stream_callback=_stream_emit,
            permission_gate=_permission_gate,
        )
    return _engine


async def _stream_emit(role: str, text: str):
    """Push a chunk to the SSE queue."""
    try:
        _stream_queue.put_nowait({"role": role, "text": text, "ts": datetime.utcnow().isoformat()})
    except asyncio.QueueFull:
        pass  # drop if queue full


# ── Startup / Shutdown ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    db = get_db()
    await db.connect()
    logger.info("ODIN backend started — port 8000")


@app.on_event("shutdown")
async def shutdown():
    db = get_db()
    await db.disconnect()
    logger.info("ODIN backend shutdown")


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "online",
        "service": "odin-core",
        "version": "3.0.0",
        "time_utc": datetime.utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER / CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/providers")
async def list_providers():
    return odin_router.list_providers()


@app.get("/api/config")
async def get_config():
    """Return sanitised config (no credentials)."""
    safe = {
        "ACTIVE_BRAIN":     CONFIG.get("ACTIVE_BRAIN"),
        "ACTIVE_REASONING": CONFIG.get("ACTIVE_REASONING"),
        "ACTIVE_FALLBACK":  CONFIG.get("ACTIVE_FALLBACK"),
        "odin":             CONFIG.get("odin", {}),
    }
    providers_safe = {}
    for k, v in CONFIG.get("providers", {}).items():
        providers_safe[k] = {
            "type":           v.get("type"),
            "default_model":  v.get("default_model"),
            "supports_tools": v.get("supports_tools"),
            "local":          v.get("local"),
            "models":         v.get("models", []),
        }
    safe["providers"] = providers_safe
    return safe


class ProviderAssignBody(BaseModel):
    role: str          # planner | reasoning | coder | verifier
    provider: str
    model: str


@app.post("/api/config/assign")
async def assign_role(body: ProviderAssignBody):
    """Reassign a role to a different provider/model at runtime."""
    _get_engine().assign_role(body.role, body.provider, body.model)
    return {"ok": True, "role": body.role, "provider": body.provider, "model": body.model}


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT (quick, no engine loop)
# ═══════════════════════════════════════════════════════════════════════════════

class ChatBody(BaseModel):
    message: str
    session_id: str = "default"
    role: str = "brain"
    provider: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/chat")
async def chat(body: ChatBody):
    messages = [
        {"role": "system", "content": "You are ODIN, an autonomous AI agent. Be concise and helpful."},
        {"role": "user",   "content": body.message},
    ]
    try:
        result = await odin_router.chat(
            messages,
            role=body.role,
            provider_override=body.provider,
            model=body.model,
        )
        return {
            "response": result.get("content", ""),
            "session_id": body.session_id,
            "provider": body.provider or CONFIG.get("ACTIVE_BRAIN"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE — RUN TASK
# ═══════════════════════════════════════════════════════════════════════════════

class RunBody(BaseModel):
    goal: str
    session_id: str = "default"


_active_task: Optional[asyncio.Task] = None


@app.post("/api/run")
async def run_task(body: RunBody, background_tasks: BackgroundTasks):
    global _active_task
    engine = _get_engine()
    if engine.running:
        raise HTTPException(status_code=409, detail="Engine is already running a task.")

    async def _execute():
        async for event in engine.run_task(body.goal, body.session_id):
            await _stream_emit("engine_event", json.dumps(event))

    _active_task = asyncio.create_task(_execute())
    return {
        "ok": True,
        "goal": body.goal,
        "session_id": body.session_id,
        "stream_url": "/api/stream",
    }


@app.post("/api/stop")
async def stop_task():
    global _active_task
    engine = _get_engine()
    _permission_gate.deny_all()
    if _active_task and not _active_task.done():
        _active_task.cancel()
    engine.running = False
    return {"ok": True, "message": "Task stopped."}


# ═══════════════════════════════════════════════════════════════════════════════
# SSE STREAM
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/stream")
async def stream(request: Request):
    """Server-Sent Events — dashboard subscribes here for live output."""
    async def generate():
        while True:
            if await request.is_disconnected():
                break
            try:
                chunk = await asyncio.wait_for(_stream_queue.get(), timeout=15.0)
                yield f"data: {json.dumps(chunk)}\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"  # keepalive

    return StreamingResponse(generate(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE STATUS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
async def status():
    engine = _get_engine()
    db = get_db()
    pending_perms = _permission_gate.get_pending()

    # Check services
    services = {}
    async with httpx.AsyncClient(timeout=4) as c:
        for name, url in [
            ("memory", f"{BELLA_URL}/health"),
            ("n8n",    f"{N8N_BASE.replace('/webhook/', '')}/healthz"),
            ("mcp",    f"http://127.0.0.1:{CONFIG.get('odin', {}).get('mcp', {}).get('port', 8099)}/health"),
        ]:
            try:
                r = await c.get(url)
                services[name] = "ok" if r.status_code < 400 else f"HTTP {r.status_code}"
            except Exception:
                services[name] = "unreachable"

    return {
        "engine": engine.get_status(),
        "permissions_pending": len(pending_perms),
        "db_connected": db._connected if hasattr(db, "_connected") else False,
        "services": services,
        "role_assignments": engine.get_role_assignments(),
        "time_utc": datetime.utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/permissions")
async def get_pending_permissions():
    return {"pending": _permission_gate.get_pending()}


class PermissionResponse(BaseModel):
    request_id: str
    approved: bool


@app.post("/api/permissions/respond")
async def respond_permission(body: PermissionResponse):
    ok = _permission_gate.respond(body.request_id, body.approved)
    if not ok:
        raise HTTPException(status_code=404, detail="Permission request not found or already resolved.")

    # Log to DB
    db = get_db()
    try:
        await db.log_permission(
            tool_name="(from dashboard)",
            params={"request_id": body.request_id},
            approved=body.approved,
            session_id="dashboard",
        )
    except Exception:
        pass

    return {"ok": True, "approved": body.approved}


@app.post("/api/permissions/deny-all")
async def deny_all_permissions():
    _permission_gate.deny_all()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# TASK QUEUE — gives engine something to work on
# ═══════════════════════════════════════════════════════════════════════════════

class TaskSubmitBody(BaseModel):
    goal: str
    source: str = "user"
    session_id: str = "default"
    priority: int = 5
    memory_injection: Optional[str] = None
    session_context: Optional[str] = None


@app.post("/api/task")
async def submit_task(body: TaskSubmitBody):
    """Submit a task to the queue"""
    queue = get_task_queue()
    context = {}
    if body.memory_injection:
        context["memory_injection"] = body.memory_injection
    if body.session_context:
        context["session_context"] = body.session_context

    task = await queue.add(
        goal=body.goal,
        source=body.source,
        session_id=body.session_id,
        priority=body.priority,
        context=context
    )
    logger.info(f"Task submitted: {task.id} from {body.source}")
    return {"ok": True, "task": task.to_dict()}


@app.get("/api/tasks")
async def list_tasks(status: Optional[str] = None, limit: int = 50):
    """List tasks"""
    queue = get_task_queue()
    tasks = await queue.list_tasks(status=status, limit=limit)
    return {"tasks": [t.to_dict() for t in tasks]}


@app.get("/api/task/{task_id}")
async def get_task(task_id: str):
    """Get task by ID"""
    queue = get_task_queue()
    task = await queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task.to_dict()}


@app.get("/api/tasks/count")
async def count_tasks(status: Optional[str] = None):
    """Count tasks"""
    queue = get_task_queue()
    count = await queue.count(status=status)
    return {"count": count, "status": status}


@app.post("/api/tasks/clear")
async def clear_completed_tasks(older_than_hours: int = 24):
    """Clear completed tasks"""
    queue = get_task_queue()
    removed = await queue.clear_completed(older_than_hours=older_than_hours)
    return {"ok": True, "removed": removed}


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY PROXY  (forwards to bella_memory_api on port 8765)
# ═══════════════════════════════════════════════════════════════════════════════

async def _bella(method: str, path: str, body: dict = None, params: dict = None):
    headers = {"X-API-Key": BELLA_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as c:
        if method == "GET":
            r = await c.get(f"{BELLA_URL}{path}", headers=headers, params=params)
        else:
            r = await c.post(f"{BELLA_URL}{path}", headers=headers, json=body or {})
        r.raise_for_status()
        return r.json()


@app.get("/api/memory/inject/{session_id}")
async def memory_inject(session_id: str):
    """Get context injection for a session (Memory Pro / bella_memory_api compatible)."""
    try:
        return await _bella("GET", f"/memory/inject/{session_id}")
    except Exception as e:
        return {"context": "", "error": str(e)}


@app.post("/api/memory/context/inject")
async def memory_context_inject(req: Request):
    """Receive a context injection from n8n scheduled summary workflow."""
    body = await req.json()
    try:
        return await _bella("POST", "/memory/context/inject", body)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/memory/save")
async def memory_save(req: Request):
    body = await req.json()
    try:
        return await _bella("POST", "/memory/save", body)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/memory/search")
async def memory_search(req: Request):
    body = await req.json()
    try:
        return await _bella("POST", "/memory/search", body)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/memory/recent")
async def memory_recent(session_id: str = "default", limit: int = 20):
    try:
        return await _bella("GET", "/memory/recent", params={"session_id": session_id, "limit": limit})
    except Exception as e:
        return {"memories": [], "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# SESSIONS / LOGS (MongoDB)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/sessions")
async def get_sessions(limit: int = 20):
    db = get_db()
    return {"sessions": await db.get_sessions(limit)}


@app.get("/api/logs")
async def get_logs(limit: int = 50):
    db = get_db()
    return {"logs": await db.get_recent_logs(limit)}


# ═══════════════════════════════════════════════════════════════════════════════
# n8n PROXY
# ═══════════════════════════════════════════════════════════════════════════════

class N8nTriggerBody(BaseModel):
    webhook: str
    payload: dict = {}


@app.post("/api/n8n/trigger")
async def n8n_trigger(body: N8nTriggerBody):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{N8N_BASE}{body.webhook.lstrip('/')}",
                json=body.payload,
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                return {"raw": r.text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PYTHON_PORT", "8001")),
        reload=False,
        log_level="info",
    )
