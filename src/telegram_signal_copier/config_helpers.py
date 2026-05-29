"""Configuration helper utilities — env parsing and path resolution.

Extracted from config.py to keep each module under 300 lines.
These functions are re-exported from config.py for backward compatibility.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


SOURCE_SPEC_SEPARATOR = "::"
APP_HOME_ENV = "TELEGRAM_SIGNAL_COPIER_HOME"


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_source_spec(value: str) -> tuple[str, str]:
    label, separator, identifier = value.partition(SOURCE_SPEC_SEPARATOR)
    if separator:
        normalized_identifier = identifier.strip()
        normalized_label = label.strip() or normalized_identifier
        return normalized_label, normalized_identifier
    normalized = value.strip()
    return normalized, normalized


def _validate_telegram_source_values(sources: list[str]) -> None:
    invalid: list[str] = []
    for source in sources:
        label, identifier = _parse_source_spec(source)
        normalized_identifier = identifier.strip()
        if normalized_identifier and not normalized_identifier.isdigit():
            invalid.append(f"{label}::{normalized_identifier}" if label != normalized_identifier else normalized_identifier)
    if invalid:
        joined = ", ".join(invalid)
        raise ValueError(
            "Invalid TELEGRAM_SOURCES values. Each source value must be numeric chat ID only "
            f"(use Label{SOURCE_SPEC_SEPARATOR}1234567890 or 1234567890 format). Invalid entries: {joined}"
        )


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_bridge_root(project_root: Path) -> Path:
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "TelegramSignalCopierBridge"
        try:
            appdata_path = Path.home() / "AppData" / "Roaming"
        except RuntimeError:
            appdata_path = project_root
        return appdata_path / "MetaQuotes" / "Terminal" / "Common" / "Files" / "TelegramSignalCopierBridge"
    return project_root / "bridge"


def _running_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _default_project_root() -> Path:
    override = os.getenv(APP_HOME_ENV)
    if override:
        return Path(override).expanduser()

    if _running_frozen():
        if os.name == "nt":
            appdata = os.getenv("APPDATA")
            if appdata:
                return Path(appdata) / "TelegramSignalCopier"
            try:
                return Path.home() / "AppData" / "Roaming" / "TelegramSignalCopier"
            except RuntimeError:
                return Path.cwd() / "TelegramSignalCopier"
        return Path.home() / ".telegram-signal-copier"

    return Path(__file__).resolve().parents[2]


def _dotenv_candidates(project_root: Path) -> list[Path]:
    candidates = [project_root / ".env"]
    if _running_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        exe_env = exe_dir / ".env"
        if exe_env not in candidates:
            candidates.append(exe_env)
    return candidates


def _load_first_dotenv(project_root: Path) -> None:
    for candidate in _dotenv_candidates(project_root):
        if candidate.exists():
            _load_dotenv(candidate)
            return


def _build_env_kwargs(root: Path) -> dict:
    """Build the full kwargs dict for AppConfig from environment variables."""
    bridge_root = Path(os.getenv("MT5_BRIDGE_DIR", str(_default_bridge_root(root))))
    telegram_sources = _csv_env("TELEGRAM_SOURCES")
    _validate_telegram_source_values(telegram_sources)
    return {
        "project_root": root,
        "bridge_inbox_dir": bridge_root,
        "bridge_outbox_dir": bridge_root / "outbox",
        "telegram_api_id": os.getenv("TELEGRAM_API_ID"),
        "telegram_api_hash": os.getenv("TELEGRAM_API_HASH"),
        "telegram_phone_number": os.getenv("TELEGRAM_PHONE_NUMBER"),
        "telegram_session_name": os.getenv("TELEGRAM_SESSION_NAME", "telegram-signal-copier"),
        "telegram_sources": telegram_sources,
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "openai_vision_model": os.getenv("OPENAI_VISION_MODEL") or os.getenv("OPENAI_MODEL"),
        "cloudflare_account_id": os.getenv("CLOUDFLARE_ACCOUNT_ID"),
        "cloudflare_api_token": os.getenv("CLOUDFLARE_API_TOKEN"),
        "cloudflare_base_url": os.getenv("CLOUDFLARE_BASE_URL", "https://api.cloudflare.com/client/v4"),
        "cloudflare_model": os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct"),
        "nvidia_cloudname": os.getenv("NVIDIA_CLOUDNAME"),
        "nvidia_api_key": os.getenv("NVIDIA_API_KEY"),
        "nvidia_base_url": os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "nvidia_model": os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
        "cerebras_api_key": os.getenv("CEREBRAS_API_KEY"),
        "cerebras_base_url": os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.net/v1"),
        "cerebras_model": os.getenv("CEREBRAS_MODEL", "llama-3.1-70b"),
        "groq_api_key": os.getenv("GROQ_API_KEY"),
        "groq_base_url": os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "ai_max_requests_per_minute": int(os.getenv("AI_MAX_REQUESTS_PER_MINUTE", "60")),
        "ai_provider_cooldown_seconds": int(os.getenv("AI_PROVIDER_COOLDOWN_SECONDS", "60")),
        "ai_provider_max_cooldown_seconds": int(os.getenv("AI_PROVIDER_MAX_COOLDOWN_SECONDS", "3600")),
        "ai_cache_ttl_seconds": int(os.getenv("AI_CACHE_TTL_SECONDS", "300")),
        "ai_persistent_cache": _bool_env("AI_PERSISTENT_CACHE", False),
        "ai_cache_path": os.getenv("AI_CACHE_PATH", str(root / "ai_cache.db")),
        "telegram_heuristic_only": _csv_env("TELEGRAM_HEURISTIC_ONLY"),
        "mt5_bridge_timeout_seconds": float(os.getenv("MT5_BRIDGE_TIMEOUT_SECONDS", "60")),
        "mt5_symbol_suffix": os.getenv("MT5_SYMBOL_SUFFIX", ""),
        "auto_add_new_symbols": _bool_env("AUTO_ADD_NEW_SYMBOLS", False),
        "dynamic_symbols_file": os.getenv("DYNAMIC_SYMBOLS_FILE", ""),
        "minimum_confidence": float(os.getenv("MINIMUM_CONFIDENCE", "0.70")),
        "default_volume": float(os.getenv("DEFAULT_VOLUME", "0.10")),
        "allowed_symbols": _csv_env("ALLOWED_SYMBOLS", "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,XAGUSD,US30,NAS100,USOIL,SPX500"),
        "dry_run": _bool_env("DRY_RUN", False),
        "approval_required_below": float(os.getenv("APPROVAL_REQUIRED_BELOW", "0.85")),
        "minimum_rr_ratio": float(os.getenv("MINIMUM_RR_RATIO", "1.5")),
        "poll_interval_seconds": float(os.getenv("POLL_INTERVAL_SECONDS", "2.0")),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_username": os.getenv("TELEGRAM_USERNAME"),
        "telegram_user_id": os.getenv("TELEGRAM_USER_ID"),
        "telegram_first_name": os.getenv("TELEGRAM_FIRST_NAME"),
    }


def build_ai_providers(config: object) -> list[dict]:
    """Build the AI provider list from an AppConfig instance."""
    providers: list[dict] = []
    if getattr(config, "openai_api_key", None):
        providers.append({
            "name": "primary",
            "api_key": config.openai_api_key,
            "base_url": config.openai_base_url,
            "model": config.openai_model,
            "vision_model": config.openai_vision_model or config.openai_model,
        })
    if getattr(config, "cloudflare_api_token", None):
        providers.append({
            "name": "cloudflare",
            "api_key": config.cloudflare_api_token,
            "base_url": config.cloudflare_base_url,
            "model": config.cloudflare_model or config.openai_model,
        })
    if getattr(config, "nvidia_api_key", None):
        providers.append({
            "name": "nvidia",
            "api_key": config.nvidia_api_key,
            "base_url": config.nvidia_base_url,
            "model": config.nvidia_model or config.openai_model,
        })
    if getattr(config, "cerebras_api_key", None):
        providers.append({
            "name": "cerebras",
            "api_key": config.cerebras_api_key,
            "base_url": config.cerebras_base_url,
            "model": config.cerebras_model or config.openai_model,
        })
    if getattr(config, "groq_api_key", None):
        providers.append({
            "name": "groq",
            "api_key": config.groq_api_key,
            "base_url": config.groq_base_url,
            "model": config.groq_model or config.openai_model,
            "vision_model": config.groq_model or config.openai_model,
        })
    return providers
