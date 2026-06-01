"""Telegram adapter sub-package — Telethon listener and helper utilities."""
from telegram_signal_copier.adapters.telegram.client import TelegramSignalListener as TelegramSignalListener  # noqa: F401
from telegram_signal_copier.adapters.telegram.helpers import (  # noqa: F401
    MessageBuffer as MessageBuffer,
    _normalize_source_name as _normalize_source_name,
    _patched_platform_uname_for_telethon as _patched_platform_uname_for_telethon,
    _prepare_telethon_ssl_runtime as _prepare_telethon_ssl_runtime,
)
