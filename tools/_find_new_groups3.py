"""Find IDs of newly-joined Telegram groups using StringSession (no file lock)."""
import asyncio, sys, unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TARGETS = ["trader tactics", "xauusd vip paid", "jonsan", "insider trading"]

def norm(s):
    return unicodedata.normalize("NFKD", s or "").casefold().strip()

async def main():
    from typing import Any
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession, StringSession
    from telegram_signal_copier.config import AppConfig

    cfg = AppConfig.from_env(Path(__file__).resolve().parents[1])
    root = Path(__file__).resolve().parents[1]

    # Convert the primary SQLite session → StringSession (read-only, no lock conflict)
    primary = root / cfg.telegram_session_name  # path without .session suffix
    print(f"Loading session from: {primary}.session")
    sqlite_s = SQLiteSession(str(primary))
    try:
        serialized = StringSession.save(sqlite_s)
    finally:
        sqlite_s.close()

    if not serialized:
        print("ERROR: Session serialization returned empty string — not logged in?")
        return

    print("Session serialized OK. Connecting...")
    client: Any = TelegramClient(StringSession(serialized), int(cfg.telegram_api_id or 0), cfg.telegram_api_hash or "")
    await client.connect()
    print("Connected. Scanning dialogs...")

    found, count = [], 0
    async for dialog in client.iter_dialogs(limit=600):
        count += 1
        title = dialog.name or ""
        for tgt in TARGETS:
            if tgt in norm(title):
                eid = getattr(dialog.entity, "id", "?")
                print(f"  FOUND  id={eid}  title={title!r}", flush=True)
                found.append((tgt, eid, title))
                break
        if count % 100 == 0:
            print(f"  ... {count} dialogs scanned, {len(found)} found so far", flush=True)

    print(f"\nDone. Scanned {count} dialogs.")
    if not found:
        print("None of the target groups found in your dialogs.")
        print("Make sure you have actually joined them in Telegram first.")
    else:
        print("\nSummary:")
        for tgt, eid, title in found:
            print(f"  {tgt!r:35}  id={eid}  title={title!r}")

    await client.disconnect()

asyncio.run(main())
