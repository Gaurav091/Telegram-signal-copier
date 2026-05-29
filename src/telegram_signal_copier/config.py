from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from telegram_signal_copier.config_helpers import (
    APP_HOME_ENV,
    SOURCE_SPEC_SEPARATOR,
    _bool_env,
    _build_env_kwargs,
    _csv_env,
    _default_bridge_root,
    _default_project_root,
    _load_first_dotenv,
    _parse_source_spec,
    _validate_telegram_source_values,
    build_ai_providers,
)


class ConfigurationError(ValueError):
    """Raised when one or more configuration values are invalid.

    Collects all issues before raising so the user sees every problem at once.
    """

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("Configuration errors:\n" + "\n".join(f"  • {i}" for i in issues))


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    bridge_inbox_dir: Path
    bridge_outbox_dir: Path
    telegram_api_id: str | None
    telegram_api_hash: str | None
    telegram_phone_number: str | None
    telegram_session_name: str
    telegram_sources: list[str]
    openai_api_key: str | None
    openai_model: str
    openai_base_url: str
    minimum_confidence: float
    default_volume: float
    allowed_symbols: list[str]
    dry_run: bool
    approval_required_below: float
    poll_interval_seconds: float
    minimum_rr_ratio: float = 1.5  # Minimum risk:reward ratio for agent validation
    openai_vision_model: str | None = None
    # optional telegram fields
    telegram_bot_token: str | None = None
    telegram_username: str | None = None
    telegram_user_id: str | None = None
    telegram_first_name: str | None = None
    # optional AI provider fallbacks
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    cloudflare_base_url: str = "https://api.cloudflare.com/client/v4"
    nvidia_cloudname: str | None = None
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    cerebras_api_key: str | None = None
    cerebras_base_url: str = "https://api.cerebras.net/v1"
    # Groq API (optional)
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    cloudflare_model: str | None = None
    nvidia_model: str | None = None
    cerebras_model: str | None = None
    groq_model: str | None = None
    # AI usage tuning
    ai_max_requests_per_minute: int = 60
    ai_provider_cooldown_seconds: int = 60
    ai_provider_max_cooldown_seconds: int = 3600
    ai_cache_ttl_seconds: int = 300
    # persistent cache for AI responses (optional)
    ai_persistent_cache: bool = False
    ai_cache_path: str = ""
    # Per-source heuristic-only (comma-separated labels or identifiers)
    telegram_heuristic_only: list[str] = None
    # MT5 bridge timeout
    mt5_bridge_timeout_seconds: float = 60.0
    # Optional broker symbol suffix to append when writing bridge commands (e.g. 'm')
    mt5_symbol_suffix: str = ""
    # Auto-add new symbols discovered in incoming signals
    auto_add_new_symbols: bool = False
    # Path to persist dynamic symbols (one per line). If empty, defaults to bridge folder/dynamic_symbols.txt
    dynamic_symbols_file: str = ""
    # runtime cache for dynamic symbols (not part of env)
    _dynamic_symbols_cache: set[str] = None

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "AppConfig":
        root = (project_root or _default_project_root()).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        _load_first_dotenv(root)
        return cls(**_build_env_kwargs(root))

    def ensure_runtime_dirs(self) -> None:
        self.bridge_inbox_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_outbox_dir.mkdir(parents=True, exist_ok=True)
        # ensure dynamic symbols file exists when using auto-add
        if self.auto_add_new_symbols:
            try:
                path = self.dynamic_symbols_path
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text("", encoding="utf-8")
            except Exception:
                pass

    def validate(self) -> None:
        """Validate all configuration values and raise :class:`ConfigurationError` listing every issue.

        Call this once at startup after :meth:`from_env` to surface all problems at once.
        """
        issues: list[str] = []

        if not self.telegram_api_id:
            issues.append("TELEGRAM_API_ID is required")
        if not self.telegram_api_hash:
            issues.append("TELEGRAM_API_HASH is required")
        if not self.telegram_phone_number:
            issues.append("TELEGRAM_PHONE_NUMBER is required")
        if not self.telegram_sources:
            issues.append("TELEGRAM_SOURCES must contain at least one source")

        # Validate source values are numeric
        try:
            _validate_telegram_source_values(self.telegram_sources)
        except ValueError as exc:
            issues.append(str(exc))

        if self.minimum_confidence < 0.0 or self.minimum_confidence > 1.0:
            issues.append(
                f"MINIMUM_CONFIDENCE must be between 0 and 1 (got {self.minimum_confidence})"
            )
        if self.default_volume <= 0:
            issues.append(f"DEFAULT_VOLUME must be positive (got {self.default_volume})")

        if issues:
            raise ConfigurationError(issues)

    @property
    def telegram_source_mappings(self) -> list[tuple[str, str]]:
        mappings: list[tuple[str, str]] = []
        for source in self.telegram_sources:
            label, identifier = _parse_source_spec(source)
            if identifier:
                mappings.append((label, identifier))
        return mappings

    @property
    def telegram_source_labels(self) -> list[str]:
        return [label for label, _ in self.telegram_source_mappings]

    @property
    def telegram_source_identifiers(self) -> list[str]:
        return [identifier for _, identifier in self.telegram_source_mappings]

    def is_source_heuristic_only(self, source_group: str) -> bool:
        if not source_group:
            return False
        if not self.telegram_heuristic_only:
            return False
        target = source_group.strip()
        # direct match against provided list
        for s in self.telegram_heuristic_only:
            if not s:
                continue
            if s.strip().lower() == target.lower():
                return True
        # match against labels or identifiers
        for label, identifier in self.telegram_source_mappings:
            if target.lower() == label.lower() or target == identifier:
                for s in self.telegram_heuristic_only:
                    if s.strip().lower() in {label.lower(), identifier}:
                        return True
        return False

    @property
    def dynamic_symbols_path(self) -> Path:
        if self.dynamic_symbols_file:
            return Path(self.dynamic_symbols_file).expanduser()
        # default to bridge folder sibling
        try:
            return Path(self.bridge_inbox_dir).parent / "dynamic_symbols.txt"
        except Exception:
            return self.project_root / "dynamic_symbols.txt"

    def _load_dynamic_symbols(self) -> set[str]:
        if self._dynamic_symbols_cache is not None:
            return self._dynamic_symbols_cache
        symbols: set[str] = set()
        try:
            path = self.dynamic_symbols_path
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    s = line.strip().upper()
                    if s:
                        symbols.add(s)
        except Exception:
            pass
        self._dynamic_symbols_cache = symbols
        return symbols

    def add_dynamic_symbol(self, symbol: str) -> bool:
        if not symbol:
            return False
        sym = symbol.strip().upper()
        if not sym:
            return False
        # Already in env-specified allowed list
        if sym in {s.upper() for s in self.allowed_symbols}:
            return False
        current = self._load_dynamic_symbols()
        if sym in current:
            return False
        try:
            path = self.dynamic_symbols_path
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(sym + "\n")
            current.add(sym)
            self._dynamic_symbols_cache = current
            return True
        except Exception:
            return False

    @property
    def merged_allowed_symbols(self) -> list[str]:
        base = [s.upper() for s in (self.allowed_symbols or [])]
        dynamic = sorted(self._load_dynamic_symbols())
        merged = list(dict.fromkeys(base + dynamic))
        return merged

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash and self.telegram_source_identifiers)

    @property
    def telegram_login_ready(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash and (self.telegram_phone_number or self.telegram_bot_token))

    @property
    def ai_ready(self) -> bool:
        return bool(
            self.openai_api_key
            or self.cloudflare_api_token
            or self.nvidia_api_key
            or self.cerebras_api_key
            or self.groq_api_key
        )

    @property
    def ai_providers(self) -> list[dict]:
        return build_ai_providers(self)