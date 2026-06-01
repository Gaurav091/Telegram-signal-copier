"""Backward-compatibility shim — TelegramSignalListener moved to adapters.telegram.client."""
from telegram_signal_copier.adapters.telegram.client import TelegramSignalListener as TelegramSignalListener  # noqa: F401
from telegram_signal_copier.adapters.telegram.helpers import (  # noqa: F401
    _normalize_source_name as _normalize_source_name,
    _patched_platform_uname_for_telethon as _patched_platform_uname_for_telethon,
)
