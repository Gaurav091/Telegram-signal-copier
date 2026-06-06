"""Search for 'Forex Gold Market Killer' channel by global Telegram search."""
import asyncio
import shutil
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from telethon import TelegramClient
from telethon.tl.functions.contacts import SearchRequest
from telegram_signal_copier.config import AppConfig

ROOT = Path(__file__).resolve().parents[1]
cfg = AppConfig.from_env(ROOT)
primary = ROOT / f"{cfg.telegram_session_name}.session"


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_session = tmp_dir / "scan.session"
    shutil.copy2(primary, tmp_session)
    session_arg = str(tmp_session.with_suffix(""))
    async with TelegramClient(session_arg, int(cfg.telegram_api_id), cfg.telegram_api_hash) as client:  # type: ignore[not-async]
        for q in ["Forex Gold Market Killer", "Gold Market Killer", "FGMK"]:
            result = await client(SearchRequest(q=q, limit=10))
            if result.chats:
                print(f"\n=== Query: {q!r} ===")
                for c in result.chats:
                    print(f"  id={c.id}  title={getattr(c, 'title', '')}  username={getattr(c, 'username', '')}")
            else:
                print(f"\n=== Query: {q!r} -> no results ===")


if __name__ == "__main__":
    asyncio.run(main())
