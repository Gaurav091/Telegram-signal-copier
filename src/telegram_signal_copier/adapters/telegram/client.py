"""Telegram signal listener — connects to Telegram and dispatches messages.

Connection helpers, platform patches, and MessageBuffer live in telegram_helpers.py.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

from telegram_signal_copier.adapters.telegram_helpers import (
    MessageBuffer,
    _normalize_source_name,
    _patched_platform_uname_for_telethon,
    _prepare_telethon_ssl_runtime,
)
from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage

logger = logging.getLogger(__name__)


class _FloodWaitSkip(Exception):
    """Raised when a Telegram FloodWaitError is hit during source resolution.
    Caught by _resolve_source_chats to skip the source gracefully instead of
    crashing the entire listener."""
    pass


class TelegramSignalListener:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._media_dir = self.config.project_root / "runtime" / "media"
        self._session_dir = self.config.project_root / "runtime" / "sessions"

    async def run(self, on_message: Callable[[TelegramSignalMessage], Awaitable[None]]) -> None:
        if not self.config.telegram_ready:
            raise RuntimeError("Telegram credentials or source groups missing")

        _prepare_telethon_ssl_runtime(self.config.project_root)
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

        buffer_window = float(os.getenv("MESSAGE_BUFFER_WINDOW_SECONDS", "25"))
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

        _prepare_telethon_ssl_runtime(self.config.project_root)
        from telethon import TelegramClient  # type: ignore[import-not-found]

        session_path = self.config.project_root / self.config.telegram_session_name
        client = TelegramClient(
            str(session_path),
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
                logger.warning(
                    "Could not resolve source '%s' (%s): %s — skipping (ensure the account is a member)",
                    label, identifier, exc,
                )
                skipped.append(label)
        if skipped:
            logger.warning("Skipped %d source(s): %s", len(skipped), skipped)
        if not resolved:
            raise RuntimeError(
                f"No sources could be resolved. Skipped: {skipped}. "
                "Ensure the account is a member of all configured channels."
            )
        return resolved

    async def _resolve_source_chat(self, client: object, label: str, identifier: str) -> object:
        try:
            from telethon.errors import FloodWaitError  # type: ignore[import-not-found]
        except ImportError:
            FloodWaitError = Exception  # type: ignore[assignment,misc]

        normalized_identifier = identifier.strip()

        # 1. Try resolving as a numeric ID (integer, including negative signs)
        is_numeric = False
        try:
            int(normalized_identifier)
            is_numeric = True
        except ValueError:
            pass

        if is_numeric:
            raw_id = int(normalized_identifier)
            # If positive ID (e.g. 192837465), try prepending -100 first, then raw
            if raw_id > 0:
                channel_id = int(f"-100{normalized_identifier}")
                for attempt_id in (channel_id, raw_id):
                    try:
                        return await client.get_entity(attempt_id)  # type: ignore[attr-defined]
                    except FloodWaitError as exc:
                        raise _FloodWaitSkip(str(exc)) from exc
                    except Exception:
                        continue
            else:
                # If negative ID (e.g. -100192837465), try it directly
                try:
                    return await client.get_entity(raw_id)  # type: ignore[attr-defined]
                except FloodWaitError as exc:
                    raise _FloodWaitSkip(str(exc)) from exc
                except Exception:
                    pass

            raise RuntimeError(
                f"Could not resolve numeric source '{label}' ({identifier}). "
                "Check that the account has joined the channel."
            )

        # 2. If it's a name, search local joined dialogs first (works for private & public chats)
        try:
            async for dialog in client.iter_dialogs():  # type: ignore[attr-defined]
                if dialog.name and dialog.name.strip().lower() == normalized_identifier.lower():
                    return dialog.entity
        except Exception as exc:
            logger.debug("Local dialog search failed for %s: %s", normalized_identifier, exc)

        # 3. If it starts with @ or is a username, try get_entity directly
        if normalized_identifier.startswith("@"):
            try:
                return await client.get_entity(normalized_identifier)  # type: ignore[attr-defined]
            except FloodWaitError as exc:
                raise _FloodWaitSkip(str(exc)) from exc
            except Exception:
                pass

        # 4. Fallback: global search
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

        normalized_label = _normalize_source_name(label)
        normalized_identifier = _normalize_source_name(identifier)

        for chat in result.chats:
            chat_id = str(getattr(chat, "id", ""))
            chat_username = str(getattr(chat, "username", "") or "")
            chat_title = str(getattr(chat, "title", "") or "")
            if chat_id == identifier:
                return chat
            if _normalize_source_name(chat_username) == normalized_identifier:
                return chat
            if _normalize_source_name(chat_title) == normalized_label:
                return chat

        raise ValueError(
            f"No matching Telegram chat found for '{label}' in search results "
            "(ensure the account has joined the group)"
        )

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
