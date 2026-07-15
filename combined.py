"""Combined memory."""

from typing import Any, Dict, List

from ..core.base_memory import BaseMemory


class CombinedMemory(BaseMemory):
    """Combine multiple memory sources."""

    def __init__(self, memories: List[BaseMemory]) -> None:
        self.memories = memories

    @property
    def memory_variables(self) -> List[str]:
        variables = []
        for m in self.memories:
            variables.extend(m.memory_variables)
        return variables

    @property
    def return_messages(self) -> bool:
        return any(m.return_messages for m in self.memories)

    def load_memory_variables(self, inputs: Dict[str, Any] | None = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for m in self.memories:
            result.update(m.load_memory_variables(inputs))
        return result

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        for m in self.memories:
            m.save_context(inputs, outputs)

    def clear(self) -> None:
        for m in self.memories:
            m.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memories": [
                {"type": m.__class__.__name__, "data": m.to_dict()}
                for m in self.memories
            ]
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        # Concrete restoration requires type registry mapping; leave to caller.
        pass
