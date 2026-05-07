from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.services.telegram_session import TelegramSessionService


logging.basicConfig(level=logging.INFO, stream=sys.stderr)

mcp = FastMCP("telegramDesktop")
_service: TelegramSessionService | None = None


def _get_service() -> TelegramSessionService:
    global _service
    if _service is None:
        _service = TelegramSessionService(AppConfig.from_env())
    return _service


@mcp.tool()
async def telegram_connection_status() -> dict[str, Any]:
    """Get current Telegram MCP connection status and signed-in account info."""
    return await _get_service().connection_status()


@mcp.tool()
async def telegram_list_dialogs(limit: int = 25, archived: bool = False) -> list[dict[str, Any]]:
    """List Telegram chats, groups, and channels available to the signed-in account.

    Args:
        limit: Maximum number of dialogs to return.
        archived: Include archived dialogs when true.
    """
    return await _get_service().list_dialogs(limit=limit, archived=archived)


@mcp.tool()
async def telegram_get_recent_messages(chat: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get recent messages from a Telegram dialog.

    Args:
        chat: Telegram username, numeric ID, or entity identifier.
        limit: Maximum number of messages to return.
    """
    return await _get_service().get_recent_messages(chat=chat, limit=limit)


@mcp.tool()
async def telegram_send_message(chat: str, text: str) -> dict[str, Any]:
    """Send a message to a Telegram dialog.

    Args:
        chat: Telegram username, numeric ID, or entity identifier.
        text: Message body to send.
    """
    return await _get_service().send_message(chat=chat, text=text)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()