from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import error, request

from telegram_signal_copier.config import AppConfig


class ProviderAdapter:
    def __init__(self, name: str, api_key: str | None, base_url: str, config: AppConfig) -> None:
        self.name = name or "unnamed"
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.config = config

    @property
    def supports_vision(self) -> bool:
        return False

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(http_request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))


class OpenAIAdapter(ProviderAdapter):
    @property
    def supports_vision(self) -> bool:
        return True


class CloudflareAdapter(ProviderAdapter):
    @property
    def supports_vision(self) -> bool:
        # Cloudflare Workers-based endpoints may support images, but conservatively treat as text-only
        return False

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        # If account id provided, prefer a namespaced endpoint
        account_id = getattr(self.config, "cloudflare_account_id", None)
        if account_id:
            url = f"{self.base_url}/accounts/{account_id}{path}"
        else:
            url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(http_request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))


class NvidiaAdapter(ProviderAdapter):
    @property
    def supports_vision(self) -> bool:
        # NVIDIA inference endpoints may support vision depending on model; treat as text-only by default
        return False


class CerebrasAdapter(ProviderAdapter):
    @property
    def supports_vision(self) -> bool:
        # Treat as text-only unless configured otherwise
        return False


def get_adapter(name: str, api_key: str | None, base_url: str, config: AppConfig) -> ProviderAdapter:
    key = (name or "").lower()
    if key in {"primary", "openai"} or "openai" in (base_url or ""):
        return OpenAIAdapter(name, api_key, base_url, config)
    if key == "cloudflare" or "cloudflare" in (base_url or ""):
        return CloudflareAdapter(name, api_key, base_url, config)
    if key == "nvidia" or "nvidia" in (base_url or ""):
        return NvidiaAdapter(name, api_key, base_url, config)
    if key == "cerebras" or "cerebras" in (base_url or ""):
        return CerebrasAdapter(name, api_key, base_url, config)
    return ProviderAdapter(name, api_key, base_url, config)
