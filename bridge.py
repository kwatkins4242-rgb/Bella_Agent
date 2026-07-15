"""
ODIN Bridge Server
Handles: shell execution, file ops, n8n forwarding
Deploy on BOTH local Dell and VPS at port 8099
Start: python bridge.py
"""

import os, json, logging, subprocess, shlex, platform, shutil
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/env/ENV"))
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("odin-bridge")

BRIDGE_PORT = int(os.getenv("BRIDGE_PORT", "8099"))
BRIDGE_KEY  = os.getenv("MCP_API_KEY", os.getenv("BRIDGE_KEY", "BELLA_2026_BRIDGE_KEY"))
HOST        = os.getenv("BRIDGE_HOST", "0.0.0.0")

app = FastAPI(title="ODIN Bridge", version="1.0.0")

# ── AUTH ──────────────────────────────────────────────────────────────────────
def verify_key(request: Request):
    key = request.headers.get("X-API-Key") or request.headers.get("X-ODIN-KEY")
    if key != BRIDGE_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return key

# ── HEALTH ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "odin-bridge",
        "host": platform.node(),
        "time_utc": datetime.utcnow().isoformat()
    }

# ── SHELL ─────────────────────────────────────────────────────────────────────
@app.post("/shell/run")
async def shell_run(request: Request, _=Depends(verify_key)):
    body = await request.json()
    command = body.get("command", "")
    timeout = body.get("timeout", 30)

    if not command:
        raise HTTPException(status_code=400, detail="No command provided")

    logger.info(f"SHELL: {command}")
    try:
        proc = subprocess.run(
            shlex.split(command) if platform.system() != "Windows" else command,
            capture_output=True, text=True, timeout=timeout,
            shell=platform.system() == "Windows"
        )
        output = proc.stdout.strip() or proc.stderr.strip() or "(no output)"
        return {"success": True, "output": output, "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "ERROR: command timed out"}
    except Exception as e:
        return {"success": False, "output": f"ERROR: {e}"}

# ── FILE OPS ──────────────────────────────────────────────────────────────────
@app.post("/n8n/trigger")
async def file_and_task_handler(request: Request, _=Depends(verify_key)):
    body = await request.json()
    task    = body.get("task", "")
    payload = body.get("payload", {})

    logger.info(f"TASK: {task} | {payload}")

    try:
        # READ FILE
        if task == "read_file":
            path = Path(payload["path"]).expanduser()
            if not path.exists():
                return {"success": False, "error": f"File not found: {path}"}
            content = path.read_text(encoding="utf-8", errors="replace")
            return {"success": True, "data": {"content": content}}

        # WRITE FILE
        elif task == "write_file":
            path = Path(payload["path"]).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload.get("content", ""), encoding="utf-8")
            return {"success": True, "data": {"written": str(path)}}

        # APPEND FILE
        elif task == "append_file":
            path = Path(payload["path"]).expanduser()
            with open(path, "a", encoding="utf-8") as f:
                f.write(payload.get("content", ""))
            return {"success": True, "data": {"appended": str(path)}}

        # LIST DIR
        elif task == "list_dir":
            path = Path(payload["path"]).expanduser()
            if not path.exists():
                return {"success": False, "error": f"Path not found: {path}"}
            pattern = payload.get("pattern", "*")
            files = sorted([str(f) for f in path.glob(pattern)])
            return {"success": True, "data": files}

        # DELETE FILE
        elif task == "delete_file":
            path = Path(payload["path"]).expanduser()
            if not path.exists():
                return {"success": False, "error": f"Not found: {path}"}
            path.unlink()
            return {"success": True, "data": {"deleted": str(path)}}

        # MOVE FILE
        elif task == "move_file":
            src = Path(payload["source"]).expanduser()
            dst = Path(payload["destination"]).expanduser()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return {"success": True, "data": {"moved": f"{src} → {dst}"}}

        # MAKE DIR
        elif task == "make_dir":
            path = Path(payload["path"]).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            return {"success": True, "data": {"created": str(path)}}

        # SEARCH FILES
        elif task == "search_files":
            root    = Path(payload.get("root", "~")).expanduser()
            pattern = payload.get("pattern", "*")
            matches = sorted([str(f) for f in root.rglob(pattern)])
            return {"success": True, "data": matches}

        # SHELL via task
        elif task == "shell_run":
            command = payload.get("command", "")
            timeout = payload.get("timeout", 30)
            proc = subprocess.run(
                shlex.split(command), capture_output=True,
                text=True, timeout=timeout
            )
            output = proc.stdout.strip() or proc.stderr.strip() or "(no output)"
            return {"success": True, "data": {"output": output, "returncode": proc.returncode}}

        else:
            return {"success": False, "error": f"Unknown task: {task}"}

    except Exception as e:
        logger.error(f"Task error: {e}")
        return {"success": False, "error": str(e)}

# ── STATUS ────────────────────────────────────────────────────────────────────
@app.get("/status")
async def status(_=Depends(verify_key)):
    return {
        "service": "odin-bridge",
        "host":    platform.node(),
        "port":    BRIDGE_PORT,
        "python":  platform.python_version(),
        "time_utc": datetime.utcnow().isoformat()
    }

# ── ENTRY ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info(f"ODIN Bridge starting on {HOST}:{BRIDGE_PORT}")
    uvicorn.run(app, host=HOST, port=BRIDGE_PORT, log_level="info")