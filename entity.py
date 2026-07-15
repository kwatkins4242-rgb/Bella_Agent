"""Conversation entity memory."""

import re
from typing import Any, Dict, List, Optional

from ..core.base_chat_message_history import BaseChatMessageHistory
from ..core.base_memory import BaseMemory
from ..core.messages import AIMessage, HumanMessage
from ..history.in_memory import ChatMessageHistory
from ..llm.base import BaseLLM
from ..utils.json import parse_json


class ConversationEntityMemory(BaseMemory):
    """Memory that extracts and stores facts about entities mentioned in conversation."""

    DEFAULT_ENTITY_EXTRACTION_TEMPLATE = """
You are an entity extraction assistant. Extract all entities (people, places, organizations, things) mentioned in the following conversation. Return a JSON list of strings.

Conversation:
{history}

JSON list of entities:
""".strip()

    DEFAULT_ENTITY_SUMMARIZATION_TEMPLATE = """
You are updating a knowledge base about entities. Given the current known summary for an entity and new lines of conversation, produce an updated summary.

Entity: {entity}
Current summary: {summary}

New lines:
{new_lines}

Updated summary (plain text, 1-3 sentences):
""".strip()

    def __init__(
        self,
        llm: BaseLLM,
        memory_key: str = "history",
        input_key: Optional[str] = None,
        output_key: Optional[str] = None,
        return_messages: bool = False,
        chat_memory: Optional[BaseChatMessageHistory] = None,
        entity_extraction_prompt: Optional[str] = None,
        entity_summarization_prompt: Optional[str] = None,
        k: Optional[int] = None,
        human_prefix: str = "Human",
        ai_prefix: str = "AI",
    ):
        self.llm = llm
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self._return_messages = return_messages
        self.chat_memory = chat_memory or ChatMessageHistory()
        self.entity_extraction_prompt = (
            entity_extraction_prompt or self.DEFAULT_ENTITY_EXTRACTION_TEMPLATE
        )
        self.entity_summarization_prompt = (
            entity_summarization_prompt or self.DEFAULT_ENTITY_SUMMARIZATION_TEMPLATE
        )
        self.k = k
        self.human_prefix = human_prefix
        self.ai_prefix = ai_prefix
        self.entity_store: Dict[str, str] = {}

    @property
    def memory_variables(self) -> List[str]:
        return [self.memory_key, "entities"]

    @property
    def return_messages(self) -> bool:
        return self._return_messages

    def _buffer_messages(self) -> List[Any]:
        messages = self.chat_memory.messages
        if self.k is not None:
            return messages[-self.k * 2 :]
        return messages

    def _get_buffer_string(self, messages: Optional[List[Any]] = None) -> str:
        messages = messages or self._buffer_messages()
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

    def _extract_entities(self) -> List[str]:
        history = self._get_buffer_string()
        if not history.strip():
            return []
        prompt = self.entity_extraction_prompt.format(history=history)
        try:
            result = parse_json(self.llm.predict(prompt))
            if isinstance(result, list):
                return [str(e).strip() for e in result if str(e).strip()]
            return []
        except Exception:
            return []

    def _summarize_entity(self, entity: str, new_lines: str) -> str:
        summary = self.entity_store.get(entity, "")
        prompt = self.entity_summarization_prompt.format(
            entity=entity, summary=summary, new_lines=new_lines
        )
        return self.llm.predict(prompt).strip()

    def _get_new_lines(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> str:
        input_key = self.input_key or list(inputs.keys())[0]
        output_key = self.output_key or list(outputs.keys())[0]
        return f"{self.human_prefix}: {inputs[input_key]}\n{self.ai_prefix}: {outputs[output_key]}"

    def load_memory_variables(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        history = self._get_buffer_string()
        entities = []
        for entity, summary in self.entity_store.items():
            entities.append(f"{entity}: {summary}")
        entity_context = "\n".join(entities)
        combined = history
        if entity_context:
            combined += f"\n\nKnown facts about entities:\n{entity_context}"
        if self.return_messages:
            return {self.memory_key: [HumanMessage(content=combined)]}
        return {self.memory_key: combined, "entities": self.entity_store}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        input_key = self.input_key or list(inputs.keys())[0]
        output_key = self.output_key or list(outputs.keys())[0]
        human_msg = HumanMessage(content=str(inputs[input_key]))
        ai_msg = AIMessage(content=str(outputs[output_key]))
        self.chat_memory.add_message(human_msg)
        self.chat_memory.add_message(ai_msg)

        new_lines = self._get_new_lines(inputs, outputs)
        entities = self._extract_entities()
        for entity in entities:
            self.entity_store[entity] = self._summarize_entity(entity, new_lines)

    def clear(self) -> None:
        self.chat_memory.clear()
        self.entity_store.clear()

    def to_dict(self) -> Dict[str, Any]:
        from ..core.messages import messages_to_dict

        return {
            "memory_key": self.memory_key,
            "return_messages": self.return_messages,
            "entity_store": dict(self.entity_store),
            "messages": messages_to_dict(self.chat_memory.messages),
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        from ..core.messages import messages_from_dict

        self._return_messages = data.get("return_messages", self._return_messages)
        self.entity_store = dict(data.get("entity_store", {}))
        self.chat_memory = ChatMessageHistory(messages=messages_from_dict(data.get("messages", [])))
