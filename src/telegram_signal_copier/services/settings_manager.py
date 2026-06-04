"""Settings manager for loading/saving configuration dynamically.

Stores parameters in a JSON file inside the project root directory.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SettingsManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.settings_path = self.project_root / "settings.json"
        self._cache: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        """Load settings from JSON file, falling back to defaults."""
        if not self.settings_path.exists():
            self._cache = self._get_defaults()
            self.save()
            return self._cache

        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            # Ensure defaults are populated if missing in JSON
            defaults = self._get_defaults()
            for key, val in defaults.items():
                if key not in data:
                    data[key] = val
            self._cache = data
            return data
        except Exception as exc:
            logger.error("Failed to load settings.json: %s — using defaults", exc)
            self._cache = self._get_defaults()
            return self._cache

    def save(self) -> None:
        """Save settings cache to JSON file."""
        try:
            self.project_root.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as exc:
            logger.error("Failed to save settings.json: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self.save()

    def _get_defaults(self) -> dict[str, Any]:
        """Default application parameters."""
        return {
            "telegram_api_id": "",
            "telegram_api_hash": "",
            "telegram_phone_number": "",
            "telegram_session_name": "telegram-signal-copier",
            "telegram_sources": [],
            "openai_api_key": "",
            "openai_model": "gpt-4o-mini",
            "openai_base_url": "https://api.openai.com/v1",
            "mt5_symbol_suffix": "",
            "default_volume": 0.01,
            "minimum_confidence": 0.45,
            "approval_required_below": 0.45,
            "allowed_symbols": ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "ETHUSD"],
            "dry_run": False,
            "minimum_rr_ratio": 0.0,
            
            # Filtering
            "enable_time_filter": False,
            "time_from": "00:00",
            "time_to": "23:59",
            "enable_sessions_filter": False,
            "session_asian": True,
            "session_london": True,
            "session_new_york": True,
            
            # Custom Keywords (Buy / Sell)
            "custom_buy_keywords": ["LONG", "CALL", "BULLISH", "BUY"],
            "custom_sell_keywords": ["SHORT", "PUT", "BEARISH", "SELL"]
        }
