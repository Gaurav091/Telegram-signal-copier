from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from telegram_signal_copier.config import AppConfig


@dataclass(slots=True)
class TelegramIdentity:
    id: int | None
    username: str | None
    first_name: str | None
    is_bot: bool


class TelegramSessionService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._client: Any | None = None
        self._lock = asyncio.Lock()

    async def connection_status(self) -> dict[str, Any]:
        client = await self.get_client()
        me = await client.get_me()
        identity = TelegramIdentity(
            id=getattr(me, "id", None),
            username=getattr(me, "username", None),
            first_name=getattr(me, "first_name", None),
            is_bot=bool(getattr(me, "bot", False)),
        )
        return {
            "connected": bool(client.is_connected()),
            "session_name": self.config.telegram_session_name,
            "identity": {
                "id": identity.id,
                "username": identity.username,
                "first_name": identity.first_name,
                "is_bot": identity.is_bot,
            },
        }

    async def list_dialogs(self, limit: int = 25, archived: bool = False) -> list[dict[str, Any]]:
        client = await self.get_client()
        dialogs: list[dict[str, Any]] = []
        async for dialog in client.iter_dialogs(limit=max(1, min(limit, 100)), archived=archived):
            entity = dialog.entity
            dialogs.append(
                {
                    "id": getattr(entity, "id", dialog.id),
                    "title": dialog.name,
                    "username": getattr(entity, "username", None),
                    "unread_count": dialog.unread_count,
                    "is_user": bool(dialog.is_user),
                    "is_group": bool(dialog.is_group),
                    "is_channel": bool(dialog.is_channel),
                    "pinned": bool(dialog.pinned),
                }
            )
        return dialogs

    async def get_recent_messages(self, chat: str, limit: int = 20) -> list[dict[str, Any]]:
        client = await self.get_client()
        entity = await self._resolve_entity(client, chat)
        messages: list[dict[str, Any]] = []
        async for message in client.iter_messages(entity, limit=max(1, min(limit, 100))):
            messages.append(
                {
                    "id": message.id,
                    "date": message.date.isoformat() if message.date else None,
                    "sender_id": getattr(message, "sender_id", None),
                    "text": message.message or "",
                    "has_media": bool(message.media),
                    "reply_to_msg_id": getattr(message, "reply_to_msg_id", None),
                    "out": bool(message.out),
                }
            )
        return messages

    async def send_message(self, chat: str, text: str) -> dict[str, Any]:
        client = await self.get_client()
        entity = await self._resolve_entity(client, chat)
        message = await client.send_message(entity, text)
        return {
            "chat": chat,
            "message_id": getattr(message, "id", None),
            "date": message.date.isoformat() if getattr(message, "date", None) else None,
            "text": message.message or text,
        }

    async def get_client(self) -> Any:
        async with self._lock:
            if self._client is not None and self._client.is_connected():
                return self._client

            if not self.config.telegram_api_id or not self.config.telegram_api_hash:
                raise RuntimeError("Telegram API ID and API hash are required in .env for MCP access")

            from telethon import TelegramClient  # type: ignore[import-not-found]

            client = TelegramClient(
                self.config.telegram_session_name,
                int(self.config.telegram_api_id),
                self.config.telegram_api_hash,
            )
            await client.connect()

            if not await client.is_user_authorized():
                if self.config.telegram_bot_token:
                    await client.start(bot_token=self.config.telegram_bot_token)
                else:
                    raise RuntimeError(
                        "Telegram session is not authorized. Run `python -m telegram_signal_copier login` first."
                    )

            self._client = client
            return client

    async def _resolve_entity(self, client: Any, chat: str) -> Any:
        identifier = chat.strip()
        if identifier.startswith("@"):
            identifier = identifier[1:]
        if identifier.isdigit():
            return await client.get_entity(int(identifier))
        return await client.get_entity(identifier)