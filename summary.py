"""Conversation summary memory."""

from typing import Any, Dict, List, Optional

from ..core.base_chat_message_history import BaseChatMessageHistory
from ..core.base_memory import BaseMemory
from ..core.messages import AIMessage, HumanMessage
from ..history.in_memory import ChatMessageHistory
from ..llm.base import BaseLLM


class ConversationSummaryMemory(BaseMemory):
    """Memory that maintains a running summary of the conversation."""

    DEFAULT_SUMMARIZER_TEMPLATE = """
Progressively summarize the lines of conversation provided, adding onto the previous summary returning a new summary.

EXAMPLE
Current summary:
The human asks what the AI thinks of artificial intelligence. The AI thinks artificial intelligence is a force for good.

New lines of conversation:
Human: Why do you think artificial intelligence is a force for good?
AI: Because it will help humans reach their full potential.

New summary:
The human asks what the AI thinks of artificial intelligence. The AI thinks artificial intelligence is a force for good because it will help humans reach their full potential.
END OF EXAMPLE

Current summary:
{summary}

New lines of conversation:
{new_lines}

New summary:
""".strip()

    def __init__(
        self,
        llm: BaseLLM,
        memory_key: str = "history",
        input_key: Optional[str] = None,
        output_key: Optional[str] = None,
        return_messages: bool = False,
        chat_memory: Optional[BaseChatMessageHistory] = None,
        prompt_template: Optional[str] = None,
        human_prefix: str = "Human",
        ai_prefix: str = "AI",
    ):
        self.llm = llm
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self._return_messages = return_messages
        self.chat_memory = chat_memory or ChatMessageHistory()
        self.prompt_template = prompt_template or self.DEFAULT_SUMMARIZER_TEMPLATE
        self.human_prefix = human_prefix
        self.ai_prefix = ai_prefix
        self.buffer: str = ""

    @property
    def memory_variables(self) -> List[str]:
        return [self.memory_key]

    @property
    def return_messages(self) -> bool:
        return self._return_messages

    def predict_new_summary(
        self, messages: List[Any], existing_summary: str
    ) -> str:
        new_lines = self._get_buffer_string(messages)
        prompt = self.prompt_template.format(summary=existing_summary, new_lines=new_lines)
        return self.llm.predict(prompt).strip()

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

    def load_memory_variables(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.return_messages:
            return {self.memory_key: [HumanMessage(content=self.buffer)]}
        return {self.memory_key: self.buffer}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        input_key = self.input_key or list(inputs.keys())[0]
        output_key = self.output_key or list(outputs.keys())[0]
        human_msg = HumanMessage(content=str(inputs[input_key]))
        ai_msg = AIMessage(content=str(outputs[output_key]))
        self.chat_memory.add_message(human_msg)
        self.chat_memory.add_message(ai_msg)
        self.buffer = self.predict_new_summary(
            self.chat_memory.messages[-2:], self.buffer
        )

    def clear(self) -> None:
        self.chat_memory.clear()
        self.buffer = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_key": self.memory_key,
            "return_messages": self.return_messages,
            "buffer": self.buffer,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        self._return_messages = data.get("return_messages", self._return_messages)
        self.buffer = data.get("buffer", "")
