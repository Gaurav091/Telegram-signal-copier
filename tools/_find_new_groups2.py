"""Find IDs of newly-joined Telegram groups. Writes to _find_new_groups_result.txt."""
import asyncio, sys, unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TARGETS = ["trader tactics", "xauusd vip paid", "jonsan", "insider trading"]
OUT = Path(__file__).parent / "_find_new_groups_result.txt"

def norm(s):
    return unicodedata.normalize("NFKD", s or "").casefold().strip()

async def main():
    from typing import Any
    from telethon import TelegramClient
    from telegram_signal_copier.config import AppConfig
    cfg = AppConfig.from_env(Path(__file__).resolve().parents[1])
    client: Any = TelegramClient(cfg.telegram_session_name, int(cfg.telegram_api_id or 0), cfg.telegram_api_hash or "")
    await client.connect()
    OUT.write_text("Scanning...\n", encoding="utf-8")
    found, count = [], 0
    async for dialog in client.iter_dialogs(limit=600):
        count += 1
        title = dialog.name or ""
        for tgt in TARGETS:
            if tgt in norm(title):
                eid = getattr(dialog.entity, "id", "?")
                line = f"FOUND  id={eid}  title={title!r}\n"
                print(line, end="", flush=True)
                with OUT.open("a", encoding="utf-8") as f:
                    f.write(line)
                found.append((tgt, eid, title))
                break
        if count % 50 == 0:
            msg = f"  scanned {count}...\n"
            print(msg, end="", flush=True)
            with OUT.open("a", encoding="utf-8") as f:
                f.write(msg)
    summary = f"Done. Scanned {count}, found {len(found)}.\n"
    for tgt, eid, title in found:
        summary += f"  {tgt!r:35} id={eid}  title={title!r}\n"
    if not found:
        summary += "  None found.\n"
    print(summary, flush=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(summary)
    await client.disconnect()

asyncio.run(main())
