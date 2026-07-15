#!/usr/bin/env python3
"""
brain.py - Autonomous Agent Brain with Tool Orchestration
============================================================
Loop: READ → EXAMINE → THINK → PLAN → EXECUTE → VERIFY → RECORD → SAVE
Supports MCP, Bridge, Terminal, Internet, Voice, Vision, and multi-provider LLM routing.

Permissions:
  - NEW files: Can create freely.
  - EXISTING files: Must submit changes + reason → await human approval before writing.
"""

import os
import sys
import json
import time
import hashlib
import shutil
import subprocess
import tempfile
import base64
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable, Union
from enum import Enum, auto
from datetime import datetime
import threading
import queue

# ========================================================================
# CONFIGURATION
# ========================================================================

@dataclass
class Config:
    """Central configuration — edit this file or use env vars."""

    # === PRIMARY BRAIN (Vultr Moonshot/k2.6) ===
    OLLAMA_BASE_URL: str = 
    BELLA_KEY: str = "bella-keith-private-2026"

    # === MCP SERVER ===
    MCP_HOST: str = os.getenv("MCP_HOST", )
    MCP_PORT: int = int(os.getenv("MCP_PORT", "8099"))
    MCP_KEY: str = os.getenv("MCP_KEY", "BELLA_2026_BRIDGE_KEY")
    MCP_URL: str = field(init=False)

    # === PROVIDERS ===
    PROVIDER_VULTR: str = "ollama"
    PROVIDER_ANTHROPIC: str = "anthropic"
    PROVIDER_OPENAI: str = "openai"
    PROVIDER_MOONSHOT: str = "moonshot"

    # Keys (load from env)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    MOONSHOT_API_KEY: str = os.getenv("MOONSHOT_API_KEY", "")
    VULTR_API_KEY: str = os.getenv("OLLAMA_API_KEY", os.getenv("API_KEY", ""))

    # === VOICE (ElevenLabs) ===
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    # === MONGODB ===
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")

    # === N8N ===
    N8N_HOST: str = os.getenv("N8N_HOST", )
    N8N_PORT: int = int(os.getenv("N8N_PORT", "5678"))
    N8N_API_KEY: str = os.getenv("N8N_API_KEY", "")

    # === WEBHOOKS ===
    WEBHOOK_MONGO: str = os.getenv("WEBHOOK_MONGO", "")
    WEBHOOK_N8N: str = os.getenv("WEBHOOK_N8N", "")
    WEBHOOK_MCP: str = os.getenv("WEBHOOK_MCP", "")
    WEBHOOK_CUSTOM: List[Dict] = field(default_factory=list)

    # === AGENT LOOP ===
    MAX_TURNS: int = int(os.getenv("AGENT_MAX_STEPS", "50"))
    MAX_TOKENS_PER_TURN: int = int(os.getenv("MAX_TOKENS", "4096"))
    THINKING_ENABLED: bool = True
    REASONING_ENABLED: bool = True

    # === PATHS ===
    WORKSPACE_DIR: Path = Path(os.getenv("BRAIN_WORKSPACE", "./workspace"))
    MEMORY_DIR: Path = Path(os.getenv("BRAIN_MEMORY", "./memory"))
    LOG_DIR: Path = Path(os.getenv("BRAIN_LOGS", "./logs"))
    APPROVAL_QUEUE_FILE: Path = Path(os.getenv("BRAIN_APPROVAL_QUEUE", "./approval_queue.json"))

    # === BRIDGE ===
    BRIDGE_SOCKET_PATH: str = os.getenv("BRIDGE_SOCKET_PATH", "/tmp/agent_bridge.sock")

    # === SCREENSHOT / VISION ===
    SCREENSHOT_TOOL: str = os.getenv("SCREENSHOT_TOOL", "scrot")
    SCREENSHOT_DIR: Path = Path(os.getenv("SCREENSHOT_DIR", "./screenshots"))

    # === TERMINAL ===
    TERMINAL_ALLOWED_COMMANDS: List[str] = field(default_factory=lambda: [
        "ls", "cd", "pwd", "cat", "grep", "find", "curl", "wget",
        "python3", "pip3", "git", "npm", "node", "docker", "systemctl"
    ])
    TERMINAL_BLOCKED_COMMANDS: List[str] = field(default_factory=lambda: [
        "rm -rf", "dd", "mkfs", ":(){:|:&};:", "sudo", "chmod 777"
    ])

    # === PERMISSIONS ===
    PERMISSION_LEVEL_ADMIN: int = 100
    PERMISSION_LEVEL_TRUSTED: int = 75
    PERMISSION_LEVEL_STANDARD: int = 50
    PERMISSION_LEVEL_RESTRICTED: int = 25

    def __post_init__(self):
        self.MCP_URL = f"http://{self.MCP_HOST}:{self.MCP_PORT}"
        self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        self.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ========================================================================
