"""One-shot script to find IDs of the 4 newly-joined Telegram groups."""
import asyncio
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TARGETS = [
    "trader tactics",
    "xauusd vip paid",
    "jonsan",
    "insider trading",
]

def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").casefold().strip()

async def main() -> None:
    from typing import Any
    from telethon import TelegramClient
    from telegram_signal_copier.config import AppConfig

    cfg = AppConfig.from_env(Path(__file__).resolve().parents[1])
    client: Any = TelegramClient(
        cfg.telegram_session_name,
        int(cfg.telegram_api_id or 0),
        cfg.telegram_api_hash,
    )
    await client.connect()
    print("Connected. Scanning dialogs (limit=500)...")
    found: list[tuple[str, int, str]] = []
    count = 0
    async for dialog in client.iter_dialogs(limit=500):
        count += 1
        title = dialog.name or ""
        nt = norm(title)
        for tgt in TARGETS:
            if tgt in nt:
                eid = dialog.entity.id if hasattr(dialog.entity, "id") else "?"
                print(f"  FOUND  id={eid}  title={title!r}")
                found.append((tgt, eid, title))
                break
    print(f"\nScanned {count} dialogs.")
    if not found:
        print("None of the 4 target groups found — they may not be joined yet.")
    else:
        print("\nSummary:")
        for tgt, eid, title in found:
            print(f"  target={tgt!r:30}  id={eid}  title={title!r}")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
