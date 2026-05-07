from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import threading
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.adapters.provider_adapters import get_adapter


class OpenAIClient:
    """AI orchestration client with provider adapters, caching, rate-limiting, and circuit-breakers.

    Assigns text vs vision tasks to providers based on declared capabilities and runtime health.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.model = config.openai_model

        # Build provider states from config in preferred order
        self.providers: list[dict[str, Any]] = []
        now = time.time()
        for p in config.ai_providers:
            base_url = (p.get("base_url") or "").rstrip("/")
            name = p.get("name") or "unnamed"
            adapter = get_adapter(name, p.get("api_key"), base_url, config)
            self.providers.append(
                {
                    "name": name,
                    "adapter": adapter,
                    "api_key": p.get("api_key"),
                    "base_url": base_url,
                    "supports_vision": adapter.supports_vision,
                    "failure_count": 0,
                    "trip_until": 0.0,
                    "last_failure": 0.0,
                }
            )

        # In-memory cache for identical requests (raw_text + image hash)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cache_lock = threading.Lock()

        # Simple token-bucket rate limiter (requests per minute)
        self._capacity = max(1, int(self.config.ai_max_requests_per_minute))
        self._tokens = float(self._capacity)
        self._last_refill = time.time()
        self._token_lock = threading.Lock()

        # Lock for provider iteration
        self._provider_lock = threading.Lock()

    # ---- Public API -----------------------------------------------------------------
    def parse_signal(self, raw_text: str, image_path: str | None = None) -> dict[str, Any]:
        # prefer providers that support vision when image is present
        payload = self._build_chat_payload(raw_text, image_path)
        result = self._call_with_fallbacks("/chat/completions", payload, image_path=image_path, require_vision=bool(image_path))
        # Normalize to inner JSON payload expected by callers
        try:
            message_content = result["choices"][0]["message"]["content"]
            if isinstance(message_content, str):
                return json.loads(message_content)
            if isinstance(message_content, dict):
                return message_content
        except Exception:
            # Fall back to returning whatever came back
            return result

    def extract_chart_levels(
        self,
        image_path: str,
        symbol: str | None = None,
        side: str | None = None,
        entry_price: float | None = None,
    ) -> dict[str, Any]:
        # Chart level extraction is vision-only; require a vision-capable provider
        context_parts: list[str] = []
        if symbol:
            context_parts.append(f"Symbol: {symbol}")
        if side:
            context_parts.append(f"Expected direction: {side}")
        if entry_price is not None:
            context_parts.append(f"Entry price already identified: {entry_price}")
        context = ", ".join(context_parts) if context_parts else "Unknown symbol and direction"
        system_prompt = (
            "You are analyzing a trading chart image to identify key price levels for risk management. "
            "Look for visually marked stop loss and take profit levels, horizontal lines, "
            "support and resistance zones, and any annotated price labels on the chart. "
            "Return strict JSON with keys: stop_loss, take_profits, confidence, notes. "
            "stop_loss must be a number or null. take_profits must be an array of numbers (can be empty). "
            "confidence must be 0 to 1 reflecting how clearly the levels are visible in the chart. "
            "Only return levels you can see clearly marked or labelled in the image. "
            "Do not invent levels that are not visible. If no levels are visible return null and empty array."
        )
        content: list[dict[str, Any]] = [
            {"type": "text", "text": f"Chart context: {context}. Identify stop loss and take profit levels from the chart."},
            {"type": "image_url", "image_url": {"url": self._image_data_url(Path(image_path))}},
        ]
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        }
        result = self._call_with_fallbacks("/chat/completions", payload, image_path=image_path, require_vision=True)
        try:
            message_content = result["choices"][0]["message"]["content"]
            if isinstance(message_content, str):
                return json.loads(message_content)
            if isinstance(message_content, dict):
                return message_content
        except Exception:
            return result

    # ---- Internal helpers -----------------------------------------------------------
    def _build_chat_payload(self, raw_text: str, image_path: str | None) -> dict[str, Any]:
        system_prompt = (
            "Extract a trading signal from Telegram content and chart images. "
            "Treat image content as primary evidence when an image is present. "
            "If a caption says NEW, NEW TRADE, or just NEW and the image contains a fresh buy or sell setup with entry, SL, or TP, extract it as a new actionable signal. "
            "Do not treat result updates like pips done, points done, TP hit, SL hit, or profit booked as a new signal unless a fresh entry with SL or TP is also present. "
            "If entry is shown as a range like 4744/4740, set entry_price to the first number and populate entry_range_low and entry_range_high with the lower and upper bounds. "
            "Return strict JSON with keys: symbol, side, order_type, entry_price, "
            "entry_range_low, entry_range_high, stop_loss, take_profits, confidence, notes. "
            "side must be BUY, SELL, or null. order_type must be MARKET, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, or null. "
            "take_profits must be an array of numbers. confidence must be 0 to 1. "
            "If field is missing, use null."
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": raw_text}]
        if image_path:
            content.append({"type": "image_url", "image_url": {"url": self._image_data_url(Path(image_path))}})
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content if image_path else raw_text},
            ],
        }
        return payload

    def _call_with_fallbacks(self, path: str, payload: dict[str, Any], image_path: str | None = None, require_vision: bool = False) -> dict[str, Any]:
        # Cache key based on payload JSON and image bytes hash
        cache_key = self._compute_cache_key(payload, image_path)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and (time.time() - cached[0]) < self.config.ai_cache_ttl_seconds:
                return cached[1]

        # Enforce global rate limit via token bucket
        if not self._acquire_token():
            raise RuntimeError("AI global rate limit exceeded")

        provider_errors: list[str] = []
        now = time.time()

        # Choose candidates: prefer vision-capable providers when vision required
        with self._provider_lock:
            candidates = [p for p in self.providers if (not require_vision) or p.get("supports_vision")]
            # fallback: if none support vision but vision not strictly required, allow any
            if require_vision and not candidates:
                provider_errors.append("No vision-capable providers configured")
                raise RuntimeError("No vision-capable providers configured")

            for provider in candidates:
                name = provider.get("name") or "unnamed"
                api_key = provider.get("api_key")
                base_url = provider.get("base_url") or ""
                if not api_key or not base_url:
                    provider_errors.append(f"{name}: missing api_key or base_url")
                    continue

                # Skip providers currently tripped
                if provider.get("trip_until", 0) > now:
                    provider_errors.append(f"{name}: tripped until {provider['trip_until']}")
                    continue

                try:
                    adapter = provider.get("adapter")
                    if adapter is None:
                        # fallback: simple HTTP POST
                        body = json.dumps(payload).encode("utf-8")
                        http_request = request.Request(
                            f"{base_url}{path}",
                            data=body,
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            method="POST",
                        )
                        with request.urlopen(http_request, timeout=60) as response:
                            result = json.loads(response.read().decode("utf-8"))
                    else:
                        result = adapter.post(path, payload)

                    # Success: reset provider failure state
                    provider["failure_count"] = 0
                    provider["trip_until"] = 0.0
                    # Cache and return
                    with self._cache_lock:
                        self._cache[cache_key] = (time.time(), result)
                    return result
                except error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="replace")
                    # On rate limit -> increase failure and trip provider
                    if exc.code == 429:
                        self._record_provider_failure(provider, exc)
                        provider_errors.append(f"{name}: 429 {detail}")
                        continue
                    # Non-retryable for this payload
                    provider_errors.append(f"{name}: {exc.code} {detail}")
                    # mark as failed but not tripped
                    provider["failure_count"] = provider.get("failure_count", 0) + 1
                    provider["last_failure"] = time.time()
                    continue
                except Exception as exc:
                    provider_errors.append(f"{name}: {exc}")
                    self._record_provider_failure(provider, exc)
                    continue

        raise RuntimeError("All AI providers failed: " + " | ".join(provider_errors))

    def _record_provider_failure(self, provider: dict[str, Any], exc: Exception) -> None:
        now = time.time()
        base = max(1, self.config.ai_provider_cooldown_seconds)
        max_cool = max(1, self.config.ai_provider_max_cooldown_seconds)
        provider["failure_count"] = provider.get("failure_count", 0) + 1
        # exponential backoff on trips
        cooldown = min(max_cool, base * (2 ** (provider["failure_count"] - 1)))
        provider["trip_until"] = now + cooldown
        provider["last_failure"] = now

    def _acquire_token(self) -> bool:
        with self._token_lock:
            now = time.time()
            # refill tokens proportional to time passed
            elapsed = now - self._last_refill
            if elapsed > 0:
                # refill per minute
                refill = (elapsed / 60.0) * self._capacity
                self._tokens = min(float(self._capacity), self._tokens + refill)
                self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def _compute_cache_key(self, payload: dict[str, Any], image_path: str | None) -> str:
        h = hashlib.sha256()
        h.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
        if image_path:
            try:
                data = Path(image_path).read_bytes()
                h.update(hashlib.sha256(data).digest())
            except Exception:
                # if image unreadable, incorporate path only
                h.update(image_path.encode("utf-8"))
        return h.hexdigest()

    @staticmethod
    def _image_data_url(path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