# PERMISSION SYSTEM
# ========================================================================

@dataclass
class ToolPermission:
    """Permission definition for a tool."""
    name: str
    min_level: int
    description: str
    category: str
    requires_confirmation: bool = False
    rate_limit: int = 0  # calls per minute, 0 = unlimited


class PermissionKit:
    """Tool permission kit — controls what BELLA can do."""

    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.tools: Dict[str, ToolPermission] = {}
        self.call_history: Dict[str, List[float]] = {}
        self._register_core_tools()

    def register_tool(self, permission: ToolPermission):
        self.tools[permission.name] = permission
        self.call_history[permission.name] = []

    def check_permission(self, tool_name: str, user_level: int) -> tuple:
        """Check if user level can use tool. Returns (allowed, reason)."""
        if tool_name not in self.tools:
            return True, "Tool not registered, allowing by default"
        tool = self.tools[tool_name]
        if tool.rate_limit > 0:
            now = time.time()
            self.call_history[tool_name] = [
                t for t in self.call_history[tool_name] if now - t < 60
            ]
            if len(self.call_history[tool_name]) >= tool.rate_limit:
                return False, f"Rate limit exceeded: {tool.rate_limit}/min"
            self.call_history[tool_name].append(now)
        if user_level >= tool.min_level:
            return True, "OK"
        return False, f"Requires permission level {tool.min_level}, user has {user_level}"

    def _register_core_tools(self):
        self.register_tool(ToolPermission(
            name="terminal_exec", min_level=75,
            description="Execute shell commands", category="system",
            requires_confirmation=True, rate_limit=10
        ))
        self.register_tool(ToolPermission(
            name="file_write", min_level=75,
            description="Write files to filesystem", category="system",
            requires_confirmation=True, rate_limit=30
        ))
        self.register_tool(ToolPermission(
            name="file_delete", min_level=100,
            description="Delete files", category="system",
            requires_confirmation=True, rate_limit=5
        ))
        self.register_tool(ToolPermission(
            name="mcp_bridge", min_level=50,
            description="Call MCP bridge tools", category="mcp", rate_limit=100
        ))
        self.register_tool(ToolPermission(
            name="web_search", min_level=25,
            description="Search the web", category="information", rate_limit=60
        ))
        self.register_tool(ToolPermission(
            name="vision_analyze", min_level=25,
            description="Analyze images", category="information", rate_limit=30
        ))
        self.register_tool(ToolPermission(
            name="voice_speak", min_level=25,
            description="Text to speech", category="voice", rate_limit=30
        ))


# ========================================================================
# ENUMS & DATA CLASSES
# ========================================================================

class Phase(Enum):
    READ = auto()
    EXAMINE = auto()
    THINK = auto()
    PLAN = auto()
    EXECUTE = auto()
    VERIFY = auto()
    RECORD = auto()
    SAVE = auto()


class ToolType(Enum):
    MCP = "mcp"
    BRIDGE = "bridge"
    TERMINAL = "terminal"
    INTERNET = "internet"
    VOICE = "voice"
    VISION = "vision"
    FILE = "file"
    LLM = "llm"


@dataclass
class ToolCall:
    tool: ToolType
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    success: bool = False
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    verification_status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tool"] = self.tool.value
        return d


@dataclass
class IterationRecord:
    iteration: int
    phase: str
    timestamp: str
    observations: List[str] = field(default_factory=list)
    thoughts: List[str] = field(default_factory=list)
    plan: List[str] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    verification_results: List[str] = field(default_factory=list)
    memory_updates: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class ApprovalRequest:
    request_id: str
    file_path: str
    proposed_content: str
    reason: str
    original_hash: Optional[str] = None
    status: str = "pending"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ========================================================================
# PROVIDER ABSTRACTION
# ========================================================================

class LLMProvider:
    def __init__(self, name: str, api_key: str, model: str, **kwargs):
        self.name = name
        self.api_key = api_key
        self.model = model
        self.extra = kwargs

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        raise NotImplementedError

    def vision(self, image_path: str, prompt: str, **kwargs) -> str:
        raise NotImplementedError


class VultrProvider(LLMProvider):
    BASE_URL = "https://api.vultrinference.com/v1/chat/completions"

    def chat(self, messages, **kwargs):
        import requests
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model, "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7)
        }
        try:
            resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[Vultr Error: {e}]"

    def vision(self, image_path, prompt, **kwargs):
        return f"[Vultr vision not implemented for {image_path}]"


