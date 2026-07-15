"""
Task Queue - Gives ODIN engine something to work on
Pulls from: dashboard, n8n webhooks, scheduled jobs, file watcher
"""

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

logger = logging.getLogger("odin.task_queue")

@dataclass
class Task:
    """A task for the ODIN engine to execute"""
    id: str
    goal: str
    source: str  # "user", "n8n", "schedule", "file_watcher"
    session_id: str
    priority: int = 5  # 1-10, higher = more urgent
    status: str = "pending"  # pending, running, complete, failed
    created_at: str = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    context: Optional[Dict[str, Any]] = None  # memory injection, etc

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TaskQueue:
    """Persistent task queue with priority ordering"""

    def __init__(self, queue_file: str = "data/task_queue.json"):
        self.queue_file = Path(queue_file)
        self.queue: List[Task] = []
        self._lock = asyncio.Lock()
        self._load()
        logger.info(f"Task queue initialized → {self.queue_file}")

    def _load(self):
        """Load queue from disk"""
        if self.queue_file.exists():
            try:
                data = json.loads(self.queue_file.read_text())
                self.queue = [Task(**t) for t in data]
                logger.info(f"Loaded {len(self.queue)} tasks from disk")
            except Exception as e:
                logger.error(f"Failed to load queue: {e}")
                self.queue = []
        else:
            self.queue = []

    def _save(self):
        """Save queue to disk"""
        try:
            self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            data = [t.to_dict() for t in self.queue]
            self.queue_file.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.error(f"Failed to save queue: {e}")

    async def add(
        self,
        goal: str,
        source: str = "user",
        session_id: str = "default",
        priority: int = 5,
        context: Optional[Dict[str, Any]] = None
    ) -> Task:
        """Add a task to the queue"""
        async with self._lock:
            task = Task(
                id=f"task_{int(datetime.now().timestamp() * 1000)}",
                goal=goal,
                source=source,
                session_id=session_id,
                priority=priority,
                context=context or {}
            )
            self.queue.append(task)
            # Sort by priority (highest first), then by creation time
            self.queue.sort(key=lambda t: (-t.priority, t.created_at))
            self._save()
            logger.info(f"✓ Task added: {task.id} (priority {priority}, source {source})")
            return task

    async def get_next(self) -> Optional[Task]:
        """Get next pending task (highest priority)"""
        async with self._lock:
            for task in self.queue:
                if task.status == "pending":
                    return task
            return None

    async def mark_running(self, task_id: str):
        """Mark task as running"""
        async with self._lock:
            for task in self.queue:
                if task.id == task_id:
                    task.status = "running"
                    task.started_at = datetime.now().isoformat()
                    self._save()
                    logger.info(f"Task {task_id} → running")
                    return

    async def mark_complete(self, task_id: str, result: Dict[str, Any]):
        """Mark task as complete"""
        async with self._lock:
            for task in self.queue:
                if task.id == task_id:
                    task.status = "complete"
                    task.completed_at = datetime.now().isoformat()
                    task.result = result
                    self._save()
                    logger.info(f"Task {task_id} → complete")
                    return

    async def mark_failed(self, task_id: str, error: str):
        """Mark task as failed"""
        async with self._lock:
            for task in self.queue:
                if task.id == task_id:
                    task.status = "failed"
                    task.completed_at = datetime.now().isoformat()
                    task.error = error
                    self._save()
                    logger.error(f"Task {task_id} → failed: {error}")
                    return

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        async with self._lock:
            for task in self.queue:
                if task.id == task_id:
                    return task
            return None

    async def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> List[Task]:
        """List tasks, optionally filtered by status"""
        async with self._lock:
            if status:
                filtered = [t for t in self.queue if t.status == status]
            else:
                filtered = self.queue
            return filtered[:limit]

    async def count(self, status: Optional[str] = None) -> int:
        """Count tasks, optionally filtered by status"""
        async with self._lock:
            if status:
                return sum(1 for t in self.queue if t.status == status)
            return len(self.queue)

    async def clear_completed(self, older_than_hours: int = 24):
        """Remove completed tasks older than N hours"""
        async with self._lock:
            cutoff = datetime.now().timestamp() - (older_than_hours * 3600)
            before_count = len(self.queue)
            self.queue = [
                t for t in self.queue
                if t.status != "complete" or datetime.fromisoformat(t.completed_at).timestamp() > cutoff
            ]
            removed = before_count - len(self.queue)
            if removed > 0:
                self._save()
                logger.info(f"Cleared {removed} old completed tasks")
            return removed


# Global singleton
_queue: Optional[TaskQueue] = None

def get_task_queue() -> TaskQueue:
    """Get the global task queue instance"""
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue
