"""
ODIN Provider Router
Reads config.json — swap providers by changing ACTIVE_BRAIN / ACTIVE_REASONING.
No model names hardcoded anywhere in your agent code.

Usage:
    from router import get_brain, get_reasoning, chat

    # Use whatever provider config.json says
    response = await chat("your message", role="brain")
    response = await chat("complex task", role="reasoning")
"""

import os, json, httpx
from pathlib import Path
from dotenv import load_dotenv

# ── Load env and config ───────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_ROOT = _HERE.parent  # /AGENT root

# Load env: prefer AGENT root .env, fallback to odin-core/.env
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_HERE / ".env", override=False)

# Config lives in /AGENT/config.json (root), with odin-core/config.json as fallback
_CONFIG_PATH = _ROOT / "config.json"
if not _CONFIG_PATH.exists():
    _CONFIG_PATH = _HERE / "odin_config.json"

with open(_CONFIG_PATH) as f:
    CONFIG = json.load(f)

PROVIDERS = CONFIG["providers"]

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def get_provider(role: str = "brain") -> dict:
    """Get provider config for a role: brain | reasoning | fallback"""
    key = {
        "brain":     CONFIG.get("ACTIVE_BRAIN", "ollama"),
        "reasoning": CONFIG.get("ACTIVE_REASONING", "gemini"),
        "fallback":  CONFIG.get("ACTIVE_FALLBACK", "ollama"),
    }.get(role, "ollama")
    p = PROVIDERS.get(key, PROVIDERS["ollama"]).copy()
    p["_name"] = key
    return p

def resolve(p: dict) -> dict:
    """Resolve env var references in provider config"""
    out = {}
    for k, v in p.items():
        if isinstance(v, str) and v.endswith("_env"):
            pass
        elif k.endswith("_env"):
            field = k.replace("_env", "")
            out[field] = _env(v)
        else:
            out[k] = v
    return out

# ── Callers per provider type ─────────────────────────────────────────────────

async def _call_openai_compat(p: dict, messages: list, tools: list = None, model: str = None) -> str:
    base_url = p.get("base_url", _env(p.get("base_url_env", ""), "http://localhost:11434/v1"))
    api_key  = _env(p.get("api_key_env", ""), "no-key")
    model    = model or _env(p.get("default_model_env", ""), p.get("default_model", ""))

    payload = {"model": model, "messages": messages, "max_tokens": 4096}
    if tools and p.get("supports_tools"):
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload
        )
        r.raise_for_status()
        data = r.json()

    choice = data["choices"][0]["message"]
    # Return full message dict so caller can detect tool_calls
    return choice

async def _call_gemini(p: dict, messages: list, tools: list = None, model: str = None) -> dict:
    api_key = _env(p.get("api_key_env", "GEMINI_API_KEY"))
    model   = model or p.get("default_model", "gemini-2.5-flash")
    base    = p.get("base_url", "https://generativelanguage.googleapis.com/v1beta")
    url     = f"{base}/models/{model}:generateContent?key={api_key}"

    # Convert OpenAI-style messages to Gemini format
    contents = []
    system_text = None
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        elif m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})
        elif m["role"] == "tool":
            contents.append({"role": "user", "parts": [{"text": f"[tool result] {m['content']}"}]})

    payload = {"contents": contents}
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text}]}

    # Gemini tool format
    if tools and p.get("supports_tools"):
        fn_decls = []
        for t in tools:
            if t.get("type") == "function":
                fn_decls.append(t["function"])
        if fn_decls:
            payload["tools"] = [{"function_declarations": fn_decls}]

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(url, json=payload)
        r.raise_for_status()
        data = r.json()

    candidate = data["candidates"][0]["content"]
    # Check for function calls
    for part in candidate.get("parts", []):
        if "functionCall" in part:
            fc = part["functionCall"]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"gemini_{fc['name']}",
                    "type": "function",
                    "function": {
                        "name": fc["name"],
                        "arguments": json.dumps(fc.get("args", {}))
                    }
                }]
            }

    text = "".join(p.get("text", "") for p in candidate.get("parts", []) if "text" in p)
    return {"role": "assistant", "content": text}