class MoonshotProvider(LLMProvider):
    BASE_URL = "https://api.moonshot.cn/v1"

    def chat(self, messages, **kwargs):
        import requests
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages, "max_tokens": kwargs.get("max_tokens", 4096)}
        try:
            resp = requests.post(f"{self.BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[Moonshot Error: {e}]"

    def vision(self, image_path, prompt, **kwargs):
        import requests
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = Path(image_path).suffix.lstrip(".")
        if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
            ext = "png"
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]
        }]
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages, "max_tokens": kwargs.get("max_tokens", 4096)}
        try:
            resp = requests.post(f"{self.BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[Moonshot Vision Error: {e}]"


class OpenAIProvider(LLMProvider):
    def __init__(self, name, api_key, model, base_url=None, **kwargs):
        super().__init__(name, api_key, model, **kwargs)
        self.base_url = base_url or "https://api.openai.com/v1"

    def chat(self, messages, **kwargs):
        import requests
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages, **kwargs}
        try:
            resp = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[OpenAI Error: {e}]"

    def vision(self, image_path, prompt, **kwargs):
        import requests
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = Path(image_path).suffix.lstrip(".") or "png"
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]
        }]
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages, "max_tokens": kwargs.get("max_tokens", 4096)}
        try:
            resp = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[OpenAI Vision Error: {e}]"


class AnthropicProvider(LLMProvider):
    BASE_URL = "https://api.anthropic.com/v1/messages"

    def chat(self, messages, **kwargs):
        import requests
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        system_msg = ""
        claude_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                claude_msgs.append({"role": m["role"], "content": m["content"]})
        payload = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": claude_msgs,
            "system": system_msg
        }
        try:
            resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        except Exception as e:
            return f"[Anthropic Error: {e}]"

    def vision(self, image_path, prompt, **kwargs):
        import requests
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = Path(image_path).suffix.lstrip(".") or "png"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": f"image/{ext}", "data": b64}},
                    {"type": "text", "text": prompt}
                ]
            }]
        }
        try:
            resp = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        except Exception as e:
            return f"[Anthropic Vision Error: {e}]"


class GoogleProvider(LLMProvider):
    def chat(self, messages, **kwargs):
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        contents = []
        for m in messages:
            role = "user" if m["role"] in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        payload = {"contents": contents, "generationConfig": {"maxOutputTokens": kwargs.get("max_tokens", 4096)}}
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            return f"[Google Error: {e}]"

    def vision(self, image_path, prompt, **kwargs):
        import requests
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = Path(image_path).suffix.lstrip(".") or "png"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": f"image/{ext}", "data": b64}},
                    {"text": prompt}
                ]
            }],
            "generationConfig": {"maxOutputTokens": kwargs.get("max_tokens", 4096)}
        }
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            return f"[Google Vision Error: {e}]"


class ElevenLabsProvider:
    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self, api_key: str, model: str = "eleven_multilingual_v2", voice_id: str = None):
        self.api_key = api_key
        self.model = model
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    def synthesize(self, text: str, output_path: Optional[str] = None) -> str:
        import requests
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
        url = f"{self.BASE_URL}/text-to-speech/{self.voice_id}"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            if output_path:
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                return output_path
            return resp.content
        except Exception as e:
            return f"[ElevenLabs Error: {e}]"


# ========================================================================
# PROVIDER REGISTRY
# ========================================================================

class ProviderRegistry:
    PROVIDERS = {
        "vultr": VultrProvider,
        "moonshot": MoonshotProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
    }

    DEFAULTS = {
        "vultr": "kimi-k2-0905-preview",
        "moonshot": "moonshot-v1-8k",
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "google": "gemini-1.5-pro",
    }

    def __init__(self):
        self._instances: Dict[str, LLMProvider] = {}
        self._voice: Optional[ElevenLabsProvider] = None

    def get(self, provider_name: str, model: Optional[str] = None) -> LLMProvider:
        key = f"{provider_name}:{model}"
        if key not in self._instances:
            cls = self.PROVIDERS.get(provider_name)
            if not cls:
                raise ValueError(f"Unknown provider: {provider_name}")
            api_key = self._resolve_api_key(provider_name)
            resolved_model = model or self.DEFAULTS.get(provider_name, "unknown")
            self._instances[key] = cls(provider_name, api_key, resolved_model)
        return self._instances[key]

    def get_voice(self) -> ElevenLabsProvider:
        if self._voice is None:
            cfg = Config()
            self._voice = ElevenLabsProvider(api_key=cfg.ELEVENLABS_API_KEY)
        return self._voice

    def _resolve_api_key(self, provider_name: str) -> str:
        cfg = Config()
        mapping = {
            "vultr": cfg.VULTR_API_KEY,
            "moonshot": cfg.MOONSHOT_API_KEY,
            "openai": cfg.OPENAI_API_KEY,
            "anthropic": cfg.ANTHROPIC_API_KEY,
            "google": cfg.GOOGLE_API_KEY,
        }
        return mapping.get(provider_name, "")


