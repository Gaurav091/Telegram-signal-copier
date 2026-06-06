"""Type stubs for telethon.events."""

from __future__ import annotations

from typing import Any, Callable

class NewMessage:
    def __init__(self, chats: list[Any] | None = ...) -> None: ...
    def __call__(self, f: Callable[..., Any]) -> Callable[..., Any]: ...
