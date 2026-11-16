"""Talking to the AI model. Any OpenAI-compatible chat API works (set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL).

Uses only the standard library so the backend has few dependencies. Tests use FakeLLM.
"""
import json
import urllib.request
from typing import Protocol


class LLM(Protocol):
    def chat_json(self, system: str, user: str) -> dict: ...


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    def chat_json(self, system: str, user: str) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.load(resp)
        return json.loads(data["choices"][0]["message"]["content"])


class FakeLLM:
    """Returns scripted replies; records every prompt. For tests and local demos without an API key."""

    def __init__(self, replies: list[dict] | None = None):
        self.replies = list(replies or [])
        self.calls: list[tuple[str, str]] = []

    def chat_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if self.replies:
            return self.replies.pop(0)
        return {"answer": "Demo answer", "follow_up": "", "found_in_notes": False, "used_sources": []}