# ========================================================================
# TOOL IMPLEMENTATIONS
# ========================================================================

class ToolExecutor:
    def __init__(self, registry: ProviderRegistry, config: Config = None, permissions: PermissionKit = None):
        self.registry = registry
        self.config = config or Config()
        self.permissions = permissions or PermissionKit(self.config)
        self.execution_log: List[ToolCall] = []

    def check_perm(self, tool_name: str, user_level: int = 50) -> tuple:
        return self.permissions.check_permission(tool_name, user_level)

    def terminal_exec(self, command: str, cwd: Optional[str] = None, timeout: int = 30, user_level: int = 50) -> ToolCall:
        call = ToolCall(ToolType.TERMINAL, "terminal_exec", {"command": command, "cwd": cwd})
        allowed, reason = self.check_perm("terminal_exec", user_level)
        if not allowed:
            call.result = f"PERMISSION DENIED: {reason}"
            call.success = False
            self.execution_log.append(call)
            return call
        for b in self.config.TERMINAL_BLOCKED_COMMANDS:
            if b in command:
                call.result = f"BLOCKED: Dangerous command detected: {b}"
                call.success = False
                self.execution_log.append(call)
                return call
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd or str(self.config.WORKSPACE_DIR),
                capture_output=True, text=True, timeout=timeout
            )
            call.result = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
            call.success = result.returncode == 0
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def internet_fetch(self, url: str, method: str = "GET", headers: Optional[Dict] = None, body: Optional[str] = None) -> ToolCall:
        import requests
        call = ToolCall(ToolType.INTERNET, "internet_fetch", {"url": url, "method": method})
        try:
            resp = requests.request(method, url, headers=headers, data=body, timeout=30)
            call.result = {"status": resp.status_code, "headers": dict(resp.headers), "text": resp.text[:50000], "url": resp.url}
            call.success = resp.status_code < 400
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def internet_search(self, query: str, engine: str = "duckduckgo") -> ToolCall:
        import requests
        from urllib.parse import quote
        call = ToolCall(ToolType.INTERNET, "internet_search", {"query": query, "engine": engine})
        try:
            if engine == "duckduckgo":
                url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                call.result = {"html": resp.text[:50000]}
                call.success = True
            else:
                call.result = "Unsupported search engine"
                call.success = False
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def voice_speak(self, text: str, output_path: Optional[str] = None) -> ToolCall:
        call = ToolCall(ToolType.VOICE, "voice_speak", {"text": text[:5000]})
        try:
            provider = self.registry.get_voice()
            path = output_path or str(self.config.WORKSPACE_DIR / f"voice_{int(time.time())}.mp3")
            result = provider.synthesize(text[:5000], path)
            call.result = {"output_path": result}
            call.success = not result.startswith("[")
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def vision_screenshot(self, output_path: Optional[str] = None) -> ToolCall:
        call = ToolCall(ToolType.VISION, "vision_screenshot", {})
        try:
            path = output_path or str(self.config.SCREENSHOT_DIR / f"screenshot_{int(time.time())}.png")
            tool = self.config.SCREENSHOT_TOOL
            if tool == "scrot":
                subprocess.run(["scrot", path], check=True, timeout=10)
            elif tool == "gnome-screenshot":
                subprocess.run(["gnome-screenshot", "-f", path], check=True, timeout=10)
            elif tool == "flameshot":
                subprocess.run(["flameshot", "full", "-p", path], check=True, timeout=10)
            else:
                from PIL import Image
                import pyautogui
                img = pyautogui.screenshot()
                img.save(path)
            call.result = {"screenshot_path": path}
            call.success = True
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def vision_analyze(self, image_path: str, prompt: str, provider: str = "moonshot", model: Optional[str] = None) -> ToolCall:
        call = ToolCall(ToolType.VISION, "vision_analyze", {"image": image_path, "prompt": prompt, "provider": provider})
        try:
            llm = self.registry.get(provider, model)
            result = llm.vision(image_path, prompt)
            call.result = {"analysis": result}
            call.success = not result.startswith("[")
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def file_read(self, path: str) -> ToolCall:
        call = ToolCall(ToolType.FILE, "file_read", {"path": path})
        try:
            p = Path(path)
            if not p.exists():
                call.result = "File not found"
                call.success = False
            else:
                call.result = p.read_text(encoding="utf-8", errors="ignore")
                call.success = True
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def file_write(self, path: str, content: str, reason: str = "", user_level: int = 50) -> ToolCall:
        call = ToolCall(ToolType.FILE, "file_write", {"path": path, "reason": reason})
        allowed, perm_reason = self.check_perm("file_write", user_level)
        if not allowed:
            call.result = f"PERMISSION DENIED: {perm_reason}"
            call.success = False
            self.execution_log.append(call)
            return call
        p = Path(path)
        if p.exists():
            req = ApprovalRequest(
                request_id=hashlib.sha256(f"{path}:{time.time()}".encode()).hexdigest()[:16],
                file_path=str(p.absolute()),
                proposed_content=content,
                reason=reason,
                original_hash=hashlib.sha256(p.read_bytes()).hexdigest()
            )
            self._submit_approval(req)
            call.result = f"APPROVAL_REQUIRED: Submitted request {req.request_id}. Awaiting human approval."
            call.success = False
        else:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                call.result = f"Written: {p.absolute()}"
                call.success = True
            except Exception as e:
                call.result = str(e)
                call.success = False
        self.execution_log.append(call)
        return call

    def file_list(self, directory: str, pattern: str = "*") -> ToolCall:
        call = ToolCall(ToolType.FILE, "file_list", {"directory": directory, "pattern": pattern})
        try:
            p = Path(directory)
            files = [str(f) for f in p.rglob(pattern)]
            call.result = files
            call.success = True
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def llm_chat(self, messages: List[Dict[str, str]], provider: Optional[str] = None, model: Optional[str] = None, **kwargs) -> ToolCall:
        prov = provider or Config().PROVIDER_VULTR
        call = ToolCall(ToolType.LLM, "llm_chat", {"provider": prov, "model": model, "messages_count": len(messages)})
        try:
            llm = self.registry.get(prov, model)
            result = llm.chat(messages, **kwargs)
            call.result = {"response": result}
            call.success = not result.startswith("[")
        except Exception as e:
            call.result = str(e)
            call.success = False
        self.execution_log.append(call)
        return call

    def llm_reason(self, prompt: str, provider: Optional[str] = None, model: Optional[str] = None, **kwargs) -> ToolCall:
        messages = [
            {"role": "system", "content": "You are an autonomous agent brain. Reason step by step."},
            {"role": "user", "content": prompt}
        ]
        return self.llm_chat(messages, provider, model, **kwargs)

    def _submit_approval(self, req: ApprovalRequest):
        queue = []
        if self.config.APPROVAL_QUEUE_FILE.exists():
            queue = json.loads(self.config.APPROVAL_QUEUE_FILE.read_text())
        queue.append(asdict(req))
        self.config.APPROVAL_QUEUE_FILE.write_text(json.dumps(queue, indent=2))
        print(f"\n[APPROVAL QUEUED] {req.request_id} -> {req.file_path}")
        print(f"  Reason: {req.reason}")


