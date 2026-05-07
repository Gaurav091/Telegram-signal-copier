from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from telegram_signal_copier.config import AppConfig


class OpenAIClient:
    def __init__(self, config: AppConfig) -> None:
        self.model = config.openai_model
        # build providers list from config in preferred order
        self.providers: list[dict[str, str]] = []
        for p in config.ai_providers:
            # ensure base_url normalized
            self.providers.append({
                "name": p.get("name"),
                "api_key": p.get("api_key"),
                "base_url": (p.get("base_url") or "").rstrip("/"),
            })

    def parse_signal(self, raw_text: str, image_path: str | None = None) -> dict[str, Any]:
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
        response = self._post_json("/chat/completions", payload)
        message_content = response["choices"][0]["message"]["content"]
        if not isinstance(message_content, str):
            raise ValueError("Unexpected AI response payload")
        return json.loads(message_content)

    def extract_chart_levels(
        self,
        image_path: str,
        symbol: str | None = None,
        side: str | None = None,
        entry_price: float | None = None,
    ) -> dict[str, Any]:
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
        response = self._post_json("/chat/completions", payload)
        message_content = response["choices"][0]["message"]["content"]
        if not isinstance(message_content, str):
            raise ValueError("Unexpected AI response payload")
        return json.loads(message_content)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.providers:
            raise RuntimeError("No AI providers configured")

        provider_errors: list[str] = []
        # Try providers in order
        for provider in self.providers:
            name = provider.get("name") or "unnamed"
            api_key = provider.get("api_key")
            base_url = provider.get("base_url") or ""
            if not api_key or not base_url:
                provider_errors.append(f"{name}: missing api_key or base_url")
                continue

            max_attempts = 5
            for attempt in range(max_attempts):
                try:
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
                        return json.loads(response.read().decode("utf-8"))
                except error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="replace")
                    # On rate limit, exponential backoff and retry the same provider
                    if exc.code == 429 and attempt < max_attempts - 1:
                        wait_time = 2 ** attempt
                        time.sleep(wait_time)
                        continue
                    provider_errors.append(f"{name}: {exc.code} {detail}")
                    break
                except Exception as exc:  # network errors, etc.
                    provider_errors.append(f"{name}: {exc}")
                    break

        raise RuntimeError("All AI providers failed: " + " | ".join(provider_errors))

    @staticmethod
    def _image_data_url(path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"