"""
Bella/JARVIS/ODIN Main Application v2.0
FastAPI server with chat, agent, voice, vision, and MCP tool capabilities
Enhanced with carry-on memory file integration
"""
import os
import json
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
import base64
from datetime import datetime

# Load environment variables
load_dotenv()

# Import custom modules
from providers import ProviderManager
from mcp_client import MCPClient
from agent import ReactAgent
from voice import VoiceManager
from vision import VisionManager

# Import reasoning engine (Claude for deep thinking)
try:
    from reasoning import ReasoningEngine
    reasoning_engine = ReasoningEngine()
    REASONING_AVAILABLE = reasoning_engine.available
except ImportError:
    reasoning_engine = None
    REASONING_AVAILABLE = False

# Import unified memory bridge (new single source of truth)
try:
    from unified_memory import save_turn, get_context_for_session, memory_status
    UNIFIED_MEMORY_AVAILABLE = True
except ImportError:
    UNIFIED_MEMORY_AVAILABLE = False

# Import MongoDB memory core (canonical persistent memory)
MEMORY_CORE_AVAILABLE = False
try:
    import memory_core as memory
    from memory_core import (
        remember_episode, recall_episodes,
        remember_win, write_handoff, get_trust_score, log_emotion
    )
    MEMORY_CORE_AVAILABLE = True
except ImportError:
    memory = None
    # Dummy placeholders so names are always defined; real functions only used when flag is True.
    def remember_episode(*args, **kwargs):
        return None
    def recall_episodes(*args, **kwargs):
        return []
    def remember_win(*args, **kwargs):
        pass
    def write_handoff(*args, **kwargs):
        pass
    def get_trust_score(*args, **kwargs):
        return {"score": 10, "note": "Getting acquainted", "milestones": []}
    def log_emotion(*args, **kwargs):
        pass
    MEMORY_CORE_AVAILABLE = False

# Import MCP tools (Bella's carry-on memory)
MCP_TOOLS_AVAILABLE = False
try:
    from mcp_client import MCPClient
    MCP_TOOLS_AVAILABLE = True
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import Bella's purse (persistent working memory)
try:
    from purse import (
        load_purse, save_purse, get_purse_context,
        purse_add, purse_remove, purse_read, purse_update_section
    )
    PURSE_AVAILABLE = True
    logger.info("👜 Bella's purse loaded")
except ImportError:
    PURSE_AVAILABLE = False
    logger.warning("Purse not available")

# Log memory backend status
if UNIFIED_MEMORY_AVAILABLE:
    logger.info("🔗 Unified memory bridge active")
if MEMORY_CORE_AVAILABLE:
    try:
        db = memory._get_db()  # type: ignore
        status = "connected" if db is not None else "degraded"
        logger.info(f"✅ Canonical memory system: MongoDB ({status})")
    except Exception as e:
        logger.warning(f"MongoDB memory check failed: {e}")

