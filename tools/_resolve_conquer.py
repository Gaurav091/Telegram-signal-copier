"""Resolve FOREX MARKET CONQUER group ID using Telethon."""
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import GetFullChannelRequest

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))
from telegram_signal_copier.config import AppConfig

cfg = AppConfig.from_env()
session = str(pathlib.Path("runtime/sessions/telegram-signal-copier-listener.session"))

async def main():
    client = TelegramClient(session, cfg.telegram_api_id, cfg.telegram_api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Not authorized")
        return

    # Search by name
    result = await client(SearchRequest(q="FOREX MARKET CONQUER", limit=10))
    for chat in result.chats:
        print(f"ID: -{1000000000000 + chat.id}  Title: {chat.title}  Username: {getattr(chat, 'username', None)}")

    await client.disconnect()

asyncio.run(main())
