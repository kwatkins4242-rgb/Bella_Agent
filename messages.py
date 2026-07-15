"""Chat message types for Bella Memory."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class BaseMessage(BaseModel):
    """Base class for all messages."""

    content: Union[str, List[Union[str, Dict[str, Any]]]]
    type: str = "base"
    name: Optional[str] = None
    additional_kwargs: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content,
            "name": self.name,
            "additional_kwargs": self.additional_kwargs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseMessage":
        msg_type = data.get("type", "base")
        mapping = {
            "human": HumanMessage,
            "ai": AIMessage,
            "system": SystemMessage,
            "function": FunctionMessage,
            "tool": ToolMessage,
        }
        target = mapping.get(msg_type, cls)
        return target(
            content=data.get("content", ""),
            name=data.get("name"),
            additional_kwargs=data.get("additional_kwargs", {}),
        )

    def __str__(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return str(self.content)


class HumanMessage(BaseMessage):
    """Message from a human/user."""

    type: str = "human"


class AIMessage(BaseMessage):
    """Message from an AI assistant."""

    type: str = "ai"


class SystemMessage(BaseMessage):
    """System instruction message."""

    type: str = "system"


class FunctionMessage(BaseMessage):
    """Message produced by a function call."""

    type: str = "function"


class ToolMessage(BaseMessage):
    """Message produced by a tool call."""

    type: str = "tool"


def messages_to_dict(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    return [m.to_dict() for m in messages]


def messages_from_dict(data: List[Dict[str, Any]]) -> List[BaseMessage]:
    return [BaseMessage.from_dict(d) for d in data]