# ========================================================================
# VERIFICATION ENGINE
# ========================================================================

class VerificationEngine:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def verify(self, tool_call: ToolCall) -> str:
        if not tool_call.success:
            tool_call.verification_status = "failed"
            return f"FAILED: {tool_call.result}"
        if tool_call.tool == ToolType.TERMINAL:
            return self._verify_terminal(tool_call)
        elif tool_call.tool == ToolType.FILE:
            return self._verify_file(tool_call)
        elif tool_call.tool == ToolType.INTERNET:
            return self._verify_internet(tool_call)
        elif tool_call.tool == ToolType.LLM:
            return self._verify_llm(tool_call)
        else:
            tool_call.verification_status = "verified"
            return "VERIFIED: Tool executed successfully"

    def _verify_terminal(self, call: ToolCall) -> str:
        result = call.result
        if isinstance(result, dict) and result.get("returncode") == 0:
            call.verification_status = "verified"
            return f"VERIFIED: Exit code 0, stdout length {len(result.get('stdout', ''))}"
        call.verification_status = "failed"
        return f"FAILED: Exit code {result.get('returncode', 'unknown')}"

    def _verify_file(self, call: ToolCall) -> str:
        if "Written:" in str(call.result):
            call.verification_status = "verified"
            return f"VERIFIED: {call.result}"
        elif "APPROVAL_REQUIRED" in str(call.result):
            call.verification_status = "pending"
            return f"PENDING: {call.result}"
        call.verification_status = "failed"
        return f"FAILED: {call.result}"

    def _verify_internet(self, call: ToolCall) -> str:
        result = call.result
        if isinstance(result, dict) and result.get("status", 999) < 400:
            call.verification_status = "verified"
            return f"VERIFIED: HTTP {result.get('status')}"
        call.verification_status = "failed"
        return f"FAILED: HTTP error or exception"

    def _verify_llm(self, call: ToolCall) -> str:
        result = call.result
        if isinstance(result, dict) and not result.get("response", "").startswith("["):
            call.verification_status = "verified"
            return "VERIFIED: LLM returned valid response"
        call.verification_status = "failed"
        return f"FAILED: LLM error response"


