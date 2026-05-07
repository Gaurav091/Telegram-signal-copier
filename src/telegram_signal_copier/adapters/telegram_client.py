from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
import shutil

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.models import TelegramSignalMessage


class TelegramSignalListener:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._media_dir = self.config.project_root / "runtime" / "media"
        self._session_dir = self.config.project_root / "runtime" / "sessions"

    async def run(self, on_message: Callable[[TelegramSignalMessage], Awaitable[None]]) -> None:
        if not self.config.telegram_ready:
            raise RuntimeError("Telegram credentials or source groups missing")

        from telethon import TelegramClient, events  # type: ignore[import-not-found]

        self._media_dir.mkdir(parents=True, exist_ok=True)

        client = TelegramClient(
            self._listener_session(),
            int(self.config.telegram_api_id or "0"),
            self.config.telegram_api_hash or "",
        )

        await self._start_client(client)
        source_chats = await self._resolve_source_chats(client)

        event_builder = events.NewMessage(chats=source_chats)

        @client.on(event_builder)
        async def handler(event: object) -> None:
            message = await self._event_to_message(event)
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
        for label, source in self.config.telegram_source_mappings:
            identifier = source.strip()
            if not identifier:
                continue
            try:
                resolved.append(await self._resolve_source_chat(client, label, identifier))
            except Exception as exc:  # type: ignore[misc]
                raise RuntimeError(f"Failed to resolve configured source '{label}' ({identifier}): {exc}") from exc
        return resolved

    async def _resolve_source_chat(self, client: object, label: str, identifier: str) -> object:
        normalized_identifier = identifier[1:] if identifier.startswith("@") else identifier
        try:
            if normalized_identifier.isdigit():
                return await client.get_entity(int(normalized_identifier))  # type: ignore[attr-defined]
            return await client.get_entity(normalized_identifier)  # type: ignore[attr-defined]
        except Exception:
            return await self._search_source_chat(client, label, normalized_identifier)

    async def _search_source_chat(self, client: object, label: str, identifier: str) -> object:
        from telethon.tl.functions.contacts import SearchRequest  # type: ignore[import-not-found]

        result = await client(SearchRequest(q=label, limit=20))  # type: ignore[attr-defined]
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
        raw_text = event.raw_text or ""  # type: ignore[attr-defined]
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