# Initialize FastAPI app
app = FastAPI(
    title="Bella AI Assistant",
    description="Autonomous AI agent with multi-provider support and carry-on memory",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
provider_manager = ProviderManager()
mcp_client = MCPClient()
agent = ReactAgent(provider_manager, mcp_client)
voice_manager = VoiceManager()
vision_manager = VisionManager(provider_manager)

# Carry-on memory file (local JSON, always works even if DB/MCP down)
CARRY_ON_MEMORY_PATH = Path(os.getenv("CARRY_ON_MEMORY_PATH", "bella_memory.json"))

class SimpleResult:
    def __init__(self, success: bool, result: dict = None, error: str = None):
        self.success = success
        self.result = result or {}
        self.error = error

class MemoryFileTool:
    """Simple carry-on memory file tool backed by local JSON."""
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else CARRY_ON_MEMORY_PATH
        self._data = {"sections": {}}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {"sections": {}}
        if "sections" not in self._data:
            self._data["sections"] = {}

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")

    def execute(self, action: str, section: str = None, content: str = None, entry_id: str = None,
                tags=None, importance: int = 5, query: str = None, limit: int = 50):
        if action in ("read",):
            return SimpleResult(True, {"entries": self._data["sections"].get(section, [])[:limit]})
        if action in ("write", "add"):
            entry = {
                "id": entry_id or f"{datetime.utcnow().isoformat()}_{hash(content) % 10000}",
                "content": content,
                "tags": tags or [],
                "importance": importance,
                "created": datetime.utcnow().isoformat()
            }
            self._data["sections"].setdefault(section or "general", []).append(entry)
            self._save()
            return SimpleResult(True, {"saved": True, "entry": entry})
        if action in ("list_sections", "sections"):
            return SimpleResult(True, {"sections": list(self._data["sections"].keys())})
        if action == "search":
            matches = []
            q = (query or "").lower()
            for sec, entries in self._data["sections"].items():
                if section and sec != section:
                    continue
                for e in entries:
                    if q in e.get("content", "").lower() or any(q in t.lower() for t in e.get("tags", [])):
                        matches.append({**e, "section": sec})
            return SimpleResult(True, {"entries": matches[:limit]})
        if action == "stats":
            return SimpleResult(True, {
                "sections": len(self._data["sections"]),
                "entries": sum(len(v) for v in self._data["sections"].values())
            })
        return SimpleResult(False, error=f"Unknown action: {action}")

memory_file_tool = MemoryFileTool()

# Tool execution helper for chat endpoint
def execute_tool(fn_name: str, args: dict) -> dict:
    """Execute a tool by name. Uses agent's tool executor when available."""
    if hasattr(agent, 'tools') and hasattr(agent.tools, '_execute_tool'):
        return agent.tools._execute_tool(fn_name, args)
    # Fallback handlers for memory tools
    if fn_name == "memory_read":
        return {"result": mcp_client.memory_read(args.get("session_id", "default"), args.get("limit", 10))}
    if fn_name == "memory_write":
        return {"result": mcp_client.memory_write(args.get("content", ""), args.get("session_id", "default"), args.get("importance", 5))}
    if fn_name == "memory_search":
        query = args.get("query", "")
        limit = args.get("limit", 5)
        results = []
        # Search carry-on memory
        try:
            local = memory_file_tool.execute(action="search", query=query, limit=limit)
            if local.success:
                results.extend(local.result.get("entries", []))
        except Exception as e:
            logger.warning(f"Local memory search failed: {e}")
        # Search MongoDB via unified memory if available
        if UNIFIED_MEMORY_AVAILABLE:
            import asyncio
            try:
                ctx = asyncio.run(get_context_for_session(args.get("session_id", "default"), query, limit))
                if ctx:
                    results.append({"source": "unified_memory", "content": ctx})
            except Exception as e:
                logger.warning(f"Unified memory search failed: {e}")
        return {"result": results}
    if fn_name == "memory_save":
        content = args.get("content", "")
        session_id = args.get("session_id", "default")
        importance = args.get("importance", 6)
        tags = args.get("tags", [])
        # Save to carry-on memory
        memory_file_tool.execute(action="add", section="notes", content=content, importance=importance, tags=tags)
        # Save to MongoDB
        if MEMORY_CORE_AVAILABLE:
            remember_episode(content, session_id, role="assistant", importance=importance, tags=tags)
        if UNIFIED_MEMORY_AVAILABLE:
            import asyncio
            try:
                asyncio.run(save_turn(session_id, "assistant", content, source="tool", importance=importance, tags=tags))
            except Exception as e:
                logger.warning(f"Unified memory save failed: {e}")
        return {"result": "saved"}
    if fn_name == "file_read":
        return {"result": mcp_client.file_read(args.get("path", ""))}
    if fn_name == "file_write":
        return {"result": mcp_client.file_write(args.get("path", ""), args.get("content", ""))}
    if fn_name == "shell_run":
        return {"result": mcp_client.shell_run(args.get("command", ""))}
    return {"error": f"Unknown tool: {fn_name}"}

# Available tools exposed to the model
available_tools = [
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search Bella's memory archive for relevant context. Use when you need to recall facts, projects, past conversations, or if you feel lost.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "limit": {"type": "integer", "description": "Max results", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_save",
            "description": "Save something important Bella should remember for future sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "session_id": {"type": "string"},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 10, "default": 6},
                    "tags": {"type": "array", "items": {"type": "string"}, "default": []}
                },
                "required": ["content", "session_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read a file from the server. Use when the user refers to a file you cannot see.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write a file to the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shell_run",
            "description": "Run a shell command on the server. Use sparingly and only when asked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"]
            }
        }
    }
]


