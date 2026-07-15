"""Conversation knowledge graph memory."""

import re
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from ..core.base_chat_message_history import BaseChatMessageHistory
from ..core.base_memory import BaseMemory
from ..core.messages import AIMessage, HumanMessage
from ..history.in_memory import ChatMessageHistory
from ..llm.base import BaseLLM
from ..utils.json import parse_json


class ConversationKGMemory(BaseMemory):
    """Memory that builds a knowledge graph of entities and relationships."""

    DEFAULT_KNOWLEDGE_TRIPLE_EXTRACTION_TEMPLATE = """
You are a knowledge graph extraction assistant. Given some conversation, extract entities and relationships between them.
Return a JSON list of triples of the form ["subject", "predicate", "object"].

Conversation:
{history}

JSON list of triples:
""".strip()

    def __init__(
        self,
        llm: BaseLLM,
        memory_key: str = "history",
        input_key: Optional[str] = None,
        output_key: Optional[str] = None,
        return_messages: bool = False,
        chat_memory: Optional[BaseChatMessageHistory] = None,
        knowledge_extraction_prompt: Optional[str] = None,
        human_prefix: str = "Human",
        ai_prefix: str = "AI",
    ):
        self.llm = llm
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self._return_messages = return_messages
        self.chat_memory = chat_memory or ChatMessageHistory()
        self.knowledge_extraction_prompt = (
            knowledge_extraction_prompt or self.DEFAULT_KNOWLEDGE_TRIPLE_EXTRACTION_TEMPLATE
        )
        self.human_prefix = human_prefix
        self.ai_prefix = ai_prefix
        self.knowledge_graph: nx.DiGraph = nx.DiGraph()

    @property
    def memory_variables(self) -> List[str]:
        return [self.memory_key]

    @property
    def return_messages(self) -> bool:
        return self._return_messages

    def _get_buffer_string(self) -> str:
        string_messages = []
        for m in self.chat_memory.messages:
            if isinstance(m, HumanMessage):
                prefix = self.human_prefix
            elif isinstance(m, AIMessage):
                prefix = self.ai_prefix
            else:
                prefix = m.type.capitalize()
            string_messages.append(f"{prefix}: {m.content}")
        return "\n".join(string_messages)

    def get_knowledge_triples(self) -> List[Tuple[str, str, str]]:
        return [
            (u, data.get("relation", ""), v)
            for u, v, data in self.knowledge_graph.edges(data=True)
        ]

    def _extract_triples(self) -> List[Tuple[str, str, str]]:
        history = self._get_buffer_string()
        if not history.strip():
            return []
        prompt = self.knowledge_extraction_prompt.format(history=history)
        try:
            result = parse_json(self.llm.predict(prompt))
            triples = []
            for item in result:
                if isinstance(item, (list, tuple)) and len(item) == 3:
                    triples.append(tuple(str(x).strip() for x in item))
            return triples
        except Exception:
            return []

    def load_memory_variables(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        history = self._get_buffer_string()
        triples = self.get_knowledge_triples()
        if triples:
            facts = "\n".join(f"- {s} {p} {o}" for s, p, o in triples)
            context = f"{history}\n\nKnown facts:\n{facts}"
        else:
            context = history
        if self.return_messages:
            return {self.memory_key: [HumanMessage(content=context)]}
        return {self.memory_key: context}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        input_key = self.input_key or list(inputs.keys())[0]
        output_key = self.output_key or list(outputs.keys())[0]
        human_msg = HumanMessage(content=str(inputs[input_key]))
        ai_msg = AIMessage(content=str(outputs[output_key]))
        self.chat_memory.add_message(human_msg)
        self.chat_memory.add_message(ai_msg)

        triples = self._extract_triples()
        for subject, predicate, obj in triples:
            self.knowledge_graph.add_edge(subject, obj, relation=predicate)

    def clear(self) -> None:
        self.chat_memory.clear()
        self.knowledge_graph.clear()

    def to_dict(self) -> Dict[str, Any]:
        from ..core.messages import messages_to_dict

        return {
            "memory_key": self.memory_key,
            "return_messages": self.return_messages,
            "triples": [
                [u, data.get("relation", ""), v]
                for u, v, data in self.knowledge_graph.edges(data=True)
            ],
            "messages": messages_to_dict(self.chat_memory.messages),
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        from ..core.messages import messages_from_dict

        self._return_messages = data.get("return_messages", self._return_messages)
        self.chat_memory = ChatMessageHistory(messages=messages_from_dict(data.get("messages", [])))
        self.knowledge_graph.clear()
        for subject, predicate, obj in data.get("triples", []):
            self.knowledge_graph.add_edge(subject, obj, relation=predicate)
