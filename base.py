"""Vector store abstractions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Document:
    page_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """Abstract vector store."""

    @abstractmethod
    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Add texts and return their IDs."""

    @abstractmethod
    def similarity_search(
        self, query: str, k: int = 4, filter: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Return the k most similar documents to the query."""

    def add_documents(self, documents: List[Document]) -> List[str]:
        return self.add_texts(
            [d.page_content for d in documents],
            metadatas=[d.metadata for d in documents],
        )

    @abstractmethod
    def save_local(self, directory: str) -> None:
        """Persist vector store to disk."""

    @classmethod
    @abstractmethod
    def load_local(cls, directory: str) -> "VectorStore":
        """Load vector store from disk."""
