"""Minimal diagnostic: connect to Telegram, print any exception verbosely."""
import asyncio
import traceback
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from telegram_signal_copier.config import AppConfig


async def _probe():
    from typing import Any
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession, StringSession

    cfg = AppConfig.from_env()
    session_dir = cfg.project_root / 'runtime' / 'sessions'
    session_name = str(session_dir / f'{cfg.telegram_session_name}-listener')

    print('Session path:', session_name + '.session')
    session_file = Path(session_name + '.session')
    if not session_file.exists():
        print('SESSION FILE NOT FOUND — need to run login first')
        return

    # Load StringSession from SQLite
    sq = SQLiteSession(session_name)
    try:
        serialized = StringSession.save(sq)
    finally:
        sq.close()

    if not serialized:
        print('StringSession is EMPTY — session not authorized')
        return

    print('StringSession loaded ok, length', len(serialized))

    client: Any = TelegramClient(
        StringSession(serialized),
        int(cfg.telegram_api_id or '0'),
        cfg.telegram_api_hash or '',
    )

    print('Calling client.connect()...')
    await client.connect()
    print('Connected:', client.is_connected())

    authorized = await client.is_user_authorized()
    print('Authorized:', authorized)

    if not authorized:
        print('NOT AUTHORIZED — session expired, need to re-login')
        await client.disconnect()
        return

    me = await client.get_me()
    print('Logged in as:', getattr(me, 'username', None) or getattr(me, 'first_name', None))

    print('Resolving first source...')
    sources = cfg.telegram_source_mappings
    if sources:
        label, ident = sources[0]
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
                    entity = await client.get_entity(raw_id)
                else:
                    for attempt_id in (int(f'-100{ident}'), raw_id):
                        try:
                            entity = await client.get_entity(attempt_id)
                            break
                        except Exception:
                            continue
            else:
                try:
                    async for dialog in client.iter_dialogs():
                        if dialog.name and dialog.name.strip().lower() == ident.strip().lower():
                            entity = dialog.entity
                            break
                except Exception:
                    pass

                if entity is None:
                    entity = await client.get_entity(ident)

            if entity:
                print('Resolved source:', label, '->', getattr(entity, 'title', None) or getattr(entity, 'username', None))
            else:
                raise ValueError('Could not resolve entity')
        except Exception as e:
            print('Failed to resolve source:', label, ident, ':', e)

    await client.disconnect()
    print('Disconnected cleanly')


if __name__ == '__main__':
    try:
        asyncio.run(_probe())
    except Exception:
        traceback.print_exc()
