"""Resolve all configured sources and print results + errors."""
import asyncio
import traceback
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from telegram_signal_copier.config import AppConfig


async def _probe():
    from typing import Any
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession, StringSession
    from telethon.errors import FloodWaitError

    cfg = AppConfig.from_env()
    session_dir = cfg.project_root / 'runtime' / 'sessions'
    session_name = str(session_dir / f'{cfg.telegram_session_name}-listener')

    sq = SQLiteSession(session_name)
    try:
        serialized = StringSession.save(sq)
    finally:
        sq.close()

    client: Any = TelegramClient(StringSession(serialized), int(cfg.telegram_api_id or 0), cfg.telegram_api_hash or "")
    await client.connect()
    assert await client.is_user_authorized(), 'Not authorized'

    sources = cfg.telegram_source_mappings
    print(f'Resolving {len(sources)} sources...')
    ok = []
    fail = []
    for label, ident in sources:
        try:
            is_numeric = False
            try:
                int(ident)
                is_numeric = True
            except ValueError:
                pass

            entity = None
            if is_numeric:
                raw_id = int(ident)
                if raw_id < 0:
                    try:
                        entity = await client.get_entity(raw_id)
                    except Exception:
                        pass
                else:
                    for attempt_id in (int(f'-100{ident}'), raw_id):
                        try:
                            entity = await client.get_entity(attempt_id)
                            break
                        except FloodWaitError as e:
                            print(f'  FLOOD_WAIT {label} ({ident}): {e}')
                            entity = None
                            break
                        except Exception:
                            continue
            else:
                # 1. Try local joined dialogs by name
                try:
                    async for dialog in client.iter_dialogs():
                        if dialog.name and dialog.name.strip().lower() == ident.strip().lower():
                            entity = dialog.entity
                            break
                except Exception:
                    pass

                # 2. Fallback: try standard get_entity
                if entity is None:
                    try:
                        entity = await client.get_entity(ident.lstrip('@'))
                    except Exception:
                        pass

            if entity is None:
                fail.append((label, ident, 'Could not resolve source by ID, name, or username'))
            else:
                ok.append((label, ident, getattr(entity, 'title', None) or getattr(entity, 'username', None)))
        except FloodWaitError as e:
            fail.append((label, ident, f'FloodWait: {e}'))
        except Exception as e:
            fail.append((label, ident, f'{type(e).__name__}: {e}'))

    print('\n=== RESOLVED ===')
    for l, i, t in ok:
        print(f'  OK  {l} ({i}) -> {t}')
    print('\n=== FAILED ===')
    for l, i, e in fail:
        print(f'  FAIL  {l} ({i}): {e}')

    await client.disconnect()
    print('\nTotal:', len(ok), 'ok,', len(fail), 'failed')


if __name__ == '__main__':
    try:
        asyncio.run(_probe())
    except Exception:
        traceback.print_exc()
