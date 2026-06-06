"""Type stubs for Telethon — minimal declarations for Pyrefly."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Coroutine, TypeVar

_T = TypeVar("_T")

class TelegramClient:
    def __init__(
        self,
        session: str | object,
        api_id: int,
        api_hash: str,
        *,
        connection_retries: int = ...,
        device_model: str = ...,
        system_version: str = ...,
        app_version: str = ...,
        lang_code: str = ...,
        system_lang_code: str = ...,
        base_logger: str = ...,
        proxy: dict | None = ...,
        timeout: int = ...,
        request_retries: int = ...,
        flood_sleep_threshold: int = ...,
        raise_security_errors: bool = ...,
        session_name: str = ...,
    ) -> None: ...

    async def __aenter__(self) -> TelegramClient: ...
    async def __aexit__(self, *args: Any) -> None: ...

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def start(
        self,
        phone: str | None = ...,
        bot_token: str | None = ...,
        password: str | None = ...,
        force_sms: bool = ...,
        code_callback: Callable[[], Coroutine[Any, Any, str]] | None = ...,
        first_name: str = ...,
        last_name: str = ...,
        max_attempts: int = ...,
    ) -> None: ...
    async def is_user_authorized(self) -> bool: ...
    async def get_me(self) -> User | None: ...
    async def get_entity(self, identifier: int | str) -> Chat: ...
    async def iter_dialogs(self, limit: int = ..., archived: bool = ...) -> AsyncIterator[Dialog]: ...
    async def iter_messages(self, entity: Any, limit: int = ...) -> AsyncIterator[Message]: ...
    async def send_message(self, entity: Any, text: str) -> Message: ...
    async def download_media(self, message: Any, file: str | None = ...) -> str | None: ...
    async def run_until_disconnected(self) -> None: ...
    def is_connected(self) -> bool: ...
    def on(self, event: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...
    async def __call__(self, request: Any) -> Any: ...

    # Internal methods
    @property
    def session(self) -> Any: ...

class User:
    id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    bot: bool
    phone: str | None

class Chat:
    id: int
    title: str | None
    username: str | None

class Dialog:
    id: int
    name: str
    entity: Any
    unread_count: int
    is_user: bool
    is_group: bool
    is_channel: bool
    pinned: bool
    archived: bool

class Message:
    id: int
    message: str
    date: Any
    sender_id: int | None
    media: Any
    out: bool
    reply_to_msg_id: int | None
    photo: Any

# Re-export submodule types (actual Telethon uses submodules, not nested classes)
# The individual .pyi files in typings/telethon/* define the actual type stubs
from telethon.events import *  # noqa: F401, F403
from telethon.errors import *  # noqa: F401, F403
from telethon.sessions import *  # noqa: F401, F403
from telethon.tl import *  # noqa: F401, F403
from telethon.client.telegrambaseclient import TelegramBaseClient as TelegramBaseClient
