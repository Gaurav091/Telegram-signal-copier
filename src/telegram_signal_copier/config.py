from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


SOURCE_SPEC_SEPARATOR = "::"


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


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_bridge_root(project_root: Path) -> Path:
    if os.name == "nt":
        appdata = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "MetaQuotes" / "Terminal" / "Common" / "Files" / "TelegramSignalCopierBridge"
    return project_root / "bridge"


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
        root = project_root or Path(__file__).resolve().parents[2]
        _load_dotenv(root / ".env")
        bridge_root = Path(os.getenv("MT5_BRIDGE_DIR", _default_bridge_root(root)))
        return cls(
            project_root=root,
            # Commands are written to the bridge ROOT (not inbox/ subfolder) because
            # MQL5's FileFindFirst with FILE_COMMON cannot reliably enumerate subdirectories.
            bridge_inbox_dir=bridge_root,
            bridge_outbox_dir=bridge_root / "outbox",
            telegram_api_id=os.getenv("TELEGRAM_API_ID"),
            telegram_api_hash=os.getenv("TELEGRAM_API_HASH"),
            telegram_phone_number=os.getenv("TELEGRAM_PHONE_NUMBER"),
            telegram_session_name=os.getenv("TELEGRAM_SESSION_NAME", "telegram-signal-copier"),
            telegram_sources=_csv_env("TELEGRAM_SOURCES"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_vision_model=os.getenv("OPENAI_VISION_MODEL") or os.getenv("OPENAI_MODEL"),
            cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID"),
            cloudflare_api_token=os.getenv("CLOUDFLARE_API_TOKEN"),
            cloudflare_base_url=os.getenv("CLOUDFLARE_BASE_URL", "https://api.cloudflare.com/client/v4"),
            cloudflare_model=os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct"),
            nvidia_cloudname=os.getenv("NVIDIA_CLOUDNAME"),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
            nvidia_base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            nvidia_model=os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY"),
            cerebras_base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.net/v1"),
            cerebras_model=os.getenv("CEREBRAS_MODEL", "llama-3.1-70b"),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            ai_max_requests_per_minute=int(os.getenv("AI_MAX_REQUESTS_PER_MINUTE", "60")),
            ai_provider_cooldown_seconds=int(os.getenv("AI_PROVIDER_COOLDOWN_SECONDS", "60")),
            ai_provider_max_cooldown_seconds=int(os.getenv("AI_PROVIDER_MAX_COOLDOWN_SECONDS", "3600")),
            ai_cache_ttl_seconds=int(os.getenv("AI_CACHE_TTL_SECONDS", "300")),
            ai_persistent_cache=_bool_env("AI_PERSISTENT_CACHE", False),
            ai_cache_path=os.getenv("AI_CACHE_PATH", str(root / "ai_cache.db")),
            telegram_heuristic_only=_csv_env("TELEGRAM_HEURISTIC_ONLY"),
            mt5_bridge_timeout_seconds=float(os.getenv("MT5_BRIDGE_TIMEOUT_SECONDS", "60")),
            mt5_symbol_suffix=os.getenv("MT5_SYMBOL_SUFFIX", ""),
            auto_add_new_symbols=_bool_env("AUTO_ADD_NEW_SYMBOLS", False),
            dynamic_symbols_file=os.getenv("DYNAMIC_SYMBOLS_FILE", ""),
            minimum_confidence=float(os.getenv("MINIMUM_CONFIDENCE", "0.70")),
            default_volume=float(os.getenv("DEFAULT_VOLUME", "0.10")),
            allowed_symbols=_csv_env("ALLOWED_SYMBOLS", "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,XAGUSD,US30,NAS100,USOIL,SPX500"),
            dry_run=_bool_env("DRY_RUN", True),
            approval_required_below=float(os.getenv("APPROVAL_REQUIRED_BELOW", "0.85")),
            minimum_rr_ratio=float(os.getenv("MINIMUM_RR_RATIO", "1.5")),
            poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "2.0")),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_username=os.getenv("TELEGRAM_USERNAME"),
            telegram_user_id=os.getenv("TELEGRAM_USER_ID"),
            telegram_first_name=os.getenv("TELEGRAM_FIRST_NAME"),
        )

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
    def ai_providers(self) -> list[dict[str, str]]:
        providers: list[dict[str, str]] = []
        if self.openai_api_key:
            providers.append(
                {
                    "name": "primary",
                    "api_key": self.openai_api_key,
                    "base_url": self.openai_base_url,
                    "model": self.openai_model,
                    "vision_model": self.openai_vision_model or self.openai_model,
                }
            )
        if self.cloudflare_api_token:
            providers.append(
                {
                    "name": "cloudflare",
                    "api_key": self.cloudflare_api_token,
                    "base_url": self.cloudflare_base_url,
                    "model": self.cloudflare_model or self.openai_model,
                }
            )
        if self.nvidia_api_key:
            providers.append(
                {
                    "name": "nvidia",
                    "api_key": self.nvidia_api_key,
                    "base_url": self.nvidia_base_url,
                    "model": self.nvidia_model or self.openai_model,
                }
            )
        if self.cerebras_api_key:
            providers.append(
                {
                    "name": "cerebras",
                    "api_key": self.cerebras_api_key,
                    "base_url": self.cerebras_base_url,
                    "model": self.cerebras_model or self.openai_model,
                }
            )
        if self.groq_api_key:
            providers.append(
                {
                    "name": "groq",
                    "api_key": self.groq_api_key,
                    "base_url": self.groq_base_url,
                    "model": self.groq_model or self.openai_model,
                    "vision_model": self.groq_model or self.openai_model,
                }
            )
        return providers