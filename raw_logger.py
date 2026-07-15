"""
ODIN Memory — Layer 1: Raw Logger
Logs every conversation turn verbatim. Nothing is filtered or summarized.
Each session gets its own JSON file in raw_store/.
This is the ground truth — all higher layers derive from here.
"""

import sys
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from settings import get_settings

settings = get_settings()
STORE_DIR = settings.raw_store_dir
STORE_DIR.mkdir(parents=True, exist_ok=True)


class RawLogger:

    def log(self, session_id: str, role: str, content: str, timestamp: str = None,
             source: str = "unknown") -> dict:
        """
        Append a single message to a session log.
        Creates the session file if it doesn't exist.
        `source` tags where this came from (reins/odin/bella/api/manual) —
        this matters once multiple clients feed the same memory system.
        """
        session_file = STORE_DIR / f"{session_id}.json"

        if session_file.exists():
            with open(session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)
        else:
            session_data = {
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "messages": [],
            }

        message = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "source": source,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        }

        session_data["messages"].append(message)
        session_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        session_data["message_count"] = len(session_data["messages"])

        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

        return message

    def get_session(self, session_id: str) -> dict | None:
        session_file = STORE_DIR / f"{session_id}.json"
        if not session_file.exists():
            return None
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_recent_messages(self, session_id: str, n: int = 20) -> list:
        session = self.get_session(session_id)
        if not session:
            return []
        return session["messages"][-n:]

    def list_sessions(self) -> list[str]:
        return [f.stem for f in STORE_DIR.glob("*.json")]

    def get_sessions_since(self, since_iso: str) -> list[dict]:
        results = []
        for session_id in self.list_sessions():
            session = self.get_session(session_id)
            if session and session.get("last_updated", "") >= since_iso:
                results.append(session)
        return results

    def get_most_recent_session(self) -> dict | None:
        """Whatever session was touched last, across all sessions — used for
        the 'quick refresh of the last conversation' injection."""
        sessions = self.list_sessions()
        if not sessions:
            return None
        best = None
        for sid in sessions:
            s = self.get_session(sid)
            if not s:
                continue
            if best is None or s.get("last_updated", "") > best.get("last_updated", ""):
                best = s
        return best

    def export_session_text(self, session_id: str) -> str:
        session = self.get_session(session_id)
        if not session:
            return ""
        lines = []
        for msg in session["messages"]:
            lines.append(f"[{msg['role'].upper()}]: {msg['content']}")
        return "\n".join(lines)

    def delete_session(self, session_id: str) -> bool:
        session_file = STORE_DIR / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()
            return True
        return False

    def get_all_messages_flat(self) -> list[dict]:
        all_msgs = []
        for session_id in self.list_sessions():
            session = self.get_session(session_id)
            if session:
                for msg in session["messages"]:
                    msg["session_id"] = session_id
                    all_msgs.append(msg)
        all_msgs.sort(key=lambda m: m.get("timestamp", ""))
        return all_msgs

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Plain substring search across all raw messages — the crude
        first-pass search the MCP tool will call before anything smarter."""
        q = query.lower()
        hits = []
        for msg in self.get_all_messages_flat():
            if q in msg.get("content", "").lower():
                hits.append(msg)
        return hits[-limit:]
