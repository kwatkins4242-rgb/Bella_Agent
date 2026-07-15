"""Vector store retriever memory."""

from typing import Any, Dict, List, Optional

from ..core.base_memory import BaseMemory
from ..vectorstore.base import VectorStore


class VectorStoreRetrieverMemory(BaseMemory):
    """Memory that retrieves relevant historical context from a vector store."""

    def __init__(
        self,
        vectorstore: VectorStore,
        memory_key: str = "history",
        input_key: Optional[str] = None,
        output_key: Optional[str] = None,
        return_messages: bool = False,
        k: int = 4,
        search_kwargs: Optional[Dict[str, Any]] = None,
    ):
        self.vectorstore = vectorstore
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self._return_messages = return_messages
        self.k = k
        self.search_kwargs = search_kwargs or {}

    @property
    def memory_variables(self) -> List[str]:
        return [self.memory_key]

    @property
    def return_messages(self) -> bool:
        return self._return_messages

    def load_memory_variables(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        inputs = inputs or {}
        query_key = self.input_key or list(inputs.keys())[0] if inputs else "input"
        query = str(inputs.get(query_key, ""))
        docs = self.vectorstore.similarity_search(
            query, k=self.k, **self.search_kwargs
        )
        if self.return_messages:
            from ..core.messages import HumanMessage
            return {self.memory_key: [HumanMessage(content=doc.page_content) for doc in docs]}
        return {self.memory_key: "\n".join(doc.page_content for doc in docs)}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        input_key = self.input_key or list(inputs.keys())[0]
        output_key = self.output_key or list(outputs.keys())[0]
        text = f"Human: {inputs[input_key]}\nAI: {outputs[output_key]}"
        self.vectorstore.add_texts([text])

    def clear(self) -> None:
        # Clear is store-specific; for in-memory we reset lists
        self.vectorstore.documents.clear()
        self.vectorstore.embeddings.clear()
        self.vectorstore.ids.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_key": self.memory_key,
            "return_messages": self.return_messages,
            "k": self.k,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        self._return_messages = data.get("return_messages", self._return_messages)
        self.k = data.get("k", self.k)
