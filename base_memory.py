"""Abstract memory interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseMemory(ABC):
    """Base interface for memory classes."""

    @property
    @abstractmethod
    def memory_variables(self) -> List[str]:
        """Input/output keys this memory exposes."""

    @abstractmethod
    def load_memory_variables(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return memory variables to add to chain/agent inputs."""

    @abstractmethod
    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Save context from this conversation turn."""

    @abstractmethod
    def clear(self) -> None:
        """Clear memory contents."""

    @property
    def return_messages(self) -> bool:
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize memory state to a dict. Override in concrete classes."""
        return {}

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore memory state from a dict. Override in concrete classes."""
        pass
