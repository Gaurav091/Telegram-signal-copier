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
import shelve

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

        # Optional persistent cache (shelve) to survive restarts
        self._persistent_db = None
        if getattr(self.config, "ai_persistent_cache", False):
            try:
                path = getattr(self.config, "ai_cache_path") or str(self.config.project_root / "ai_cache.db")
                self._persistent_db = shelve.open(str(path), writeback=False)
            except Exception:
                self._persistent_db = None

        # Simple token-bucket rate limiter (requests per minute)
        self._capacity = max(1, int(self.config.ai_max_requests_per_minute))
        self._tokens = float(self._capacity)
        self._last_refill = time.time()
        self._token_lock = threading.Lock()

        # Lock for provider iteration
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
        result = self._call_with_fallbacks("/chat/completions", payload, image_path=image_path, require_vision=has_vision)
        try:
            message_content = result["choices"][0]["message"]["content"]
            if isinstance(message_content, str):
                return json.loads(message_content)
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
        system_prompt = (
            "You are a trading signal intent classifier for a Telegram-to-MT5 copier system. "
            "Classify the intent of the incoming message into exactly one of:\n"
            "  NEW_TRADE_SIGNAL  — A fresh entry signal (buy/sell) with at least one of: entry zone, SL, TP. "
            "Includes chart images showing colored entry/SL/TP zones even if there is no text.\n"
            "  CHART_ANALYSIS    — A chart image with zones/levels posted that could be a new signal but lacks "
            "explicit buy/sell direction; requires deeper analysis.\n"
            "  TRADE_UPDATE      — An update on an existing position: TP hit, SL hit, move SL, partial close, "
            "congratulations, pips booked, add to position.\n"
            "  INFORMATIONAL     — Market commentary, news, announcements, educational content, general opinion. "
            "Not directly tradeable.\n"
            "\nSignals of a NEW_TRADE_SIGNAL chart: colored rectangular zones (green=TP zone, red/pink=SL zone), "
            "multi-timeframe analysis charts, clearly marked entry zones.\n"
            "Signs of TRADE_UPDATE: words like 'TP hit', 'TP1 done', 'pips', 'move SL', 'closed', "
            "'congratulations', 'partial close', screenshots of broker P&L showing closed trades.\n"
            "\nReturn strict JSON: {\"intent\": \"...\", \"confidence\": 0.0-1.0, \"reasoning\": \"brief text\"}"
        )
        content: list[dict[str, Any]] = [
            {"type": "text", "text": raw_text or "(no text — analyze image only)"}
        ]
        if image_path:
            content.append({"type": "image_url", "image_url": {"url": self._image_data_url(Path(image_path))}})
        intent_payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
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
            return json.loads(msg) if isinstance(msg, str) else msg
        except Exception as exc:
            return {"intent": "UNKNOWN", "confidence": 0.0, "reasoning": str(exc)}

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
            "You are a precise trading chart level extractor. Extract EXACT numeric stop-loss and take-profit "
            "price levels from the chart image.\n\n"
            "COMMON VISUAL PATTERNS IN THESE CHARTS:\n"
            "- COLORED RECTANGULAR ZONES are the primary trading signals:\n"
            "  * GREEN/TEAL zones = take-profit / buy-target area. "
            "Read the UPPER boundary price from the Y-axis scale (right side) as TP level. "
            "Multiple green zones = multiple TP targets (TP1 = nearest, TP2 = further).\n"
            "  * RED/PINK/SALMON zones = stop-loss area or short-target area. "
            "Read the UPPER boundary from Y-axis as the stop-loss price.\n"
            "  * PURPLE/MAUVE/LAVENDER zones = secondary target, DCA zone, or informational zone.\n"
            "- Y-AXIS (right side of chart): shows numeric price scale — read values aligned with zone edges.\n"
            "- Chart title top-left: shows symbol (e.g. 'Gold Spot / U.S. Dollar' = XAUUSD, '3' = 3-min chart).\n"
            "- If multiple timeframe views are shown side-by-side, use the most zoomed-in view for exact levels.\n\n"
            "INSTRUCTIONS:\n"
            "1. Locate RED/PINK zone → read UPPER edge price from Y-axis = stop_loss.\n"
            "2. Locate GREEN zone(s) → read UPPER edge price from Y-axis for each = take_profits list.\n"
            "3. confidence = 0-1 reflecting clarity of zone boundaries and Y-axis label visibility.\n"
            "4. Return ONLY levels you can clearly see. Do not invent values.\n\n"
            "Return strict JSON: stop_loss (number or null), take_profits (array of numbers, empty if none), "
            "confidence (0 to 1), notes (string)."
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
    def _build_chat_payload(
        self,
        raw_text: str,
        image_path: str | None,
        all_image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are an expert trading signal analyst for a Telegram-to-MT5 signal copier. "
            "Extract a COMPLETE trading signal from the provided text and/or chart image(s).\n\n"
            "CHART IMAGE VISUAL PATTERNS (very important):\n"
            "- COLORED RECTANGULAR ZONES are the key signals from these chart types:\n"
            "  * GREEN/TEAL rectangular zones = take-profit / buy-target area. "
            "The UPPER edge of the green zone (read from the Y-axis price scale on the right) is the TP level. "
            "The LOWER edge of the green zone is the entry/buy zone. "
            "Multiple green zones = multiple take-profit targets.\n"
            "  * RED/PINK/SALMON zones = stop-loss zone. "
            "The UPPER edge of the red zone is the stop-loss price.\n"
            "  * PURPLE/MAUVE zones = secondary target, DCA/add zone, or informational.\n"
            "- Y-AXIS (right side of chart): numeric price scale — read values at zone boundaries.\n"
            "- Chart header shows symbol: 'Gold Spot / U.S. Dollar' = XAUUSD. "
            "Timeframe shown after symbol (3 = 3-min, 5 = 5-min, 15 = 15-min).\n"
            "- If price is moving UP toward a green zone above = BUY/LONG signal. "
            "If price moving DOWN toward green zone below = SELL/SHORT signal.\n"
            "- Multiple charts side-by-side showing same zone = confirmation across timeframes.\n\n"
            "TEXT SIGNAL PATTERNS:\n"
            "- Parse: BUY/SELL direction, entry price (or range like 4744/4740), SL level, TP level(s).\n"
            "- Entry range: set entry_price = midpoint, entry_range_low + entry_range_high = bounds.\n\n"
            "RULES:\n"
            "- Image is PRIMARY evidence when present; text is secondary/confirmation.\n"
            "- Do NOT treat TP-hit, congratulations, pips-done, or result messages as new signals.\n"
            "- If a fresh entry zone is shown alongside an update text, still extract as new signal.\n\n"
            "Return strict JSON with keys: symbol, side, order_type, entry_price, "
            "entry_range_low, entry_range_high, stop_loss, take_profits, confidence, notes. "
            "side must be BUY, SELL, or null. "
            "order_type: MARKET, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, or null. "
            "take_profits: array of numbers. confidence: 0 to 1. Missing fields: null."
        )
        has_vision = bool(image_path or all_image_paths)
        content: list[dict[str, Any]] = [{"type": "text", "text": raw_text or "(analyze chart image)"}]
        # Add images — primary first, then additional charts (cap at 4 to avoid token overflow)
        img_paths: list[str] = []
        if image_path:
            img_paths.append(image_path)
        if all_image_paths:
            for p in all_image_paths:
                if p and p not in img_paths:
                    img_paths.append(p)
        for img in img_paths[:4]:
            content.append({"type": "image_url", "image_url": {"url": self._image_data_url(Path(img))}})
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content if has_vision else raw_text},
            ],
        }
        return payload

    def _call_with_fallbacks(self, path: str, payload: dict[str, Any], image_path: str | None = None, require_vision: bool = False) -> dict[str, Any]:
        # Cache key based on payload JSON and image bytes hash
        cache_key = self._compute_cache_key(payload, image_path)
        # Check persistent cache first
        if self._persistent_db is not None:
            try:
                if cache_key in self._persistent_db:
                    entry = self._persistent_db[cache_key]
                    if (time.time() - entry[0]) < self.config.ai_cache_ttl_seconds:
                        return entry[1]
            except Exception:
                pass
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
                    if self._persistent_db is not None:
                        try:
                            self._persistent_db[cache_key] = (time.time(), result)
                            # sync to disk
                            try:
                                self._persistent_db.sync()
                            except Exception:
                                pass
                        except Exception:
                            pass
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
