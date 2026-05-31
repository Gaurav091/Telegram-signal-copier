"""Telegram connection helpers and MessageBuffer.

Extracted from telegram_client.py to keep each module under 300 lines.
These symbols are re-exported from telegram_client.py for backward compatibility.
"""
from __future__ import annotations

import asyncio
import ctypes.util
import logging
import os
import platform
import shutil
import unicodedata
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from telegram_signal_copier.models import TelegramSignalMessage

logger = logging.getLogger(__name__)


def _prepare_telethon_ssl_runtime(project_root: Path) -> None:
    if os.name != "nt":
        return

    if ctypes.util.find_library("ssl"):
        return

    candidates = [
        Path("C:/Program Files/OpenSSL-Win64/bin"),
        Path("C:/Program Files/OpenSSL-Win32/bin"),
        Path("C:/Program Files/Common Files/SSL"),
    ]
    source_dir = next((path for path in candidates if path.exists()), None)
    if source_dir is None:
        return

    ssl_dll = source_dir / "ssl.dll"
    if not ssl_dll.exists():
        versioned_ssl = sorted(source_dir.glob("libssl-*-x64.dll")) or sorted(source_dir.glob("libssl-*.dll"))
        if not versioned_ssl:
            return
        source_ssl = versioned_ssl[0]
        shim_dir = project_root / "runtime" / "openssl_shim"
        shim_dir.mkdir(parents=True, exist_ok=True)
        shim_ssl = shim_dir / "ssl.dll"
        try:
            shutil.copy2(source_ssl, shim_ssl)
            for crypto in source_dir.glob("libcrypto-*.dll"):
                target = shim_dir / crypto.name
                if not target.exists():
                    shutil.copy2(crypto, target)
            source_dir = shim_dir
        except Exception as exc:
            logger.debug("[TG] OpenSSL shim creation failed: %s", exc)
            return

    current_path = os.environ.get("PATH", "")
    source_dir_str = str(source_dir)
    if source_dir_str.lower() not in current_path.lower():
        os.environ["PATH"] = source_dir_str + os.pathsep + current_path

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if callable(add_dll_directory):
        try:
            add_dll_directory(source_dir_str)
        except OSError:
            logger.debug("add_dll_directory(%s) failed", source_dir_str, exc_info=True)


def _normalize_source_name(name: str) -> str:
    """NFKD-normalize + casefold a source name for comparison.

    NFKD compatibility decomposition converts Unicode mathematical bold/italic
    letters to their plain ASCII equivalents, so a .env entry of 'GOLD BIG LOT
    SIGNALS' will match a Telegram group using Unicode math-bold characters.
    Emojis are preserved because they have no compatibility decomposition.
    """
    return unicodedata.normalize("NFKD", name).casefold().strip()


@contextmanager
def _patched_platform_uname_for_telethon() -> object:
    if os.name != "nt":
        yield
        return

    original_uname = platform.uname

    # Python 3.14 on Windows can hang in platform.uname() while issuing a WMI
    # query from Telethon's TelegramClient constructor. Telethon only needs
    # machine and release to derive default device/system labels.
    fallback = SimpleNamespace(
        system="Windows",
        node=os.environ.get("COMPUTERNAME", "localhost"),
        release=os.environ.get("TELEGRAM_SYSTEM_RELEASE", "10"),
        version=os.environ.get("TELEGRAM_SYSTEM_VERSION", ""),
        machine=os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64"),
        processor=os.environ.get("PROCESSOR_IDENTIFIER", "AMD64"),
    )

    platform.uname = lambda: fallback
    try:
        yield
    finally:
        platform.uname = original_uname


class MessageBuffer:
    """Groups messages from the same source channel within a rolling time window.

    When a new message arrives from a source, any existing flush timer is reset.
    After ``window_seconds`` of silence from that source, all buffered messages
    are combined into a single ``TelegramSignalMessage`` and sent to the callback.
    """

    def __init__(self, window_seconds: float = 25.0) -> None:
        self._window = window_seconds
        self._buffers: dict[str, list[TelegramSignalMessage]] = {}
        self._tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._lock = asyncio.Lock()

    async def add(
        self,
        message: TelegramSignalMessage,
        flush_callback: Callable[[TelegramSignalMessage], Awaitable[None]],
    ) -> None:
        async with self._lock:
            key = message.source_group
            self._buffers.setdefault(key, []).append(message)
            logger.debug(
                "[BUFFER] +1 msg for %s (total=%d) id=%s",
                key,
                len(self._buffers[key]),
                message.message_id,
            )
            existing = self._tasks.get(key)
            if existing and not existing.done():
                existing.cancel()
            self._tasks[key] = asyncio.create_task(
                self._delayed_flush(key, flush_callback)
            )

    async def _delayed_flush(
        self,
        key: str,
        callback: Callable[[TelegramSignalMessage], Awaitable[None]],
    ) -> None:
        await asyncio.sleep(self._window)
        async with self._lock:
            messages = self._buffers.pop(key, [])
            self._tasks.pop(key, None)
        if not messages:
            return
        combined = self._combine(messages)
        logger.info(
            "[BUFFER] Flushing %d messages from %s → combined id=%s images=%d",
            len(messages),
            key,
            combined.message_id,
            len(combined.all_image_paths),
        )
        await callback(combined)

    @staticmethod
    def _combine(messages: list[TelegramSignalMessage]) -> TelegramSignalMessage:
        texts = [m.raw_text for m in messages if m.raw_text and m.raw_text.strip()]
        all_images: list[str] = []
        for m in messages:
            for p in m.effective_image_paths():
                if p not in all_images:
                    all_images.append(p)

        mid = (
            f"{messages[0].message_id}..{messages[-1].message_id}"
            if len(messages) > 1
            else messages[0].message_id
        )
        return TelegramSignalMessage(
            source_group=messages[0].source_group,
            message_id=mid,
            raw_text="\n---\n".join(texts),
            image_path=all_images[0] if all_images else None,
            sender=messages[0].sender,
            all_image_paths=all_images,
            grouped_count=len(messages),
        )
