"""JSON file backed chat history."""

import json
import os
from pathlib import Path
from typing import List

from ..core.base_chat_message_history import BaseChatMessageHistory
from ..core.messages import BaseMessage, messages_from_dict, messages_to_dict


class FileChatMessageHistory(BaseChatMessageHistory):
    """Chat history persisted to a JSON file on disk."""

    def __init__(self, file_path: str | os.PathLike) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._messages: List[BaseMessage] = []
        self._load()

    def _load(self) -> None:
        if not self.file_path.exists():
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._messages = messages_from_dict(data)
        except (json.JSONDecodeError, ValueError):
            self._messages = []

    def _save(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(messages_to_dict(self._messages), f, indent=2, ensure_ascii=False)

    def add_message(self, message: BaseMessage) -> None:
        self._messages.append(message)
        self._save()

    def get_messages(self) -> List[BaseMessage]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()
        self._save()
