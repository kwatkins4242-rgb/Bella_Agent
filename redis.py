"""Redis backed chat history."""

import json
from typing import Any, List

from ..core.base_chat_message_history import BaseChatMessageHistory
from ..core.messages import BaseMessage, messages_from_dict, messages_to_dict


class RedisChatMessageHistory(BaseChatMessageHistory):
    """Chat history persisted to Redis. Requires redis package."""

    def __init__(
        self,
        session_id: str,
        url: str = "redis://localhost:6379/0",
        key_prefix: str = "bella_memory:",
        redis_client: Any | None = None,
    ) -> None:
        import redis as redis_lib

        self.session_id = session_id
        self.key_prefix = key_prefix
        self.redis = redis_client or redis_lib.from_url(url)
        self.key = f"{key_prefix}{session_id}"

    def add_message(self, message: BaseMessage) -> None:
        self.redis.rpush(self.key, json.dumps(message.to_dict(), ensure_ascii=False))

    def get_messages(self) -> List[BaseMessage]:
        raw = self.redis.lrange(self.key, 0, -1)
        return messages_from_dict([json.loads(item) for item in raw])

    def clear(self) -> None:
        self.redis.delete(self.key)