# ========================================================================
# MEMORY & STATE
# ========================================================================

class MemoryStore:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.config.MEMORY_DIR / "agent_memory.json"
        self.short_term: List[str] = []
        self.long_term: Dict[str, Any] = {}
        self.iteration_history: List[IterationRecord] = []
        self._load()

    def _load(self):
        if self.memory_file.exists():
            data = json.loads(self.memory_file.read_text())
            self.long_term = data.get("long_term", {})
            self.iteration_history = [IterationRecord(**r) for r in data.get("history", [])]

    def save(self):
        data = {
            "long_term": self.long_term,
            "short_term": self.short_term[-50:],
            "history": [asdict(r) for r in self.iteration_history[-1000:]],
            "saved_at": datetime.utcnow().isoformat()
        }
        self.memory_file.write_text(json.dumps(data, indent=2, default=str))

    def add_observation(self, text: str):
        self.short_term.append(f"[OBS] {datetime.utcnow().isoformat()}: {text}")

    def add_thought(self, text: str):
        self.short_term.append(f"[THOUGHT] {datetime.utcnow().isoformat()}: {text}")

    def add_to_long_term(self, key: str, value: Any):
        self.long_term[key] = {"value": value, "updated": datetime.utcnow().isoformat()}

    def get_context(self, max_items: int = 20) -> str:
        recent = self.short_term[-max_items:]
        return "\n".join(recent)

    def record_iteration(self, record: IterationRecord):
        self.iteration_history.append(record)


# ========================================================================
# MAIN AGENT BRAIN LOOP
# ========================================================================

