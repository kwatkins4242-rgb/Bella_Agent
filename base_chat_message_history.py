"""Abstract history interface."""

from abc import ABC, abstractmethod
from typing import List

from .messages import BaseMessage


class BaseChatMessageHistory(ABC):
    """Interface for a chat message history store."""

    @abstractmethod
    def add_message(self, message: BaseMessage) -> None:
        """Add a message to the store."""

    @abstractmethod
    def get_messages(self) -> List[BaseMessage]:
        """Retrieve all messages in the store."""

    @abstractmethod
    def clear(self) -> None:
        """Clear the store."""

    def add_user_message(self, content: str) -> None:
        from .messages import HumanMessage

        self.add_message(HumanMessage(content=content))

    def add_ai_message(self, content: str) -> None:
        from .messages import AIMessage

        self.add_message(AIMessage(content=content))

    @property
    def messages(self) -> List[BaseMessage]:
        return self.get_messages()

    def __len__(self) -> int:
        return len(self.get_messages())

    def __bool__(self) -> bool:
        return bool(self.get_messages())
