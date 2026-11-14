"""Thin wrapper around the Anthropic SDK. One model ID for everyone (LORE_MODEL)."""
import json
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .config import get_settings

_client: anthropic.Anthropic | None = None


class LLMError(Exception):
    pass


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, u: Any) -> None:
        self.calls += 1
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0

    def as_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens}


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key or None)
    return _client


def complete(
    system: str,
    messages: list[dict],
    usage: Usage,
    schema: dict | None = None,
    effort: str = "medium",
    max_tokens: int = 16000,
) -> Any:
    """Return parsed JSON when `schema` is given, otherwise the text answer."""
    output_config: dict[str, Any] = {"effort": effort}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    resp = client().beta.messages.create(
        model=get_settings().lore_model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config=output_config,
        # On a policy decline the API retries on a fallback model inside the same call
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    usage.add(resp.usage)
    if resp.stop_reason == "refusal":
        raise LLMError("The model declined this request")
    if resp.stop_reason == "max_tokens":
        raise LLMError("The model ran out of output tokens")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text) if schema is not None else text
