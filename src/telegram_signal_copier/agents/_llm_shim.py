"""Stdlib-only LLM shim — drop-in replacement for langchain_openai.ChatOpenAI.

Wraps the existing ``OpenAIClient`` (which already uses only ``urllib``,
``json``, and other stdlib modules) so the agent pipeline has zero dependency
on ``langchain``, ``langgraph``, ``openai``, or ``pydantic``.

Usage (same interface as ChatOpenAI)::

    from telegram_signal_copier.agents._llm_shim import SimpleLLM
    llm = SimpleLLM(openai_client)
    response = llm.invoke([
        {"role": "system", "content": "..."},
        {"role": "user",   "content": "..."},
    ])
    text = response.content   # str
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telegram_signal_copier.adapters.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class _Response:
    """Minimal response wrapper exposing ``.content`` (mirrors langchain AIMessage)."""

    __slots__ = ("content",)

    def __init__(self, content: str) -> None:
        self.content = content


def _to_openai_msg(msg: Any) -> dict[str, Any]:
    """Normalise a message to an OpenAI ``{"role": ..., "content": ...}`` dict.

    Accepts:
    * Plain dicts (already in OpenAI format).
    * Legacy langchain message objects that have ``.type`` and ``.content``
      (kept for transitional backward-compat).
    """
    if isinstance(msg, dict):
        return msg
    # langchain HumanMessage / SystemMessage / AIMessage
    role_map = {"human": "user", "system": "system", "ai": "assistant"}
    raw_type = getattr(msg, "type", "human")
    role = role_map.get(raw_type, "user")
    content = getattr(msg, "content", str(msg))
    return {"role": role, "content": content}


class SimpleLLM:
    """Stdlib replacement for ``langchain_openai.ChatOpenAI``.

    Delegates all HTTP work to ``OpenAIClient._call_with_fallbacks`` which
    already implements provider rotation, circuit-breaking, caching and
    rate-limiting using only Python standard-library modules.
    """

    def __init__(self, client: "OpenAIClient") -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invoke(self, messages: list[Any]) -> _Response:
        """Call the LLM and return a response with a ``.content`` attribute.

        Parameters
        ----------
        messages:
            List of message dicts ``{"role": ..., "content": ...}`` or
            langchain message objects.  Vision content is supported — include
            ``{"type": "image_url", "image_url": {"url": "data:..."}}`` blocks
            in the user message ``content`` list.
        """
        normalized = [_to_openai_msg(m) for m in messages]

        # Detect whether any message contains inline image blocks so the
        # provider selector can route to a vision-capable backend.
        has_image = any(
            isinstance(m.get("content"), list)
            and any(
                isinstance(b, dict) and b.get("type") == "image_url"
                for b in m["content"]
            )
            for m in normalized
        )

        payload: dict[str, Any] = {
            "model": self._client.model,
            "temperature": 0,
            # Request structured JSON output.  CloudflareAdapter strips this
            # automatically if the endpoint doesn't support it.
            "response_format": {"type": "json_object"},
            "messages": normalized,
        }

        result = self._client._call_with_fallbacks(
            "/chat/completions",
            payload,
            image_path=None,
            require_vision=has_image,
        )

        content = result["choices"][0]["message"]["content"]
        # Some providers return content as a list of typed blocks.
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        return _Response(str(content))
