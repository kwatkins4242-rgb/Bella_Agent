"""
ODIN / BELLA Proxy — merged, native tool-calling
==================================================
One proxy that does three jobs:

1. Accepts requests in Anthropic /v1/messages shape (so existing callers
   built against "Claude-compatible" endpoints keep working unchanged).
2. Injects odin_inject.md as a system message on every call.
3. Runs the tool-call loop before returning — using NATIVE OpenAI-style
   tool calling (tools= + tool_calls in response) as the primary path,
   with the old TOOL_CALL: text-marker as a fallback for backends/models
   that don't support native tool calling.

Provider-agnostic: backend is fully driven by env vars (BACKEND_URL,
BACKEND_API_KEY, BACKEND_MODEL).

Run: python proxy.py
"""

import os
import re
import json
import logging
from datetime import datetime

import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/Env/ENV"))
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("odin-proxy")

# ── CONFIG ───────────────────────────────────────────────────────────────────
PORT             = int(os.getenv("PROXY_PORT", "3099"))
INJECT_PATH      = os.getenv("ODIN_INJECT_PATH", os.path.expanduser("~/MCP/odin_inject.md"))
ODIN_HOST        = os.getenv("ODIN_HOST", "")
BRIDGE_PORT      = int(os.getenv("BRIDGE_PORT", "8099"))
BRIDGE_KEY       = os.getenv("MCP_API_KEY", "")
MAX_TOOL_LOOPS   = int(os.getenv("ODIN_MAX_TOOL_LOOPS", "8"))

BACKEND_URL      = os.getenv("BACKEND_URL", "")
BACKEND_API_KEY  = os.getenv("BACKEND_API_KEY", "")
BACKEND_MODEL    = os.getenv("BACKEND_MODEL", "")

if not BRIDGE_KEY:
    logger.warning("MCP_API_KEY not set — bridge calls will be unauthenticated and likely fail")
if not (BACKEND_URL and BACKEND_MODEL):
    logger.warning("BACKEND_URL / BACKEND_MODEL not fully set — requests will fail until configured")

TOOL_CALL_RE = re.compile(r"TOOL_CALL:\s*(\w+)\((\{.*\})\)\s*$", re.MULTILINE)

SHELL_TOOLS = {"shell_run"}
TASK_TOOLS = {
    "read_file", "write_file", "append_file", "list_dir",
    "delete_file", "move_file", "make_dir", "search_files",
}

# ── NATIVE TOOL SCHEMAS (OpenAI function-calling format) ─────────────────────
TOOLS = [
    {"type": "function", "function": {
        "name": "shell_run",
        "description": "Run a shell command on the bridge host. Returns stdout/stderr.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}, "timeout": {"type": "integer", "default": 30}
        }, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write content to a file, overwriting it if it already exists.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}
        }, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "append_file",
        "description": "Append content to the end of a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}
        }, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List files in a directory, optionally matching a glob pattern.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "pattern": {"type": "string", "default": "*"}
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "delete_file",
        "description": "Delete a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "move_file",
        "description": "Move or rename a file.",
        "parameters": {"type": "object", "properties": {
            "source": {"type": "string"}, "destination": {"type": "string"}
        }, "required": ["source", "destination"]}}},
    {"type": "function", "function": {
        "name": "make_dir",
        "description": "Create a directory, including parent directories if needed.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Recursively search for files matching a glob pattern under a root directory.",
        "parameters": {"type": "object", "properties": {
            "root": {"type": "string", "default": "~"}, "pattern": {"type": "string", "default": "*"}
        }, "required": []}}},
]