# Request/Response Models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    model: Optional[str] = None
    provider: Optional[str] = None
    max_tokens: Optional[int] = 4000
    temperature: Optional[float] = 0.7
    use_memory_file: Optional[bool] = True  # include carry-on memory

class ChatResponse(BaseModel):
    response: str
    model: str
    provider: str
    session_id: str
    usage: Optional[Dict[str, int]] = None

class BridgeRequest(BaseModel):
    task: str
    session_id: Optional[str] = "agent_session"

class BridgeResponse(BaseModel):
    status: str
    answer: Optional[str] = None
    steps: List[Dict[str, Any]]
    total_steps: int

class SpeakRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None

class VisionRequest(BaseModel):
    image: str  # Base64 encoded image
    prompt: Optional[str] = "Describe this image in detail."
    format: Optional[str] = "base64"

class ProviderSwitchRequest(BaseModel):
    provider: str

# NEW: Memory File Request Models
class MemoryFileRequest(BaseModel):
    action: str = "read"
    section: Optional[str] = None
    content: Optional[str] = None
    entry_id: Optional[str] = None
    tags: Optional[List[str]] = None
    importance: int = 5
    query: Optional[str] = None
    limit: int = 50

class ContextInjectRequest(BaseModel):
    session_id: str
    context: str
    source: Optional[str] = "external"

class ReasoningRequest(BaseModel):
    question: str
    context: Optional[str] = None
    thinking_type: str = "deep"  # "deep" | "strategic" | "analytical" | "creative"
    max_tokens: int = 4000

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    health_data = {
        "status": "online",
        "service": "Bella AI Assistant",
        "timestamp": datetime.utcnow().isoformat(),
        "active_provider": provider_manager.active_provider,
        "available_providers": provider_manager.list_providers(),
        "features": {
            "unified_memory": UNIFIED_MEMORY_AVAILABLE,
            "legacy_memory_core": MEMORY_CORE_AVAILABLE,
            "mcp_tools": MCP_TOOLS_AVAILABLE,
            "carry_on_memory": memory_file_tool is not None,
            "voice": True,
            "vision": True,
            "agent": True
        }
    }
    
    # Legacy memory health
    try:
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        health_data["mongodb"] = "connected"
        client.close()
    except Exception:
        health_data["mongodb"] = "unavailable (using JSON file fallback)"
    
    # Check unified memory services
    if UNIFIED_MEMORY_AVAILABLE:
        try:
            health_data["memory_services"] = await memory_status()
        except Exception as e:
            health_data["memory_services"] = {"error": str(e)}
    
    return health_data

# Root endpoint - serve dashboard
@app.get("/")
async def root():
    """Serve the main dashboard"""
    static_path = "static/index.html"
    if os.path.exists(static_path):
        return FileResponse(static_path)
    elif os.path.exists("static/dashboard.html"):
        return FileResponse("static/dashboard.html")
    else:
        return {
            "service": "Bella AI Assistant",
            "status": "online",
            "version": "2.0.0",
            "endpoints": {
                "chat": "/v1/chat",
                "agent": "/bridge",
                "voice": "/v1/speak",
                "vision": "/v1/vision",
                "memory_file": "/v1/memory-file",
                "health": "/health"
            }
        }

