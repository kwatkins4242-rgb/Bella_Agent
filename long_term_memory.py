"""
ODIN Memory — Layer 2: Long-Term Memory Store
Thread-safe-ish, capped, atomic-write storage of distilled facts
(not raw conversation — that's Layer 1). Facts get reinforced when
repeated, and garbage-collected when the store gets too large.
"""
from __future__ import annotations
import sys
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

try:
    import fcntl
    HAVE_FCNTL = True
except ImportError:
    HAVE_FCNTL = False

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from settings import get_settings

settings = get_settings()
MEMORY_FILE = settings.longterm_file
MAX_MEMORIES = 5_000
GC_THRESHOLD = 1.2 * MAX_MEMORIES

logger = logging.getLogger("odin.memory.longterm")


class LongTermMemory:
    def __init__(self) -> None:
        self._ensure_file()

    # ---------- low-level helpers ----------
    @staticmethod
    def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                if HAVE_FCNTL:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    except OSError:
                        pass
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp.replace(path)
        except OSError as e:
            logger.exception("failed to write %s: %s", path, e)

    @staticmethod
    def _load() -> Dict[str, Any]:
        try:
            with MEMORY_FILE.open("r", encoding="utf-8") as f:
                if HAVE_FCNTL:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    except OSError:
                        pass
                return json.load(f)
        except FileNotFoundError:
            return {"version": "1.0", "memories": []}
        except json.JSONDecodeError:
            logger.error("corrupted %s — resetting", MEMORY_FILE)
            return {"version": "1.0", "memories": []}

    def _ensure_file(self) -> None:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not MEMORY_FILE.exists():
            self._atomic_write(MEMORY_FILE, {"version": "1.0", "memories": []})

    def _gc(self, data: Dict[str, Any]) -> None:
        memories = data["memories"]
        if len(memories) < GC_THRESHOLD:
            return
        logger.warning("memory cap hit — trimming")
        memories.sort(key=lambda m: (
            m.get("last_reinforced", ""),
            m.get("reinforcement_count", 1),
        ))
        data["memories"] = memories[-MAX_MEMORIES:]
        data["count"] = len(data["memories"])

    # ---------- public API ----------
    def add_memory(self, fact: Dict[str, Any]) -> str:
        data = self._load()
        content = fact.get("content", "").strip()
        if not content:
            raise ValueError("empty memory content")

        for m in data["memories"]:
            if m["content"].lower() == content.lower():
                return self.reinforce(m["id"])

        mem_id = str(uuid.uuid4())[:8]
        memory = {
            "id": mem_id,
            "content": content,
            "category": fact.get("category", "general"),
            "tags": fact.get("tags", []),
            "confidence": min(max(float(fact.get("confidence", 0.8)), 0.0), 1.0),
            "source_session": fact.get("source_session"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_reinforced": datetime.now(timezone.utc).isoformat(),
            "reinforcement_count": 1,
            "active": True,
        }
        data["memories"].append(memory)
        self._gc(data)
        self._atomic_write(MEMORY_FILE, data)
        return mem_id

    def reinforce(self, mem_id: str) -> str:
        data = self._load()
        for m in data["memories"]:
            if m["id"] == mem_id:
                m["last_reinforced"] = datetime.now(timezone.utc).isoformat()
                m["reinforcement_count"] = m.get("reinforcement_count", 1) + 1
                self._atomic_write(MEMORY_FILE, data)
                return mem_id
        raise KeyError(f"no memory with id {mem_id}")

    def deactivate(self, mem_id: str) -> bool:
        data = self._load()
        for m in data["memories"]:
            if m["id"] == mem_id:
                m["active"] = False
                self._atomic_write(MEMORY_FILE, data)
                return True
        return False

    def get_all(self, active_only: bool = True) -> List[Dict[str, Any]]:
        data = self._load()
        mems = data["memories"]
        return [m for m in mems if m.get("active", True)] if active_only else mems

    def get_by_category(self, category: str) -> List[Dict[str, Any]]:
        return [m for m in self.get_all() if m.get("category") == category]

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        q = query.lower()
        hits = [
            m for m in self.get_all()
            if q in m["content"].lower() or q in " ".join(m.get("tags", [])).lower()
        ]
        hits.sort(key=lambda m: m.get("last_reinforced", ""), reverse=True)
        return hits[:limit]

    def count(self) -> int:
        return len(self.get_all())
