"""Shared test fixtures."""

import pytest

from bella_memory.llm.base import BaseLLM


class FakeLLM(BaseLLM):
    """A deterministic LLM for tests."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def predict(self, prompt, stop=None):
        self.calls.append(prompt)
        for key, value in self.responses.items():
            if key in prompt:
                return value
        return "fake response"


@pytest.fixture
def fake_llm():
    return FakeLLM()