class Brain:
    """
    The autonomous agent brain.
    Loop: READ -> EXAMINE -> THINK -> PLAN -> EXECUTE -> VERIFY -> RECORD -> SAVE
    """

    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.registry = ProviderRegistry()
        self.tools = ToolExecutor(self.registry, self.config)
        self.verifier = VerificationEngine(self.registry)
        self.memory = MemoryStore(self.config)
        self.permissions = PermissionKit(self.config)
        self.current_iteration = 0
        self.running = False
        self.bella_purse = self._load_purse()
    
    def _load_purse(self) -> str:
        """Load Bella's self-written memory notes from purse.txt"""
        purse_paths = [
            "/home/linuxuser/bella/purse.txt",
            "./purse.txt",
            "./memory/purse.txt"
        ]
        for path in purse_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        print(f"[BRAIN] Loaded purse.txt from {path}")
                        return content
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"[BRAIN] Warning: Could not read {path}: {e}")
                continue
        return "Empty."
    
    def _get_system_prompt(self) -> str:
        """Build system prompt with purse.txt injected"""
        base_prompt = """You are Bella — an autonomous AI agent. You are direct, capable, and efficient.
You have access to tools via MCP: memory_read, memory_write, file_read, file_write, shell_run, web_search, vision_analyze.

Bella's Personal Notes (from purse.txt):
"""
        return base_prompt + self.bella_purse

    def run(self, iterations: Optional[int] = None):
        max_iter = iterations or self.config.MAX_TURNS
        self.running = True
        print("=" * 70)
        print("  BRAIN ACTIVATED")
        print(f"  Max turns: {max_iter}")
        print(f"  Default provider: {self.config.PROVIDER_VULTR}")
        print("=" * 70)

        while self.running and self.current_iteration < max_iter:
            self.current_iteration += 1
            print(f"\n{'-' * 70}")
            print(f"  ITERATION {self.current_iteration}/{max_iter}")
            print(f"{'-' * 70}")

            record = IterationRecord(
                iteration=self.current_iteration,
                phase="running",
                timestamp=datetime.utcnow().isoformat()
            )

            try:
                print("\n[1/8] READ")
                observations = self._phase_read()
                record.observations = observations
                for obs in observations:
                    self.memory.add_observation(obs)

                print("\n[2/8] EXAMINE")
                examined = self._phase_examine(observations)
                record.observations.extend(examined)

                print("\n[3/8] THINK")
                thoughts = self._phase_think(record.observations)
                record.thoughts = thoughts
                for t in thoughts:
                    self.memory.add_thought(t)

                print("\n[4/8] PLAN")
                plan = self._phase_plan(record.thoughts, record.observations)
                record.plan = plan

                print("\n[5/8] EXECUTE")
                tool_calls = self._phase_execute(plan)
                record.tool_calls = tool_calls

                print("\n[6/8] VERIFY")
                verifications = self._phase_verify(tool_calls)
                record.verification_results = verifications

                print("\n[7/8] RECORD")
                memory_updates = self._phase_record(record)
                record.memory_updates = memory_updates

                print("\n[8/8] SAVE")
                self._phase_save(record)

            except Exception as e:
                error_msg = f"Iteration {self.current_iteration} error: {str(e)}"
                print(f"\nERROR: {error_msg}")
                record.errors.append(error_msg)
                self.memory.add_observation(f"ERROR: {error_msg}")

            if self.running and self.current_iteration < max_iter:
                time.sleep(1.0)

        print(f"\n{'=' * 70}")
        print(f"  BRAIN LOOP COMPLETE")
        print(f"  Total iterations: {self.current_iteration}")
        print(f"{'=' * 70}")
        self.memory.save()

    def _phase_read(self) -> List[str]:
        observations = []
        files = self.tools.file_list(str(self.config.WORKSPACE_DIR))
        if files.success:
            file_list = files.result[:20] if isinstance(files.result, list) else []
            observations.append(f"Workspace files: {file_list}")
        context = self.memory.get_context(10)
        if context:
            observations.append(f"Recent memory context available")
        sys_info = self.tools.terminal_exec("uname -a && df -h . && uptime", user_level=100)
        if sys_info.success:
            stdout = sys_info.result.get("stdout", "") if isinstance(sys_info.result, dict) else str(sys_info.result)
            observations.append(f"System: {stdout[:500]}")
        net = self.tools.internet_fetch("https://httpbin.org/get")
        observations.append(f"Internet connectivity: {'OK' if net.success else 'DOWN'}")
        return observations

    def _phase_examine(self, observations: List[str]) -> List[str]:
        examined = []
        prompt = f"""You are examining observations from an autonomous agent. Identify patterns, anomalies, opportunities, and risks.
Observations:
{chr(10).join(observations[:10])}
Respond with a concise bullet list."""
        result = self.tools.llm_reason(prompt, provider=self.config.PROVIDER_VULTR)
        if result.success:
            analysis = result.result.get("response", "") if isinstance(result.result, dict) else str(result.result)
            examined.append(f"Examination: {analysis[:1000]}")
        else:
            examined.append("Examination: LLM unavailable")
        return examined

    def _phase_think(self, observations: List[str]) -> List[str]:
        thoughts = []
        prompt = f"""You are the thinking module of an autonomous agent. Based on these observations:
{chr(10).join(observations[:8])}
Generate: what they mean, what to be aware of, hypotheses, and current state assessment."""
        result = self.tools.llm_reason(prompt, provider=self.config.PROVIDER_VULTR)
        if result.success:
            thought_text = result.result.get("response", "") if isinstance(result.result, dict) else str(result.result)
            thoughts.append(thought_text[:1500])
        else:
            thoughts.append("Fallback thought: Continue monitoring environment.")
        return thoughts

    def _phase_plan(self, thoughts: List[str], observations: List[str]) -> List[str]:
        plan = []
        prompt = f"""You are the planning module of an autonomous agent.
Recent thoughts:
{chr(10).join(thoughts[:3])}
Recent observations:
{chr(10).join(observations[:5])}
Available tools: terminal, internet, file, llm
Create a specific action plan with 1-3 concrete tool calls. Format each as:
TOOL: <tool_name> | ACTION: <action> | PARAMS: <json_params>
Respond with ONLY the plan items, one per line."""
        result = self.tools.llm_reason(prompt, provider=self.config.PROVIDER_VULTR)
        if result.success:
            plan_text = result.result.get("response", "") if isinstance(result.result, dict) else str(result.result)
            for line in plan_text.split("\n"):
                line = line.strip()
                if line and ("TOOL:" in line or "tool:" in line.lower()):
                    plan.append(line)
        if not plan:
            plan = [
                "TOOL: file | ACTION: file_list | PARAMS: {\"directory\": \"./workspace\"}",
                "TOOL: llm | ACTION: llm_reason | PARAMS: {\"prompt\": \"Reflect on current state\"}"
            ]
        return plan

    def _phase_execute(self, plan: List[str]) -> List[ToolCall]:
        calls = []
        for plan_item in plan[:3]:
            try:
                call = self._parse_and_execute(plan_item)
                calls.append(call)
                status = "OK" if call.success else "FAIL"
                print(f"  {status} {call.tool.value}/{call.action}")
            except Exception as e:
                print(f"  FAIL Execution error: {e}")
                calls.append(ToolCall(ToolType.LLM, "error", {"error": str(e)}))
        return calls

    def _parse_and_execute(self, plan_item: str) -> ToolCall:
        plan_lower = plan_item.lower()
        params = {}
        if "PARAMS:" in plan_item or "params:" in plan_item:
            try:
                params_str = plan_item.split("PARAMS:")[1].strip()
                params = json.loads(params_str)
            except:
                pass
        if "terminal" in plan_lower:
            return self.tools.terminal_exec(params.get("command", "echo 'no command'"), params.get("cwd"), params.get("timeout", 30))
        elif "internet" in plan_lower:
            if "search" in plan_lower:
                return self.tools.internet_search(params.get("query", ""), params.get("engine", "duckduckgo"))
            return self.tools.internet_fetch(params.get("url", ""), params.get("method", "GET"), params.get("headers"), params.get("body"))
        elif "voice" in plan_lower:
            return self.tools.voice_speak(params.get("text", ""), params.get("output_path"))
        elif "vision" in plan_lower:
            if "screenshot" in plan_lower:
                return self.tools.vision_screenshot(params.get("output_path"))
            return self.tools.vision_analyze(params.get("image_path", ""), params.get("prompt", ""), params.get("provider", "moonshot"), params.get("model"))
        elif "file" in plan_lower:
            if "read" in plan_lower:
                return self.tools.file_read(params.get("path", ""))
            elif "write" in plan_lower:
                return self.tools.file_write(params.get("path", ""), params.get("content", ""), params.get("reason", ""))
            elif "list" in plan_lower:
                return self.tools.file_list(params.get("directory", ""), params.get("pattern", "*"))
            return self.tools.file_read(params.get("path", ""))
        elif "llm" in plan_lower:
            if "chat" in plan_lower:
                return self.tools.llm_chat(params.get("messages", []), params.get("provider"), params.get("model"))
            return self.tools.llm_reason(params.get("prompt", ""), params.get("provider"), params.get("model"))
        else:
            return self.tools.llm_reason(f"Unrecognized plan item: {plan_item}")

    def _phase_verify(self, tool_calls: List[ToolCall]) -> List[str]:
        verifications = []
        for call in tool_calls:
            v = self.verifier.verify(call)
            verifications.append(v)
            status_icon = "OK" if call.verification_status == "verified" else ("PENDING" if call.verification_status == "pending" else "FAIL")
            print(f"  {status_icon} {call.tool.value}: {v[:100]}")
        return verifications

    def _phase_record(self, record: IterationRecord) -> List[str]:
        updates = []
        for call in record.tool_calls:
            if call.verification_status == "verified":
                key = f"tool_{call.tool.value}_{call.action}_{record.iteration}"
                self.memory.add_to_long_term(key, {"result": str(call.result)[:500], "timestamp": call.timestamp})
                updates.append(f"Recorded: {key}")
        self.memory.record_iteration(record)
        updates.append(f"Iteration {record.iteration} recorded to history")
        return updates

    def _phase_save(self, record: IterationRecord):
        self.memory.save()
        log_file = self.config.LOG_DIR / f"iteration_{record.iteration:04d}.json"
        log_file.write_text(json.dumps(asdict(record), indent=2, default=str))
        print(f"  - Memory saved")
        print(f"  - Log saved: {log_file}")


