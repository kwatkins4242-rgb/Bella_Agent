"""High-level memory manager that wires history + memory + persistence."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.base_memory import BaseMemory
from ..core.messages import AIMessage, HumanMessage, SystemMessage
from ..history.file import FileChatMessageHistory
from ..history.sqlite import SQLiteChatMessageHistory
from ..memory.buffer import ConversationBufferMemory
from ..memory.buffer_window import ConversationBufferWindowMemory
from ..memory.combined import CombinedMemory
from ..memory.entity import ConversationEntityMemory
from ..memory.kg import ConversationKGMemory
from ..memory.summary import ConversationSummaryMemory
from ..memory.vectorstore import VectorStoreRetrieverMemory
from ..vectorstore.in_memory import InMemoryVectorStore
from .checkpoint import CheckpointManager


class MemoryManager:
    """Manages a memory instance for a session and handles load/save lifecycle."""

    MEMORY_TYPES = {
        "buffer": ConversationBufferMemory,
        "buffer_window": ConversationBufferWindowMemory,
        "summary": ConversationSummaryMemory,
        "entity": ConversationEntityMemory,
        "kg": ConversationKGMemory,
        "vectorstore": VectorStoreRetrieverMemory,
        "combined": CombinedMemory,
    }

    def __init__(
        self,
        session_id: str,
        memory: Optional[BaseMemory] = None,
        storage_path: str = "./bella_memory_data",
        checkpoint_enabled: bool = True,
    ):
        self.session_id = session_id
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.memory = memory or self._default_memory()
        self.checkpoint = CheckpointManager(str(self.storage_path / "checkpoints"))
        self.checkpoint_enabled = checkpoint_enabled

    def _default_memory(self) -> ConversationBufferMemory:
        history = FileChatMessageHistory(
            self.storage_path / "sessions" / f"{self.session_id}.json"
        )
        return ConversationBufferMemory(
            memory_key="history",
            return_messages=True,
            chat_memory=history,
            human_prefix="Charles",
            ai_prefix="Bella",
        )

    def load_memory_variables(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.memory.load_memory_variables(inputs)

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        self.memory.save_context(inputs, outputs)
        if self.checkpoint_enabled:
            self.checkpoint.save(self.session_id, self.memory.to_dict())

    def add_exchange(self, human: str, ai: str) -> None:
        self.save_context({"input": human}, {"output": ai})

    def add_user_fact(self, fact: str) -> None:
        """Manually add a fact to memory (useful for reminders/preferences)."""
        self.memory.chat_memory.add_message(
            SystemMessage(content=f"[Known fact] {fact}")
        )

    def clear(self) -> None:
        self.memory.clear()

    def save(self) -> None:
        self.checkpoint.save(self.session_id, self.memory.to_dict())

    def restore(self, filepath: Optional[str] = None) -> None:
        data = self.checkpoint.load(self.session_id, filepath=filepath)
        self.memory.from_dict(data)

    @classmethod
    def build_from_config(cls, session_id: str, config: Dict[str, Any]) -> "MemoryManager":
        """Build a memory manager from a JSON-like config."""
        storage_path = config.get("storage_path", "./bella_memory_data")
        memory_type = config.get("memory_type", "buffer")
        memory_cls = cls.MEMORY_TYPES.get(memory_type, ConversationBufferMemory)
        kwargs = dict(config.get("memory_kwargs", {}))

        if memory_type in {"summary", "entity", "kg"}:
            from ..llm.ollama_llm import OllamaLLM

            kwargs["llm"] = OllamaLLM.from_config(config.get("llm", {}))

        if memory_type == "vectorstore":
            vectorstore_path = config.get("vectorstore_path")
            if vectorstore_path and Path(vectorstore_path).exists():
                vectorstore = InMemoryVectorStore.load_local(vectorstore_path)
            else:
                vectorstore = InMemoryVectorStore()
            kwargs["vectorstore"] = vectorstore

        if memory_type == "combined":
            sub_memories = []
            for sub in config.get("memories", []):
                sub_type = sub.get("type", "buffer")
                sub_cls = cls.MEMORY_TYPES.get(sub_type, ConversationBufferMemory)
                sub_kwargs = dict(sub.get("kwargs", {}))
                if sub_type in {"summary", "entity", "kg"}:
                    from ..llm.ollama_llm import OllamaLLM

                    sub_kwargs["llm"] = OllamaLLM.from_config(config.get("llm", {}))
                if sub_type == "vectorstore":
                    sub_kwargs["vectorstore"] = InMemoryVectorStore()
                sub_memories.append(sub_cls(**sub_kwargs))
            memory: BaseMemory = CombinedMemory(memories=sub_memories)
        else:
            history_path = config.get("history_path") or (
                Path(storage_path) / "sessions" / f"{session_id}.json"
            )
            kwargs["chat_memory"] = FileChatMessageHistory(history_path)
            memory = memory_cls(**kwargs)

        return cls(
            session_id=session_id,
            memory=memory,
            storage_path=storage_path,
            checkpoint_enabled=config.get("checkpoint_enabled", True),
        )
