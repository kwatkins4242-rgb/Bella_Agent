"""
FAST MCP Server — Professional Build
~/MCP/server.py

Loads from ~/env/ENV automatically.
Start: python server.py          → stdio (default)
       python server.py stdio    → stdio
       python server.py http     → HTTP on MCP_PORT (default 8080)
       python server.py http --port 8080
"""

import os, json, logging, httpx, subprocess, platform, shlex
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# ── ENV ──────────────────────────────────────────────────────────────────────
load_dotenv(os.path.expanduser("~/env/ENV"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fast-mcp")

# ── CONFIG ───────────────────────────────────────────────────────────────────
MCP_PORT         = int(os.getenv("MCP_PORT",     "8080"))
ODIN_BRIDGE_URL  = os.getenv("BRIDGE_URL",        "http://127.0.0.1:8099")
ODIN_BRIDGE_KEY  = os.getenv("MCP_API_KEY",      os.getenv("BRIDGE_KEY", "BELLA_2026_BRIDGE_KEY"))
ODIN_CORE_URL    = os.getenv("ODIN_CORE_URL",    "http://127.0.0.1:8001")
BELLA_URL        = os.getenv("MEMORY_API_URL",   "http://127.0.0.1:8005")
MONGO_URI        = os.getenv("MONGO_URI",        "mongodb://localhost:27017")
N8N_WEBHOOK_URL  = os.getenv("N8N_WEBHOOK_URL",  "http://127.0.0.1:5678/webhook")
N8N_API_KEY      = os.getenv("N8N_API_KEY",      "")

mcp = FastMCP(name="FAST-MCP")

# Legacy root-level HTTP endpoints that the rest of the stack expects.
# FastMCP 3.x owns the HTTP server, so we register these via custom_route.
@mcp.custom_route("/health", methods=["GET"])
async def legacy_health(request):
    return JSONResponse({"status": "ok", "service": "fast-mcp", "version": "3.4.4"})

@mcp.custom_route("/tools", methods=["GET"])
async def legacy_list_tools(request):
    tools = []
    registered = await mcp.list_tools()
    for tool in registered:
        tools.append({
            "name": getattr(tool, "name", "unknown"),
            "description": getattr(tool, "description", "") or "",
            "parameters": getattr(tool, "parameters", {}) if getattr(tool, "parameters", None) else {},
        })
    return JSONResponse({"tools": tools})

@mcp.custom_route("/execute", methods=["POST"])
async def legacy_execute(request):
    body = await request.json()
    tool_name = body.get("tool") or body.get("name")
    params = body.get("params") or body.get("arguments") or {}
    try:
        result = await mcp.call_tool(tool_name, params)
        text_parts = []
        for c in getattr(result, "content", []) or []:
            text_parts.append(getattr(c, "text", ""))
        return JSONResponse({"tool": tool_name, "result": "\n".join(text_parts)})
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {e}")
        return JSONResponse({"tool": tool_name, "error": str(e)}, status_code=500)

# Remove unused separate FastAPI app and starlette imports.
# http_app = FastAPI()  # no longer needed; routes registered on mcp directly.

# ── HELPERS ──────────────────────────────────────────────────────────────────
def _bh():
    return {
        "X-API-Key":    ODIN_BRIDGE_KEY,
        "X-ODIN-KEY":   ODIN_BRIDGE_KEY,
        "Content-Type": "application/json",
    }

def _bella_headers():
    return {
        "X-API-Key":   os.getenv("BELLA_API_KEY", "bella-keith-private-2026"),
        "Content-Type": "application/json",
    }

async def _bridge(endpoint: str, body: dict, timeout: int = 60) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{ODIN_BRIDGE_URL}{endpoint}", headers=_bh(), json=body)
        r.raise_for_status()
        return r.json()

async def _bella(method: str, endpoint: str, body: dict = None, params: dict = None, timeout: int = 30):
    async with httpx.AsyncClient(timeout=timeout) as c:
        if method == "GET":
            r = await c.get(f"{BELLA_URL}{endpoint}", headers=_bella_headers(), params=params)
        else:
            r = await c.post(f"{BELLA_URL}{endpoint}", headers=_bella_headers(), json=body or {})
        r.raise_for_status()
        return r.json()

async def _n8n(path: str, payload: dict = {}, timeout: int = 60) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as c:
        h = {"Content-Type": "application/json"}
        if N8N_API_KEY:
            h["X-N8N-API-KEY"] = N8N_API_KEY
        url = f"{N8N_WEBHOOK_URL}/{path.lstrip('/')}"
        r = await c.post(url, headers=h, json=payload)
        r.raise_for_status()
        return r.json()

# ═════════════════════════════════════════════════════════════════════════════
# SHELL TOOLS
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def shell_run(command: str, timeout: int = 30) -> str:
    """Run a shell command on the ODIN bridge server."""
    try:
        result = await _bridge("/shell/run", {"command": command}, timeout)
        return result.get("output", json.dumps(result))
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def shell_run_local(command: str, timeout: int = 30) -> str:
    """Run a shell command locally on THIS machine (the laptop)."""
    try:
        proc = subprocess.run(
            shlex.split(command) if platform.system() != "Windows" else command,
            capture_output=True, text=True, timeout=timeout, shell=platform.system() == "Windows"
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        return out if out else (err if err else "(no output)")
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def shell_background(command: str) -> str:
    """Start a background process locally and return immediately."""
    try:
        subprocess.Popen(shlex.split(command), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Started: {command}"
    except Exception as e:
        return f"ERROR: {e}"

# ═════════════════════════════════════════════════════════════════════════════
# FILE TOOLS
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def file_read(path: str) -> str:
    """Read a file via ODIN bridge."""
    try:
        result = await _bridge("/n8n/trigger", {"task": "read_file", "payload": {"path": path}, "api_key": ODIN_BRIDGE_KEY})
        if result.get("success"):
            return result.get("data", {}).get("content", json.dumps(result))
        return f"Error: {result.get('error', 'unknown')}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_read_local(path: str) -> str:
    """Read a file on THIS local machine."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"ERROR: file not found: {path}"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_write(path: str, content: str) -> str:
    """Write content to a file via ODIN bridge."""
    try:
        result = await _bridge("/n8n/trigger", {"task": "write_file", "payload": {"path": path, "content": content}, "api_key": ODIN_BRIDGE_KEY})
        return "Written." if result.get("success") else f"Error: {result.get('error')}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_write_local(path: str, content: str) -> str:
    """Write content to a file on THIS local machine."""
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written: {path}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_append_local(path: str, content: str) -> str:
    """Append content to a file on THIS local machine."""
    try:
        p = Path(path).expanduser()
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended to: {path}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_list(path: str) -> str:
    """List directory contents via ODIN bridge."""
    try:
        result = await _bridge("/n8n/trigger", {"task": "list_dir", "payload": {"path": path}, "api_key": ODIN_BRIDGE_KEY})
        return json.dumps(result.get("data", []), indent=2) if result.get("success") else f"Error: {result.get('error')}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_list_local(path: str = "~", pattern: str = "*") -> str:
    """List files on THIS local machine. Supports glob patterns."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"ERROR: path not found: {path}"
        files = sorted([str(f) for f in p.glob(pattern)])
        return json.dumps(files, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_delete(path: str) -> str:
    """Delete a file via ODIN bridge."""
    try:
        result = await _bridge("/n8n/trigger", {"task": "delete_file", "payload": {"path": path}, "api_key": ODIN_BRIDGE_KEY})
        return "Deleted." if result.get("success") else f"Error: {result.get('error')}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_delete_local(path: str) -> str:
    """Delete a file on THIS local machine."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"ERROR: not found: {path}"
        p.unlink()
        return f"Deleted: {path}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_move(source: str, destination: str) -> str:
    """Move or rename a file via ODIN bridge."""
    try:
        result = await _bridge("/n8n/trigger", {"task": "move_file", "payload": {"source": source, "destination": destination}, "api_key": ODIN_BRIDGE_KEY})
        return "Moved." if result.get("success") else f"Error: {result.get('error')}"
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def file_search(root: str = "~", pattern: str = "*") -> str:
    """Search files recursively via ODIN bridge."""
    try:
        result = await _bridge("/n8n/trigger", {"task": "search_files", "payload": {"root": root, "pattern": pattern}, "api_key": ODIN_BRIDGE_KEY})
        return json.dumps(result.get("data", []), indent=2) if result.get("success") else f"Error: {result.get('error')}"
    except Exception as e:
        return f"ERROR: {e}"

# ═════════════════════════════════════════════════════════════════════════════
# BELLA MEMORY TOOLS
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def memory_save(content: str, session_id: str = "odin_default", tags: list = []) -> str:
    """Save a memory to Bella."""
    try:
        result = await _bella("POST", "/memory/save", {"content": content, "session_id": session_id, "tags": tags})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def memory_search(query: str, session_id: str = "odin_default", limit: int = 5) -> str:
    """Search Bella memory."""
    try:
        result = await _bella("POST", "/memory/search", {"query": query, "session_id": session_id, "limit": limit})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def memory_inject(session_id: str = "odin_default") -> str:
    """Pull Bella memory context ready to inject into a prompt."""
    try:
        result = await _bella("GET", f"/memory/inject/{session_id}")
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

# ═════════════════════════════════════════════════════════════════════════════
# n8n WORKFLOW TOOLS
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def n8n_trigger(webhook_path: str, payload: dict = {}) -> str:
    """Fire an n8n webhook. webhook_path = slug after /webhook/"""
    try:
        result = await _n8n(webhook_path, payload)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def n8n_bella_start(session_id: str = "odin_default") -> str:
    """Trigger the Bella session-start n8n workflow."""
    try:
        result = await _n8n("bella-session-start", {"session_id": session_id})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def n8n_feed_memory(content: str, session_id: str = "odin_default") -> str:
    """Push content into Bella memory via n8n feed-memory webhook."""
    try:
        result = await _n8n("bella-feed-memory", {"content": content, "session_id": session_id})
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

# ═════════════════════════════════════════════════════════════════════════════
# ODIN CORE TOOLS
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def odin_chat(message: str, session_id: str = "mcp_session") -> str:
    """Send a message to ODIN core /api/chat."""
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{ODIN_CORE_URL}/api/chat", json={"message": message, "session_id": session_id})
            r.raise_for_status()
            data = r.json()
            return data.get("response", data.get("content", json.dumps(data)))
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def odin_auto(task: str) -> str:
    """Send an autonomous task to ODIN /api/auto — ODIN plans and executes."""
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{ODIN_CORE_URL}/api/auto", json={"task": task})
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def odin_code(prompt: str, language: str = "python") -> str:
    """Ask ODIN to generate or review code."""
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{ODIN_CORE_URL}/api/code", json={"prompt": prompt, "language": language})
            r.raise_for_status()
            data = r.json()
            return data.get("code", data.get("response", json.dumps(data)))
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def odin_status() -> str:
    """Get ODIN core system status and active modules."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{ODIN_CORE_URL}/api/status")
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
    except Exception as e:
        return f"ERROR: {e}"

# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM / UTILITY TOOLS
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def health_check(service: str = "all") -> str:
    """Ping ODIN services. service: all | bridge | bella | n8n | odin"""
    targets = {
        "bridge": f"{ODIN_BRIDGE_URL}/health",
        "bella":  f"{BELLA_URL}/health",
        "odin":   f"{ODIN_CORE_URL}/health",
    }
    check = list(targets.keys()) if service == "all" else [service]
    results = {}
    async with httpx.AsyncClient(timeout=8) as c:
        for name in check:
            if name not in targets:
                results[name] = "unknown service"
                continue
            try:
                r = await c.get(targets[name])
                results[name] = "ok" if r.status_code < 400 else f"HTTP {r.status_code}"
            except Exception as e:
                results[name] = "unreachable"
    return json.dumps(results, indent=2)

@mcp.tool()
async def env_check() -> str:
    """Show which ENV keys are loaded (values masked for security)."""
    keys = [
        "MCP_URL", "MCP_API_KEY", "BELLA_API_KEY", "MEMORY_API_URL",
        "N8N_WEBHOOK_URL", "N8N_API_KEY", "ODIN_CORE_URL", "MONGO_URI",
        "PROXY_API_KEY", "SEARCH_PROVIDER"
    ]
    result = {}
    for k in keys:
        v = os.getenv(k, "")
        result[k] = "SET" if v else "NOT SET"
    return json.dumps(result, indent=2)

@mcp.tool()
async def system_info() -> str:
    """Return basic system info about THIS machine."""
    try:
        info = {
            "platform": platform.system(),
            "hostname": platform.node(),
            "python":   platform.python_version(),
            "cwd":      os.getcwd(),
            "user":     os.getenv("USER", os.getenv("USERNAME", "unknown")),
            "time_utc": datetime.utcnow().isoformat(),
        }
        return json.dumps(info, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def timestamp() -> str:
    """Return current UTC timestamp."""
    return datetime.utcnow().isoformat()

@mcp.tool()
async def json_parse(text: str) -> str:
    """Parse and pretty-print a JSON string. Useful for debugging."""
    try:
        return json.dumps(json.loads(text), indent=2)
    except Exception as e:
        return f"ERROR: invalid JSON — {e}"

@mcp.tool()
async def http_get(url: str, headers: dict = {}) -> str:
    """Make a raw HTTP GET request to any URL."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=headers)
            try:
                return json.dumps(r.json(), indent=2)
            except Exception:
                return r.text
    except Exception as e:
        return f"ERROR: {e}"

@mcp.tool()
async def http_post(url: str, payload: dict = {}, headers: dict = {}) -> str:
    """Make a raw HTTP POST request to any URL."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            h = {"Content-Type": "application/json", **headers}
            r = await c.post(url, headers=h, json=payload)
            try:
                return json.dumps(r.json(), indent=2)
            except Exception:
                return r.text
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
async def web_search(query: str, max_results: int = 5) -> str:
    """Perform a web search using Ollama Cloud Search API."""
    try:
        api_key = os.getenv("OLLAMA_API_KEY", "")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://ollama.com/api/web_search",
                headers=headers,
                json={"query": query, "max_results": max_results}
            )
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
    except Exception as e:
        logger.error(f"web_search failed: {e}")
        # Fallback to local duckduckgo search if available
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                return json.dumps({"results": results}, indent=2)
        except Exception as ex:
            return f"ERROR: web search failed: {e} (fallback: {ex})"


@mcp.tool()
async def web_fetch(url: str) -> str:
    """Fetch the contents of a web page using Ollama Cloud Fetch API."""
    try:
        api_key = os.getenv("OLLAMA_API_KEY", "")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://ollama.com/api/web_fetch",
                headers=headers,
                json={"url": url}
            )
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
    except Exception as e:
        logger.error(f"web_fetch failed: {e}")
        return f"ERROR: web fetch failed: {e}"


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import uvicorn
    args = sys.argv[1:]
    transport = args[0] if args else "stdio"

    if transport == "http":
        port = MCP_PORT
        # allow --port override
        if "--port" in args:
            port = int(args[args.index("--port") + 1])
        logger.info(f"Starting FAST MCP Server — HTTP on 0.0.0.0:{port}")
        # Use streamable-http so custom routes registered via @mcp.custom_route
        # are exposed at root alongside the MCP protocol endpoint.
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        logger.info(f"Starting FAST MCP Server — transport: {transport}")
        mcp.run(transport=transport)