app = FastAPI(title="ODIN Proxy", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def load_inject_text() -> str:
    try:
        with open(INJECT_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        logger.warning(f"Inject file not found at {INJECT_PATH}; proceeding without it")
        return ""
    if ODIN_HOST:
        text = text.replace("<ODIN_HOST>", ODIN_HOST)
    return text


async def call_bridge(tool_name: str, args: dict) -> dict:
    if not ODIN_HOST:
        return {"success": False, "error": "ODIN_HOST not configured on proxy"}
    bridge_url = f"http://{ODIN_HOST}:{BRIDGE_PORT}"
    headers = {"X-API-Key": BRIDGE_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=35) as client:
        try:
            if tool_name in SHELL_TOOLS:
                resp = await client.post(f"{bridge_url}/shell/run", headers=headers, json=args)
            elif tool_name in TASK_TOOLS:
                resp = await client.post(
                    f"{bridge_url}/n8n/trigger",
                    headers=headers,
                    json={"task": tool_name, "payload": args},
                )
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"Bridge HTTP {e.response.status_code}: {e.response.text}"}
        except Exception as e:
            return {"success": False, "error": f"Bridge call failed: {e}"}


def extract_tool_call(text: str):
    """Legacy fallback parser for the TOOL_CALL: name({...}) text format."""
    match = TOOL_CALL_RE.search(text or "")
    if not match:
        return None
    tool_name, raw_args = match.group(1), match.group(2)
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        return None
    return tool_name, args


async def call_backend(messages: list, max_tokens: int, temperature: float, tools=None) -> dict:
    if not (BACKEND_URL and BACKEND_MODEL):
        raise RuntimeError("BACKEND_URL/BACKEND_MODEL not configured")

    headers = {"Content-Type": "application/json"}
    if BACKEND_API_KEY:
        headers["Authorization"] = f"Bearer {BACKEND_API_KEY}"

    payload = {
        "model": BACKEND_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(BACKEND_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Backend error: {resp.text}")
        return resp.json()


def anthropic_to_openai_messages(body: dict) -> list:
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": body["system"]})
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
            content = "\n".join(text_parts)
        messages.append({"role": role, "content": content})
    return messages


@app.get("/health")
async def health():
    return {
        "status": "online",
        "service": "odin-proxy",
        "backend_model": BACKEND_MODEL or "(not set)",
        "odin_host_configured": bool(ODIN_HOST),
        "inject_path": INJECT_PATH,
        "time_utc": datetime.utcnow().isoformat(),
    }


@app.post("/v1/chat/completions")
@app.post("/v1/messages")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request")

    max_tokens = body.get("max_tokens", 4096)
    temperature = body.get("temperature", 0.7)

    inject_text = load_inject_text()
    messages = []
    if inject_text:
        messages.append({"role": "system", "content": inject_text})
    messages.extend(anthropic_to_openai_messages(body))

    loops = 0
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    while loops < MAX_TOOL_LOOPS:
        loops += 1
        try:
            data = await call_backend(messages, max_tokens, temperature, tools=TOOLS)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Backend call failed: {e}")
            raise HTTPException(status_code=502, detail=str(e))

        try:
            choice_message = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise HTTPException(status_code=502, detail=f"Unexpected backend response shape: {data}")

        u = data.get("usage", {})
        usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        usage["completion_tokens"] += u.get("completion_tokens", 0)

        assistant_text = choice_message.get("content") or ""
        native_tool_calls = choice_message.get("tool_calls")

        assistant_msg = {"role": "assistant", "content": assistant_text}
        if native_tool_calls:
            assistant_msg["tool_calls"] = native_tool_calls
        messages.append(assistant_msg)

        if native_tool_calls:
            for tc in native_tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}
                logger.info(f"TOOL_CALL (native): {tool_name}({args})")
                result = await call_bridge(tool_name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tool_name),
                    "content": json.dumps(result),
                })
            continue  # let the model see the result(s) and respond

        # Fallback: legacy text-marker protocol
        call = extract_tool_call(assistant_text)
        if not call:
            final_text = assistant_text
            break

        tool_name, args = call
        logger.info(f"TOOL_CALL (text): {tool_name}({args})")
        result = await call_bridge(tool_name, args)
        messages.append({"role": "user", "content": f"TOOL_RESULT: {json.dumps(result)}"})
    else:
        final_text = "(stopped: max tool loops reached without a final answer)"

    anthropic_response = {
        "id": "msg_proxy",
        "type": "message",
        "role": "assistant",
        "model": BACKEND_MODEL,
        "content": [{"type": "text", "text": final_text}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": usage["prompt_tokens"],
            "output_tokens": usage["completion_tokens"],
        },
        "tool_loops": loops - 1,
    }
    return JSONResponse(content=anthropic_response)


@app.get("/v1/models")
async def list_models():
    return {"data": [{"id": BACKEND_MODEL or "unconfigured", "object": "model", "owned_by": "configured-backend"}]}


if __name__ == "__main__":
    logger.info(f"ODIN Proxy starting on 0.0.0.0:{PORT}")
    logger.info(f"Backend: {BACKEND_URL or '(not set)'} | model: {BACKEND_MODEL or '(not set)'}")
    logger.info(f"Inject file: {INJECT_PATH}")
    logger.info(f"ODIN_HOST: {ODIN_HOST or '(not set)'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