# Chat endpoint
@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat completion endpoint with integrated carry-on memory
    """
    try:
        # Build system prompt with memory context
        system_content_parts = []

        # Add Bella's purse (persistent working memory) - ALWAYS INCLUDE THIS
        if PURSE_AVAILABLE:
            purse_context = get_purse_context()
            system_content_parts.append(purse_context)
            system_content_parts.append("\n---\n")

        # Add unified memory context (MongoDB + Memory Pro) — new single source of truth
        if UNIFIED_MEMORY_AVAILABLE:
            try:
                context = await get_context_for_session(request.session_id or "default", request.message, limit=5)
                if context:
                    system_content_parts.append("// Unified memory context:\n")
                    system_content_parts.append(context)
                    system_content_parts.append("\n---\n")
            except Exception as e:
                logger.warning(f"Could not load unified memory context: {e}")

        # Add legacy memory fallback
        if MEMORY_CORE_AVAILABLE:
            base_prompt = "You are Bella, a warm, intelligent AI assistant built for Keith Watkins. Be helpful, direct, and concise."
            system_content_parts.append(base_prompt)
            try:
                recent_memories = recall_episodes(session_id=request.session_id or "default", limit=5, min_importance=5)
                if recent_memories:
                    context_snippets = "\n".join([f"  - {m.get('content', '')[:100]}" for m in recent_memories])
                    system_content_parts.append(f"\n// Recent context:\n{context_snippets}\n")
            except Exception as e:
                logger.warning(f"Could not recall legacy memories: {e}")
        else:
            system_content_parts.append("You are Bella, a warm, intelligent AI assistant built for Keith Watkins. Be helpful, direct, and concise.")
        
        # Add carry-on memory if enabled
        if request.use_memory_file and memory_file_tool:
            try:
                # Get recent important entries from memory file
                for section in ["preferences", "projects", "reminders"]:
                    result = memory_file_tool.execute(action="read", section=section, limit=5)
                    if result.success and result.result.get("entries"):
                        entries = result.result["entries"]
                        if entries:
                            system_content_parts.append(f"\n// Bella's notes ({section}):")
                            for entry in entries[-3:]:  # Last 3 entries
                                if entry.get("importance", 5) >= 6:
                                    system_content_parts.append(f"  - {entry['content'][:150]}")
            except Exception as e:
                logger.warning(f"Could not load carry-on memory: {e}")
        
        # Combine system prompt
        system_content = "\n".join(system_content_parts)
        
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": request.message}
        ]

        response = provider_manager.chat(
            messages=messages,
            model=request.model,
            provider=request.provider,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            tools=available_tools
        )

        if "error" in response:
            raise HTTPException(status_code=500, detail=response["error"])

        reply_content = response.get("content", "")

        # Handle tool calls
        tool_calls = response.get("tool_calls", [])
        tool_results = []
        if tool_calls:
            for tc in tool_calls:
                try:
                    fn_name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    result = execute_tool(fn_name, args)
                    tool_results.append({"tool": fn_name, "args": args, "result": result})
                    reply_content += f"\n\n[Tool: {fn_name}]\n{json.dumps(result, indent=2)}"
                except Exception as e:
                    logger.error(f"Tool execution error: {e}")

        # Save to unified memory (MongoDB + Memory Pro)
        if UNIFIED_MEMORY_AVAILABLE:
            try:
                await save_turn(
                    session_id=request.session_id or "default",
                    role="assistant",
                    content=f"User: {request.message}\nBella: {reply_content[:300]}",
                    source="bella_chat",
                    importance=5,
                    tags=["chat"]
                )
            except Exception as e:
                logger.warning(f"Unified memory save failed: {e}")
        
        # Legacy fallback
        elif MEMORY_CORE_AVAILABLE:
            remember_episode(
                content=f"User: {request.message}\nBella: {reply_content[:300]}",
                session_id=request.session_id or "default",
                role="assistant",
                importance=5,
                tags=["chat"],
            )
            # Check for frustration
            frustration_words = {"wtf", "broken", "why", "again", "fix", "still", "ugh", "ffs", "damn"}
            if any(w in request.message.lower() for w in frustration_words):
                log_emotion(request.session_id or "default", "frustrated", confidence=0.7)
        else:
            try:
                mcp_client.memory_write(
                    f"User: {request.message}\nBella: {reply_content[:200]}",
                    request.session_id or "default"
                )
            except Exception as e:
                logger.warning(f"MCP memory fallback failed: {e}")

        return ChatResponse(
            response=reply_content,
            model=response.get("model", "unknown"),
            provider=response.get("provider", "unknown"),
            session_id=request.session_id,
            usage=response.get("usage")
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Agent bridge endpoint
@app.post("/bridge", response_model=BridgeResponse)
async def bridge(request: BridgeRequest):
    """
    Full agent loop endpoint
    Run autonomous agent with ReAct pattern
    """
    try:
        # Inject carry-on memory into agent context
        if memory_file_tool:
            try:
                # Add important reminders to the task context
                reminders = memory_file_tool.execute(action="read", section="reminders", limit=3)
                if reminders.success and reminders.result.get("entries"):
                    reminder_text = "\n".join([f"- {e['content'][:100]}" for e in reminders.result["entries"]])
                    enhanced_task = f"{request.task}\n\n[Bella's reminders]:\n{reminder_text}"
                    result = agent.run(enhanced_task, request.session_id)
                else:
                    result = agent.run(request.task, request.session_id)
            except Exception as e:
                logger.warning(f"Could not enhance task with memory: {e}")
                result = agent.run(request.task, request.session_id)
        else:
            result = agent.run(request.task, request.session_id)
        
        return BridgeResponse(
            status=result.get("status", "unknown"),
            answer=result.get("answer") or result.get("partial_result"),
            steps=result.get("steps", []),
            total_steps=result.get("total_steps", 0)
        )
    
    except Exception as e:
        logger.error(f"Agent error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Voice/TTS endpoint
@app.post("/v1/speak")
async def speak(request: SpeakRequest):
    """
    Text-to-speech endpoint
    Convert text to audio using ElevenLabs or edge-tts
    """
    try:
        # Run TTS in thread pool to avoid event loop conflicts
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            audio_bytes = await loop.run_in_executor(
                executor,
                voice_manager.speak,
                request.text,
                request.voice_id
            )

        if not audio_bytes or len(audio_bytes) == 0:
            raise HTTPException(status_code=500, detail="TTS generation failed")

        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"}
        )

    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Vision endpoint
@app.post("/v1/vision")
async def vision(request: VisionRequest):
    """
    Image analysis endpoint
    Analyze images using vision-capable AI models
    """
    try:
        result = vision_manager.analyze_image(
            request.image,
            request.prompt,
            request.format
        )
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        return result
    
    except Exception as e:
        logger.error(f"Vision error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Reasoning endpoint (Claude deep thinking)
@app.post("/v1/reason")
async def reason(request: ReasoningRequest):
    """
    Deep reasoning endpoint using Claude (Anthropic/Bedrock)
    For complex analysis, strategic decisions, multi-step reasoning
    """
    if not REASONING_AVAILABLE or not reasoning_engine:
        raise HTTPException(
            status_code=503,
            detail="Reasoning engine not available. Configure AWS Bedrock or Anthropic API."
        )

    try:
        logger.info(f"🧠 Reasoning request: {request.thinking_type}")

        result = reasoning_engine.reason(
            question=request.question,
            context=request.context,
            thinking_type=request.thinking_type,
            max_tokens=request.max_tokens
        )

        return {
            "question": request.question,
            "thinking_type": request.thinking_type,
            "reasoning": result.get("reasoning", ""),
            "model": result.get("model", "claude"),
            "confidence": result.get("confidence", "high")
        }

    except Exception as e:
        logger.error(f"Reasoning error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Provider management
@app.get("/providers")
async def list_providers():
    """List all available providers"""
    providers = provider_manager.list_providers()
    return {
        "providers": providers,
        "active": provider_manager.active_provider
    }

@app.post("/providers/switch")
async def switch_provider(request: ProviderSwitchRequest):
    """Switch active provider"""
    success = provider_manager.set_active_provider(request.provider)
    
    if not success:
        raise HTTPException(status_code=400, detail="Invalid provider")
    
    return {
        "status": "success",
        "active_provider": provider_manager.active_provider
    }

@app.get("/providers/{provider_name}")
async def get_provider_info(provider_name: str):
    """Get provider capabilities and configuration"""
    config = provider_manager.get_provider_config(provider_name)
    capabilities = provider_manager.get_provider_capabilities(provider_name)
    
    if not config:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    return {
        "name": provider_name,
        "label": config.get("label", provider_name),
        "capabilities": capabilities,
        "models": config.get("models", {})
    }

# Memory endpoints
@app.get("/memory/{session_id}")
async def get_memory(session_id: str, limit: int = 20):
    """Retrieve session memories from MongoDB"""
    try:
        if MEMORY_CORE_AVAILABLE:
            memories = recall_episodes(session_id=session_id, limit=limit)
            return {"session_id": session_id, "memories": memories, "source": "mongodb"}
        else:
            try:
                memories = mcp_client.memory_read(session_id, limit)
                return {"session_id": session_id, "memories": memories, "source": "mcp"}
            except Exception as e:
                return {"session_id": session_id, "memories": [], "source": "mcp", "error": str(e)}
    except Exception as e:
        logger.error(f"Memory retrieval error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/memory")
async def save_memory(session_id: str, content: str, role: str = "user", importance: int = 5):
    """Save to MongoDB memory"""
    try:
        if MEMORY_CORE_AVAILABLE:
            episode_id = remember_episode(
                content=content,
                session_id=session_id,
                role=role,
                importance=importance
            )
            return {"status": "saved", "id": episode_id, "source": "mongodb"}
        else:
            try:
                result = mcp_client.memory_write(content, session_id)
                return {**result, "source": "mcp"}
            except Exception as e:
                return {"status": "error", "source": "mcp", "error": str(e)}
    except Exception as e:
        logger.error(f"Memory save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Memory core endpoints (only if available)
if MEMORY_CORE_AVAILABLE:
    @app.get("/memory/context/{session_id}")
    async def get_memory_context(session_id: str):
        """Get full memory context for a session"""
        memories = recall_episodes(session_id=session_id, limit=10, min_importance=5)
        context = ""
        if memories:
            context = "Recent memories:\n" + "\n".join([f"- {m.get('content', '')[:100]}" for m in memories])

        return {
            "session_id": session_id,
            "context": context,
            "memories": memories,
            "backend": "mongodb"
        }

    @app.post("/memory/episode")
    async def save_episode(
        session_id: str,
        content: str,
        importance: int = 5,
        emotion: str = None,
        tags: str = None,
        project: str = None,
    ):
        """Save a memory episode with full metadata"""
        tag_list = tags.split(",") if tags else []
        episode_id = remember_episode(content, session_id, importance=importance,
                                       emotion=emotion, tags=tag_list, project=project)
        return {"status": "saved", "id": episode_id}

    @app.post("/memory/handoff")
    async def save_handoff(
        session_id: str,
        summary: str,
        last_action: str,
        next_step: str,
        project: str = None,
    ):
        """Write session handoff so Jarvis never loses the thread"""
        write_handoff(session_id, summary, last_action, next_step, project=project)
        return {"status": "handoff_saved"}

    @app.get("/memory/trust")
    async def get_trust():
        """Get current trust score with Charles"""
        return get_trust_score()

# =============================================================================
# BELLA'S PURSE ENDPOINTS (Persistent Working Memory)
# =============================================================================

if PURSE_AVAILABLE:
    @app.get("/purse")
    async def get_purse():
        """Get Bella's purse contents (formatted for reading)"""
        return {"purse": purse_read(), "raw": load_purse()}

    @app.post("/purse/add")
    async def add_to_purse_endpoint(section: str, item: str):
        """Add item to purse section"""
        result = purse_add(section, item)
        return {"status": "success", "message": result}

    @app.post("/purse/remove")
    async def remove_from_purse_endpoint(section: str, item: str = None, index: int = None):
        """Remove item from purse section"""
        result = purse_remove(section, item, index)
        return {"status": "success", "message": result}

    @app.post("/purse/update")
    async def update_purse_endpoint(section: str, items: List[str]):
        """Replace entire purse section"""
        result = purse_update_section(section, items)
        return {"status": "success", "message": result}

