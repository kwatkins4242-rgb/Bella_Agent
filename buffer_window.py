"""Conversation buffer window memory."""

from typing import Any, Dict, List, Optional

from ..core.base_chat_message_history import BaseChatMessageHistory
from ..core.base_memory import BaseMemory
from ..core.messages import AIMessage, HumanMessage
from ..history.in_memory import ChatMessageHistory


class ConversationBufferWindowMemory(BaseMemory):
    """Memory that stores the last k exchanges."""

    def __init__(
        self,
        memory_key: str = "history",
        input_key: Optional[str] = None,
        output_key: Optional[str] = None,
        return_messages: bool = False,
        k: int = 5,
        chat_memory: Optional[BaseChatMessageHistory] = None,
        human_prefix: str = "Human",
        ai_prefix: str = "AI",
    ):
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self._return_messages = return_messages
        self.k = k
        self.chat_memory = chat_memory or ChatMessageHistory()
        self.human_prefix = human_prefix
        self.ai_prefix = ai_prefix

    @property
    def memory_variables(self) -> List[str]:
        return [self.memory_key]

    @property
    def return_messages(self) -> bool:
        return self._return_messages

    def _windowed_messages(self) -> List[Any]:
        messages = self.chat_memory.messages
        return messages[-self.k * 2 :] if self.k else list(messages)

    def load_memory_variables(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        windowed = self._windowed_messages()
        if self.return_messages:
            return {self.memory_key: windowed}
        return {self.memory_key: self._get_buffer_string(windowed)}

    def _get_buffer_string(self, messages: List[Any]) -> str:
        string_messages = []
        for m in messages:
            if isinstance(m, HumanMessage):
                prefix = self.human_prefix
            elif isinstance(m, AIMessage):
                prefix = self.ai_prefix
            else:
                prefix = m.type.capitalize()
            string_messages.append(f"{prefix}: {m.content}")
        return "\n".join(string_messages)

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        input_key = self.input_key or list(inputs.keys())[0]
        output_key = self.output_key or list(outputs.keys())[0]
        self.chat_memory.add_message(HumanMessage(content=str(inputs[input_key])))
        self.chat_memory.add_message(AIMessage(content=str(outputs[output_key])))

    def clear(self) -> None:
        self.chat_memory.clear()

    def to_dict(self) -> Dict[str, Any]:
        from ..core.messages import messages_to_dict

        return {
            "memory_key": self.memory_key,
            "return_messages": self.return_messages,
            "k": self.k,
            "messages": messages_to_dict(self.chat_memory.messages),
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        from ..core.messages import messages_from_dict

        self._return_messages = data.get("return_messages", self._return_messages)
        self.k = data.get("k", self.k)
        self.chat_memory = ChatMessageHistory(messages=messages_from_dict(data.get("messages", [])))
