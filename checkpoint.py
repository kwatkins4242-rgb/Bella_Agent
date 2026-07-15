"""Checkpoint manager for periodic memory snapshots."""

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class CheckpointManager:
    """Save and restore memory snapshots by session/user."""

    def __init__(self, base_dir: str = "./memory_checkpoints"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        path = self.base_dir / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(
        self,
        session_id: str,
        state: Dict[str, Any],
        label: Optional[str] = None,
    ) -> Path:
        session_dir = self._session_dir(session_id)
        timestamp = int(time.time())
        label = label or "checkpoint"
        filename = f"{label}_{timestamp}.json"
        filepath = session_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        return filepath

    def load(self, session_id: str, filepath: Optional[str] = None) -> Dict[str, Any]:
        session_dir = self._session_dir(session_id)
        if filepath:
            target = Path(filepath)
        else:
            files = sorted(session_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
            if not files:
                return {}
            target = files[-1]
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_checkpoints(self, session_id: str) -> List[Path]:
        session_dir = self._session_dir(session_id)
        return sorted(session_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)

    def prune(self, session_id: str, keep: int = 10) -> None:
        files = self.list_checkpoints(session_id)
        for old in files[:-keep]:
            old.unlink()

    def clone(self, source_session: str, target_session: str) -> None:
        source = self._session_dir(source_session)
        target = self._session_dir(target_session)
        shutil.copytree(source, target, dirs_exist_ok=True)