# =============================================================================
# NEW: CARRY-ON MEMORY FILE ENDPOINTS
# =============================================================================

@app.get("/v1/memory-file")
async def memory_file_read(
    section: str = None,
    limit: int = 50,
    query: str = None
):
    """
    Read Bella's carry-on memory file
    
    Query params:
    - section: Specific section to read (preferences, projects, todos, etc.)
    - limit: Max entries to return
    - query: Search query for finding specific memories
    """
    if not memory_file_tool:
        raise HTTPException(status_code=503, detail="Memory file tool not available")
    
    try:
        if query:
            # Search mode
            result = memory_file_tool.execute(action="search", query=query, section=section)
        else:
            # Read mode
            result = memory_file_tool.execute(action="read", section=section, limit=limit)
        
        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)
        
        return result.result
    
    except Exception as e:
        logger.error(f"Memory file read error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/memory-file")
async def memory_file_write(request: MemoryFileRequest):
    """
    Write to Bella's carry-on memory file
    
    Actions:
    - read: Read sections or entries
    - write/add: Add new entry
    - update/edit: Update existing entry
    - delete/remove: Delete entry
    - search/find: Search memories
    - list_sections/sections: List all sections
    - archive: Archive old entries
    - stats: Get statistics
    """
    if not memory_file_tool:
        raise HTTPException(status_code=503, detail="Memory file tool not available")
    
    try:
        params = {
            "action": request.action,
            "section": request.section,
            "content": request.content,
            "entry_id": request.entry_id,
            "tags": request.tags,
            "importance": request.importance,
            "query": request.query,
            "limit": request.limit
        }
        
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        
        result = memory_file_tool.execute(**params)
        
        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)
        
        return result.result
    
    except Exception as e:
        logger.error(f"Memory file write error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/memory-file/stats")
