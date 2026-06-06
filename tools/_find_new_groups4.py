"""Find IDs of newly-joined Telegram groups.
Uses a temporary copy of the session file to avoid lock conflicts.
"""
import asyncio, sys, unicodedata, shutil, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TARGETS = ["trader tactics", "xauusd vip paid", "jonsan", "insider trading"]

def norm(s):
    return unicodedata.normalize("NFKD", s or "").casefold().strip()

async def main():
    from typing import Any
    from telethon import TelegramClient
    from telegram_signal_copier.config import AppConfig

    cfg = AppConfig.from_env(Path(__file__).resolve().parents[1])
    root = Path(__file__).resolve().parents[1]
    primary = root / f"{cfg.telegram_session_name}.session"

    # Copy to a temp dir so there's zero lock conflict
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_session = tmp_dir / "scan.session"
    shutil.copy2(primary, tmp_session)
    session_arg = str(tmp_session.with_suffix(""))
    print(f"Session copy: {tmp_session}", flush=True)

    client: Any = TelegramClient(session_arg, int(cfg.telegram_api_id or 0), cfg.telegram_api_hash or "")
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("ERROR: Not authorized. Run `python -m telegram_signal_copier connect` first.")
            return
        print("Connected. Scanning dialogs (limit=600)...", flush=True)

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
                print(f"  ... {count} scanned, {len(found)} found", flush=True)

        print(f"\nDone. Scanned {count} dialogs.", flush=True)
        if not found:
            print("None of the target groups found — join them in Telegram first.")
        else:
            print("\nSummary:")
            for tgt, eid, title in found:
                print(f"  {tgt!r:35}  id={eid}  title={title!r}")
    finally:
        await client.disconnect()
        shutil.rmtree(tmp_dir, ignore_errors=True)

asyncio.run(main())
