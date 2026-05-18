from __future__ import annotations

import asyncio
import logging
import os
import platform
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from pathlib import Path
import shutil
from types import SimpleNamespace

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage

logger = logging.getLogger(__name__)


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
    This lets the system read 3–4 chart images posted in quick succession as a
    single multi-timeframe signal rather than 3 independent (and likely rejected)
    partial signals.
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
            # Reset flush timer
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


class TelegramSignalListener:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._media_dir = self.config.project_root / "runtime" / "media"
        self._session_dir = self.config.project_root / "runtime" / "sessions"

    async def run(self, on_message: Callable[[TelegramSignalMessage], Awaitable[None]]) -> None:
        if not self.config.telegram_ready:
            raise RuntimeError("Telegram credentials or source groups missing")

        logger.info("[TG] importing Telethon runtime")
        from telethon import TelegramClient, events  # type: ignore[import-not-found]
        logger.info("[TG] Telethon import complete")

        self._media_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[TG] building listener session")
        session = self._listener_session()
        logger.info("[TG] listener session ready")

        logger.info("[TG] constructing TelegramClient")
        with _patched_platform_uname_for_telethon():
            client = TelegramClient(
                session,
                int(self.config.telegram_api_id or "0"),
                self.config.telegram_api_hash or "",
            )
        logger.info("[TG] TelegramClient constructed")

        logger.info("[TG] connecting listener client")
        await self._connect_listener_client(client)
        logger.info("[TG] listener client connected")
        source_chats = await self._resolve_source_chats(client)
        logger.info("[TG] source chats resolved: %d", len(source_chats))

        # Buffer window from config (default 25 s); set MESSAGE_BUFFER_WINDOW_SECONDS=0 to disable
        buffer_window = float(
            __import__("os").getenv("MESSAGE_BUFFER_WINDOW_SECONDS", "25")
        )
        use_buffer = buffer_window > 0
        buffer = MessageBuffer(window_seconds=buffer_window) if use_buffer else None

        event_builder = events.NewMessage(chats=source_chats)

        @client.on(event_builder)
        async def handler(event: object) -> None:
            message = await self._event_to_message(event)
            if buffer is not None:
                await buffer.add(message, on_message)
            else:
                await on_message(message)

        await client.run_until_disconnected()

    async def login(self) -> None:
        if not self.config.telegram_login_ready:
            raise RuntimeError("Telegram API ID, API hash, and phone number or bot token are required")

        from telethon import TelegramClient  # type: ignore[import-not-found]

        client = TelegramClient(
            self.config.telegram_session_name,
            int(self.config.telegram_api_id or "0"),
            self.config.telegram_api_hash or "",
        )
        await self._start_client(client)
        await client.disconnect()

    async def _start_client(self, client: object) -> None:
        if self.config.telegram_phone_number:
            await client.start(phone=self.config.telegram_phone_number)  # type: ignore[attr-defined]
            return
        if self.config.telegram_bot_token:
            await client.start(bot_token=self.config.telegram_bot_token)  # type: ignore[attr-defined]
            return
        raise RuntimeError("Telegram login requested without phone number or bot token")

    async def _connect_listener_client(self, client: object) -> None:
        await client.connect()  # type: ignore[attr-defined]
        if await client.is_user_authorized():  # type: ignore[attr-defined]
            return
        if self.config.telegram_bot_token:
            await client.start(bot_token=self.config.telegram_bot_token)  # type: ignore[attr-defined]
            return
        raise RuntimeError(
            "Telegram listener session is not authorized. Run `python -m telegram_signal_copier login` first."
        )

    def _listener_session_name(self) -> str:
        self._session_dir.mkdir(parents=True, exist_ok=True)
        primary_session = self.config.project_root / f"{self.config.telegram_session_name}.session"
        listener_session = self._session_dir / f"{self.config.telegram_session_name}-listener.session"

        if primary_session.exists() and self._should_refresh_session(primary_session, listener_session):
            shutil.copy2(primary_session, listener_session)

        return str(listener_session.with_suffix(""))

    def _listener_session(self) -> object:
        from telethon.sessions import SQLiteSession, StringSession  # type: ignore[import-not-found]

        session_name = self._listener_session_name()
        sqlite_session = SQLiteSession(session_name)
        try:
            serialized = StringSession.save(sqlite_session)
        finally:
            sqlite_session.close()
        if not serialized:
            raise RuntimeError("Telegram listener session is not authorized. Run `python -m telegram_signal_copier login` first.")
        return StringSession(serialized)

    @staticmethod
    def _should_refresh_session(primary_session: Path, listener_session: Path) -> bool:
        if not listener_session.exists():
            return True
        return primary_session.stat().st_mtime > listener_session.stat().st_mtime

    async def _resolve_source_chats(self, client: object) -> list[object]:
        resolved: list[object] = []
        skipped: list[str] = []
        for label, source in self.config.telegram_source_mappings:
            identifier = source.strip()
            if not identifier:
                continue
            try:
                resolved.append(await self._resolve_source_chat(client, label, identifier))
            except _FloodWaitSkip as exc:
                logger.warning(
                    "Skipping source '%s' (%s) due to Telegram flood wait: %s — will retry after restart",
                    label, identifier, exc,
                )
                skipped.append(label)
            except Exception as exc:  # type: ignore[misc]
                raise RuntimeError(f"Failed to resolve configured source '{label}' ({identifier}): {exc}") from exc
        if skipped:
            logger.warning("Skipped %d source(s) due to flood wait: %s", len(skipped), skipped)
        if not resolved:
            raise RuntimeError(
                f"All configured sources are unavailable (flood wait or error). Skipped: {skipped}"
            )
        return resolved

    async def _resolve_source_chat(self, client: object, label: str, identifier: str) -> object:
        try:
            from telethon.errors import FloodWaitError  # type: ignore[import-not-found]
        except ImportError:
            FloodWaitError = Exception  # type: ignore[assignment,misc]

        normalized_identifier = identifier[1:] if identifier.startswith("@") else identifier

        # Numeric ID: try both raw int and channel format (-100XXXXX) before any fallback.
        # Never use SearchRequest for numeric IDs — it burns API quota and hits flood limits.
        if normalized_identifier.isdigit():
            raw_id = int(normalized_identifier)
            channel_id = int(f"-100{normalized_identifier}")
            for attempt_id in (channel_id, raw_id):
                try:
                    return await client.get_entity(attempt_id)  # type: ignore[attr-defined]
                except FloodWaitError as exc:
                    raise _FloodWaitSkip(str(exc)) from exc
                except Exception:
                    continue
            # Last resort: peer object
            try:
                from telethon.tl.types import PeerChannel  # type: ignore[import-not-found]
                return await client.get_entity(PeerChannel(raw_id))  # type: ignore[attr-defined]
            except FloodWaitError as exc:
                raise _FloodWaitSkip(str(exc)) from exc
            except Exception:
                pass
            raise RuntimeError(
                f"Could not resolve numeric source '{label}' ({identifier}) with any ID format. "
                "Check that the account is a member of the channel."
            )

        # Username / invite link: direct get_entity, then search fallback
        try:
            return await client.get_entity(normalized_identifier)  # type: ignore[attr-defined]
        except FloodWaitError as exc:
            raise _FloodWaitSkip(str(exc)) from exc
        except Exception:
            pass

        return await self._search_source_chat(client, label, normalized_identifier)

    async def _search_source_chat(self, client: object, label: str, identifier: str) -> object:
        try:
            from telethon.errors import FloodWaitError  # type: ignore[import-not-found]
            from telethon.tl.functions.contacts import SearchRequest  # type: ignore[import-not-found]
        except ImportError:
            FloodWaitError = Exception  # type: ignore[assignment,misc]
            raise RuntimeError("telethon not available")

        try:
            result = await client(SearchRequest(q=label, limit=20))  # type: ignore[attr-defined]
        except FloodWaitError as exc:
            raise _FloodWaitSkip(str(exc)) from exc

        normalized_label = label.casefold()
        normalized_identifier = identifier.casefold()

        for chat in result.chats:
            chat_id = str(getattr(chat, "id", ""))
            chat_username = str(getattr(chat, "username", "") or "")
            chat_title = str(getattr(chat, "title", "") or "")
            if chat_id == identifier:
                return chat
            if chat_username.casefold() == normalized_identifier:
                return chat
            if chat_title.casefold() == normalized_label:
                return chat

        raise ValueError("No matching Telegram chat found via search fallback")

    async def _event_to_message(self, event: object) -> TelegramSignalMessage:
        chat = await event.get_chat()  # type: ignore[attr-defined]
        sender = await event.get_sender()  # type: ignore[attr-defined]
        raw_text = getattr(event, "raw_text", "") or ""  # type: ignore[attr-defined]
        image_path = await self._download_media(event)
        return TelegramSignalMessage(
            source_group=getattr(chat, "title", None) or getattr(chat, "username", "unknown-source"),
            message_id=str(event.id),  # type: ignore[attr-defined]
            raw_text=raw_text,
            image_path=image_path,
            sender=getattr(sender, "username", None) or getattr(sender, "first_name", None),
        )

    async def _download_media(self, event: object) -> str | None:
        if not getattr(event.message, "photo", None):  # type: ignore[attr-defined]
            return None
        file_path = self._media_dir / f"{event.id}.jpg"  # type: ignore[attr-defined]
        downloaded = await event.download_media(file=file_path)  # type: ignore[attr-defined]
        return str(Path(downloaded)) if downloaded else None


class _FloodWaitSkip(Exception):
    """Raised when a Telegram FloodWaitError is hit during source resolution.
    Caught by _resolve_source_chats to skip the source gracefully instead of
    crashing the entire listener."""
    pass