async def memory_file_stats():
    """Get carry-on memory file statistics"""
    if not memory_file_tool:
        raise HTTPException(status_code=503, detail="Memory file tool not available")
    
    try:
        result = memory_file_tool.execute(action="stats")
        
        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)
        
        return result.result
    
    except Exception as e:
        logger.error(f"Memory file stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/memory-file/sections")
async def memory_file_sections():
    """List all available memory file sections"""
    if not memory_file_tool:
        raise HTTPException(status_code=503, detail="Memory file tool not available")
    
    try:
        result = memory_file_tool.execute(action="list_sections")
        
        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)
        
        return result.result
    
    except Exception as e:
        logger.error(f"Memory file sections error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# N8N WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/webhooks/context-inject")
async def context_inject(request: ContextInjectRequest, background_tasks: BackgroundTasks):
    """
    Webhook for n8n to inject context
    Used by memory loop workflow to add periodic context updates
    """
    try:
        # Store the context injection in memory
        if MEMORY_CORE_AVAILABLE:
            remember_episode(
                content=f"[Context Update from {request.source}] {request.context}",
                session_id=request.session_id,
                role="system",
                importance=6,
                tags=["context_injection", request.source]
            )
        
        return {
            "status": "injected",
            "session_id": request.session_id,
            "source": request.source,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Context inject error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Serve static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Startup event
@app.on_event("startup")
async def startup_event():
    """Log startup information and seed memory if empty."""
    logger.info("=" * 60)
    logger.info("🚀 Bella AI Assistant v2.0 Starting")
    logger.info("=" * 60)
    logger.info(f"Active Provider: {provider_manager.active_provider}")
    logger.info(f"Available Providers: {len(provider_manager.list_providers())}")
    logger.info(f"MCP URL: {mcp_client.base_url}")
    logger.info(f"TTS Provider: {voice_manager.tts_provider}")
    logger.info(f"Agent Max Steps: {agent.max_steps}")

    if MEMORY_CORE_AVAILABLE:
        logger.info("Memory Core: ✅ ACTIVE (human-feeling memory)")
        try:
            # Seed Keith's memory if empty
            trust = get_trust_score()
            if trust["score"] == 10 and trust["note"] == "Getting acquainted" and hasattr(memory, "bootstrap_keith"):
                memory.bootstrap_keith()
                logger.info("Memory Core: ✅ Seeded Keith's baseline facts")
                trust = get_trust_score()
            logger.info(f"Trust Level: {trust['score']}/100 — {trust['note']}")
        except Exception as e:
            logger.warning(f"Memory bootstrap check failed: {e}")
    else:
        logger.info("Memory Core: ⚠️ Not loaded (using basic MCP memory)")
    
    if PURSE_AVAILABLE:
        logger.info("Purse: ✅ ACTIVE (persistent working memory)")
        try:
            purse = load_purse()
            logger.info(f"  Last updated: {purse.get('last_updated', 'N/A')[:19]}")
        except:
            pass
    else:
        logger.info("Purse: ⚠️ Not available")

    if memory_file_tool:
        logger.info("Carry-On Memory: ✅ ACTIVE (persistent memory file)")
    else:
        logger.info("Carry-On Memory: ⚠️ Not loaded")

    logger.info("=" * 60)
    logger.info("Endpoints:")
    logger.info(f"  - Chat:       POST /v1/chat")
    logger.info(f"  - Agent:      POST /bridge")
    logger.info(f"  - Memory:     GET  /memory/{{session_id}}")
    logger.info(f"  - MemoryFile: GET/POST /v1/memory-file")
    logger.info(f"  - Voice:      POST /v1/speak")
    logger.info(f"  - Vision:     POST /v1/vision")
    logger.info(f"  - Health:     GET  /health")
    logger.info("=" * 60)

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PYTHON_PORT", 8000))
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