async def _call_bedrock(p: dict, messages: list, tools: list = None, model: str = None) -> dict:
    try:
        import boto3
    except ImportError:
        return {"role": "assistant", "content": "ERROR: boto3 not installed. Run: pip install boto3"}

    model = model or p.get("default_model", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    region = _env(p.get("region_env", "AWS_REGION"), "us-east-1")

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        aws_access_key_id=_env(p.get("access_key_env", "AWS_ACCESS_KEY_ID")),
        aws_secret_access_key=_env(p.get("secret_key_env", "AWS_SECRET_ACCESS_KEY"))
    )

    system_text = next((m["content"] for m in messages if m["role"] == "system"), "You are ODIN.")
    msgs = [m for m in messages if m["role"] != "system"]

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": system_text,
        "messages": msgs
    }
    if tools and p.get("supports_tools"):
        body["tools"] = [{"name": t["function"]["name"],
                          "description": t["function"].get("description", ""),
                          "input_schema": t["function"].get("parameters", {})} for t in tools]

    resp = client.invoke_model(modelId=model, body=json.dumps(body))
    data = json.loads(resp["body"].read())

    if data.get("stop_reason") == "tool_use":
        tool_use = next(b for b in data["content"] if b["type"] == "tool_use")
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_use["id"],
                "type": "function",
                "function": {"name": tool_use["name"], "arguments": json.dumps(tool_use["input"])}
            }]
        }

    text = next((b["text"] for b in data["content"] if b["type"] == "text"), "")
    return {"role": "assistant", "content": text}

# ── Main public function ──────────────────────────────────────────────────────

async def chat(
    messages: list,
    role: str = "brain",
    tools: list = None,
    model: str = None,
    provider_override: str = None
) -> dict:
    """
    Send messages to the configured provider for this role.
    Returns OpenAI-style message dict: {role, content} or {role, content, tool_calls}

    Args:
        messages: list of {role, content} dicts
        role: "brain" | "reasoning" | "fallback"
        tools: optional list of OpenAI-format tool defs
        model: override model name
        provider_override: force a specific provider key
    """
    p = PROVIDERS.get(provider_override) if provider_override else get_provider(role)
    p = resolve(p)
    ptype = p.get("type", "openai_compat")

    try:
        if ptype == "gemini":
            return await _call_gemini(p, messages, tools, model)
        elif ptype == "bedrock":
            return await _call_bedrock(p, messages, tools, model)
        else:
            return await _call_openai_compat(p, messages, tools, model)
    except Exception as e:
        # Auto-fallback
        if role != "fallback":
            print(f"[router] {p.get('_name', role)} failed ({e}), falling back...")
            return await chat(messages, role="fallback", tools=tools, model=None)
        return {"role": "assistant", "content": f"ERROR: all providers failed — {e}"}

def list_providers() -> dict:
    """Show all configured providers and their status"""
    out = {}
    for name, p in PROVIDERS.items():
        key_env = p.get("api_key_env", "")
        has_key = bool(_env(key_env)) if key_env else p.get("local", False)
        out[name] = {
            "type": p.get("type"),
            "model": p.get("default_model", ""),
            "tools": p.get("supports_tools", False),
            "local": p.get("local", False),
            "ready": has_key
        }
    return out


# ── Router class (used by engine.py via get_router()) ─────────────────────────

class OdinRouter:
    """
    Thin wrapper around the module-level chat() and list_providers() functions.
    engine.py calls: router.chat(role, messages, stream=True)
    """

    def __init__(self):
        self._assignments: dict = {}  # role -> {"provider": ..., "model": ...}

    def get_assignments(self) -> dict:
        return self._assignments

    def assign_role(self, role: str, provider: str, model: str):
        self._assignments[role] = {"provider": provider, "model": model}

    async def chat(
        self,
        role: str,
        messages: list,
        stream: bool = False,
        tools: list = None,
    ):
        """
        Call the appropriate provider for a role.
        Yields text chunks (engine uses `async for chunk in router.chat(...)`).
        """
        override = self._assignments.get(role, {})
        provider_name = override.get("provider") or None
        model_override = override.get("model") or None

        result = await chat(
            messages,
            role=role,
            tools=tools,
            model=model_override,
            provider_override=provider_name,
        )
        content = result.get("content", "") or ""
        # Simulate streaming: yield the full content as one chunk
        yield content


_router_instance = None


def get_router() -> OdinRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = OdinRouter()
    return _router_instance

if __name__ == "__main__":
    import asyncio
    print("ODIN Provider Status:")
    print(json.dumps(list_providers(), indent=2))

    async def test():
        msgs = [
            {"role": "system", "content": "You are ODIN. Be brief."},
            {"role": "user", "content": "Say: ODIN router online."}
        ]
        print("\n[brain test]")
        r = await chat(msgs, role="brain")
        print(r.get("content", r))

        print("\n[reasoning test]")
        r = await chat(msgs, role="reasoning")
        print(r.get("content", r))

    asyncio.run(test())
