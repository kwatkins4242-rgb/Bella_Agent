"""Ollama / OpenAI-compatible LLM wrapper."""

import json
import os
from typing import Any, Dict, List, Optional

import requests

from .base import BaseLLM


class OllamaLLM(BaseLLM):
    """LLM wrapper for Ollama chat/completion endpoints.

    Defaults to the remote Ollama host from your config if no base_url is given.
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.model = model
        self.base_url = (
            base_url
            or os.getenv("OLLAMA_BASE_URL", "http://100.58.95.110:11434")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY") or os.getenv("BELLA_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.headers = headers or {}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    def _chat_url(self) -> str:
        # Handle both raw Ollama URLs and OpenAI compatible endpoints
        if "/v1" in self.base_url:
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/api/chat"

    def _is_ollama_endpoint(self) -> bool:
        return "/api/chat" in self._chat_url()

    def predict(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.predict_messages(messages, stop=stop)

    def predict_messages(
        self, messages: List[Dict[str, Any]], stop: Optional[List[str]] = None
    ) -> str:
        url = self._chat_url()
        if self._is_ollama_endpoint():
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.temperature},
            }
            if stop:
                payload["options"]["stop"] = stop
        else:
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if stop:
                payload["stop"] = stop

        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json", **self.headers},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        if self._is_ollama_endpoint():
            return data.get("message", {}).get("content", "")
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "OllamaLLM":
        """Instantiate from a config dict / env overrides."""
        return cls(
            model=config.get("model", os.getenv("OLLAMA_MODEL", "llama3.1:8b")),
            base_url=config.get("base_url", os.getenv("OLLAMA_BASE_URL")),
            api_key=config.get("api_key", os.getenv("BELLA_API_KEY")),
            temperature=float(config.get("temperature", 0.2)),
            max_tokens=int(config.get("max_tokens", 4096)),
        )
