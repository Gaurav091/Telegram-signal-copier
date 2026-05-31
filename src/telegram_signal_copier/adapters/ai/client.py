"""OpenAI-compatible AI client with multi-key round-robin, caching, and circuit-breaking.

All HTTP is delegated to ProviderAdapter.post() or performed inline with requests.
Do not add aiohttp or urllib.request here.
"""
from __future__ import annotations

import json
import shelve
import threading
import time
import warnings
from pathlib import Path
from typing import Any

import requests

from telegram_signal_copier.adapters.ai_cache import AIResponseCache
from telegram_signal_copier.adapters.circuit_breaker import CircuitBreaker
from telegram_signal_copier.adapters.openai_prompts import (
    CLASSIFY_INTENT_SYSTEM_PROMPT,
    EXTRACT_CHART_LEVELS_SYSTEM_PROMPT,
    PARSE_SIGNAL_SYSTEM_PROMPT,
)
from telegram_signal_copier.adapters.openai_utils import (
    build_providers,
    compute_cache_key,
    image_data_url,
    json_from_text,
)
from telegram_signal_copier.config import AppConfig


class OpenAIClient:
    """AI orchestration client with provider adapters, caching, rate-limiting, and circuit-breakers.
    Assigns text vs vision tasks to providers based on declared capabilities and runtime health.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.model = config.openai_model
        self.providers: list[dict[str, Any]] = build_providers(config)

        # AI response cache (in-memory + optional persistence)
        _persistent_db = None
        if getattr(self.config, "ai_persistent_cache", False):
            try:
                path = getattr(self.config, "ai_cache_path") or str(self.config.project_root / "ai_cache.db")
                _persistent_db = shelve.open(str(path), writeback=False)
            except Exception:
                import logging as _logging
                _logging.getLogger(__name__).debug("Could not open persistent AI cache", exc_info=True)
        self._ai_cache = AIResponseCache(
            ttl_seconds=self.config.ai_cache_ttl_seconds,
            persistent_db=_persistent_db,
        )
        self._cache_lock = threading.Lock()

        # Circuit breaker
        self._circuit_breaker = CircuitBreaker(
            base_cooldown_seconds=self.config.ai_provider_cooldown_seconds,
            max_cooldown_seconds=self.config.ai_provider_max_cooldown_seconds,
        )

        # Token-bucket rate limiter
        self._capacity = max(1, int(self.config.ai_max_requests_per_minute))
        self._tokens = float(self._capacity)
        self._last_refill = time.time()
        self._token_lock = threading.Lock()
        self._provider_lock = threading.Lock()

    # ---- Public API -----------------------------------------------------------------

    def parse_signal(
        self,
        raw_text: str,
        image_path: str | None = None,
        all_image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Parse a trading signal from text and/or chart image(s)."""
        has_vision = bool(image_path or all_image_paths)
        payload = self._build_chat_payload(raw_text, image_path, all_image_paths)
        try:
            result = self._call_with_fallbacks("/chat/completions", payload, image_path=image_path, require_vision=has_vision)
        except Exception as vision_exc:
            if not has_vision:
                raise
            text_payload = self._build_chat_payload(raw_text, None, None)
            result = self._call_with_fallbacks("/chat/completions", text_payload, image_path=None, require_vision=False)
            try:
                parsed_fallback = result["choices"][0]["message"]["content"]
                parsed_obj = json_from_text(parsed_fallback) if isinstance(parsed_fallback, str) else parsed_fallback
                if isinstance(parsed_obj, dict):
                    notes = parsed_obj.get("notes")
                    if isinstance(notes, list):
                        notes.append(f"Vision providers unavailable; used text-only AI fallback: {vision_exc}")
                    elif isinstance(notes, str) and notes.strip():
                        parsed_obj["notes"] = notes + f" | Vision providers unavailable; used text-only AI fallback: {vision_exc}"
                    else:
                        parsed_obj["notes"] = f"Vision providers unavailable; used text-only AI fallback: {vision_exc}"
                    return parsed_obj
            except Exception:
                pass
        try:
            message_content = result["choices"][0]["message"]["content"]
            if isinstance(message_content, str):
                return json_from_text(message_content)
            if isinstance(message_content, dict):
                return message_content
        except Exception:
            return result

    def classify_intent(
        self,
        raw_text: str,
        image_path: str | None = None,
    ) -> dict[str, Any]:
        """Classify message intent before deciding how to process it.

        Returns a dict with keys: intent, confidence, reasoning.
        Intent values: NEW_TRADE_SIGNAL | TRADE_UPDATE | INFORMATIONAL | CHART_ANALYSIS
        """
        content: list[dict[str, Any]] = [
            {"type": "text", "text": raw_text or "(no text — analyze image only)"}
        ]
        if image_path:
            content.append({"type": "image_url", "image_url": {"url": image_data_url(Path(image_path))}})
        intent_payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": CLASSIFY_INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        }
        try:
            result = self._call_with_fallbacks(
                "/chat/completions",
                intent_payload,
                image_path=image_path,
                require_vision=bool(image_path),
            )
            msg = result["choices"][0]["message"]["content"]
            return json_from_text(msg) if isinstance(msg, str) else msg
        except Exception as exc:
            return {"intent": "UNKNOWN", "confidence": 0.0, "reasoning": str(exc)}

    def extract_chart_levels(
        self,
        image_path: str,
        symbol: str | None = None,
        side: str | None = None,
        entry_price: float | None = None,
    ) -> dict[str, Any]:
        """Extract stop-loss and take-profit levels from a chart image."""
        context_parts: list[str] = []
        if symbol:
            context_parts.append(f"Symbol: {symbol}")
        if side:
            context_parts.append(f"Expected direction: {side}")
        if entry_price is not None:
            context_parts.append(f"Entry price already identified: {entry_price}")
        context = ", ".join(context_parts) if context_parts else "Unknown symbol and direction"
        content: list[dict[str, Any]] = [
            {"type": "text", "text": f"Chart context: {context}. Identify stop loss and take profit levels from the chart."},
            {"type": "image_url", "image_url": {"url": image_data_url(Path(image_path))}},
        ]
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": EXTRACT_CHART_LEVELS_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        }
        result = self._call_with_fallbacks("/chat/completions", payload, image_path=image_path, require_vision=True)
        try:
            message_content = result["choices"][0]["message"]["content"]
            if isinstance(message_content, str):
                return json_from_text(message_content)
            if isinstance(message_content, dict):
                return message_content
        except Exception:
            return result

    # ---- Internal helpers -----------------------------------------------------------

    def _build_chat_payload(
        self,
        raw_text: str,
        image_path: str | None,
        all_image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        has_vision = bool(image_path or all_image_paths)
        content: list[dict[str, Any]] = [{"type": "text", "text": raw_text or "(analyze chart image)"}]
        img_paths: list[str] = []
        if image_path:
            img_paths.append(image_path)
        if all_image_paths:
            for p in all_image_paths:
                if p and p not in img_paths:
                    img_paths.append(p)
        for img in img_paths[:4]:
            content.append({"type": "image_url", "image_url": {"url": image_data_url(Path(img))}})
        return {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": PARSE_SIGNAL_SYSTEM_PROMPT},
                {"role": "user", "content": content if has_vision else raw_text},
            ],
        }

    def _call_with_fallbacks(
        self,
        path: str,
        payload: dict[str, Any],
        image_path: str | None = None,
        require_vision: bool = False,
    ) -> dict[str, Any]:
        cache_key = compute_cache_key(payload, image_path)
        cached = self._ai_cache.get(cache_key)
        if cached is not None:
            return cached

        if not self._acquire_token():
            raise RuntimeError("AI global rate limit exceeded")

        provider_errors: list[str] = []

        with self._provider_lock:
            candidates = [p for p in self.providers if (not require_vision) or p.get("supports_vision")]
            if require_vision and not candidates:
                raise RuntimeError("No vision-capable providers configured")

            for provider in candidates:
                name = provider.get("name") or "unnamed"
                api_key = provider.get("api_key")
                base_url = provider.get("base_url") or ""
                if not api_key or not base_url:
                    provider_errors.append(f"{name}: missing api_key or base_url")
                    continue

                if self._circuit_breaker.is_open(provider):
                    reason = provider.get("disabled_reason") or f"tripped until {provider.get('trip_until', 0)}"
                    provider_errors.append(f"{name}: {reason}")
                    continue

                provider_payload = dict(payload)
                provider_payload["model"] = (
                    provider.get("vision_model") if require_vision else provider.get("model")
                ) or self.model

                try:
                    adapter = provider.get("adapter")
                    if adapter is None:
                        headers = {
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        }
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            http_resp = requests.post(
                                f"{base_url}{path}",
                                json=provider_payload,
                                headers=headers,
                                timeout=60,
                                verify=False,
                            )
                        http_resp.raise_for_status()
                        result = http_resp.json()
                    else:
                        result = adapter.post(path, provider_payload)

                    self._circuit_breaker.record_success(provider)
                    self._ai_cache.put(cache_key, result)
                    return result
                except requests.exceptions.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response is not None else 0
                    detail = exc.response.text if exc.response is not None else str(exc)
                    if status_code == 429:
                        self._circuit_breaker.record_failure(provider, exc, kind="rate_limit")
                        provider_errors.append(f"{name}: 429 {detail}")
                        continue
                    provider_errors.append(f"{name}: {status_code} {detail}")
                    self._circuit_breaker.record_hard_failure(provider, status_code, detail)
                    continue
                except Exception as exc:
                    provider_errors.append(f"{name}: {exc}")
                    self._circuit_breaker.record_failure(provider, exc, kind="network")
                    continue

        raise RuntimeError("All AI providers failed: " + " | ".join(provider_errors))

    def _acquire_token(self) -> bool:
        with self._token_lock:
            now = time.time()
            elapsed = now - self._last_refill
            if elapsed > 0:
                refill = (elapsed / 60.0) * self._capacity
                self._tokens = min(float(self._capacity), self._tokens + refill)
                self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