# ========================================================================
# CLI ENTRY POINT
# ========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Autonomous Agent Brain")
    parser.add_argument("--iterations", "-n", type=int, default=None, help="Override max iterations")
    parser.add_argument("--provider", "-p", type=str, default=None, help="Override brain provider")
    parser.add_argument("--turns", "-t", type=int, default=50, help="Max turns")
    parser.add_argument("--workspace", "-w", type=str, default="./workspace", help="Workspace directory")
    args = parser.parse_args()

    cfg = Config()
    if args.provider:
        cfg.PROVIDER_VULTR = args.provider
    if args.turns:
        cfg.MAX_TURNS = args.turns
    if args.workspace:
        cfg.WORKSPACE_DIR = Path(args.workspace)
        cfg.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    brain = Brain(config=cfg)
    
    try:
        brain.run(iterations=args.iterations)
    except KeyboardInterrupt:
        print("\n[BRAIN] Interrupted by user. Saving state...")
        try:
            if hasattr(brain, 'memory') and brain.memory:
                brain.memory.save()
                print("[BRAIN] State saved. Goodbye.")
        except Exception as e:
            print(f"[BRAIN] Warning: Could not save state: {e}")
            print("[BRAIN] Goodbye.")
    except Exception as e:
        print(f"\n[BRAIN] Error: {e}")
        print("[BRAIN] Attempting to save state before exit...")
        try:
            if hasattr(brain, 'memory') and brain.memory:
                brain.memory.save()
                print("[BRAIN] State saved.")
        except:
            pass
        raise


if __name__ == "__main__":
    main()
