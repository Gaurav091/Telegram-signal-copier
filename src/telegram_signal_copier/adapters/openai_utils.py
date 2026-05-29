"""Utility helpers shared across the OpenAI client.

Extracted from openai_client.py for maintainability:
  - json_from_text   — parse model response to dict
  - image_data_url   — encode image as data URI
  - compute_cache_key — hash payload + image for cache key
  - build_providers  — construct provider state list from config
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telegram_signal_copier.config import AppConfig
    from telegram_signal_copier.adapters.provider_adapters import get_adapter as _get_adapter_type  # noqa: F401


def json_from_text(text: str) -> dict[str, Any]:
    """Parse a model response that may contain fenced or embedded JSON."""
    import re

    # Fast path: strict JSON already
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Extract fenced JSON blocks
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        parsed = json.loads(fence_match.group(1))
        if isinstance(parsed, dict):
            return parsed

    # Extract first JSON object substring
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Model response did not contain JSON object")


def image_data_url(path: Path) -> str:
    """Encode an image file as a data URI for API payloads."""
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def compute_cache_key(payload: dict[str, Any], image_path: str | None) -> str:
    """Compute a SHA-256 cache key from payload + optional image bytes."""
    h = hashlib.sha256()
    h.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    if image_path:
        try:
            data = Path(image_path).read_bytes()
            h.update(hashlib.sha256(data).digest())
        except Exception:
            h.update(image_path.encode("utf-8"))
    return h.hexdigest()


def build_providers(config: "AppConfig") -> list[dict[str, Any]]:
    """Build the provider state list from the AppConfig AI providers."""
    import time
    from telegram_signal_copier.adapters.provider_adapters import get_adapter

    providers: list[dict[str, Any]] = []
    now = time.time()
    _ = now  # used to document when the snapshot was taken

    for p in config.ai_providers:
        base_url = (p.get("base_url") or "").rstrip("/")
        name = p.get("name") or "unnamed"
        adapter = get_adapter(name, p.get("api_key"), base_url, config)
        providers.append(
            {
                "name": name,
                "adapter": adapter,
                "api_key": p.get("api_key"),
                "base_url": base_url,
                "model": p.get("model") or config.openai_model,
                "vision_model": p.get("vision_model") or p.get("model") or config.openai_model,
                "supports_vision": adapter.supports_vision,
                "failure_count": 0,
                "hard_fail_count": 0,
                "trip_until": 0.0,
                "last_failure": 0.0,
                "disabled_until": 0.0,
                "disabled_reason": "",
            }
        )
    return providers
