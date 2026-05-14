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

    def probe(self) -> bool:
        """Lightweight probe to validate API base_url and api_key. Tries a few common endpoints.

        Returns True on a successful HTTP 200 response, False otherwise.
        """
        candidates = [f"{self.base_url}/v1/models", f"{self.base_url}/models", f"{self.base_url}"]
        for url in candidates:
            try:
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                req = request.Request(url, headers=headers, method="GET")
                with request.urlopen(req, timeout=10) as resp:
                    if resp.getcode() == 200:
                        return True
            except Exception:
                continue
        return False


class OpenAIAdapter(ProviderAdapter):
    @property
    def supports_vision(self) -> bool:
        return True


class GroqAdapter(OpenAIAdapter):
    """Groq is fully OpenAI-compatible; no payload translation needed."""

    @property
    def supports_vision(self) -> bool:
        return True


class CloudflareAdapter(ProviderAdapter):
    @property
    def supports_vision(self) -> bool:
        # Cloudflare Workers-based endpoints may support images, but conservatively treat as text-only
        return False

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Cloudflare Workers AI OpenAI-compatible endpoint:
        # https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions
        account_id = getattr(self.config, "cloudflare_account_id", None)
        if account_id:
            url = f"{self.base_url}/accounts/{account_id}/ai/v1{path}"
        else:
            url = f"{self.base_url}{path}"

        # Cloudflare expects json_schema and may reject json_object.
        cf_payload = dict(payload)
        rf = cf_payload.get("response_format")
        if isinstance(rf, dict) and rf.get("type") == "json_object":
            cf_payload.pop("response_format", None)

        body = json.dumps(cf_payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(http_request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))


class NvidiaAdapter(ProviderAdapter):
    @property
    def supports_vision(self) -> bool:
        # NVIDIA inference endpoints may support vision depending on model; treat as text-only by default
        return False

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Some configs use legacy NGC base URL which is not OpenAI chat-compatible.
        base = self.base_url
        if "api.ngc.nvidia.com" in base:
            base = "https://integrate.api.nvidia.com/v1"
        url = f"{base}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(http_request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))


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
    if key == "groq" or "groq" in (base_url or ""):
        return GroqAdapter(name, api_key, base_url, config)
    return ProviderAdapter(name, api_key, base_url, config)
