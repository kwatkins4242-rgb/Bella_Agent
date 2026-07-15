"""Pure local in-memory vector store using sklearn cosine similarity."""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from .base import Document, VectorStore


class InMemoryVectorStore(VectorStore):
    """Local, zero-cost vector store. Embeddings via a configurable embedder."""

    def __init__(
        self,
        embedding_function: Optional[Callable[[str], List[float]]] = None,
        documents: Optional[List[Document]] = None,
        embeddings: Optional[List[List[float]]] = None,
        ids: Optional[List[str]] = None,
    ):
        self.embedding_function = embedding_function or self._default_embedding
        self.documents: List[Document] = list(documents or [])
        self.embeddings: List[np.ndarray] = [
            np.array(e, dtype=np.float32) for e in (embeddings or [])
        ]
        self.ids: List[str] = list(ids or [])

    def _default_embedding(self, text: str) -> List[float]:
        """Fallback: simple hashed character-ngram vector with fixed dimension."""
        dim = 128
        vec = np.zeros(dim, dtype=np.float32)
        text = text.lower()
        for i in range(len(text) - 2):
            ngram = text[i : i + 3]
            idx = hash(ngram) % dim
            vec[idx] += 1
        norm = np.linalg.norm(vec)
        if norm == 0:
            return [0.0] * dim
        return (vec / norm).tolist()

    def _embed(self, text: str) -> np.ndarray:
        vec = self.embedding_function(text)
        return np.array(vec, dtype=np.float32)

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        ids = []
        for i, text in enumerate(texts):
            doc_id = str(uuid.uuid4())
            metadata = (metadatas or [{}])[i] if metadatas else {}
            self.documents.append(Document(page_content=text, metadata=metadata))
            self.embeddings.append(self._embed(text))
            self.ids.append(doc_id)
            ids.append(doc_id)
        return ids

    def add_documents(self, documents: List[Document]) -> List[str]:
        return self.add_texts(
            [d.page_content for d in documents],
            metadatas=[d.metadata for d in documents],
        )

    def similarity_search(
        self, query: str, k: int = 4, filter: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        if not self.embeddings:
            return []
        query_vec = self._embed(query).reshape(1, -1)
        embeddings = np.stack(self.embeddings)
        # Cosine similarity requires consistent dimensionality
        if query_vec.shape[1] != embeddings.shape[1]:
            # Re-embed existing docs with current embedder to match dimensions
            embeddings = np.stack([self._embed(d.page_content) for d in self.documents])
        scores = cosine_similarity(query_vec, embeddings)[0]
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)
        results: List[Document] = []
        for idx, score in indexed:
            doc = self.documents[idx]
            if filter and not all(doc.metadata.get(k) == v for k, v in filter.items()):
                continue
            results.append(Document(
                page_content=doc.page_content,
                metadata={**doc.metadata, "score": float(score)},
            ))
            if len(results) >= k:
                break
        return results

    def save_local(self, directory: str) -> None:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        data = {
            "ids": self.ids,
            "documents": [
                {"page_content": d.page_content, "metadata": d.metadata}
                for d in self.documents
            ],
            "embeddings": [e.tolist() for e in self.embeddings],
        }
        with open(path / "vectorstore.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load_local(cls, directory: str) -> "InMemoryVectorStore":
        path = Path(directory)
        with open(path / "vectorstore.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        store = cls()
        store.ids = data.get("ids", [])
        store.documents = [
            Document(page_content=d["page_content"], metadata=d.get("metadata", {}))
            for d in data.get("documents", [])
        ]
        store.embeddings = [np.array(e, dtype=np.float32) for e in data.get("embeddings", [])]
        return store
